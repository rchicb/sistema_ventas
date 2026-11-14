import hmac

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.core.dependencies import get_usuario_repo
from app.repositories.usuario import UsuarioRepository
from app.services.auth import (
    SESSION_COOKIE,
    create_session_token,
    hash_password,
    read_session_user_id,
    verify_password,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def render_login(request, message="", status_code=200):
    repo = UsuarioRepository()
    users_exist = repo.contar_usuarios() > 0
    initial_setup_available = not users_exist and bool(settings.ADMIN_SETUP_KEY)
    return HTMLResponse(
        templates.env.get_template("login.html").render(
            request=request,
            message=message,
            initial_setup_available=initial_setup_available,
            initial_setup_needed=not users_exist,
            setup_key_configured=bool(settings.ADMIN_SETUP_KEY),
        ),
        status_code=status_code,
    )


def set_login_cookie(response, request, user_id):
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(user_id),
        max_age=12 * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


@router.get("/login")
def login_page(
    request: Request,
    usuario_repo: UsuarioRepository = Depends(get_usuario_repo),
):
    user_id = read_session_user_id(request.cookies.get(SESSION_COOKIE, ""))
    usuario = usuario_repo.buscar_por_id(user_id) if user_id else None
    if (
        usuario
        and usuario["state_id"] == 1
        and (
            usuario["role"] == "admin"
            or usuario["seller_state_id"] == 1
        )
    ):
        return RedirectResponse("/", status_code=303)
    return render_login(request)


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    usuario_repo: UsuarioRepository = Depends(get_usuario_repo),
):
    usuario = usuario_repo.buscar_por_usuario(username)
    if (
        not usuario
        or usuario["state_id"] != 1
        or (
            usuario["role"] == "vendedor"
            and usuario["seller_state_id"] != 1
        )
        or not verify_password(password, usuario["password_hash"])
    ):
        return render_login(request, "Usuario o contraseña incorrectos.", 401)

    response = RedirectResponse("/", status_code=303)
    set_login_cookie(response, request, usuario["id"])
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/setup-admin")
def setup_admin(
    request: Request,
    setup_key: str = Form(...),
    username: str = Form(..., min_length=3, max_length=80),
    password: str = Form(..., min_length=12, max_length=256),
    usuario_repo: UsuarioRepository = Depends(get_usuario_repo),
):
    if len(username.strip()) < 3:
        return render_login(request, "El usuario debe tener al menos 3 caracteres.", 400)
    if (
        not settings.ADMIN_SETUP_KEY
        or not hmac.compare_digest(setup_key, settings.ADMIN_SETUP_KEY)
    ):
        return render_login(request, "La clave de configuración no es válida.", 403)
    created = usuario_repo.crear_administrador_inicial(
        username, hash_password(password)
    )
    if not created:
        return render_login(
            request,
            "La configuración inicial ya fue completada o el usuario ya existe.",
            409,
        )
    return RedirectResponse("/login", status_code=303)
