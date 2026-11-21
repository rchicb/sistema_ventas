from app.core.database import db_pool
import psycopg2.extras

class BaseRepository:
    def execute_query(self, query: str, params: tuple = None, fetch: bool = False):
        conn = db_pool.get_connection()
        result = None
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                cursor.execute(query, params or ())
                if fetch:
                    result = cursor.fetchall()
                conn.commit()
        finally:
            db_pool.put_connection(conn)
        return result

    def guardar_producto_duplicado(
        self,
        company_id: int,
        code: str,
        description: str,
        product_state_id: int,
        size_label: str,
        prices: tuple,
        price_state_id: int,
        color_ids: list[int],
    ):
        conn = db_pool.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM companies WHERE id = %s FOR UPDATE",
                    (company_id,),
                )
                if not cursor.fetchone():
                    conn.commit()
                    return None

                cursor.execute(
                    """
                    SELECT id FROM products
                    WHERE company_id = %s AND code = %s
                    FOR UPDATE
                    """,
                    (company_id, code),
                )
                producto_existente = cursor.fetchone()
                if producto_existente:
                    product_id = producto_existente[0]
                else:
                    cursor.execute(
                        """
                        INSERT INTO products (company_id, code, description, state_id)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (company_id, code) DO NOTHING
                        RETURNING id
                        """,
                        (company_id, code, description, product_state_id),
                    )
                    producto_nuevo = cursor.fetchone()
                    if producto_nuevo:
                        product_id = producto_nuevo[0]
                    else:
                        cursor.execute(
                            """
                            SELECT id FROM products
                            WHERE company_id = %s AND code = %s
                            FOR UPDATE
                            """,
                            (company_id, code),
                        )
                        producto_existente = cursor.fetchone()
                        if not producto_existente:
                            raise ValueError(
                                "No se pudo crear ni localizar el producto duplicado."
                            )
                        product_id = producto_existente[0]

                cursor.execute(
                    """
                    INSERT INTO base_price (
                        product_id, size_label, cost_without_discount,
                        cost_with_discount, sale_price_suggested, state_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (product_id, size_label) DO NOTHING
                    RETURNING id
                    """,
                    (
                        product_id, size_label, *prices, price_state_id,
                    ),
                )
                precio_nuevo = cursor.fetchone()
                if not precio_nuevo:
                    raise ValueError(
                        "El producto con ese código ya tiene asignada esa talla."
                    )

                if color_ids:
                    cursor.execute(
                        """
                        INSERT INTO product_colors (product_id, color_id)
                        SELECT %s, selected.color_id
                        FROM unnest(%s::int[]) AS selected(color_id)
                        ON CONFLICT (product_id, color_id) DO NOTHING
                        """,
                        (product_id, color_ids),
                    )
            conn.commit()
            return product_id, precio_nuevo[0]
        except Exception:
            conn.rollback()
            raise
        finally:
            db_pool.put_connection(conn)

    def actualizar_producto_sin_precio(
        self,
        product_id: int,
        company_id: int,
        code: str,
        description: str,
        state_id: int,
        color_ids: list[int],
        size_label: str = None,
        prices: tuple = None,
    ):
        conn = db_pool.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE products
                    SET company_id = %s, code = %s, description = %s, state_id = %s
                    WHERE id = %s
                    RETURNING id
                    """,
                    (company_id, code, description, state_id, product_id),
                )
                if not cursor.fetchone():
                    conn.commit()
                    return None

                if size_label is not None and prices is not None:
                    cursor.execute(
                        """
                        INSERT INTO base_price (
                            product_id, size_label, cost_without_discount,
                            cost_with_discount, sale_price_suggested, state_id
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (product_id, size_label) DO NOTHING
                        RETURNING id
                        """,
                        (product_id, size_label, *prices, state_id),
                    )
                    if not cursor.fetchone():
                        raise ValueError(
                            "Ya existe un registro para ese producto y categoría de talla."
                        )

                cursor.execute(
                    "DELETE FROM product_colors WHERE product_id = %s",
                    (product_id,),
                )
                if color_ids:
                    cursor.execute(
                        """
                        INSERT INTO product_colors (product_id, color_id)
                        SELECT %s, selected.color_id
                        FROM unnest(%s::int[]) AS selected(color_id)
                        """,
                        (product_id, color_ids),
                    )
            conn.commit()
            return product_id
        except Exception:
            conn.rollback()
            raise
        finally:
            db_pool.put_connection(conn)

    def fusionar_talla_duplicada(
        self,
        product_id: int,
        precio_id: int,
        producto_existente_id: int,
        size_label: str,
        prices: tuple,
        state_id: int,
        color_ids: list[int],
    ):
        conn = db_pool.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM products
                    WHERE id = ANY(%s)
                    ORDER BY id
                    FOR UPDATE
                    """,
                    ([product_id, producto_existente_id],),
                )
                productos_bloqueados = cursor.fetchall()
                if len(productos_bloqueados) != 2 or product_id == producto_existente_id:
                    conn.commit()
                    return None

                cursor.execute(
                    """
                    SELECT id FROM base_price
                    WHERE id = %s AND product_id = %s
                    FOR UPDATE
                    """,
                    (precio_id, product_id),
                )
                if not cursor.fetchone():
                    conn.commit()
                    return None

                cursor.execute(
                    """
                    SELECT 1 FROM sales
                    WHERE base_price_id = %s
                    LIMIT 1
                    """,
                    (precio_id,),
                )
                if cursor.fetchone():
                    raise ValueError(
                        "No se puede asociar esta talla porque ya tiene ventas registradas."
                    )

                cursor.execute(
                    """
                    INSERT INTO base_price (
                        product_id, size_label, cost_without_discount,
                        cost_with_discount, sale_price_suggested, state_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (product_id, size_label) DO NOTHING
                    RETURNING id
                    """,
                    (
                        producto_existente_id, size_label, *prices, state_id,
                    ),
                )
                precio_nuevo = cursor.fetchone()
                if not precio_nuevo:
                    raise ValueError(
                        "El producto con ese código ya tiene asignada esa talla."
                    )

                cursor.execute(
                    "DELETE FROM base_price WHERE id = %s AND product_id = %s",
                    (precio_id, product_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        "No se pudo mover la talla duplicada al producto existente."
                    )

                if color_ids:
                    cursor.execute(
                        """
                        INSERT INTO product_colors (product_id, color_id)
                        SELECT %s, selected.color_id
                        FROM unnest(%s::int[]) AS selected(color_id)
                        ON CONFLICT (product_id, color_id) DO NOTHING
                        """,
                        (producto_existente_id, color_ids),
                    )

                cursor.execute(
                    """
                    DELETE FROM products p
                    WHERE p.id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM base_price bp WHERE bp.product_id = p.id
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM sales s WHERE s.product_id = p.id
                      )
                    """,
                    (product_id,),
                )
            conn.commit()
            return precio_nuevo[0]
        except Exception:
            conn.rollback()
            raise
        finally:
            db_pool.put_connection(conn)

    def eliminar_registro_catalogo(self, product_id: int, precio_id: int = None):
        conn = db_pool.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM products WHERE id = %s FOR UPDATE",
                    (product_id,),
                )
                if not cursor.fetchone():
                    conn.commit()
                    return None

                if precio_id is not None:
                    cursor.execute(
                        """
                        DELETE FROM base_price bp
                        WHERE bp.id = %s AND bp.product_id = %s
                          AND NOT EXISTS (
                              SELECT 1 FROM sales s WHERE s.base_price_id = bp.id
                          )
                        RETURNING bp.id
                        """,
                        (precio_id, product_id),
                    )
                    eliminado = cursor.fetchone()
                    if eliminado:
                        conn.commit()
                        return eliminado[0]

                    cursor.execute(
                        "SELECT id FROM base_price WHERE id = %s AND product_id = %s",
                        (precio_id, product_id),
                    )
                    if not cursor.fetchone():
                        conn.commit()
                        return None
                    raise ValueError(
                        "No se puede eliminar esta talla porque tiene ventas registradas."
                    )

                cursor.execute(
                    """
                    DELETE FROM products p
                    WHERE p.id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM base_price bp WHERE bp.product_id = p.id
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM sales s WHERE s.product_id = p.id
                      )
                    RETURNING p.id
                    """,
                    (product_id,),
                )
                eliminado = cursor.fetchone()
                if eliminado:
                    conn.commit()
                    return eliminado[0]
                cursor.execute(
                    "SELECT 1 FROM base_price WHERE product_id = %s LIMIT 1",
                    (product_id,),
                )
                if cursor.fetchone():
                    raise ValueError(
                        "Seleccione la talla y el precio para eliminar solo ese registro."
                    )
                raise ValueError(
                    "No se puede eliminar el producto porque tiene ventas registradas."
                )
        except Exception:
            conn.rollback()
            raise
        finally:
            db_pool.put_connection(conn)

    def reemplazar_colores_producto(self, product_id: int, color_ids: list[int]):
        conn = db_pool.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM product_colors WHERE product_id = %s",
                    (product_id,),
                )
                if color_ids:
                    cursor.execute(
                        """
                        INSERT INTO product_colors (product_id, color_id)
                        SELECT %s, selected.color_id
                        FROM unnest(%s::int[]) AS selected(color_id)
                        """,
                        (product_id, color_ids),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            db_pool.put_connection(conn)

    def guardar_colores_y_precio_producto(
        self,
        product_id: int,
        color_ids: list[int],
        size_label: str = None,
        prices: tuple = None,
    ):
        conn = db_pool.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM product_colors WHERE product_id = %s",
                    (product_id,),
                )
                if color_ids:
                    cursor.execute(
                        """
                        INSERT INTO product_colors (product_id, color_id)
                        SELECT %s, selected.color_id
                        FROM unnest(%s::int[]) AS selected(color_id)
                        """,
                        (product_id, color_ids),
                    )
                if size_label is not None and prices is not None:
                    cursor.execute(
                        """
                        INSERT INTO base_price (
                            product_id, size_label, cost_without_discount,
                            cost_with_discount, sale_price_suggested, state_id
                        )
                        VALUES (%s, %s, %s, %s, %s, 1)
                        ON CONFLICT (product_id, size_label)
                        DO UPDATE SET
                            cost_without_discount = EXCLUDED.cost_without_discount,
                            cost_with_discount = EXCLUDED.cost_with_discount,
                            sale_price_suggested = EXCLUDED.sale_price_suggested,
                            state_id = EXCLUDED.state_id
                        """,
                        (product_id, size_label, *prices),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            db_pool.put_connection(conn)
