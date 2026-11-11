import time
import psycopg2
from psycopg2 import pool
from app.core.config import settings

class DatabaseConnectionPool:
    def __init__(self):
        self._pool = None

    def initialize(self):
        for i in range(5):
            try:
                self._pool = psycopg2.pool.SimpleConnectionPool(
                    1, 10, dsn=settings.DATABASE_URL
                )
                print("Pool de conexiones a PostgreSQL inicializado con éxito.")
                return
            except psycopg2.OperationalError as e:
                print(f"Esperando a la base de datos... Reintento {i+1}/5. Error: {e}")
                time.sleep(3)
        raise Exception("No se pudo conectar a la base de datos PostgreSQL.")

    def get_connection(self):
        if not self._pool:
            raise Exception("El pool de conexiones no está inicializado.")
        return self._pool.getconn()

    def put_connection(self, conn):
        if self._pool and conn:
            self._pool.putconn(conn)

    def close_all(self):
        if self._pool:
            self._pool.closeall()

db_pool = DatabaseConnectionPool()

def init_db():
    commands = [
        """
        CREATE TABLE states (
            id INT PRIMARY KEY,
            nombre VARCHAR(50) UNIQUE NOT NULL,       
            modulo VARCHAR(30) NOT NULL,              
            descripcion VARCHAR(150)                  
        );  

        """,
        """
        CREATE TABLE IF NOT EXISTS sizes (
            label CHAR(1) PRIMARY KEY,
            start_number INT NOT NULL,
            end_number INT NOT NULL,
            state_id INT NOT NULL DEFAULT 1 REFERENCES states(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS seller (
            id INT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            code INT NOT NULL,
            state_id INT NOT NULL DEFAULT 1 REFERENCES states(id)            
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS companies (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            state_id INT NOT NULL DEFAULT 1 REFERENCES states(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS products (            
            id SERIAL PRIMARY KEY,
            company_id INT REFERENCES empresas(id) ON DELETE RESTRICT,
            code VARCHAR(50) NOT NULL,
            state_id INT NOT NULL DEFAULT 1 REFERENCES states(id),
            UNIQUE(company_id, code)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS base_price (            
            id SERIAL PRIMARY KEY,
            producto_id INT REFERENCES productos(id) ON DELETE CASCADE,
            talla_letra CHAR(1) REFERENCES categorias_tallas(letra),
            precio_costo NUMERIC(10, 2) NOT NULL,
            UNIQUE(producto_id, talla_letra) 
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS venta (
            id SERIAL PRIMARY KEY,
            vendedor_id INT REFERENCES vendedores(id),
            producto_id INT REFERENCES productos(id),
            numero_vendido INT NOT NULL,          
            precio_base_historico NUMERIC(10, 2) NOT NULL, 
            precio_venta_manual NUMERIC(10, 2) NOT NULL,   
            porcentaje_comision INT NOT NULL,
            fecha DATE DEFAULT CURRENT_DATE
        )
        """
    ]
    
    conn = None
    try:
        conn = db_pool.get_connection()
        with conn.cursor() as cursor:
            for command in commands:
                cursor.execute(command)
            conn.commit()
            
            cursor.execute("SELECT COUNT(*) FROM categorias_tallas")
            if cursor.fetchone()[0] == 0:
                tallas_base = [
                    ('A', '20 - 26'), ('B', '27 - 32'), ('C', '33 - 36'), ('D', '37 - 43'),
                    ('E', '16 - 21'), ('F', '19 - 26'), ('G', '5 - 12'),  ('H', '34 - 43'),
                    ('I', '37 - 40'), ('J', '33 - 39'), ('K', '33 - 37')
                ]
                cursor.executemany("INSERT INTO categorias_tallas (letra, rango) VALUES (%s, %s)", tallas_base)
                
            cursor.execute("SELECT COUNT(*) FROM vendedores")
            if cursor.fetchone()[0] == 0:
                cursor.execute("INSERT INTO vendedores (id, nombre) VALUES (%s, %s)", (101, "Vendedor Central"))

            cursor.execute("SELECT COUNT(*) FROM productos")
            if cursor.fetchone()[0] == 0:
                productos_base = [
                    ('Kanguro', '4144', 'A', 121.00),
                    ('Kanguro', '4144', 'B', 129.00),
                    ('Kanguro', '4144', 'C', 142.00),
                    ('Kanguro', '4151', 'A', 114.00),
                    ('Kanguro', '4151', 'B', 122.00),
                    ('Kanguro', '4151', 'C', 135.00),
                    ('Penny BB', '856', 'F', 122.00),
                    ('Penny BB', '921 / 925 / 930 / 926', 'F', 135.00),
                    ('Penny BB', '940', 'F', 139.00)
                ]
                cursor.executemany(
                    "INSERT INTO productos (empresa, codigo, talla_letra, precio_base) VALUES (%s, %s, %s, %s)",
                    productos_base
                )
            conn.commit()
    except Exception as e:
        print(f"Error inicializando DB: {e}")
    finally:
        if conn:
            db_pool.put_connection(conn)
