from datetime import date, timedelta

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse,HTMLResponse
from fastapi.templating import Jinja2Templates
from app.repositories.venta import VentaRepository
from app.repositories.base import BaseRepository
from app.repositories.usuario import UsuarioRepository
from app.core.dependencies import (
    administrador_actual,
    get_usuario_repo,
    usuario_actual,
)
from app.services.auth import hash_password
from app.services.pricing import PricingService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
GASTOS_CATEGORIAS = (
    "Comida", "Refacciones", "Tortillas", "Frescos",
    "Desayuno", "Almuerzo", "Pago Bodega","Pago Puestos","Otros gastos varios"
)

def get_venta_repo(): return VentaRepository()
def get_base_repo(): return BaseRepository()

@router.get("/")
def dashboard(
    request: Request,
    fecha: str = None,
    mes: str = None,
    semana: str = None,
    vendedor_id: int = None,
    venta_repo: VentaRepository = Depends(get_venta_repo),
    base_repo: BaseRepository = Depends(get_base_repo),
    usuario=Depends(usuario_actual),
):
    es_admin = usuario["role"] == "admin"
    if not es_admin:
        if not usuario["seller_id"]:
            raise HTTPException(status_code=403, detail="La cuenta no tiene vendedor asignado.")
        if vendedor_id is not None and vendedor_id != usuario["seller_id"]:
            raise HTTPException(status_code=403, detail="No puede consultar reportes de otros vendedores.")
        vendedor_id = usuario["seller_id"]

    filtros_periodo = [value for value in (fecha, mes, semana) if value]
    if len(filtros_periodo) > 1:
        raise HTTPException(
            status_code=400,
            detail="Seleccione solo un filtro de período: fecha, mes o semana.",
        )

    fecha_inicio = fecha_fin = None
    try:
        if fecha:
            fecha_inicio = date.fromisoformat(fecha)
            fecha_fin = fecha_inicio + timedelta(days=1)
        elif mes:
            primer_dia = date.fromisoformat(f"{mes}-01")
            siguiente_mes = (
                date(primer_dia.year + 1, 1, 1)
                if primer_dia.month == 12
                else date(primer_dia.year, primer_dia.month + 1, 1)
            )
            fecha_inicio, fecha_fin = primer_dia, siguiente_mes
        elif semana:
            anio, numero_semana = semana.split("-W", 1)
            fecha_inicio = date.fromisocalendar(int(anio), int(numero_semana), 1)
            fecha_fin = fecha_inicio + timedelta(days=7)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400, detail="El filtro de fecha, mes o semana no es válido."
        )

    raw_ventas = venta_repo.obtener_reporte_ganancias(
        fecha_inicio, fecha_fin, vendedor_id
    ) or []
    
    ventas_procesadas = []
    total_bruto = 0.0
    total_comisiones = 0.0
    utilidad_antes_gastos = 0.0
    
    for item in raw_ventas:
        (
            v_id, v_nombre, p_empresa, p_codigo, p_talla, p_base, p_vendido,
            porc_comision, fecha_venta, numero_vendido
        ) = item
        
        p_base = float(p_base)
        p_vendido = float(p_vendido)
        porc_comision = float(porc_comision)
        
        comision = PricingService.calcular_ganancia_vendedor(porc_comision)
        utilidad = PricingService.calcular_utilidad_empresa(p_vendido, p_base, comision)
        
        total_bruto += p_vendido
        total_comisiones += comision
        utilidad_antes_gastos += utilidad
        
        ventas_procesadas.append({
            "id": v_id, "vendedor": v_nombre, "empresa": p_empresa, "codigo": p_codigo,
            "talla": p_talla, "base": p_base, "vendido": p_vendido, "comision": comision,
            "utilidad": utilidad, "fecha": fecha_venta, "numero_vendido": numero_vendido
        })

    if es_admin:
        gastos = venta_repo.obtener_gastos(fecha_inicio, fecha_fin) or []
        total_gastos = sum(float(gasto[4]) for gasto in gastos)
        total_utilidad = round(utilidad_antes_gastos - total_gastos, 2)
        vendedores = base_repo.execute_query(
            "SELECT id, name FROM seller WHERE state_id = 1 ORDER BY name",
            fetch=True,
        ) or []
    else:
        gastos = []
        total_gastos = 0
        total_utilidad = 0
        vendedores = []
    reporte_vendedores = venta_repo.obtener_reporte_vendedores(
        fecha_inicio, fecha_fin, vendedor_id
    ) or []

    # SOLUCIÓN INGENIERIL: Forzamos el contexto directamente a través del motor Jinja2 subyacente
    # Esto evita que Starlette intente procesar o mutar el diccionario en sus middlewares internos
    html_content = templates.env.get_template("dashboard.html").render(
        request=request,
        ventas=ventas_procesadas,
        total_bruto=round(total_bruto, 2),
        total_comisiones=round(total_comisiones, 2),
        utilidad_antes_gastos=round(utilidad_antes_gastos, 2),
        total_gastos=round(total_gastos, 2),
        total_utilidad=total_utilidad,
        gastos=gastos,
        categorias_gastos=GASTOS_CATEGORIAS,
        reporte_vendedores=reporte_vendedores,
        vendedores=vendedores,
        filtro_fecha=fecha or "",
        filtro_mes=mes or "",
        filtro_semana=semana or "",
        vendedor_seleccionado=vendedor_id,
        fecha_hoy=date.today().isoformat(),
        usuario=usuario,
        es_admin=es_admin,
    )
    return HTMLResponse(content=html_content)

