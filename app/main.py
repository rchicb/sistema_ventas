import os

from fastapi import FastAPI
from app.core.database import db_pool, init_db
from app.core.config import settings
from app.repositories.usuario import UsuarioRepository
from app.routers import auth, web
from app.services.auth import hash_password

app = FastAPI(title="Sistema Relacional de Ventas - SOLID")

app.include_router(web.router)
app.include_router(auth.router)

@app.on_event("startup")
def startup_event():
    db_pool.initialize()
    init_db()
    if settings.ADMIN_SETUP_KEY and len(settings.ADMIN_SETUP_KEY) < 24:
        raise RuntimeError("ADMIN_SETUP_KEY debe tener al menos 24 caracteres.")
    configured_session_key = os.getenv("SESSION_SECRET_KEY")
    if configured_session_key and len(configured_session_key) < 32:
        raise RuntimeError("SESSION_SECRET_KEY debe tener al menos 32 caracteres.")
    if bool(settings.ADMIN_USERNAME) != bool(settings.ADMIN_PASSWORD):
        raise RuntimeError(
            "Configure ADMIN_USERNAME y ADMIN_PASSWORD juntos para crear el administrador inicial."
        )
    if settings.ADMIN_USERNAME:
        if len(settings.ADMIN_PASSWORD) < 12 or len(settings.ADMIN_USERNAME.strip()) < 3:
            raise RuntimeError(
                "ADMIN_USERNAME debe tener 3 caracteres y ADMIN_PASSWORD al menos 12."
            )
        UsuarioRepository().crear_administrador_inicial(
            settings.ADMIN_USERNAME, hash_password(settings.ADMIN_PASSWORD)
        )

@app.on_event("shutdown")
def shutdown_event():
    db_pool.close_all()
