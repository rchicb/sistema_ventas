import math
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.services.reporting import procesar_reporte_ventas, ventas_del_dia
from app.repositories.contracts import (
    CatalogRepositoryPort,
    SalesRepositoryPort,
    UserRepositoryPort,
)
from app.core.time import fecha_actual_guatemala
from app.core.dependencies import (
    administrador_actual,
    get_catalog_repo,
    get_venta_repo,
    get_usuario_repo,
    usuario_actual,
)
from app.services.passwords import hash_password

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
GASTOS_CATEGORIAS = (
    "Comida", "Refacciones", "Tortillas", "Frescos",
    "Desayuno", "Almuerzo", "Pago Bodega","Pago Puestos","Otros gastos varios"
)
COMISIONES_PERMITIDAS = frozenset(
    Decimal(monto) for monto in ("0", "2", "3", "5", "10", "15", "20")
)

def url_reporte_ventas(
    fecha=None,
    mes=None,
    fecha_inicio=None,
    fecha_fin=None,
    vendedor_id=None,
    todos=False,
):
    filtros = {
        nombre: valor
        for nombre, valor in (
            ("fecha", fecha),
            ("mes", mes),
            ("fecha_inicio", fecha_inicio),
            ("fecha_fin", fecha_fin),
            ("vendedor_id", vendedor_id),
            ("todos", "true" if todos else None),
        )
        if valor not in (None, "")
    }
    return f"/?{urlencode(filtros)}" if filtros else "/"

@router.get("/")
def dashboard(
    request: Request,
    fecha: str = None,
    mes: str = None,
    fecha_inicio: str = None,
    fecha_fin: str = None,
    todos: bool = False,
    vendedor_id: int = None,
    historial_vendedor_id: int = None,
    estado_pago: str = "",
    pago_vendedor_id: int = None,
    pago_fecha_venta: str = "",
    filtro_aplicado: bool = False,
    venta_repo: SalesRepositoryPort = Depends(get_venta_repo),
    base_repo: CatalogRepositoryPort = Depends(get_catalog_repo),
    usuario=Depends(usuario_actual),
):
    if fecha or mes or fecha_inicio or fecha_fin:
        todos = False
    elif not todos:
        fecha = fecha_actual_guatemala().isoformat()

    es_admin = usuario["role"] == "admin"
    if estado_pago not in ("", "pagado", "parcial", "pendiente"):
        raise HTTPException(
            status_code=400, detail="El estado de pago seleccionado no es válido."
        )
    if not es_admin:
        if not usuario["seller_id"]:
            raise HTTPException(status_code=403, detail="La cuenta no tiene vendedor asignado.")
        if vendedor_id is not None and vendedor_id != usuario["seller_id"]:
            raise HTTPException(status_code=403, detail="No puede consultar reportes de otros vendedores.")
        vendedor_id = usuario["seller_id"]
        historial_vendedor_id = None

    if bool(fecha_inicio) != bool(fecha_fin):
        raise HTTPException(
            status_code=400,
            detail="Seleccione una fecha inicial y una fecha final para el rango.",
        )
    cantidad_periodos = sum(
        (bool(fecha), bool(mes), bool(fecha_inicio and fecha_fin))
    )
    if cantidad_periodos > 1:
        raise HTTPException(
            status_code=400, detail="Seleccione solo un filtro: día, mes o rango."
        )

    inicio_periodo = fin_periodo = None
    try:
        if fecha:
            inicio_periodo = date.fromisoformat(fecha)
            fin_periodo = inicio_periodo + timedelta(days=1)
        elif mes:
            primer_dia = date.fromisoformat(f"{mes}-01")
            siguiente_mes = (
                date(primer_dia.year + 1, 1, 1)
                if primer_dia.month == 12
                else date(primer_dia.year, primer_dia.month + 1, 1)
            )
            inicio_periodo, fin_periodo = primer_dia, siguiente_mes
        elif fecha_inicio and fecha_fin:
            inicio_periodo = date.fromisoformat(fecha_inicio)
            fecha_final = date.fromisoformat(fecha_fin)
            if inicio_periodo > fecha_final:
                raise HTTPException(
                    status_code=400,
                    detail="La fecha inicial no puede ser posterior a la fecha final.",
                )
            fin_periodo = fecha_final + timedelta(days=1)
    except (ValueError, TypeError, OverflowError):
        raise HTTPException(
            status_code=400, detail="El filtro de fecha, mes o rango no es válido."
        )

    raw_ventas = venta_repo.obtener_reporte_ganancias(
        inicio_periodo, fin_periodo, vendedor_id
    ) or []
    
    (
        ventas_procesadas,
        total_bruto,
        total_comisiones,
        utilidad_antes_gastos,
    ) = procesar_reporte_ventas(raw_ventas)

    if historial_vendedor_id is not None or estado_pago:
        historial_raw_ventas = venta_repo.obtener_reporte_ganancias(
            inicio_periodo,
            fin_periodo,
            vendedor_id,
            historial_vendedor_id,
            estado_pago or None,
        ) or []
        ventas_ids_historial = {venta[0] for venta in historial_raw_ventas}
        ventas_procesadas = [
            venta for venta in ventas_procesadas
            if venta["id"] in ventas_ids_historial
        ]

    if es_admin:
        gastos = venta_repo.obtener_gastos(inicio_periodo, fin_periodo) or []
        total_gastos = sum(float(gasto[4]) for gasto in gastos)
        total_utilidad = round(utilidad_antes_gastos - total_gastos, 2)
        vendedores = base_repo.execute_query(
            "SELECT id, name FROM seller WHERE state_id = 1 ORDER BY name",
            fetch=True,
        ) or []
        administradores = base_repo.execute_query(
            """
            SELECT id, username FROM app_users
            WHERE role = 'admin' AND state_id = 1
            ORDER BY username
            """,
            fetch=True,
        ) or []
    else:
        gastos = []
        total_gastos = 0
        total_utilidad = 0
        vendedores = []
        administradores = []
    vendedor_ids_activos = {vendedor[0] for vendedor in vendedores}
    if pago_vendedor_id is not None and pago_vendedor_id not in vendedor_ids_activos:
        raise HTTPException(
            status_code=400, detail="El vendedor del filtro de pagos no está activo."
        )
    vendedor_pago_seleccionado = (
        pago_vendedor_id
        if pago_vendedor_id is not None
        else (vendedores[0][0] if vendedores else None)
    )
    try:
        fecha_filtro_pago = (
            date.fromisoformat(pago_fecha_venta) if pago_fecha_venta else None
        )
    except ValueError:
        raise HTTPException(
            status_code=400, detail="La fecha del filtro de pagos no es válida."
        )
    fecha_ventas_pago = fecha_filtro_pago or (
        date.fromisoformat(fecha) if fecha else None
    )
    ventas_pendientes_pago = (
        venta_repo.obtener_ventas_pendientes_pago(
            vendedor_pago_seleccionado, inicio_periodo, fin_periodo
        ) or []
        if es_admin and vendedor_pago_seleccionado is not None else []
    )
    reporte_vendedores = venta_repo.obtener_reporte_vendedores(
        inicio_periodo, fin_periodo, vendedor_id
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
        filtro_fecha_inicio=fecha_inicio or "",
        filtro_fecha_fin=fecha_fin or "",
        filtro_todos=todos,
        vendedor_seleccionado=vendedor_id,
        historial_vendedor_seleccionado=historial_vendedor_id,
        estado_pago_seleccionado=estado_pago,
        pago_fecha_ventas=fecha_ventas_pago,
        filtro_aplicado=filtro_aplicado,
        administradores=administradores,
        ventas_pendientes_pago=ventas_pendientes_pago,
        vendedor_pago_seleccionado=vendedor_pago_seleccionado,
        fecha_hoy=fecha_actual_guatemala().isoformat(),
        usuario=usuario,
        es_admin=es_admin,
    )
    return HTMLResponse(content=html_content)

