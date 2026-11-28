from datetime import date, timedelta
from typing import Any

from app.repositories.contracts import SalesRepositoryPort
from app.services.pricing import PricingService


def ventas_del_dia(
    venta_repo: SalesRepositoryPort, fecha: str, vendedor_id: int = None
) -> list[dict[str, Any]]:
    inicio = date.fromisoformat(fecha)
    ventas = venta_repo.obtener_reporte_ganancias(
        inicio, inicio + timedelta(days=1), vendedor_id
    ) or []
    return [
        {
            "id": venta[0],
            "vendedor": venta[1],
            "vendedores": [
                {"nombre": nombre, "pagado": nombre in (venta[11] or [])}
                for nombre in (venta[12] or [])
            ],
            "empresa": venta[2],
            "numero": venta[4],
            "color": venta[5],
            "base": venta[6],
            "vendido": venta[7],
            "comision": venta[8],
            "estado_pago": venta[10],
            "codigo": (
                f"{venta[3]} - {venta[13]}"
                if venta[13]
                else venta[3]
            ),
        }
        for venta in ventas
    ]


def procesar_reporte_ventas(
    raw_ventas: list[Any],
) -> tuple[list[dict[str, Any]], float, float, float]:
    ventas_procesadas = []
    total_bruto = 0.0
    total_comisiones = 0.0
    utilidad_antes_gastos = 0.0

    for item in raw_ventas:
        (
            venta_id,
            vendedor,
            empresa,
            codigo,
            talla,
            color,
            precio_base,
            precio_vendido,
            comision_asignada,
            fecha_venta,
            estado_pago,
            vendedores_pagados,
            vendedores_asignados,
            descripcion_producto,
            excluir_de_utilidad,
        ) = item

        precio_base = float(precio_base)
        precio_vendido = float(precio_vendido)
        comision_asignada = float(comision_asignada)
        comision = PricingService.calcular_ganancia_vendedor(comision_asignada)
        excluir_de_utilidad = bool(excluir_de_utilidad)
        precio_bruto = (
            precio_vendido - comision
            if excluir_de_utilidad
            else precio_vendido
        )
        utilidad = (
            0
            if excluir_de_utilidad
            else PricingService.calcular_utilidad_empresa(
                precio_vendido, precio_base, comision
            )
        )

        total_bruto += precio_bruto
        total_comisiones += comision
        utilidad_antes_gastos += utilidad
        ventas_procesadas.append(
            {
                "id": venta_id,
                "vendedor": vendedor,
                "vendedores": [
                    {
                        "nombre": nombre,
                        "pagado": nombre in (vendedores_pagados or []),
                    }
                    for nombre in (vendedores_asignados or [])
                ],
                "empresa": empresa,
                "codigo": (
                    f"{codigo} - {descripcion_producto}"
                    if descripcion_producto
                    else codigo
                ),
                "talla": talla,
                "color": color,
                "base": precio_base,
                "vendido": precio_vendido,
                "comision": comision,
                "utilidad": utilidad,
                "fecha": fecha_venta,
                "estado_pago": estado_pago,
            }
        )

    return (
        ventas_procesadas,
        total_bruto,
        total_comisiones,
        utilidad_antes_gastos,
    )
