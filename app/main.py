import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from .avisos import avisar_pedido_listo, manager
from .avisos import router as router_avisos
from .cliente_cocina import crear_procesador
from .estadisticas import router as router_estadisticas
from .pagina import router as router_pagina
from .pedidos import bloqueo_pedidos, datos_invalidos, pedidos, router


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
    # Los avisos WebSocket se envían desde hilos; necesitan este bucle.
    manager.bucle = asyncio.get_running_loop()
    # Cada pedido nuevo se envía por TCP al servicio de cocina. Cuando cocina
    # lo deja listo, el procesador llama a avisar_pedido_listo desde su hilo
    # y el aviso sale por WebSocket.
    app.state.procesar_pedido = crear_procesador(
        pedidos, bloqueo_pedidos, al_listo=avisar_pedido_listo
    )
    yield


app = FastAPI(title="Pedidos de cafetería", lifespan=ciclo_de_vida)
app.add_exception_handler(RequestValidationError, datos_invalidos)
app.include_router(router)
app.include_router(router_pagina)
app.include_router(router_avisos)
app.include_router(router_estadisticas)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
