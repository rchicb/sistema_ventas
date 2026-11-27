from decimal import Decimal

from app.repositories.base import BaseRepository
from app.core.database import db_pool

class VentaRepository(BaseRepository):
    def registrar_venta(
        self,
        vendedor_id: int,
        sucursal_id: int,
        base_price_id: int,
        precio_vendido: float,
        comision_vendedor: Decimal,
        number_sold: Decimal,
        color_id: int = None,
        fecha=None,
        segundo_vendedor_id: int = None,
        segunda_comision: Decimal = Decimal("0"),
    ):
        query = """
            INSERT INTO sales (
                seller_id, branch_id, product_id, color_id, number_sold,
                historical_base_price,
                sale_price, commission, base_price_id, created_at
            )
            SELECT %s, branch.id, p.id, %s, %s, bp.cost_with_discount, %s, %s, bp.id,
                   COALESCE(%s, CURRENT_DATE)
            FROM branches branch
            JOIN base_price bp ON bp.id = %s
            JOIN products p ON p.id = bp.product_id
            JOIN sizes size ON size.label = bp.size_label
            JOIN companies company ON company.id = p.company_id
            JOIN seller ON seller.id = %s
            WHERE branch.id = %s
                AND branch.state_id = 1
                AND bp.state_id = 1
                AND p.state_id = 1
                AND size.state_id = 1
                AND company.state_id = 1
                AND seller.state_id = 1
                AND (
                    (%s IS NULL AND NOT EXISTS (
                        SELECT 1 FROM product_colors pc
                        WHERE pc.product_id = p.id
                    ))
                    OR EXISTS (
                        SELECT 1 FROM product_colors pc
                        WHERE pc.product_id = p.id AND pc.color_id = %s
                    )
                )
                AND (%s = 0 OR %s BETWEEN size.start_number AND size.end_number)
            RETURNING id
        """
        with db_pool.transaction() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (
                        vendedor_id, color_id, number_sold, precio_vendido,
                        comision_vendedor + segunda_comision, fecha,
                        base_price_id, vendedor_id, sucursal_id,
                        color_id, color_id, number_sold, number_sold,
                    ),
                )
                result = cursor.fetchone()
                if not result:
                    raise ValueError(
                        "No se pudo registrar la venta. Verifique el vendedor, "
                        "la sucursal, el producto, el color seleccionado y el "
                        "rango de talla."
                    )
                venta_id = result[0]
                cursor.execute(
                    """
                    INSERT INTO sales_commissions (sale_id, seller_id, commission)
                    VALUES (%s, %s, %s)
                    """,
                    (venta_id, vendedor_id, comision_vendedor),
                )
                if segundo_vendedor_id is not None:
                    cursor.execute(
                        """
                        INSERT INTO sales_commissions (sale_id, seller_id, commission)
                        SELECT %s, id, %s
                        FROM seller
                        WHERE id = %s AND state_id = 1
                        RETURNING seller_id
                        """,
                        (venta_id, segunda_comision, segundo_vendedor_id),
                    )
                    if not cursor.fetchone():
                        raise ValueError(
                            "El segundo vendedor no existe o está inactivo."
                        )

    def obtener_reporte_ganancias(
        self,
        fecha_inicio=None,
        fecha_fin=None,
        vendedor_id=None,
        vendedor_historial_id=None,
        estado_pago=None,
    ):
        conditions = []
        params = []
        if fecha_inicio is not None:
            conditions.append("s.created_at >= %s")
            params.append(fecha_inicio)
        if fecha_fin is not None:
            conditions.append("s.created_at < %s")
            params.append(fecha_fin)
        if vendedor_id is not None:
            conditions.append(
                "EXISTS (SELECT 1 FROM sales_commissions sc "
                "WHERE sc.sale_id = s.id AND sc.seller_id = %s)"
            )
            params.append(vendedor_id)
        if vendedor_historial_id is not None:
            conditions.append(
                "EXISTS (SELECT 1 FROM sales_commissions sc "
                "WHERE sc.sale_id = s.id AND sc.seller_id = %s)"
            )
            params.append(vendedor_historial_id)
        if estado_pago is not None:
            conditions.append(
                """
                CASE
                    WHEN COALESCE(sale_payment_status.paid, FALSE)
                        THEN 'pagado'
                    WHEN COALESCE(sale_payment_status.any_paid, FALSE)
                        THEN 'parcial'
                    ELSE 'pendiente'
                END = %s
                """
            )
            params.append(estado_pago)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            WITH commissions AS (
                SELECT sale_id, SUM(commission) AS commission
                FROM sales_commissions
                GROUP BY sale_id
            ),
            commission_sellers AS (
                SELECT sc.sale_id,
                       STRING_AGG(seller.name, ', ' ORDER BY seller.name) AS sellers,
                       ARRAY_AGG(seller.name ORDER BY seller.name) AS seller_names
                FROM sales_commissions sc
                JOIN seller ON seller.id = sc.seller_id
                GROUP BY sc.sale_id
            ),
            sale_payment_status AS (
                SELECT sc.sale_id,
                       BOOL_AND(payment.sale_id IS NOT NULL) AS paid,
                       BOOL_OR(payment.sale_id IS NOT NULL) AS any_paid,
                       ARRAY_AGG(seller.name ORDER BY seller.name)
                           FILTER (WHERE payment.sale_id IS NOT NULL) AS paid_sellers
                FROM sales_commissions sc
                JOIN seller ON seller.id = sc.seller_id
                LEFT JOIN seller_payment_sales payment
                  ON payment.sale_id = sc.sale_id
                 AND payment.seller_id = sc.seller_id
                GROUP BY sc.sale_id
            )
            SELECT 
                s.id, COALESCE(commission_sellers.sellers, seller.name),
                c.name, p.code, s.number_sold, colors.name,
                s.historical_base_price, s.sale_price,
                COALESCE(commissions.commission, 0), s.created_at,
                CASE
                    WHEN COALESCE(sale_payment_status.paid, FALSE)
                        THEN 'pagado'
                    WHEN COALESCE(sale_payment_status.any_paid, FALSE)
                        THEN 'parcial'
                    ELSE 'pendiente'
                END,
                COALESCE(sale_payment_status.paid_sellers, ARRAY[]::varchar[]),
                COALESCE(commission_sellers.seller_names, ARRAY[seller.name])
            FROM sales s
            JOIN seller ON s.seller_id = seller.id
            JOIN products p ON s.product_id = p.id
            JOIN companies c ON p.company_id = c.id
            LEFT JOIN base_price bp ON bp.id = s.base_price_id
            LEFT JOIN colors ON colors.id = s.color_id
            LEFT JOIN commissions ON commissions.sale_id = s.id
            LEFT JOIN commission_sellers ON commission_sellers.sale_id = s.id
            LEFT JOIN sale_payment_status ON sale_payment_status.sale_id = s.id
            {where_clause}
            ORDER BY s.created_at DESC, s.id DESC
        """
        return self.execute_query(query, tuple(params), fetch=True)

    def obtener_venta_para_editar(self, venta_id: int):
        result = self.execute_query(
            """
            SELECT id, seller_id, branch_id, product_id, color_id, number_sold,
                   historical_base_price, sale_price, commission,
                   base_price_id, created_at
            FROM sales
            WHERE id = %s
            """,
            (venta_id,),
            fetch=True,
        )
        return result[0] if result else None

    def obtener_comisiones_venta(self, venta_id: int):
        return self.execute_query(
            """
            SELECT seller_id, commission
            FROM sales_commissions
            WHERE sale_id = %s
            ORDER BY seller_id
            """,
            (venta_id,),
            fetch=True,
        )

    def actualizar_venta(
        self,
        venta_id: int,
        vendedor_id: int,
        sucursal_id: int,
        base_price_id: int,
        color_id: int,
        numero_vendido: Decimal,
        precio_base: float,
        precio_vendido: float,
        comision: Decimal,
        fecha,
        segundo_vendedor_id: int = None,
        segunda_comision: Decimal = Decimal("0"),
    ):
        query = """
            UPDATE sales AS sale
            SET seller_id = seller.id,
                branch_id = branch.id,
                product_id = p.id,
                color_id = %s,
                number_sold = %s,
                historical_base_price = %s,
                sale_price = %s,
                commission = %s,
                base_price_id = bp.id,
                created_at = %s
            FROM seller
            JOIN branches branch ON branch.id = %s
            JOIN base_price bp ON bp.id = %s
            JOIN products p ON p.id = bp.product_id
            JOIN sizes size ON size.label = bp.size_label
            JOIN companies company ON company.id = p.company_id
            WHERE sale.id = %s
                AND NOT EXISTS (
                    SELECT 1 FROM seller_payment_sales paid
                    WHERE paid.sale_id = sale.id
                )
                AND seller.id = %s
                AND (branch.state_id = 1 OR sale.branch_id = branch.id)
                AND (bp.state_id = 1 OR sale.base_price_id = bp.id)
                AND (p.state_id = 1 OR sale.product_id = p.id)
                AND (size.state_id = 1 OR sale.base_price_id = bp.id)
                AND (company.state_id = 1 OR sale.product_id = p.id)
                AND (seller.state_id = 1 OR sale.seller_id = seller.id)
                AND (
                    (%s IS NULL AND NOT EXISTS (
                        SELECT 1 FROM product_colors pc
                        WHERE pc.product_id = p.id
                    ))
                    OR EXISTS (
                        SELECT 1 FROM product_colors pc
                        WHERE pc.product_id = p.id AND pc.color_id = %s
                    )
                    OR (sale.product_id = p.id AND sale.color_id = %s)
                )
                AND (
                    %s = 0
                    OR %s BETWEEN size.start_number AND size.end_number
                )
            RETURNING sale.id
            """
        conn = db_pool.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (
                        color_id, numero_vendido, precio_base, precio_vendido,
                        comision + segunda_comision, fecha,
                        sucursal_id, base_price_id, venta_id, vendedor_id,
                        color_id, color_id, color_id, numero_vendido,
                        numero_vendido,
                    ),
                )
                if not cursor.fetchone():
                    raise ValueError(
                        "No se pudo modificar la venta. Verifique los datos, "
                        "el vendedor, la sucursal, el producto, el color y el "
                        "rango de talla."
                    )
                cursor.execute(
                    "DELETE FROM sales_commissions WHERE sale_id = %s",
                    (venta_id,),
                )
                cursor.execute(
                    """
                    INSERT INTO sales_commissions (sale_id, seller_id, commission)
                    VALUES (%s, %s, %s)
                    """,
                    (venta_id, vendedor_id, comision),
                )
                if segundo_vendedor_id is not None:
                    cursor.execute(
                        """
                        INSERT INTO sales_commissions (sale_id, seller_id, commission)
                        SELECT %s, id, %s
                        FROM seller
                        WHERE id = %s AND state_id = 1
                        RETURNING seller_id
                        """,
                        (venta_id, segunda_comision, segundo_vendedor_id),
                    )
                    if not cursor.fetchone():
                        raise ValueError(
                            "El segundo vendedor no existe o está inactivo."
                        )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            db_pool.put_connection(conn)

    def eliminar_venta(self, venta_id: int):
        result = self.execute_query(
            """
            DELETE FROM sales
            WHERE id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM seller_payment_sales paid
                  WHERE paid.sale_id = sales.id
              )
            RETURNING id
            """,
            (venta_id,),
            fetch=True,
        )
        if result:
            return result
        if self.execute_query(
            "SELECT 1 FROM seller_payment_sales WHERE sale_id = %s LIMIT 1",
            (venta_id,),
            fetch=True,
        ):
            raise ValueError("No se puede eliminar una venta que ya fue pagada.")
        return None

    def obtener_gastos(self, fecha_inicio=None, fecha_fin=None):
        conditions = []
        params = []
        if fecha_inicio is not None:
            conditions.append("expense_date >= %s")
            params.append(fecha_inicio)
        if fecha_fin is not None:
            conditions.append("expense_date < %s")
            params.append(fecha_fin)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT id, expense_date, category, description, amount
            FROM daily_expenses
            {where_clause}
            ORDER BY expense_date DESC, id DESC
        """
        return self.execute_query(query, tuple(params), fetch=True)

    def registrar_gastos(self, gastos):
        fechas, categorias, descripciones, montos = zip(*gastos)
        self.execute_query(
            """
            INSERT INTO daily_expenses (
                expense_date, category, description, amount
            )
            SELECT gasto.expense_date, gasto.category, gasto.description, gasto.amount
            FROM unnest(
                %s::date[], %s::text[], %s::text[], %s::numeric[]
            ) AS gasto(expense_date, category, description, amount)
            """,
            (
                list(fechas),
                list(categorias),
                [descripcion or None for descripcion in descripciones],
                list(montos),
            ),
        )

    def actualizar_gastos(self, gastos):
        if not gastos:
            raise ValueError("Debe seleccionar al menos un gasto.")
        gasto_ids, fechas, categorias, descripciones, montos = zip(*gastos)
        if len(set(gasto_ids)) != len(gasto_ids):
            raise ValueError("No se pueden repetir los identificadores de gasto.")
        conn = db_pool.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE daily_expenses AS gasto
                    SET expense_date = cambios.fecha,
                        category = cambios.categoria,
                        description = cambios.descripcion,
                        amount = cambios.monto
                    FROM unnest(
                        %s::int[], %s::date[], %s::text[], %s::text[], %s::numeric[]
                    ) AS cambios(gasto_id, fecha, categoria, descripcion, monto)
                    WHERE gasto.id = cambios.gasto_id
                    RETURNING gasto.id
                    """,
                    (
                        list(gasto_ids),
                        list(fechas),
                        list(categorias),
                        [descripcion or None for descripcion in descripciones],
                        list(montos),
                    ),
                )
                if len(cursor.fetchall()) != len(gasto_ids):
                    raise ValueError("Uno o más gastos ya no existen.")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            db_pool.put_connection(conn)

    def obtener_ventas_pendientes_pago(
        self, vendedor_id, fecha_inicio=None, fecha_fin=None
    ):
        conditions = ["sc.seller_id = %s"]
        params = [vendedor_id]
        if fecha_inicio is not None:
            conditions.append("s.created_at >= %s")
            params.append(fecha_inicio)
        if fecha_fin is not None:
            conditions.append("s.created_at < %s")
            params.append(fecha_fin)
        return self.execute_query(
            f"""
            SELECT s.id, s.created_at, c.name, p.code, bp.size_label,
                   s.number_sold, colors.name, sc.commission
            FROM sales_commissions sc
            JOIN sales s ON s.id = sc.sale_id
            JOIN products p ON p.id = s.product_id
            JOIN companies c ON c.id = p.company_id
            LEFT JOIN base_price bp ON bp.id = s.base_price_id
            LEFT JOIN colors ON colors.id = s.color_id
            WHERE {" AND ".join(conditions)}
              AND NOT EXISTS (
                  SELECT 1
                  FROM seller_payment_sales paid
                  WHERE paid.sale_id = sc.sale_id
                    AND paid.seller_id = sc.seller_id
              )
            ORDER BY s.created_at, s.id
            """,
            tuple(params),
            fetch=True,
        )

    def registrar_pago_vendedor(
        self, vendedor_id, fecha, notas, admin_user_id, venta_ids
    ):
        if not venta_ids or len(set(venta_ids)) != len(venta_ids):
            raise ValueError("Seleccione una o más ventas distintas para pagar.")

        conn = db_pool.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id FROM app_users
                    WHERE id = %s AND role = 'admin' AND state_id = 1
                    """,
                    (admin_user_id,),
                )
                if not cursor.fetchone():
                    raise ValueError("El administrador seleccionado no está activo.")

                cursor.execute(
                    """
                    SELECT id FROM seller
                    WHERE id = %s AND state_id = 1
                    """,
                    (vendedor_id,),
                )
                if not cursor.fetchone():
                    raise ValueError("El vendedor seleccionado no está activo.")

                cursor.execute(
                    """
                    SELECT id FROM sales
                    WHERE id = ANY(%s)
                    ORDER BY id
                    FOR UPDATE
                    """,
                    (venta_ids,),
                )
                ventas_bloqueadas = cursor.fetchall()
                if len(ventas_bloqueadas) != len(venta_ids):
                    raise ValueError("Una o más ventas seleccionadas no existen.")

                cursor.execute(
                    """
                    SELECT sc.sale_id, sc.commission
                    FROM sales_commissions sc
                    WHERE sc.seller_id = %s
                      AND sc.sale_id = ANY(%s)
                      AND NOT EXISTS (
                          SELECT 1 FROM seller_payment_sales paid
                          WHERE paid.sale_id = sc.sale_id
                            AND paid.seller_id = sc.seller_id
                      )
                    ORDER BY sc.sale_id
                    """,
                    (vendedor_id, venta_ids),
                )
                comisiones = cursor.fetchall()
                if len(comisiones) != len(venta_ids):
                    raise ValueError(
                        "Una o más ventas ya fueron pagadas o no pertenecen "
                        "al vendedor seleccionado."
                    )

                monto = sum(
                    (Decimal(str(comision)) for _, comision in comisiones),
                    Decimal("0"),
                )
                cursor.execute(
                    """
                    INSERT INTO seller_payments (
                        seller_id, payment_date, amount, notes, admin_user_id
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (vendedor_id, fecha, monto, notas or None, admin_user_id),
                )
                pago_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO seller_payment_sales (
                        seller_payment_id, sale_id, seller_id
                    )
                    SELECT %s, selected.sale_id, %s
                    FROM unnest(%s::int[]) AS selected(sale_id)
                    """,
                    (pago_id, vendedor_id, venta_ids),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            db_pool.put_connection(conn)

    def obtener_reporte_vendedores(
        self, fecha_inicio=None, fecha_fin=None, vendedor_id=None
    ):
        sales_conditions = []
        payment_conditions = []
        legacy_payment_conditions = [
            """
            NOT EXISTS (
                SELECT 1
                FROM seller_payment_sales paid_sale
                WHERE paid_sale.seller_payment_id = p.id
            )
            """
        ]
        sales_params = []
        payment_params = []
        legacy_payment_params = []
        if fecha_inicio is not None:
            sales_conditions.append("s.created_at >= %s")
            payment_conditions.append("s.created_at >= %s")
            legacy_payment_conditions.append("p.payment_date >= %s")
            sales_params.append(fecha_inicio)
            payment_params.append(fecha_inicio)
            legacy_payment_params.append(fecha_inicio)
        if fecha_fin is not None:
            sales_conditions.append("s.created_at < %s")
            payment_conditions.append("s.created_at < %s")
            legacy_payment_conditions.append("p.payment_date < %s")
            sales_params.append(fecha_fin)
            payment_params.append(fecha_fin)
            legacy_payment_params.append(fecha_fin)
        if vendedor_id is not None:
            sales_conditions.append("sc.seller_id = %s")
            payment_conditions.append("sc.seller_id = %s")
            legacy_payment_conditions.append("p.seller_id = %s")
            sales_params.append(vendedor_id)
            payment_params.append(vendedor_id)
            legacy_payment_params.append(vendedor_id)

        sales_where = (
            f"WHERE {' AND '.join(sales_conditions)}" if sales_conditions else ""
        )
        payments_where = (
            f"WHERE {' AND '.join(payment_conditions)}"
            if payment_conditions else ""
        )
        legacy_payments_where = (
            f"WHERE {' AND '.join(legacy_payment_conditions)}"
            if legacy_payment_conditions else ""
        )
        query = f"""
            WITH commissions AS (
                SELECT sc.seller_id, assigned_seller.name AS vendedor,
                       s.created_at AS fecha,
                       SUM(sc.commission) AS comision,
                       COUNT(DISTINCT s.id) AS ventas
                FROM sales_commissions sc
                JOIN sales s ON s.id = sc.sale_id
                JOIN seller assigned_seller ON assigned_seller.id = sc.seller_id
                {sales_where}
                GROUP BY sc.seller_id, assigned_seller.name, s.created_at
            ),
            payment_events AS (
                SELECT sc.seller_id, s.created_at AS fecha_venta,
                       p.id AS payment_id, p.payment_date,
                       admin.username AS administrador,
                       SUM(sc.commission) AS monto
                FROM seller_payment_sales paid_sale
                JOIN seller_payments p
                  ON p.id = paid_sale.seller_payment_id
                JOIN sales s ON s.id = paid_sale.sale_id
                JOIN sales_commissions sc
                  ON sc.sale_id = paid_sale.sale_id
                 AND sc.seller_id = paid_sale.seller_id
                LEFT JOIN app_users admin ON admin.id = p.admin_user_id
                {payments_where}
                GROUP BY sc.seller_id, s.created_at, p.id,
                         p.payment_date, admin.username
            ),
            payment_events_with_totals AS (
                SELECT payment_events.*,
                       SUM(monto) OVER (
                           PARTITION BY seller_id, fecha_venta
                           ORDER BY payment_date, payment_id
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                       ) AS pagado_acumulado
                FROM payment_events
            ),
            payments_by_sale_date AS (
                SELECT seller_id, fecha_venta, SUM(monto) AS pagado
                FROM payment_events
                GROUP BY seller_id, fecha_venta
            ),
            legacy_payments AS (
                SELECT p.id AS payment_id, p.seller_id, seller.name AS vendedor,
                       p.payment_date, p.amount,
                       admin.username AS administrador
                FROM seller_payments p
                JOIN seller ON seller.id = p.seller_id
                LEFT JOIN app_users admin ON admin.id = p.admin_user_id
                {legacy_payments_where}
            ),
            sales_report AS (
                SELECT c.seller_id, c.vendedor, c.fecha,
                       c.ventas, c.comision,
                       COALESCE(p.pagado, 0) AS pagado,
                       GREATEST(c.comision - COALESCE(p.pagado, 0), 0) AS pendiente
                FROM commissions c
                LEFT JOIN payments_by_sale_date p
                  ON p.seller_id = c.seller_id AND p.fecha_venta = c.fecha
            )
            SELECT seller_id, vendedor, fecha, ventas, comision,
                   NULL::numeric AS pago_linea, pagado,
                   pendiente, NULL::text AS fecha_pago,
                   NULL::text AS administrador, 'resumen' AS tipo_linea,
                   0 AS orden_linea, 0 AS payment_id
            FROM sales_report
            UNION ALL
            SELECT e.seller_id, c.vendedor, e.fecha_venta, NULL::bigint,
                   NULL::numeric, e.monto, e.pagado_acumulado,
                   GREATEST(c.comision - e.pagado_acumulado, 0),
                   e.payment_date::text, e.administrador, 'pago' AS tipo_linea,
                   1 AS orden_linea, e.payment_id
            FROM payment_events_with_totals e
            JOIN commissions c
              ON c.seller_id = e.seller_id AND c.fecha = e.fecha_venta
            UNION ALL
            SELECT p.seller_id, p.vendedor, NULL::date, NULL::bigint,
                   NULL::numeric, p.amount, p.amount, NULL::numeric,
                   p.payment_date::text, p.administrador, 'historico' AS tipo_linea,
                   1 AS orden_linea, p.payment_id
            FROM legacy_payments p
            ORDER BY fecha DESC NULLS LAST, vendedor, orden_linea,
                     fecha_pago, payment_id
        """
        return self.execute_query(
            query,
            tuple(sales_params + payment_params + legacy_payment_params),
            fetch=True,
        )
