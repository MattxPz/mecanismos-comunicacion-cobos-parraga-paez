import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

from .pedidos import bloqueo_pedidos, pedidos


logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """Guarda los clientes WebSocket conectados y les envía avisos."""

    def __init__(self) -> None:
        self.conexiones: list[WebSocket] = []
        # Bucle de eventos de Uvicorn. Se guarda al arrancar la app (lifespan)
        # para poder enviar avisos desde hilos, como el del procesador de cocina.
        self.bucle: asyncio.AbstractEventLoop | None = None

    async def conectar(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.conexiones.append(websocket)

    def desconectar(self, websocket: WebSocket) -> None:
        # Puede llamarse dos veces para el mismo cliente (fallo de envío y
        # WebSocketDisconnect), así que no falla si ya no está.
        if websocket in self.conexiones:
            self.conexiones.remove(websocket)

    async def broadcast(self, mensaje: dict[str, object]) -> None:
        # Se recorre una copia porque desconectar() modifica la lista original.
        for websocket in list(self.conexiones):
            try:
                await websocket.send_json(mensaje)
            except Exception:
                # Un cliente caído no debe impedir el envío a los demás.
                logger.warning("Se quita un cliente WebSocket que no recibió el aviso")
                self.desconectar(websocket)

    def broadcast_desde_hilo(self, mensaje: dict[str, object]) -> None:
        # broadcast() es asíncrona y solo puede correr en el bucle de Uvicorn.
        # Desde otro hilo se le entrega la corrutina al bucle y no se espera:
        # el hilo de cocina no queda bloqueado por clientes lentos.
        if self.bucle is None:
            logger.warning("Aviso no enviado: la app aún no guardó su bucle de eventos")
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(mensaje), self.bucle)


manager = ConnectionManager()


def avisar_pedido_listo(pedido: dict[str, object]) -> None:
    """Avisa por WebSocket que un pedido quedó listo. Se puede llamar desde un hilo.

    Tiene la firma que espera ``crear_procesador(..., al_listo=...)``.
    """
    manager.broadcast_desde_hilo({"id": pedido["id"], "estado": pedido["estado"]})


@router.websocket("/ws")
async def avisos(websocket: WebSocket) -> None:
    await manager.conectar(websocket)
    try:
        # Se leen los mensajes del cliente solo para detectar su desconexión.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.desconectar(websocket)


# TEMPORAL: sirve para probar el aviso sin cocina TCP. Quitar cuando
# crear_procesador reciba al_listo=avisar_pedido_listo en app/main.py.
# Es una función normal (def), así que FastAPI la ejecuta en un hilo aparte,
# igual que el procesador de cocina. Prueba el mismo camino del aviso real.
@router.post("/pedidos/{id}/marcar-listo", tags=["temporal"])
def marcar_listo(id: str) -> dict[str, object]:
    with bloqueo_pedidos:
        pedido = pedidos.get(id)
        if pedido is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido no encontrado")
        listo = {**pedido, "estado": "listo"}
        pedidos[id] = listo
    avisar_pedido_listo(listo)
    return listo