@router.get("/formularios")
def mostrar_formularios(
    request: Request,
    marca_filtro: str = "",
    codigo_filtro: str = "",
    busqueda_filtro: str = "",
    duplicado_id: int = None,
    base_repo: CatalogRepositoryPort = Depends(get_catalog_repo),
    usuario_repo: UserRepositoryPort = Depends(get_usuario_repo),
    usuario=Depends(administrador_actual),
):
    marca_filtro = marca_filtro.strip()
    marca_filtro_id = None
    if marca_filtro:
        try:
            marca_filtro_id = int(marca_filtro)
        except ValueError:
            raise HTTPException(status_code=400, detail="La marca seleccionada no es válida.")
    codigo_filtro = codigo_filtro.strip()
    busqueda_filtro = busqueda_filtro.strip()
    productos_catalogo = []
    filtros_catalogo_aplicados = bool(
        marca_filtro_id or codigo_filtro or busqueda_filtro
    )
    if filtros_catalogo_aplicados:
        condiciones = []
        parametros = []
        if marca_filtro_id:
            condiciones.append("c.id = %s")
            parametros.append(marca_filtro_id)
        if codigo_filtro:
            condiciones.append("p.code ILIKE %s")
            parametros.append(f"%{codigo_filtro}%")
        if busqueda_filtro:
            condiciones.append(
                "(c.name ILIKE %s OR p.code ILIKE %s OR p.description ILIKE %s)"
            )
            termino = f"%{busqueda_filtro}%"
            parametros.extend((termino, termino, termino))
        if duplicado_id:
            parametros.append(duplicado_id)
        productos_catalogo = base_repo.execute_query(
            f"""
            SELECT bp.id, p.id, c.id, c.name, p.code, bp.size_label,
                   s.start_number, s.end_number, bp.cost_without_discount,
                   bp.cost_with_discount, bp.sale_price_suggested,
                   COALESCE(bp.state_id, p.state_id),
                   p.description,
                   ARRAY(
                       SELECT pc.color_id
                       FROM product_colors pc
                       WHERE pc.product_id = p.id
                       ORDER BY pc.color_id
                   )
            FROM products p
            JOIN companies c ON c.id = p.company_id
            LEFT JOIN base_price bp ON bp.product_id = p.id
            LEFT JOIN sizes s ON bp.size_label = s.label
            WHERE ({" AND ".join(condiciones)})
            {"OR bp.id = %s" if duplicado_id else ""}
            ORDER BY c.name, p.code, bp.size_label, bp.id
            """,
            tuple(parametros),
            fetch=True,
        ) or []
    tallas = base_repo.execute_query(
        """
        SELECT label, start_number || ' - ' || end_number
        FROM sizes
        ORDER BY label
        """,
        fetch=True
    ) or []
    estados = [(1, "Activo"), (2, "Inactivo")]
    empresas = base_repo.execute_query(
        "SELECT id, name FROM companies WHERE state_id = 1 ORDER BY name",
        fetch=True,
    ) or []
    empresas_catalogo = base_repo.execute_query(
        "SELECT id, name FROM companies ORDER BY name",
        fetch=True,
    ) or []
    colores = base_repo.execute_query(
        "SELECT id, name FROM colors ORDER BY name",
        fetch=True,
    ) or []
    productos_asignacion_colores = base_repo.execute_query(
        """
        SELECT p.id, c.name, p.code, p.description,
               ARRAY(
                   SELECT pc.color_id
                   FROM product_colors pc
                   WHERE pc.product_id = p.id
                   ORDER BY pc.color_id
               )
        FROM products p
        JOIN companies c ON c.id = p.company_id
        ORDER BY c.name, p.code
        """,
        fetch=True,
    ) or []
    productos_para_colores = [
        {
            "id": producto[0],
            "label": f"{producto[1]} · {producto[2]}"
            + (f" — {producto[3]}" if producto[3] else ""),
            "color_ids": producto[4],
        }
        for producto in productos_asignacion_colores
    ]
    tallas_activas = base_repo.execute_query(
        """
        SELECT label, start_number || ' - ' || end_number
        FROM sizes
        WHERE state_id = 1
        ORDER BY label
        """,
        fetch=True,
    ) or []
    usuarios = usuario_repo.listar_usuarios() or []
    vendedores_disponibles = usuario_repo.listar_vendedores() or []

    # Usamos .render() directo para saltarnos el middleware conflictivo de Starlette
    html_content = templates.env.get_template("formularios.html").render(
        request=request,
        productos_catalogo=productos_catalogo,
        marca_filtro=marca_filtro_id,
        codigo_filtro=codigo_filtro,
        busqueda_filtro=busqueda_filtro,
        filtros_catalogo_aplicados=filtros_catalogo_aplicados,
        duplicado_id=duplicado_id,
        tallas=tallas_activas,
        tallas_catalogo=tallas,
        estados=estados,
        empresas=empresas,
        empresas_catalogo=empresas_catalogo,
        colores=colores,
        productos_para_colores=productos_para_colores,
        es_admin=True,
        usuario=usuario,
        usuarios=usuarios,
        vendedores_disponibles=vendedores_disponibles,
    )
    return HTMLResponse(content=html_content)

