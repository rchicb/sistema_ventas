from app.repositories.base import BaseRepository

class VentaRepository(BaseRepository):
    def registrar_venta(self, vendedor_id: int, base_price_id: int, precio_vendido: float, porcentaje_ganancia: int):
        query = """
            INSERT INTO sales (
                seller_id, product_id, quantity_sold, historical_base_price,
                sale_price, commission, base_price_id
            )
            SELECT %s, p.id, 1, bp.cost_without_discount, %s, %s, bp.id
            FROM base_price bp
            JOIN products p ON p.id = bp.product_id
            WHERE bp.id = %s AND bp.state_id = 1
        """
        self.execute_query(
            query,
            (vendedor_id, precio_vendido, porcentaje_ganancia, base_price_id)
        )

    def obtener_reporte_ganancias(self):
        query = """
            SELECT 
                s.id, seller.name, c.name, p.code, bp.size_label,
                s.historical_base_price, s.sale_price, s.commission, s.created_at
            FROM sales s
            JOIN seller ON s.seller_id = seller.id
            JOIN products p ON s.product_id = p.id
            JOIN companies c ON p.company_id = c.id
            LEFT JOIN base_price bp ON bp.id = s.base_price_id
            ORDER BY s.created_at DESC, s.id DESC
        """
        return self.execute_query(query, fetch=True)
