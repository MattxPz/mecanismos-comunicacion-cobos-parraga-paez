import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """Guarda los clientes WebSocket conectados y les envía avisos."""

    def __init__(self) -> None:
        self.conexiones: list[WebSocket] = []

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


manager = ConnectionManager()


@router.websocket("/ws")
async def avisos(websocket: WebSocket) -> None:
    await manager.conectar(websocket)
    try:
        # Se leen los mensajes del cliente solo para detectar su desconexión.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.desconectar(websocket)
