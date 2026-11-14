from fastapi import Depends, HTTPException, Request

from app.repositories.usuario import UsuarioRepository
from app.services.auth import SESSION_COOKIE, read_session_user_id


def get_usuario_repo():
    return UsuarioRepository()


def usuario_actual(
    request: Request,
    usuario_repo: UsuarioRepository = Depends(get_usuario_repo),
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
