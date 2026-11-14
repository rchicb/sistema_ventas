from app.repositories.base import BaseRepository


class UsuarioRepository(BaseRepository):
    def buscar_por_usuario(self, username: str):
        rows = self.execute_query(
            """
            SELECT u.id, u.username, u.password_hash, u.role, u.seller_id,
                   u.state_id, s.state_id AS seller_state_id
            FROM app_users u
            LEFT JOIN seller s ON s.id = u.seller_id
            WHERE lower(u.username) = lower(%s)
            """,
            (username.strip(),),
            fetch=True,
        )
        return rows[0] if rows else None

    def buscar_por_id(self, user_id: int):
        rows = self.execute_query(
            """
            SELECT u.id, u.username, u.role, u.seller_id, u.state_id,
                   s.state_id AS seller_state_id
            FROM app_users u
            LEFT JOIN seller s ON s.id = u.seller_id
            WHERE u.id = %s
            """,
            (user_id,),
            fetch=True,
        )
        return rows[0] if rows else None

    def listar_usuarios(self):
        return self.execute_query(
            """
            SELECT u.id, u.username, u.role, s.name, st.name, u.state_id
            FROM app_users u
            LEFT JOIN seller s ON s.id = u.seller_id
            JOIN states st ON st.id = u.state_id
            ORDER BY u.username
            """,
            fetch=True,
        )

    def listar_vendedores(self):
        return self.execute_query(
            """
            SELECT id, code, name
            FROM seller
            WHERE state_id = 1
            ORDER BY name
            """,
            fetch=True,
        )

    def contar_usuarios(self):
        rows = self.execute_query(
            "SELECT COUNT(*) FROM app_users",
            fetch=True,
        )
        return rows[0][0]

    def crear_usuario(
        self, username, password_hash, role, seller_id, state_id
    ):
        rows = self.execute_query(
            """
            INSERT INTO app_users (username, password_hash, role, seller_id, state_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (username.strip(), password_hash, role, seller_id, state_id),
            fetch=True,
        )
        return rows[0][0] if rows else None

    def actualizar_estado(self, user_id, state_id):
        rows = self.execute_query(
            """
            UPDATE app_users AS target
            SET state_id = %s
            WHERE target.id = %s
              AND (
                  target.role <> 'admin'
                  OR %s = 1
                  OR EXISTS (
                      SELECT 1
                      FROM app_users other_admin
                      WHERE other_admin.role = 'admin'
                        AND other_admin.state_id = 1
                        AND other_admin.id <> target.id
                  )
              )
            RETURNING id
            """,
            (state_id, user_id, state_id),
            fetch=True,
        )
        return bool(rows)

    def crear_administrador_inicial(
        self, username, password_hash
    ):
        rows = self.execute_query(
            """
            WITH lock_row AS (
                SELECT pg_advisory_xact_lock(753921640)
            ),
            new_admin AS (
                INSERT INTO app_users (username, password_hash, role, state_id)
                SELECT %s, %s, 'admin', 1
                FROM lock_row
                WHERE NOT EXISTS (SELECT 1 FROM app_users)
                ON CONFLICT DO NOTHING
                RETURNING id
            )
            SELECT id FROM new_admin
            """,
            (username.strip(), password_hash),
            fetch=True,
        )
        return bool(rows)
