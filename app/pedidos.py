import logging
from collections.abc import Callable
from threading import Lock
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from .modelos import PedidoNuevo, TextoRequerido


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pedidos")
pedidos: dict[str, dict[str, object]] = {}
claves_idempotencia: dict[str, tuple[PedidoNuevo, str]] = {}
bloqueo_pedidos = Lock()


async def datos_invalidos(_request: Request, error: RequestValidationError) -> JSONResponse:
    detalles = [
        {"loc": detalle["loc"], "msg": detalle["msg"], "type": detalle["type"]}
        for detalle in error.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detalles})


async def procesar_en_segundo_plano(procesar: Callable[[str], object], pedido_id: str) -> None:
    try:
        await BackgroundTask(procesar, pedido_id)()
    except Exception:
        with bloqueo_pedidos:
            pedido = pedidos[pedido_id]
            if pedido["estado"] != "listo":
                pedidos[pedido_id] = {**pedido, "estado": "error_cocina"}
        logger.exception("Fallo al procesar el pedido %s", pedido_id)


def preparar_pedido(datos: PedidoNuevo, pedido_id: str) -> dict[str, object]:
    productos = []
    total_centavos = 0
    for producto in datos.productos:
        precio = f"{producto.precio:.2f}"
        total_centavos += producto.cantidad * int(producto.precio * 100)
        productos.append({
            "nombre": producto.nombre,
            "cantidad": producto.cantidad,
            "precio": precio,
        })

    unidades, centavos = divmod(total_centavos, 100)
    return {
        "id": pedido_id,
        "cliente": datos.cliente,
        "productos": productos,
        "total": f"{unidades}.{centavos:02d}",
        "estado": "pendiente",
    }


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {
            "model": dict[str, object],
            "description": "Pedido existente devuelto por idempotencia",
        },
        409: {"description": "Clave reutilizada con datos diferentes"},
    },
)
def crear_pedido(
    datos: PedidoNuevo,
    solicitud: Request,
    respuesta: Response,
    tareas: BackgroundTasks,
    clave: Annotated[TextoRequerido, Header(alias="Idempotency-Key")],
) -> dict[str, object]:
    with bloqueo_pedidos:
        registro = claves_idempotencia.get(clave)
        if registro is not None:
            datos_originales, pedido_id = registro
            if datos != datos_originales:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency-Key ya usada con datos diferentes",
                )
            respuesta.status_code = status.HTTP_200_OK
            return pedidos[pedido_id]

        pedido_id = str(uuid4())
        pedido = preparar_pedido(datos, pedido_id)
        pedidos[pedido_id] = pedido
        claves_idempotencia[clave] = (datos, pedido_id)

    procesar_pedido = getattr(solicitud.app.state, "procesar_pedido", None)
    if procesar_pedido is not None:
        tareas.add_task(procesar_en_segundo_plano, procesar_pedido, pedido_id)
    return pedido


@router.get("")
def listar_pedidos() -> list[dict[str, object]]:
    with bloqueo_pedidos:
        return list(pedidos.values())


@router.get("/{id}")
def consultar_pedido(id: str) -> dict[str, object]:
    pedido = pedidos.get(id)
    if pedido is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")
    return pedido
