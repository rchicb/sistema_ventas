class PricingService:
    @staticmethod
    def calcular_precio_sugerido(precio_base: float, porcentaje_incremento: float) -> float:
        return round(float(precio_base) * (1 + (porcentaje_incremento / 100)), 2)

    @staticmethod
    def calcular_ganancia_vendedor(comision_vendedor: float) -> float:
        return round(float(comision_vendedor), 2)

    @staticmethod
    def calcular_utilidad_empresa(precio_vendido: float, precio_base: float, comision_vendedor: float) -> float:
        return round(float(precio_vendido) - float(precio_base) - float(comision_vendedor), 2)
