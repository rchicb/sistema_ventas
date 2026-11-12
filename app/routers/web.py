from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse,HTMLResponse
from fastapi.templating import Jinja2Templates
from app.repositories.venta import VentaRepository
from app.repositories.base import BaseRepository
from app.services.pricing import PricingService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def get_venta_repo(): return VentaRepository()
def get_base_repo(): return BaseRepository()

@router.get("/")
def dashboard(request: Request, venta_repo: VentaRepository = Depends(get_venta_repo)):
    raw_ventas = venta_repo.obtener_reporte_ganancias() or []
    
    ventas_procesadas = []
    total_bruto = 0.0
    total_comisiones = 0.0
    total_utilidad = 0.0
    
    for item in raw_ventas:
        v_id, v_nombre, p_empresa, p_codigo, p_talla, p_base, p_vendido, porc_comision, fecha = item
        
        p_base = float(p_base)
        p_vendido = float(p_vendido)
        porc_comision = float(porc_comision)
        
        comision = PricingService.calcular_ganancia_vendedor(porc_comision)
        utilidad = PricingService.calcular_utilidad_empresa(p_vendido, p_base, comision)
        
        total_bruto += p_vendido
        total_comisiones += comision
        total_utilidad += utilidad
        
        ventas_procesadas.append({
            "id": v_id, "vendedor": v_nombre, "empresa": p_empresa, "codigo": p_codigo,
            "talla": p_talla, "base": p_base, "vendido": p_vendido, "comision": comision,
            "utilidad": utilidad, "fecha": fecha
        })
        
    # SOLUCIÓN INGENIERIL: Forzamos el contexto directamente a través del motor Jinja2 subyacente
    # Esto evita que Starlette intente procesar o mutar el diccionario en sus middlewares internos
    html_content = templates.env.get_template("dashboard.html").render(
        request=request,
        ventas=ventas_procesadas,
        total_bruto=round(total_bruto, 2),
        total_comisiones=round(total_comisiones, 2),
        total_utilidad=round(total_utilidad, 2)
    )
    return HTMLResponse(content=html_content)

@router.get("/formularios")
def mostrar_formularios(request: Request, base_repo: BaseRepository = Depends(get_base_repo)):
    vendedores = base_repo.execute_query("SELECT code, name FROM seller", fetch=True)
    productos = base_repo.execute_query(
        """
        SELECT bp.id, c.name, p.code, ' [' || s.start_number || ' - ' || s.end_number|| ' ]', 
        bp.cost_without_discount, bp.cost_with_discount, bp.sale_price_suggested
        FROM products p
        JOIN companies c ON c.id = p.company_id
        JOIN base_price bp ON bp.product_id = p.id
        JOIN sizes s ON bp.size_label = s.label
        WHERE bp.state_id = 1
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
    
    # Usamos .render() directo para saltarnos el middleware conflictivo de Starlette
    html_content = templates.env.get_template("formularios.html").render(
        request=request, 
        vendedores=vendedores, 
        productos=productos, 
        tallas=tallas
    )
    return HTMLResponse(content=html_content)

@router.post("/ventas/registrar")
def registrar_venta(
    vendedor_id: int = Form(...), base_price_id: int = Form(...),
    precio_vendido: float = Form(...), porcentaje_ganancia: int = Form(...),
    venta_repo: VentaRepository = Depends(get_venta_repo)
):
    venta_repo.registrar_venta(
        vendedor_id, base_price_id, precio_vendido, porcentaje_ganancia
    )
    return RedirectResponse(url="/", status_code=303)

@router.post("/vendedores/agregar")
def agregar_vendedor(id: int = Form(...), nombre: str = Form(...), base_repo: BaseRepository = Depends(get_base_repo)):
    base_repo.execute_query(
        "INSERT INTO seller (id, name, code) VALUES (%s, %s, %s)",
        (id, nombre, id)
    )
    return RedirectResponse(url="/formularios", status_code=303)

@router.post("/productos/agregar")
def agregar_producto(empresa: str = Form(...), codigo: str = Form(...), talla_letra: str = Form(...), precio_base: float = Form(...), base_repo: BaseRepository = Depends(get_base_repo)):
    base_repo.execute_query(
        """
        WITH company_row AS (
            INSERT INTO companies (name) VALUES (%s)
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
        ),
        product_row AS (
            INSERT INTO products (company_id, code)
            SELECT id, %s FROM company_row
            ON CONFLICT (company_id, code) DO UPDATE SET code = EXCLUDED.code
            RETURNING id
        )
        INSERT INTO base_price (product_id, size_label, cost_without_discount, cost_with_discount, sale_price_suggested)
        SELECT id, %s, %s, %s, %s FROM product_row
        ON CONFLICT (product_id, size_label)
        DO UPDATE SET cost_without_discount = EXCLUDED.cost_without_discount
        """,
        (empresa, codigo, talla_letra, precio_base, precio_base, precio_base)
    )
    return RedirectResponse(url="/formularios", status_code=303)

@router.post("/tallas/agregar")
def agregar_talla(letra: str = Form(...), rango: str = Form(...), base_repo: BaseRepository = Depends(get_base_repo)):
    base_repo.execute_query(
        """
        INSERT INTO sizes (label, start_number, end_number)
        VALUES (%s, %s, %s)
        """,
        (letra.upper(), *[int(value.strip()) for value in rango.split("-", 1)])
    )
    return RedirectResponse(url="/formularios", status_code=303)
