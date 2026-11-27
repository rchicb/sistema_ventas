from fastapi import Depends, HTTPException, Request

from app.repositories.base import CatalogRepository
from app.repositories.contracts import (
    CatalogRepositoryPort,
    SalesRepositoryPort,
    UserRepositoryPort,
)
from app.repositories.usuario import UsuarioRepository
from app.repositories.venta import VentaRepository
from app.services.sessions import SESSION_COOKIE, read_session_user_id


def get_catalog_repo() -> CatalogRepositoryPort:
    return CatalogRepository()


def get_venta_repo() -> SalesRepositoryPort:
    return VentaRepository()


def get_usuario_repo() -> UserRepositoryPort:
    return UsuarioRepository()


def usuario_actual(
    request: Request,
    usuario_repo: UserRepositoryPort = Depends(get_usuario_repo),
):
    token = request.cookies.get(SESSION_COOKIE)
    user_id = read_session_user_id(token) if token else None
    usuario = usuario_repo.buscar_por_id(user_id) if user_id else None
    if (
        not usuario
        or usuario["state_id"] != 1
        or (
            usuario["role"] == "vendedor"
            and usuario["seller_state_id"] != 1
        )
    ):
        raise HTTPException(
            status_code=303,
            headers={"Location": "/login"},
        )
    return usuario


def administrador_actual(usuario=Depends(usuario_actual)):
    if usuario["role"] != "admin":
        raise HTTPException(status_code=403, detail="Acceso solo para administradores.")
    return usuario