@router.get("/formularios")
def mostrar_formularios(
    request: Request,
    base_repo: BaseRepository = Depends(get_base_repo),
    usuario=Depends(usuario_actual),
):
    es_admin = usuario["role"] == "admin"
    if es_admin:
        vendedores = base_repo.execute_query(
            "SELECT id, name, code FROM seller WHERE state_id = 1 ORDER BY name",
            fetch=True,
        ) or []
    else:
        vendedores = base_repo.execute_query(
            "SELECT id, name, code FROM seller WHERE id = %s AND state_id = 1",
            (usuario["seller_id"],),
            fetch=True,
        ) or []
        if not vendedores:
            raise HTTPException(status_code=403, detail="El vendedor asociado está inactivo.")
    productos = base_repo.execute_query(
        """
        SELECT bp.id, c.name, p.code, ' [' || s.start_number || ' - ' || s.end_number|| ' ]', 
        bp.cost_without_discount, bp.cost_with_discount, bp.sale_price_suggested,
        s.start_number, s.end_number
        FROM products p
        JOIN companies c ON c.id = p.company_id
        JOIN base_price bp ON bp.product_id = p.id
        JOIN sizes s ON bp.size_label = s.label
        WHERE bp.state_id = 1 AND p.state_id = 1 AND c.state_id = 1 AND s.state_id = 1
        ORDER BY c.name, p.code, bp.size_label
        """,
        fetch=True
    )
    tallas = base_repo.execute_query(
        """
        SELECT label, start_number || ' - ' || end_number
        FROM sizes
        WHERE state_id = 1
        ORDER BY label
        """,
        fetch=True
    )
    estados = [(1, "Activo"), (2, "Inactivo")]
    empresas = []
    tallas = tallas or []
    if es_admin:
        empresas = base_repo.execute_query(
            "SELECT id, name FROM companies WHERE state_id = 1 ORDER BY name",
            fetch=True,
        ) or []
        usuarios = UsuarioRepository().listar_usuarios() or []
        vendedores_disponibles = UsuarioRepository().listar_vendedores() or []
    else:
        usuarios = []
        vendedores_disponibles = []
    
    # Usamos .render() directo para saltarnos el middleware conflictivo de Starlette
    html_content = templates.env.get_template("formularios.html").render(
        request=request, 
        vendedores=vendedores, 
        productos=productos, 
        tallas=tallas,
        estados=estados,
        empresas=empresas,
        es_admin=es_admin,
        usuario=usuario,
        usuarios=usuarios,
        vendedores_disponibles=vendedores_disponibles,
    )
    return HTMLResponse(content=html_content)