@router.get("/ventas")
def mostrar_ventas(
    request: Request,
    fecha: str = "",
    duplicar_id: int = None,
    vendedor_id: int = None,
    venta_repo: SalesRepositoryPort = Depends(get_venta_repo),
    base_repo: CatalogRepositoryPort = Depends(get_catalog_repo),
    usuario=Depends(usuario_actual),
):
    es_admin = usuario["role"] == "admin"
    if es_admin:
        vendedores = base_repo.execute_query(
            """
            SELECT id, name, code
            FROM seller
            WHERE state_id = 1
            ORDER BY code, name, id
            """,
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

    try:
        fecha_consulta = date.fromisoformat(fecha) if fecha else fecha_actual_guatemala()
    except ValueError:
        raise HTTPException(status_code=400, detail="La fecha de venta no es válida.")

    form_venta = {}
    if vendedor_id is not None and any(
        vendedor[0] == vendedor_id for vendedor in vendedores
    ):
        form_venta["vendedor_id"] = vendedor_id
    if duplicar_id is not None:
        venta = venta_repo.obtener_venta_para_editar(duplicar_id)
        if not venta:
            raise HTTPException(status_code=404, detail="No se encontró la venta que desea duplicar.")
        comisiones = venta_repo.obtener_comisiones_venta(duplicar_id) or []
        comisiones_por_vendedor = {
            vendedor_id: comision for vendedor_id, comision in comisiones
        }
        if not es_admin and usuario["seller_id"] not in comisiones_por_vendedor:
            raise HTTPException(status_code=403, detail="No puede duplicar esta venta.")

        if fecha:
            fecha_venta = fecha_consulta
        else:
            fecha_venta = venta[10]
            fecha_consulta = fecha_venta

        if es_admin:
            vendedor_primario_id = venta[1]
            vendedor_secundario_id = next(
                (
                    vendedor_id for vendedor_id in comisiones_por_vendedor
                    if vendedor_id != vendedor_primario_id
                ),
                None,
            )
        else:
            vendedor_primario_id = usuario["seller_id"]
            vendedor_secundario_id = (
                venta[1] if venta[1] != vendedor_primario_id else next(
                    (
                        vendedor_id for vendedor_id in comisiones_por_vendedor
                        if vendedor_id != vendedor_primario_id
                    ),
                    None,
                )
            )

        if es_admin and not any(
            vendedor[0] == vendedor_primario_id for vendedor in vendedores
        ):
            raise HTTPException(status_code=409, detail="El vendedor de la venta original ya no está activo.")
        form_venta = {
            "vendedor_id": vendedor_primario_id,
            "segundo_vendedor_id": vendedor_secundario_id,
            "sucursal_id": venta[2],
            "base_price_id": venta[9],
            "color_id": venta[4],
            "number_sold": venta[5],
            "precio_vendido": venta[7],
            "comision_vendedor": comisiones_por_vendedor.get(
                vendedor_primario_id, 0
            ),
            "comision_segundo_vendedor": (
                comisiones_por_vendedor.get(vendedor_secundario_id, 0)
                if vendedor_secundario_id is not None else 0
            ),
            "product_description": venta[11] or "",
            "fecha": fecha_venta.isoformat(),
        }

    vendedores_comision = base_repo.execute_query(
        """
        SELECT id, name, code
        FROM seller
        WHERE state_id = 1
        ORDER BY code, name, id
        """,
        fetch=True,
    ) or []
    if form_venta.get("segundo_vendedor_id") is not None and not any(
        vendedor[0] == form_venta["segundo_vendedor_id"]
        for vendedor in vendedores_comision
    ):
        raise HTTPException(
            status_code=409,
            detail="El segundo vendedor de la venta original ya no está activo.",
        )
    sucursales = base_repo.execute_query(
        """
        SELECT id, code, description
        FROM branches
        WHERE state_id = 1
        ORDER BY code
        """,
        fetch=True,
    ) or []
    if "sucursal_id" in form_venta and not any(
        sucursal[0] == form_venta["sucursal_id"] for sucursal in sucursales
    ):
        raise HTTPException(
            status_code=409,
            detail="La sucursal de la venta original ya no está activa.",
        )
    productos = base_repo.execute_query(
        """
        SELECT bp.id, c.name, p.code,
               ' [' || s.start_number || ' - ' || s.end_number || ' ]',
               bp.cost_without_discount, bp.cost_with_discount,
               bp.sale_price_suggested, p.id, p.description,
               LOWER(BTRIM(c.name)) = 'rebajado'
                   AND LOWER(BTRIM(p.code)) = 'rebajado'
        FROM products p
        JOIN companies c ON c.id = p.company_id
        JOIN base_price bp ON bp.product_id = p.id
        JOIN sizes s ON bp.size_label = s.label
        WHERE bp.state_id = 1 AND p.state_id = 1
          AND c.state_id = 1 AND s.state_id = 1
        ORDER BY c.name, p.code, bp.size_label
        """,
        fetch=True,
    ) or []
    if "base_price_id" in form_venta and not any(
        producto[0] == form_venta["base_price_id"] for producto in productos
    ):
        raise HTTPException(
            status_code=409,
            detail="El producto original ya no está activo y no se puede duplicar.",
        )
    relaciones_colores = base_repo.execute_query(
        """
        SELECT pc.product_id, colors.id, colors.name
        FROM product_colors pc
        JOIN colors ON colors.id = pc.color_id
        ORDER BY colors.name
        """,
        fetch=True,
    ) or []
    colores_por_producto = {}
    for product_id, color_id, nombre_color in relaciones_colores:
        colores_por_producto.setdefault(product_id, []).append(
            {"id": color_id, "name": nombre_color}
        )
    if form_venta.get("color_id") is not None and not any(
        color["id"] == form_venta["color_id"]
        for color in colores_por_producto.get(venta[3], [])
    ):
        color_actual = base_repo.execute_query(
            "SELECT id, name FROM colors WHERE id = %s",
            (form_venta["color_id"],),
            fetch=True,
        )
        if color_actual:
            colores_por_producto.setdefault(venta[3], []).append(
                {"id": color_actual[0][0], "name": color_actual[0][1]}
            )
    vendedor_historial_id = None if es_admin else usuario["seller_id"]
    historial_ventas = ventas_del_dia(
        venta_repo, fecha_consulta.isoformat(), vendedor_historial_id
    )
    html_content = templates.env.get_template("ventas.html").render(
        request=request,
        vendedores=vendedores,
        vendedores_comision=vendedores_comision,
        sucursales=sucursales,
        productos=productos,
        colores_por_producto=colores_por_producto,
        fecha_hoy=fecha_consulta.isoformat(),
        historial_ventas=historial_ventas,
        fecha_consulta=fecha_consulta.isoformat(),
        form_venta=form_venta,
        es_admin=es_admin,
        usuario=usuario,
    )
    return HTMLResponse(content=html_content)

@router.get("/ventas/historial")
def mostrar_historial_ventas_dia(
    fecha: str,
    venta_repo: SalesRepositoryPort = Depends(get_venta_repo),
    usuario=Depends(usuario_actual),
):
    try:
        fecha_consulta = date.fromisoformat(fecha)
    except ValueError:
        raise HTTPException(status_code=400, detail="La fecha del historial no es válida.")
    vendedor_id = None if usuario["role"] == "admin" else usuario["seller_id"]
    historial_ventas = ventas_del_dia(
        venta_repo, fecha_consulta.isoformat(), vendedor_id
    )
    return HTMLResponse(
        content=templates.env.get_template("historial_ventas_dia.html").render(
            historial_ventas=historial_ventas,
            fecha_consulta=fecha_consulta.isoformat(),
        )
    )

@router.get("/vendedores/pagos/ventas")
def listar_ventas_pendientes_pago(
    vendedor_id: int,
    fecha: date = None,
    venta_repo: SalesRepositoryPort = Depends(get_venta_repo),
    usuario=Depends(administrador_actual),
):
    fecha_fin = fecha + timedelta(days=1) if fecha else None
    ventas = venta_repo.obtener_ventas_pendientes_pago(
        vendedor_id, fecha, fecha_fin
    ) or []
    return JSONResponse(
        [
            {
                "id": venta[0],
                "fecha": venta[1].isoformat(),
                "empresa": venta[2],
                "codigo": venta[3],
                "talla": venta[4],
                "numero": venta[5],
                "color": venta[6],
                "comision": float(venta[7]),
            }
            for venta in ventas
        ]
    )

@router.get("/ventas/{venta_id}/editar")
def mostrar_editar_venta(
    venta_id: int,
    request: Request,
    fecha: str = "",
    mes: str = "",
    fecha_inicio: str = "",
    fecha_fin: str = "",
    todos: bool = False,
    vendedor_id: int = None,
    venta_repo: SalesRepositoryPort = Depends(get_venta_repo),
    base_repo: CatalogRepositoryPort = Depends(get_catalog_repo),
    usuario=Depends(administrador_actual),
):
    if venta_repo.execute_query(
        "SELECT 1 FROM seller_payment_sales WHERE sale_id = %s LIMIT 1",
        (venta_id,),
        fetch=True,
    ):
        raise HTTPException(
            status_code=409, detail="No se puede modificar una venta que ya fue pagada."
        )
    venta = venta_repo.obtener_venta_para_editar(venta_id)
    if not venta:
        raise HTTPException(status_code=404, detail="No se encontró la venta.")
    comisiones_venta = venta_repo.obtener_comisiones_venta(venta_id) or []
    comisiones_por_vendedor = {
        vendedor_id: comision for vendedor_id, comision in comisiones_venta
    }
    vendedores_asignados = [venta[1], *comisiones_por_vendedor.keys()]
    vendedores_secundarios = [
        vendedor
        for vendedor in base_repo.execute_query(
            "SELECT id, name, code FROM seller WHERE state_id = 1 OR id = ANY(%s) ORDER BY name",
            (vendedores_asignados,),
            fetch=True,
        ) or []
        if vendedor[0] != venta[1]
    ]

    vendedores = base_repo.execute_query(
        "SELECT id, name, code FROM seller WHERE state_id = 1 OR id = %s ORDER BY name",
        (venta[1],),
        fetch=True,
    ) or []
    sucursales = base_repo.execute_query(
        """
        SELECT id, code, description FROM branches
        WHERE state_id = 1 OR id = %s
        ORDER BY code
        """,
        (venta[2],),
        fetch=True,
    ) or []
    productos = base_repo.execute_query(
        """
        SELECT bp.id, p.id, c.name, p.code, bp.size_label, p.description,
               bp.cost_without_discount, s.start_number, s.end_number,
               s.start_number || ' - ' || s.end_number AS size_range,
               LOWER(BTRIM(c.name)) = 'rebajado'
                   AND LOWER(BTRIM(p.code)) = 'rebajado'
        FROM base_price bp
        JOIN products p ON p.id = bp.product_id
        JOIN companies c ON c.id = p.company_id
        JOIN sizes s ON s.label = bp.size_label
        WHERE (
            bp.state_id = 1 AND p.state_id = 1
            AND c.state_id = 1 AND s.state_id = 1
        ) OR bp.id = %s
        ORDER BY c.name, p.code, bp.size_label
        """,
        (venta[9],),
        fetch=True,
    ) or []
    relaciones_colores = base_repo.execute_query(
        """
        SELECT pc.product_id, colors.id, colors.name
        FROM product_colors pc
        JOIN colors ON colors.id = pc.color_id
        ORDER BY colors.name
        """,
        fetch=True,
    ) or []
    colores_por_producto = {}
    for product_id, color_id, nombre_color in relaciones_colores:
        colores_por_producto.setdefault(product_id, []).append(
            {"id": color_id, "name": nombre_color}
        )
    if venta[4] is not None and not any(
        color["id"] == venta[4]
        for color in colores_por_producto.get(venta[3], [])
    ):
        color_actual = base_repo.execute_query(
            "SELECT id, name FROM colors WHERE id = %s",
            (venta[4],),
            fetch=True,
        )
        if color_actual:
            colores_por_producto.setdefault(venta[3], []).append(
                {"id": color_actual[0][0], "name": color_actual[0][1]}
            )

    html_content = templates.env.get_template("editar_venta.html").render(
        request=request,
        venta=venta,
        vendedores=vendedores,
        sucursales=sucursales,
        productos=productos,
        colores_por_producto=colores_por_producto,
        vendedores_secundarios=vendedores_secundarios,
        comisiones_por_vendedor=comisiones_por_vendedor,
        segundo_vendedor_id=next(
            (
                vendedor_id
                for vendedor_id, _ in comisiones_venta
                if vendedor_id != venta[1]
            ),
            None,
        ),
        url_retorno=url_reporte_ventas(
            fecha, mes, fecha_inicio, fecha_fin, vendedor_id, todos
        ),
        filtros_reporte={
            "fecha": fecha,
            "mes": mes,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "todos": todos,
            "vendedor_id": vendedor_id or "",
        },
        usuario=usuario,
    )
    return HTMLResponse(content=html_content)

@router.post("/ventas/registrar")
def registrar_venta(
    base_price_id: int = Form(..., ge=1),
    sucursal_id: int = Form(..., ge=1),
    precio_vendido: float = Form(..., gt=0),
    comision_vendedor: Decimal = Form(..., ge=0),
    segundo_vendedor_id: int = Form(None, ge=1),
    comision_segundo_vendedor: Decimal = Form(Decimal("0"), ge=0),
    number_sold: Decimal = Form(..., ge=0),
    fecha: date = Form(...),
    color_id: int = Form(None, ge=1),
    vendedor_id: int = Form(None, ge=1),
    product_description: str = Form("", max_length=200),
    venta_repo: SalesRepositoryPort = Depends(get_venta_repo),
    usuario=Depends(usuario_actual),
):
    if usuario["role"] == "vendedor":
        vendedor_id = usuario["seller_id"]
    elif vendedor_id is None:
        raise HTTPException(status_code=400, detail="Debe seleccionar un vendedor.")
    if (
        comision_vendedor not in COMISIONES_PERMITIDAS
        or comision_segundo_vendedor not in COMISIONES_PERMITIDAS
    ):
        raise HTTPException(
            status_code=400,
            detail="Seleccione una de las comisiones disponibles.",
        )
    if segundo_vendedor_id == vendedor_id:
        raise HTTPException(
            status_code=400,
            detail="Seleccione vendedores diferentes para asignar la comisión.",
        )
    if segundo_vendedor_id is None and comision_segundo_vendedor != 0:
        raise HTTPException(
            status_code=400,
            detail="Seleccione el segundo vendedor para asignar esa comisión.",
        )
    try:
        venta_repo.registrar_venta(
            vendedor_id,
            sucursal_id,
            base_price_id,
            precio_vendido,
            comision_vendedor,
            number_sold,
            color_id,
            fecha,
            segundo_vendedor_id,
            comision_segundo_vendedor,
            product_description.strip() or None,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return RedirectResponse(
        url="/ventas?" + urlencode(
            {"fecha": fecha.isoformat(), "vendedor_id": vendedor_id}
        ),
        status_code=303,
    )

@router.post("/ventas/{venta_id}/modificar")
def modificar_venta(
    venta_id: int,
    vendedor_id: int = Form(..., ge=1),
    sucursal_id: int = Form(..., ge=1),
    base_price_id: int = Form(..., ge=1),
    numero_vendido: Decimal = Form(..., ge=0),
    precio_base: float = Form(..., gt=0),
    precio_vendido: float = Form(..., gt=0),
    comision_vendedor: Decimal = Form(..., ge=0),
    segundo_vendedor_id: int = Form(None, ge=1),
    comision_segundo_vendedor: Decimal = Form(Decimal("0"), ge=0),
    fecha: date = Form(...),
    color_id: int = Form(None, ge=1),
    product_description: str = Form("", max_length=200),
    reporte_fecha: str = Form(""),
    reporte_mes: str = Form(""),
    reporte_fecha_inicio: str = Form(""),
    reporte_fecha_fin: str = Form(""),
    reporte_todos: bool = Form(False),
    reporte_vendedor_id: int = Form(None, ge=1),
    venta_repo: SalesRepositoryPort = Depends(get_venta_repo),
    usuario=Depends(administrador_actual),
):
    if (
        comision_vendedor not in COMISIONES_PERMITIDAS
        or comision_segundo_vendedor not in COMISIONES_PERMITIDAS
    ):
        raise HTTPException(
            status_code=400,
            detail="Seleccione una de las comisiones disponibles.",
        )
    if segundo_vendedor_id == vendedor_id:
        raise HTTPException(
            status_code=400,
            detail="Seleccione vendedores diferentes para asignar la comisión.",
        )
    if segundo_vendedor_id is None and comision_segundo_vendedor != 0:
        raise HTTPException(
            status_code=400,
            detail="Seleccione el segundo vendedor para asignar esa comisión.",
        )
    try:
        venta_repo.actualizar_venta(
            venta_id, vendedor_id, sucursal_id, base_price_id, color_id,
            numero_vendido, precio_base, precio_vendido,
            comision_vendedor, fecha, segundo_vendedor_id,
            comision_segundo_vendedor, product_description.strip() or None,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return RedirectResponse(
        url=url_reporte_ventas(
            reporte_fecha, reporte_mes, reporte_fecha_inicio, reporte_fecha_fin,
            reporte_vendedor_id, reporte_todos,
        ),
        status_code=303,
    )

@router.post("/ventas/{venta_id}/eliminar")
def eliminar_venta(
    venta_id: int,
    reporte_fecha: str = Form(""),
    reporte_mes: str = Form(""),
    reporte_fecha_inicio: str = Form(""),
    reporte_fecha_fin: str = Form(""),
    reporte_todos: bool = Form(False),
    reporte_vendedor_id: int = Form(None, ge=1),
    venta_repo: SalesRepositoryPort = Depends(get_venta_repo),
    usuario=Depends(administrador_actual),
):
    try:
        if not venta_repo.eliminar_venta(venta_id):
            raise HTTPException(status_code=404, detail="No se encontró la venta.")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return RedirectResponse(
        url=url_reporte_ventas(
            reporte_fecha, reporte_mes, reporte_fecha_inicio, reporte_fecha_fin,
            reporte_vendedor_id, reporte_todos,
        ),
        status_code=303,
    )

@router.post("/gastos/registrar")
def registrar_gasto(
    fecha: list[date] = Form(...),
    categoria: list[str] = Form(...),
    monto: list[float] = Form(...),
    descripcion: list[str] = Form(...),
    venta_repo: SalesRepositoryPort = Depends(get_venta_repo),
    usuario=Depends(administrador_actual),
):
    cantidad_gastos = len(fecha)
    if not cantidad_gastos or any(
        len(valores) != cantidad_gastos
        for valores in (categoria, monto, descripcion)
    ):
        raise HTTPException(
            status_code=400, detail="Los datos de los gastos no están completos."
        )
    if any(item not in GASTOS_CATEGORIAS for item in categoria):
        raise HTTPException(status_code=400, detail="La categoría de gasto no es válida.")
    if any(not math.isfinite(item) or item < 0 for item in monto):
        raise HTTPException(status_code=400, detail="El monto de gasto no es válido.")
    venta_repo.registrar_gastos(list(zip(fecha, categoria, descripcion, monto)))
    return RedirectResponse(url="/", status_code=303)

@router.post("/gastos/modificar")
def modificar_gastos(
    gasto_id: list[int] = Form(...),
    fecha: list[date] = Form(...),
    categoria: list[str] = Form(...),
    monto: list[float] = Form(...),
    descripcion: list[str] = Form(...),
    venta_repo: SalesRepositoryPort = Depends(get_venta_repo),
    usuario=Depends(administrador_actual),
):
    cantidad_gastos = len(gasto_id)
    if not cantidad_gastos or any(
        len(valores) != cantidad_gastos
        for valores in (fecha, categoria, monto, descripcion)
    ):
        raise HTTPException(
            status_code=400, detail="Los datos de los gastos no están completos."
        )
    if any(item < 1 for item in gasto_id) or len(set(gasto_id)) != cantidad_gastos:
        raise HTTPException(status_code=400, detail="Los identificadores de gasto no son válidos.")
    if any(item not in GASTOS_CATEGORIAS for item in categoria):
        raise HTTPException(status_code=400, detail="La categoría de gasto no es válida.")
    if any(not math.isfinite(item) or item < 0 for item in monto):
        raise HTTPException(status_code=400, detail="El monto de gasto no es válido.")
    if any(len(item) > 200 for item in descripcion):
        raise HTTPException(status_code=400, detail="La descripción no puede superar 200 caracteres.")
    try:
        venta_repo.actualizar_gastos(
            list(zip(gasto_id, fecha, categoria, descripcion, monto))
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    return RedirectResponse(url="/", status_code=303)

@router.post("/vendedores/pagos")
def registrar_pago_vendedor(
    vendedor_id: int = Form(...),
    fecha: date = Form(...),
    admin_user_id: int = Form(...),
    venta_ids: list[int] = Form(...),
    notas: str = Form(""),
    venta_repo: SalesRepositoryPort = Depends(get_venta_repo),
    usuario=Depends(administrador_actual),
):
    try:
        venta_repo.registrar_pago_vendedor(
            vendedor_id, fecha, notas, admin_user_id, venta_ids
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return RedirectResponse(url="/", status_code=303)

@router.post("/vendedores/agregar")
def agregar_vendedor(
    code: int = Form(..., ge=1),
    nombre: str = Form(...),
    estado_id: int = Form(...),
    base_repo: CatalogRepositoryPort = Depends(get_catalog_repo),
    usuario=Depends(administrador_actual),
):
    if estado_id not in (1, 2):
        raise HTTPException(status_code=400, detail="El estado seleccionado no es válido.")
    base_repo.execute_query(
        "INSERT INTO seller (name, code, state_id) VALUES ( %s, %s, %s)",
        ( nombre, code, estado_id)
    )
    return RedirectResponse(url="/formularios", status_code=303)

@router.post("/productos/agregar")
def agregar_producto(
    codigo: str = Form(...),
    descripcion: str = Form("", max_length=100),
    talla_letra: str = Form(...),
    precio_base: float = Form(..., gt=0),
    precio_descuento: float = Form(..., gt=0),
    precio_sugerido: float = Form(..., gt=0),
    estado_id: int = Form(...),
    empresa_id: int = Form(None),
    nueva_empresa: str = Form(""),
    color_ids: list[int] = Form([]),
    base_repo: CatalogRepositoryPort = Depends(get_catalog_repo),
    usuario=Depends(administrador_actual),
):
    if estado_id not in (1, 2):
        raise HTTPException(status_code=400, detail="El estado seleccionado no es válido.")
    color_ids = sorted(set(color_ids))
    if color_ids and len(
        base_repo.execute_query(
            "SELECT id FROM colors WHERE id = ANY(%s)",
            (color_ids,),
            fetch=True,
        ) or []
    ) != len(color_ids):
        raise HTTPException(status_code=400, detail="Uno o más colores seleccionados no existen.")
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
        INSERT INTO products (company_id, code, description, state_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (company_id, code)
        DO UPDATE SET description = EXCLUDED.description,
                      state_id = EXCLUDED.state_id
        RETURNING id
        """,
        (company_id, codigo.strip(), descripcion.strip(), estado_id),
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
        (
            product_id, talla_letra.upper(), precio_base, precio_descuento,
            precio_sugerido, estado_id
        ),
    )
    base_repo.reemplazar_colores_producto(product_id, color_ids)
    return RedirectResponse(url="/formularios", status_code=303)

@router.post("/colores/agregar")
def agregar_color(
    nombre: str = Form(..., min_length=1, max_length=100),
    base_repo: CatalogRepositoryPort = Depends(get_catalog_repo),
    usuario=Depends(administrador_actual),
):
    nombre = nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre del color es obligatorio.")
    if base_repo.execute_query(
        "SELECT id FROM colors WHERE lower(name) = lower(%s)",
        (nombre,),
        fetch=True,
    ):
        raise HTTPException(status_code=409, detail="Ya existe un color con ese nombre.")
    base_repo.execute_query(
        "INSERT INTO colors (name) VALUES (%s)",
        (nombre,),
    )
    return RedirectResponse(url="/formularios#colores", status_code=303)

@router.post("/colores/modificar")
def modificar_color(
    color_id: int = Form(..., ge=1),
    nombre: str = Form(..., min_length=1, max_length=100),
    base_repo: CatalogRepositoryPort = Depends(get_catalog_repo),
    usuario=Depends(administrador_actual),
):
    nombre = nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre del color es obligatorio.")
    if base_repo.execute_query(
        "SELECT id FROM colors WHERE lower(name) = lower(%s) AND id <> %s",
        (nombre, color_id),
        fetch=True,
    ):
        raise HTTPException(status_code=409, detail="Ya existe un color con ese nombre.")
    actualizado = base_repo.execute_query(
        "UPDATE colors SET name = %s WHERE id = %s RETURNING id",
        (nombre, color_id),
        fetch=True,
    )
    if not actualizado:
        raise HTTPException(status_code=404, detail="No se encontró el color.")
    return RedirectResponse(url="/formularios#colores", status_code=303)

@router.post("/productos/asignar-colores")
def asignar_colores_producto(
    producto_id: int = Form(..., ge=1),
    color_ids: list[int] = Form([]),
    talla_letra: str = Form(""),
    precio_base: str = Form(""),
    precio_descuento: str = Form(""),
    precio_sugerido: str = Form(""),
    base_repo: CatalogRepositoryPort = Depends(get_catalog_repo),
    usuario=Depends(administrador_actual),
):
    color_ids = sorted(set(color_ids))
    if not base_repo.execute_query(
        "SELECT id FROM products WHERE id = %s",
        (producto_id,),
        fetch=True,
    ):
        raise HTTPException(status_code=404, detail="No se encontró el producto.")
    if color_ids and len(
        base_repo.execute_query(
            "SELECT id FROM colors WHERE id = ANY(%s)",
            (color_ids,),
            fetch=True,
        ) or []
    ) != len(color_ids):
        raise HTTPException(status_code=400, detail="Uno o más colores seleccionados no existen.")
    talla_letra = talla_letra.strip().upper() or None
    precios_ingresados = tuple(
        precio.strip() for precio in (precio_base, precio_descuento, precio_sugerido)
    )
    precios = None
    if talla_letra is None:
        if any(precios_ingresados):
            raise HTTPException(
                status_code=400,
                detail="Seleccione una talla para registrar sus precios.",
            )
    else:
        if any(not precio for precio in precios_ingresados):
            raise HTTPException(
                status_code=400,
                detail="Complete el precio base, el precio con descuento y el precio sugerido.",
            )
        try:
            precios = tuple(float(precio) for precio in precios_ingresados)
        except ValueError:
            raise HTTPException(status_code=400, detail="Los precios ingresados no son válidos.")
        if any(not math.isfinite(precio) or precio <= 0 for precio in precios):
            raise HTTPException(status_code=400, detail="Los precios deben ser mayores que cero.")
        if not base_repo.execute_query(
            "SELECT label FROM sizes WHERE label = %s AND state_id = 1",
            (talla_letra,),
            fetch=True,
        ):
            raise HTTPException(status_code=400, detail="La talla seleccionada no está activa.")
    base_repo.guardar_colores_y_precio_producto(
        producto_id,
        color_ids,
        talla_letra,
        precios,
    )
    return RedirectResponse(url="/formularios#asignar-colores", status_code=303)

@router.post("/productos/modificar")
def modificar_producto(
    precio_id: int = Form(None, ge=1),
    producto_id: int = Form(..., ge=1),
    es_duplicado: bool = Form(False),
    empresa_id: int = Form(..., ge=1),
    codigo: str = Form(..., min_length=1, max_length=50),
    descripcion: str = Form("", max_length=100),
    marca_filtro: str = Form(""),
    codigo_filtro: str = Form(""),
    busqueda_filtro: str = Form(""),
    duplicado_id: int = Form(None, ge=1),
    color_ids: list[int] = Form([]),
    talla_letra: str = Form(""),
    precio_base: str = Form(""),
    precio_descuento: str = Form(""),
    precio_sugerido: str = Form(""),
    estado_id: int = Form(...),
    base_repo: CatalogRepositoryPort = Depends(get_catalog_repo),
    usuario=Depends(administrador_actual),
):
    if estado_id not in (1, 2):
        raise HTTPException(status_code=400, detail="El estado seleccionado no es válido.")
    color_ids = sorted(set(color_ids))
    if color_ids and len(
        base_repo.execute_query(
            "SELECT id FROM colors WHERE id = ANY(%s)",
            (color_ids,),
            fetch=True,
        ) or []
    ) != len(color_ids):
        raise HTTPException(status_code=400, detail="Uno o más colores seleccionados no existen.")
    codigo = codigo.strip()
    if not codigo:
        raise HTTPException(status_code=400, detail="El código del producto es obligatorio.")
    talla_letra = talla_letra.strip().upper()
    precios_ingresados = tuple(
        precio.strip()
        for precio in (precio_base, precio_descuento, precio_sugerido)
    )
    registrar_precio = bool(talla_letra or any(precios_ingresados))
    precios = None
    if precio_id is not None or registrar_precio:
        if not talla_letra or any(not precio for precio in precios_ingresados):
            raise HTTPException(
                status_code=400,
                detail="Complete la talla y los tres precios para guardar el registro.",
            )
        try:
            precios = tuple(float(precio) for precio in precios_ingresados)
        except ValueError:
            raise HTTPException(status_code=400, detail="Los precios ingresados no son válidos.")
        if any(not math.isfinite(precio) or precio <= 0 for precio in precios):
            raise HTTPException(
                status_code=400, detail="Los precios deben ser mayores que cero."
            )
        if not base_repo.execute_query(
            "SELECT label FROM sizes WHERE label = %s",
            (talla_letra,),
            fetch=True,
        ):
            raise HTTPException(status_code=400, detail="La categoría de talla no existe.")
        if es_duplicado:
            registro_existente = []
        elif precio_id is None:
            registro_existente = base_repo.execute_query(
                """
                SELECT id FROM base_price
                WHERE product_id = %s AND size_label = %s
                """,
                (producto_id, talla_letra),
                fetch=True,
            )
        else:
            registro_existente = base_repo.execute_query(
                """
                SELECT id FROM base_price
                WHERE product_id = %s AND size_label = %s AND id <> %s
                """,
                (producto_id, talla_letra, precio_id),
                fetch=True,
            )
        if registro_existente:
            raise HTTPException(
                status_code=409,
                detail="Ya existe un registro para ese producto y categoría de talla.",
            )
    if not base_repo.execute_query(
        "SELECT id FROM companies WHERE id = %s",
        (empresa_id,),
        fetch=True,
    ):
        raise HTTPException(status_code=400, detail="La marca seleccionada no existe.")
    producto_existente_id = None
    if not es_duplicado:
        producto_existente = base_repo.execute_query(
            """
            SELECT id FROM products
            WHERE company_id = %s AND code = %s AND id <> %s
            """,
            (empresa_id, codigo, producto_id),
            fetch=True,
        ) or []
        if producto_existente:
            if precio_id is None or duplicado_id != precio_id:
                raise HTTPException(
                    status_code=409,
                    detail="Ya existe otro producto con ese código para la marca seleccionada.",
                )
            producto_existente_id = producto_existente[0][0]

    if es_duplicado:
        if not registrar_precio:
            raise HTTPException(
                status_code=400,
                detail="Seleccione una talla y complete los tres precios para guardar el duplicado.",
            )
        try:
            resultado = base_repo.guardar_producto_duplicado(
                empresa_id,
                codigo,
                descripcion.strip(),
                estado_id,
                talla_letra,
                precios,
                estado_id,
                color_ids,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error))
        if not resultado:
            raise HTTPException(status_code=404, detail="No se encontró la marca.")
        _, duplicado_id = resultado
    elif producto_existente_id is not None:
        try:
            precio_nuevo_id = base_repo.fusionar_talla_duplicada(
                producto_id,
                precio_id,
                producto_existente_id,
                talla_letra,
                precios,
                estado_id,
                color_ids,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error))
        if not precio_nuevo_id:
            raise HTTPException(
                status_code=404, detail="No se encontró el registro duplicado."
            )
        duplicado_id = precio_nuevo_id
    elif precio_id is not None:
        resultado = base_repo.execute_query(
            """
            WITH precio_actualizado AS (
                UPDATE base_price
                SET size_label = %s,
                    cost_without_discount = %s,
                    cost_with_discount = %s,
                    sale_price_suggested = %s,
                    state_id = %s
                WHERE id = %s AND product_id = %s
                RETURNING product_id
            )
            UPDATE products
            SET company_id = %s, code = %s, description = %s, state_id = %s
            WHERE id = (SELECT product_id FROM precio_actualizado)
            RETURNING id
            """,
            (
                talla_letra, *precios, estado_id, precio_id, producto_id,
                empresa_id, codigo, descripcion.strip(), estado_id,
            ),
            fetch=True,
        )
        if not resultado:
            raise HTTPException(
                status_code=404, detail="No se encontró el registro del catálogo."
            )
        base_repo.reemplazar_colores_producto(resultado[0][0], color_ids)
    else:
        try:
            resultado = base_repo.actualizar_producto_sin_precio(
                producto_id,
                empresa_id,
                codigo,
                descripcion.strip(),
                estado_id,
                color_ids,
                talla_letra if registrar_precio else None,
                precios,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error))
        if not resultado:
            raise HTTPException(status_code=404, detail="No se encontró el producto.")

    filtros = {
        key: value
        for key, value in (
            ("marca_filtro", marca_filtro.strip()),
            ("codigo_filtro", codigo_filtro.strip()),
            ("busqueda_filtro", busqueda_filtro.strip()),
            ("duplicado_id", duplicado_id),
        )
        if value not in (None, "")
    }
    query = urlencode(filtros)
    return RedirectResponse(
        url=f"/formularios?{query}#productos" if query else "/formularios#productos",
        status_code=303,
    )

@router.post("/productos/eliminar")
def eliminar_producto_catalogo(
    producto_id: int = Form(..., ge=1),
    precio_id: int = Form(None, ge=1),
    marca_filtro: str = Form(""),
    codigo_filtro: str = Form(""),
    busqueda_filtro: str = Form(""),
    base_repo: CatalogRepositoryPort = Depends(get_catalog_repo),
    usuario=Depends(administrador_actual),
):
    try:
        eliminado = base_repo.eliminar_registro_catalogo(producto_id, precio_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    if eliminado is None:
        raise HTTPException(status_code=404, detail="No se encontró el registro del catálogo.")

    filtros = {
        key: value
        for key, value in (
            ("marca_filtro", marca_filtro.strip()),
            ("codigo_filtro", codigo_filtro.strip()),
            ("busqueda_filtro", busqueda_filtro.strip()),
        )
        if value
    }
    query = urlencode(filtros)
    return RedirectResponse(
        url=f"/formularios?{query}#productos" if query else "/formularios#productos",
        status_code=303,
    )

@router.post("/tallas/agregar")
def agregar_talla(
    letra: str = Form(...),
    rango: str = Form(...),
    estado_id: int = Form(...),
    base_repo: CatalogRepositoryPort = Depends(get_catalog_repo),
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
    usuario_repo: UserRepositoryPort = Depends(get_usuario_repo),
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
    usuario_repo: UserRepositoryPort = Depends(get_usuario_repo),
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
