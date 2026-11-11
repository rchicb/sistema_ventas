from app.repositories.base import BaseRepository

class VentaRepository(BaseRepository):
    def registrar_venta(self, vendedor_id: int, producto_id: int, precio_vendido: float, porcentaje_ganancia: int):
        query = """
            INSERT INTO ventas (vendedor_id, producto_id, precio_vendido, porcentaje_ganancia)
            VALUES (%s, %s, %s, %s)
        """
        self.execute_query(query, (vendedor_id, producto_id, precio_vendido, porcentaje_ganancia))

    def obtener_reporte_ganancias(self):
        query = """
            SELECT 
                v.id, ve.nombre, p.empresa, p.codigo, p.talla_letra, p.precio_base,
                v.precio_vendido, v.porcentaje_ganancia, v.fecha
            FROM ventas v
            JOIN vendedores ve ON v.vendedor_id = ve.id
            JOIN productos p ON v.producto_id = p.id
            ORDER BY v.fecha DESC, v.id DESC
        """
        return self.execute_query(query, fetch=True)
