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
        CREATE TABLE IF NOT EXISTS states (
            id INT PRIMARY KEY,
            name VARCHAR(50) UNIQUE NOT NULL,
            module VARCHAR(30) NOT NULL,
            description VARCHAR(150)
        )
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
            name VARCHAR(100) NOT NULL UNIQUE,
            state_id INT NOT NULL DEFAULT 1 REFERENCES states(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            company_id INT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
            code VARCHAR(50) NOT NULL,
            state_id INT NOT NULL DEFAULT 1 REFERENCES states(id),
            UNIQUE (company_id, code)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS base_price (
            id SERIAL PRIMARY KEY,
            product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            size_label CHAR(1) NOT NULL REFERENCES sizes(label),
            cost_without_discount NUMERIC(10, 2) NOT NULL,
            cost_with_discount NUMERIC(10, 2) NOT NULL,
            sale_price_suggested NUMERIC(10, 2) NOT NULL,
            state_id INT NOT NULL DEFAULT 1 REFERENCES states(id),
            UNIQUE (product_id, size_label)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sales (
            id SERIAL PRIMARY KEY,
            seller_id INT NOT NULL REFERENCES seller(id),
            product_id INT NOT NULL REFERENCES products(id),
            quantity_sold INT NOT NULL,
            historical_base_price NUMERIC(10, 2) NOT NULL,
            sale_price NUMERIC(10, 2) NOT NULL,
            commission INT NOT NULL,
            base_price_id INT REFERENCES base_price(id),
            created_at DATE DEFAULT CURRENT_DATE
        )
        """,
    ]

    conn = None
    try:
        conn = db_pool.get_connection()
        with conn.cursor() as cursor:
            for command in commands:
                cursor.execute(command)

            cursor.execute(
                """
                INSERT INTO states (id, name, module, description)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (1, "Activo", "general", "Registro activo")
            )
            sizes_base = [
                ('A', 20, 26), ('B', 27, 32), ('C', 33, 36), ('D', 37, 43),
                ('E', 16, 21), ('F', 19, 26), ('G', 5, 12), ('H', 34, 43),
                ('I', 37, 40), ('J', 33, 39), ('K', 33, 37)
            ]
            cursor.executemany(
                """
                INSERT INTO sizes (label, start_number, end_number)
                VALUES (%s, %s, %s)
                ON CONFLICT (label) DO NOTHING
                """,
                sizes_base
            )
            cursor.execute(
                "INSERT INTO seller (id, name, code) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (1, "Brandon Soria", 1)
            )

            companies_base = ["Kanguro", "Dicalsa", "Coban", "Roy", "Dibercati"]
            cursor.executemany(
                """
                INSERT INTO companies (name) VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                """,
                [(name,) for name in companies_base]
            )

            products_base = [
                ("Kanguro", "4144"),
                ("Kanguro", "4151"),
                ("Dicalsa", "856"),
                ("Dicalsa", "921 / 925 / 930 / 926"),
                ("Dicalsa", "940")
            ]
            cursor.executemany(
                """
                INSERT INTO products (company_id, code)
                SELECT id, %s FROM companies WHERE name = %s
                ON CONFLICT (company_id, code) DO NOTHING
                """,
                [(code, company) for company, code in products_base]
            )

            base_prices = [
                ("Kanguro", "4144", "A", 121.00, 121.00, 121.00),
                ("Kanguro", "4144", "B", 129.00, 129.00, 129.00),
                ("Kanguro", "4144", "C", 142.00, 142.00, 142.00),
                ("Kanguro", "4151", "A", 114.00, 114.00, 114.00),
                ("Kanguro", "4151", "B", 122.00, 122.00, 122.00),
                ("Kanguro", "4151", "C", 135.00, 135.00, 135.00),
                ("Dicalsa", "856", "F", 122.00, 122.00, 122.00),
                ("Dicalsa", "921 / 925 / 930 / 926", "F", 135.00, 135.00, 135.00),
                ("Dicalsa", "940", "F", 139.00, 139.00, 139.00)
            ]
            cursor.executemany(
                """
                INSERT INTO base_price (
                    product_id, size_label, cost_without_discount,
                    cost_with_discount, sale_price_suggested
                )
                SELECT p.id, %s, %s, %s, %s
                FROM products p
                JOIN companies c ON c.id = p.company_id
                WHERE c.name = %s AND p.code = %s
                ON CONFLICT (product_id, size_label) DO NOTHING
                """,
                [
                    (
                        size_label, cost_without_discount, cost_with_discount,
                        sale_price_suggested, company, code
                    )
                    for (
                        company, code, size_label, cost_without_discount,
                        cost_with_discount, sale_price_suggested
                    ) in base_prices
                ]
            )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            db_pool.put_connection(conn)
