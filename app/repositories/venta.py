from app.repositories.base import BaseRepository

class VentaRepository(BaseRepository):
    def registrar_venta(
        self,
        vendedor_id: int,
        base_price_id: int,
        precio_vendido: float,
        porcentaje_ganancia: int,
        numero_vendido: int,
    ):
        query = """
            INSERT INTO sales (
                seller_id, product_id, quantity_sold, number_sold, historical_base_price,
                sale_price, commission, base_price_id
            )
            SELECT %s, p.id, 1, %s, bp.cost_without_discount, %s, %s, bp.id
            FROM base_price bp
            JOIN products p ON p.id = bp.product_id
            JOIN sizes size ON size.label = bp.size_label
            JOIN companies company ON company.id = p.company_id
            JOIN seller ON seller.id = %s
            WHERE bp.id = %s
                AND bp.state_id = 1
                AND p.state_id = 1
                AND size.state_id = 1
                AND company.state_id = 1
                AND seller.state_id = 1
                AND %s BETWEEN size.start_number AND size.end_number
            RETURNING id
        """
        result = self.execute_query(
            query,
            (
                vendedor_id, numero_vendido, precio_vendido,
                porcentaje_ganancia, vendedor_id, base_price_id, numero_vendido
            ),
            fetch=True
        )
        if not result:
            raise ValueError(
                "No se pudo registrar la venta. Verifique el vendedor, el producto activo y el rango de talla."
            )

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
            conditions.append("s.seller_id = %s")
            params.append(vendedor_id)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT 
                s.id, seller.name, c.name, p.code, bp.size_label,
                s.historical_base_price, s.sale_price, s.commission, s.created_at,
                s.number_sold AS numero_vendido
            FROM sales s
            JOIN seller ON s.seller_id = seller.id
            JOIN products p ON s.product_id = p.id
            JOIN companies c ON p.company_id = c.id
            LEFT JOIN base_price bp ON bp.id = s.base_price_id
            {where_clause}
            ORDER BY s.created_at DESC, s.id DESC
        """
        return self.execute_query(query, tuple(params), fetch=True)

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
            sales_conditions.append("s.seller_id = %s")
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
                SELECT s.seller_id, seller.name AS vendedor, s.created_at AS fecha,
                       SUM(s.commission) AS comision, COUNT(*) AS ventas
                FROM sales s
                JOIN seller ON seller.id = s.seller_id
                {sales_where}
                GROUP BY s.seller_id, seller.name, s.created_at
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