@router.post("/ventas/registrar")
def registrar_venta(
    base_price_id: int = Form(..., ge=1),
    precio_vendido: float = Form(..., gt=0),
    porcentaje_ganancia: int = Form(...),
    numero_vendido: int = Form(..., ge=1),
    vendedor_id: int = Form(None, ge=1),
    venta_repo: VentaRepository = Depends(get_venta_repo),
    usuario=Depends(usuario_actual),
):
    if usuario["role"] == "vendedor":
        vendedor_id = usuario["seller_id"]
    elif vendedor_id is None:
        raise HTTPException(status_code=400, detail="Debe seleccionar un vendedor.")
    if porcentaje_ganancia not in (5, 10, 15, 20):
        raise HTTPException(status_code=400, detail="El porcentaje de comisión no es válido.")
    try:
        venta_repo.registrar_venta(
            vendedor_id, base_price_id, precio_vendido, porcentaje_ganancia,
            numero_vendido
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return RedirectResponse(url="/", status_code=303)

@router.post("/gastos/registrar")
def registrar_gasto(
    fecha: date = Form(...),
    categoria: str = Form(...),
    monto: float = Form(..., ge=0),
    descripcion: str = Form(""),
    venta_repo: VentaRepository = Depends(get_venta_repo),
    usuario=Depends(administrador_actual),
):
    if categoria not in GASTOS_CATEGORIAS:
        raise HTTPException(status_code=400, detail="La categoría de gasto no es válida.")
    venta_repo.registrar_gasto(fecha, categoria, descripcion, monto)
    return RedirectResponse(url="/", status_code=303)

@router.post("/gastos/modificar")
def modificar_gasto(
    gasto_id: int = Form(..., ge=1),
    fecha: date = Form(...),
    categoria: str = Form(...),
    monto: float = Form(..., ge=0),
    descripcion: str = Form(""),
    venta_repo: VentaRepository = Depends(get_venta_repo),
    usuario=Depends(administrador_actual),
):
    if categoria not in GASTOS_CATEGORIAS:
        raise HTTPException(status_code=400, detail="La categoría de gasto no es válida.")
    try:
        venta_repo.actualizar_gasto(gasto_id, fecha, categoria, descripcion, monto)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    return RedirectResponse(url="/", status_code=303)

@router.post("/vendedores/pagos")
def registrar_pago_vendedor(
    vendedor_id: int = Form(...),
    fecha: date = Form(...),
    monto: float = Form(..., ge=0),
    notas: str = Form(""),
    venta_repo: VentaRepository = Depends(get_venta_repo),
    usuario=Depends(administrador_actual),
):
    venta_repo.registrar_pago_vendedor(vendedor_id, fecha, monto, notas)
    return RedirectResponse(url="/", status_code=303)

@router.post("/vendedores/agregar")
def agregar_vendedor(
    id: int = Form(..., ge=1),
    code: int = Form(..., ge=1),
    nombre: str = Form(...),
    estado_id: int = Form(...),
    base_repo: BaseRepository = Depends(get_base_repo),
    usuario=Depends(administrador_actual),
):
    if estado_id not in (1, 2):
        raise HTTPException(status_code=400, detail="El estado seleccionado no es válido.")
    base_repo.execute_query(
        "INSERT INTO seller (id, name, code, state_id) VALUES (%s, %s, %s, %s)",
        (id, nombre, code, estado_id)
    )
    return RedirectResponse(url="/formularios", status_code=303)

@router.post("/productos/agregar")
def agregar_producto(
    codigo: str = Form(...),
    talla_letra: str = Form(...),
    precio_base: float = Form(..., gt=0),
    estado_id: int = Form(...),
    empresa_id: int = Form(None),
    nueva_empresa: str = Form(""),
    base_repo: BaseRepository = Depends(get_base_repo),
    usuario=Depends(administrador_actual),
):
    if estado_id not in (1, 2):
        raise HTTPException(status_code=400, detail="El estado seleccionado no es válido.")
    if not base_repo.execute_query(
        "SELECT label FROM sizes WHERE label = %s",
        (talla_letra.upper(),),
        fetch=True,
    ):
        raise HTTPException(status_code=400, detail="La categoría de talla no existe.")
    if empresa_id:
        empresa = base_repo.execute_query(
            "SELECT id FROM companies WHERE id = %s AND state_id = 1",
            (empresa_id,),
            fetch=True,
        )
        if not empresa:
            raise HTTPException(status_code=400, detail="La marca seleccionada no está activa.")
        company_id = empresa[0][0]
    else:
        nombre_empresa = nueva_empresa.strip()
        if not nombre_empresa:
            raise HTTPException(status_code=400, detail="Seleccione una marca o escriba una nueva.")
        empresa = base_repo.execute_query(
            """
            INSERT INTO companies (name, state_id)
            VALUES (%s, %s)
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id, state_id
            """,
            (nombre_empresa, estado_id),
            fetch=True,
        )
        company_id, company_state = empresa[0]
        if company_state != 1 and estado_id == 1:
            raise HTTPException(status_code=400, detail="La marca existente está inactiva.")

    producto = base_repo.execute_query(
        """
        INSERT INTO products (company_id, code, state_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (company_id, code)
        DO UPDATE SET state_id = EXCLUDED.state_id
        RETURNING id
        """,
        (company_id, codigo.strip(), estado_id),
        fetch=True,
    )
    product_id = producto[0][0]
    base_repo.execute_query(
        """
        INSERT INTO base_price (
            product_id, size_label, cost_without_discount, cost_with_discount,
            sale_price_suggested, state_id
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (product_id, size_label)
        DO UPDATE SET cost_without_discount = EXCLUDED.cost_without_discount,
                      cost_with_discount = EXCLUDED.cost_with_discount,
                      sale_price_suggested = EXCLUDED.sale_price_suggested,
                      state_id = EXCLUDED.state_id
        """,
        (product_id, talla_letra, precio_base, precio_base, precio_base, estado_id),
    )
    return RedirectResponse(url="/formularios", status_code=303)

@router.post("/tallas/agregar")
def agregar_talla(
    letra: str = Form(...),
    rango: str = Form(...),
    estado_id: int = Form(...),
    base_repo: BaseRepository = Depends(get_base_repo),
    usuario=Depends(administrador_actual),
):
    try:
        inicio, fin = [int(value.strip()) for value in rango.split("-", 1)]
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="El rango debe tener el formato 42 - 46.")
    if estado_id not in (1, 2) or inicio > fin:
        raise HTTPException(status_code=400, detail="El estado o el rango de talla no es válido.")
    base_repo.execute_query(
        """
        INSERT INTO sizes (label, start_number, end_number, state_id)
        VALUES (%s, %s, %s, %s)
        """,
        (letra.upper(), inicio, fin, estado_id)
    )
    return RedirectResponse(url="/formularios", status_code=303)

