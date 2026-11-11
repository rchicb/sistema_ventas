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
