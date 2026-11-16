from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .modelos import PedidoNuevo


router = APIRouter(prefix="/pedidos")
pedidos: dict[str, dict[str, object]] = {}


async def datos_invalidos(_request: Request, error: RequestValidationError) -> JSONResponse:
    detalles = [
        {"loc": detalle["loc"], "msg": detalle["msg"], "type": detalle["type"]}
        for detalle in error.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detalles})


@router.post("", status_code=status.HTTP_201_CREATED)
def crear_pedido(datos: PedidoNuevo) -> dict[str, object]:
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
    pedido_id = str(uuid4())
    pedido = {
        "id": pedido_id,
        "cliente": datos.cliente,
        "productos": productos,
        "total": f"{unidades}.{centavos:02d}",
        "estado": "pendiente",
    }
    pedidos[pedido_id] = pedido
    return pedido


@router.get("/{id}")
def consultar_pedido(id: str) -> dict[str, object]:
    pedido = pedidos.get(id)
    if pedido is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")
    return pedido
