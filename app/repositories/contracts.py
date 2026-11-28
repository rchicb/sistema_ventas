from datetime import date
from decimal import Decimal
from typing import Any, Protocol


class QueryRepository(Protocol):
    def execute_query(
        self, query: str, params: tuple = None, fetch: bool = False
    ) -> Any: ...


class CatalogRepositoryPort(QueryRepository, Protocol):
    def guardar_producto_duplicado(
        self,
        company_id: int,
        code: str,
        description: str,
        product_state_id: int,
        size_label: str,
        prices: tuple,
        price_state_id: int,
        color_ids: list[int],
    ) -> Any: ...

    def actualizar_producto_sin_precio(
        self,
        product_id: int,
        company_id: int,
        code: str,
        description: str,
        state_id: int,
        color_ids: list[int],
        size_label: str = None,
        prices: tuple = None,
    ) -> Any: ...

    def fusionar_talla_duplicada(
        self,
        product_id: int,
        precio_id: int,
        producto_existente_id: int,
        size_label: str,
        prices: tuple,
        state_id: int,
        color_ids: list[int],
    ) -> Any: ...

    def eliminar_registro_catalogo(
        self, product_id: int, precio_id: int = None
    ) -> Any: ...

    def reemplazar_colores_producto(
        self, product_id: int, color_ids: list[int]
    ) -> None: ...

    def guardar_colores_y_precio_producto(
        self,
        product_id: int,
        color_ids: list[int],
        size_label: str = None,
        prices: tuple = None,
    ) -> None: ...


class SalesRepositoryPort(QueryRepository, Protocol):
    def registrar_venta(
        self,
        vendedor_id: int,
        sucursal_id: int,
        base_price_id: int,
        precio_vendido: float,
        comision_vendedor: Decimal,
        number_sold: Decimal,
        color_id: int = None,
        fecha: date = None,
        segundo_vendedor_id: int = None,
        segunda_comision: Decimal = Decimal("0"),
        product_description: str = None,
    ) -> None: ...

    def obtener_reporte_ganancias(
        self,
        fecha_inicio: date = None,
        fecha_fin: date = None,
        vendedor_id: int = None,
        vendedor_historial_id: int = None,
        estado_pago: str = None,
    ) -> Any: ...

    def obtener_venta_para_editar(self, venta_id: int) -> Any: ...

    def obtener_comisiones_venta(self, venta_id: int) -> Any: ...

    def actualizar_venta(
        self,
        venta_id: int,
        vendedor_id: int,
        sucursal_id: int,
        base_price_id: int,
        color_id: int,
        numero_vendido: Decimal,
        precio_base: float,
        precio_vendido: float,
        comision: Decimal,
        fecha: date,
        segundo_vendedor_id: int = None,
        segunda_comision: Decimal = Decimal("0"),
        product_description: str = None,
    ) -> None: ...

    def eliminar_venta(self, venta_id: int) -> Any: ...

    def obtener_gastos(
        self, fecha_inicio: date = None, fecha_fin: date = None
    ) -> Any: ...

    def registrar_gastos(self, gastos: Any) -> None: ...

    def actualizar_gastos(self, gastos: Any) -> None: ...

    def obtener_ventas_pendientes_pago(
        self,
        vendedor_id: int,
        fecha_inicio: date = None,
        fecha_fin: date = None,
    ) -> Any: ...

    def registrar_pago_vendedor(
        self,
        vendedor_id: int,
        fecha: date,
        notas: str,
        admin_user_id: int,
        venta_ids: list[int],
    ) -> None: ...

    def obtener_reporte_vendedores(
        self,
        fecha_inicio: date = None,
        fecha_fin: date = None,
        vendedor_id: int = None,
    ) -> Any: ...


class UserRepositoryPort(QueryRepository, Protocol):
    def buscar_por_usuario(self, username: str) -> Any: ...

    def buscar_por_id(self, user_id: int) -> Any: ...

    def listar_usuarios(self) -> Any: ...

    def listar_vendedores(self) -> Any: ...

    def contar_usuarios(self) -> int: ...

    def crear_usuario(
        self, username: str, password_hash: str, role: str, seller_id: int, state_id: int
    ) -> Any: ...

    def actualizar_estado(self, user_id: int, state_id: int) -> bool: ...

    def crear_administrador_inicial(
        self, username: str, password_hash: str
    ) -> bool: ...
