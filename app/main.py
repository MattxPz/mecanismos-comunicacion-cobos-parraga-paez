from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from .cliente_cocina import crear_procesador
from .pedidos import bloqueo_pedidos, datos_invalidos, pedidos, router


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
    # Cada pedido nuevo se envía por TCP al servicio de cocina.
    app.state.procesar_pedido = crear_procesador(pedidos, bloqueo_pedidos)
    yield


app = FastAPI(title="Pedidos de cafetería", lifespan=ciclo_de_vida)
app.add_exception_handler(RequestValidationError, datos_invalidos)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
