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
