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
        number_sold: int,
        color_id: int = None,
        fecha=None,
        segundo_vendedor_id: int = None,
        segunda_comision: Decimal = Decimal("0"),
    ):
        query = """
            INSERT INTO sales (
                seller_id, branch_id, product_id, color_id, quantity_sold, number_sold,
                historical_base_price,
                sale_price, commission, base_price_id, created_at
            )
            SELECT %s, branch.id, p.id, %s, 1, %s, bp.cost_without_discount, %s, %s, bp.id,
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
        conn = db_pool.get_connection()
        try:
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
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            db_pool.put_connection(conn)

    def obtener_reporte_ganancias(
        self, fecha_inicio=None, fecha_fin=None, vendedor_id=None
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
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            WITH commissions AS (
                SELECT sale_id, SUM(commission) AS commission
                FROM sales_commissions
                GROUP BY sale_id
            ),
            commission_sellers AS (
                SELECT sc.sale_id, STRING_AGG(seller.name, ', ' ORDER BY seller.name) AS sellers
                FROM sales_commissions sc
                JOIN seller ON seller.id = sc.seller_id
                GROUP BY sc.sale_id
            )
            SELECT 
                s.id, COALESCE(commission_sellers.sellers, seller.name),
                c.name, p.code, s.number_sold, colors.name,
                s.historical_base_price, s.sale_price,
                COALESCE(commissions.commission, 0), s.created_at
            FROM sales s
            JOIN seller ON s.seller_id = seller.id
            JOIN products p ON s.product_id = p.id
            JOIN companies c ON p.company_id = c.id
            LEFT JOIN base_price bp ON bp.id = s.base_price_id
            LEFT JOIN colors ON colors.id = s.color_id
            LEFT JOIN commissions ON commissions.sale_id = s.id
            LEFT JOIN commission_sellers ON commission_sellers.sale_id = s.id
            {where_clause}
            ORDER BY s.created_at DESC, s.id DESC
        """
        return self.execute_query(query, tuple(params), fetch=True)

    def obtener_venta_para_editar(self, venta_id: int):
        result = self.execute_query(
            """
            SELECT id, seller_id, branch_id, product_id, color_id, quantity_sold,
                   number_sold, historical_base_price, sale_price, commission,
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
        cantidad_vendida: int,
        numero_vendido: int,
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
                quantity_sold = %s,
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
                        color_id, cantidad_vendida, numero_vendido, precio_base,
                        precio_vendido, comision + segunda_comision, fecha,
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
        return self.execute_query(
            "DELETE FROM sales WHERE id = %s RETURNING id",
            (venta_id,),
            fetch=True,
        )

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

    def registrar_gasto(self, fecha, categoria, descripcion, monto):
        self.execute_query(
            """
            INSERT INTO daily_expenses (expense_date, category, description, amount)
            VALUES (%s, %s, %s, %s)
            """,
            (fecha, categoria, descripcion or None, monto)
        )

    def actualizar_gasto(self, gasto_id, fecha, categoria, descripcion, monto):
        result = self.execute_query(
            """
            UPDATE daily_expenses
            SET expense_date = %s, category = %s, description = %s, amount = %s
            WHERE id = %s
            RETURNING id
            """,
            (fecha, categoria, descripcion or None, monto, gasto_id),
            fetch=True
        )
        if not result:
            raise ValueError("No se encontró el gasto que se intentó modificar.")

    def registrar_pago_vendedor(self, vendedor_id, fecha, monto, notas):
        self.execute_query(
            """
            INSERT INTO seller_payments (seller_id, payment_date, amount, notes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (seller_id, payment_date)
            DO UPDATE SET amount = EXCLUDED.amount, notes = EXCLUDED.notes
            """,
            (vendedor_id, fecha, monto, notas or None)
        )

    def obtener_reporte_vendedores(
        self, fecha_inicio=None, fecha_fin=None, vendedor_id=None
    ):
        sales_conditions = []
        payment_conditions = []
        sales_params = []
        payment_params = []
        if fecha_inicio is not None:
            sales_conditions.append("s.created_at >= %s")
            payment_conditions.append("p.payment_date >= %s")
            sales_params.append(fecha_inicio)
            payment_params.append(fecha_inicio)
        if fecha_fin is not None:
            sales_conditions.append("s.created_at < %s")
            payment_conditions.append("p.payment_date < %s")
            sales_params.append(fecha_fin)
            payment_params.append(fecha_fin)
        if vendedor_id is not None:
            sales_conditions.append("sc.seller_id = %s")
            payment_conditions.append("p.seller_id = %s")
            sales_params.append(vendedor_id)
            payment_params.append(vendedor_id)

        sales_where = (
            f"WHERE {' AND '.join(sales_conditions)}" if sales_conditions else ""
        )
        payments_where = (
            f"WHERE {' AND '.join(payment_conditions)}"
            if payment_conditions else ""
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
            payments AS (
                SELECT p.seller_id, seller.name AS vendedor,
                       p.payment_date AS fecha, SUM(p.amount) AS pagado
                FROM seller_payments p
                JOIN seller ON seller.id = p.seller_id
                {payments_where}
                GROUP BY p.seller_id, seller.name, p.payment_date
            )
            SELECT COALESCE(c.seller_id, p.seller_id) AS seller_id,
                   COALESCE(c.vendedor, p.vendedor) AS vendedor,
                   COALESCE(c.fecha, p.fecha) AS fecha,
                   COALESCE(c.ventas, 0) AS ventas,
                   COALESCE(c.comision, 0) AS comision,
                   COALESCE(p.pagado, 0) AS pagado
            FROM commissions c
            FULL OUTER JOIN payments p
                ON p.seller_id = c.seller_id AND p.fecha = c.fecha
            ORDER BY fecha DESC, vendedor
        """
        return self.execute_query(
            query, tuple(sales_params + payment_params), fetch=True
        )
