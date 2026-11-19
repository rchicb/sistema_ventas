import os
import secrets

class Settings:
    DB_USER: str = os.getenv("DB_USER", "usuario_ventas")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "clave_segura_123")
    DB_NAME: str = os.getenv("DB_NAME", "db_sistema_ventas")
    DB_PORT: str = os.getenv("DB_PORT", "5432")
    DB_HOST: str = os.getenv("DB_HOST", "db")
    APP_PORT: int = int(os.getenv("APP_PORT", 8000))
    SESSION_SECRET_KEY: str = os.getenv(
        "SESSION_SECRET_KEY"
    ) or secrets.token_urlsafe(48)
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
    ADMIN_SETUP_KEY: str = os.getenv("ADMIN_SETUP_KEY", "")

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

settings = Settings()