@router.post("/usuarios/agregar")
def agregar_usuario(
    username: str = Form(..., min_length=3, max_length=80),
    password: str = Form(..., min_length=12, max_length=256),
    role: str = Form(...),
    seller_id: int = Form(None),
    estado_id: int = Form(...),
    usuario_repo: UsuarioRepository = Depends(get_usuario_repo),
    usuario=Depends(administrador_actual),
):
    if len(username.strip()) < 3:
        raise HTTPException(
            status_code=400, detail="El usuario debe tener al menos 3 caracteres."
        )
    if role not in ("admin", "vendedor") or estado_id not in (1, 2):
        raise HTTPException(status_code=400, detail="El rol o estado seleccionado no es válido.")
    if role == "vendedor":
        if seller_id is None or not usuario_repo.execute_query(
            "SELECT id FROM seller WHERE id = %s AND state_id = 1",
            (seller_id,),
            fetch=True,
        ):
            raise HTTPException(status_code=400, detail="Seleccione un vendedor válido.")
    else:
        seller_id = None

    user_id = usuario_repo.crear_usuario(
        username, hash_password(password), role, seller_id, estado_id
    )
    if user_id is None:
        raise HTTPException(
            status_code=409,
            detail="El usuario o vendedor ya tiene una cuenta registrada.",
        )
    return RedirectResponse(url="/formularios", status_code=303)

@router.get("/usuarios")
def administrar_usuarios(usuario=Depends(administrador_actual)):
    return RedirectResponse(url="/formularios#usuarios", status_code=303)

@router.post("/usuarios/estado")
def actualizar_estado_usuario(
    usuario_id: int = Form(..., ge=1),
    estado_id: int = Form(...),
    usuario_repo: UsuarioRepository = Depends(get_usuario_repo),
    usuario=Depends(administrador_actual),
):
    if estado_id not in (1, 2):
        raise HTTPException(status_code=400, detail="El estado seleccionado no es válido.")
    if usuario_id == usuario["id"] and estado_id != 1:
        raise HTTPException(status_code=400, detail="No puede desactivar su propia cuenta.")
    if not usuario_repo.actualizar_estado(usuario_id, estado_id):
        raise HTTPException(
            status_code=400,
            detail="No se puede desactivar el último administrador activo o el usuario no existe.",
        )
    return RedirectResponse(url="/formularios#usuarios", status_code=303)
