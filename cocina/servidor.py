"""Servidor TCP de cocina.

Protocolo: cada conexión envía un único mensaje JSON en UTF-8 terminado en
salto de línea (``\\n``) y recibe una única respuesta con el mismo formato.

Mensajes aceptados:

- ``{"tipo": "pedido", "pedido": {"id", "cliente", "productos", "total"}}``
  Prepara el pedido, registra el cobro en caja, emite la factura y responde
  ``{"estado": "listo", "id", "cobro", "factura", "repetido"}``.
  Si el pedido es inválido responde ``{"estado": "rechazado", "motivo"}``.
- ``{"tipo": "resumen"}`` devuelve los totales de cocina, caja y facturación.

Cualquier otro mensaje recibe ``{"estado": "error", "motivo"}``. Un mensaje
inválido o un cliente que se desconecta solo afectan a su propia conexión.

Ejecutar desde la raíz del proyecto::

    python -m cocina.servidor --puerto 9000 --demora 2
"""

import argparse
import json
import logging
import os
import socketserver
import sys
import time
from decimal import Decimal, InvalidOperation
from threading import Lock

from .registros import Caja, Facturacion


logger = logging.getLogger(__name__)
TAMANO_MAXIMO = 64 * 1024


def _validar(pedido: object) -> tuple[str, str, list[dict[str, object]], Decimal]:
    if not isinstance(pedido, dict):
        raise ValueError("El pedido debe ser un objeto JSON")

    pedido_id = pedido.get("id")
    cliente = pedido.get("cliente")
    productos = pedido.get("productos")
    if not isinstance(pedido_id, str) or not pedido_id.strip():
        raise ValueError("Falta el ID del pedido")
    if not isinstance(cliente, str) or not cliente.strip():
        raise ValueError("Falta el cliente del pedido")
    if not isinstance(productos, list) or not productos:
        raise ValueError("El pedido no tiene productos")

    try:
        total = Decimal(str(pedido.get("total")))
    except InvalidOperation:
        raise ValueError("Total del pedido inválido") from None
    if not total.is_finite() or total <= 0:
        raise ValueError("Total del pedido inválido")
    return pedido_id, cliente, productos, total


class Cocina:
    """Prepara pedidos y registra caja y facturación una sola vez por ID."""

    def __init__(self, demora: float = 2.0) -> None:
        self.demora = demora
        self.caja = Caja()
        self.facturacion = Facturacion()
        self._preparados: dict[str, dict[str, object]] = {}
        self._bloqueo = Lock()

    def preparar(self, pedido: object) -> dict[str, object]:
        pedido_id, cliente, productos, total = _validar(pedido)

        with self._bloqueo:
            previo = self._preparados.get(pedido_id)
        if previo is not None:
            logger.info("Pedido %s repetido: se devuelve el resultado anterior", pedido_id)
            return {**previo, "repetido": True}

        time.sleep(self.demora)  # Simula el tiempo de preparación.
        cobro = self.caja.registrar_cobro(pedido_id, cliente, total)
        factura = self.facturacion.emitir(pedido_id, cliente, productos, total)
        resultado = {
            "estado": "listo",
            "id": pedido_id,
            "cobro": cobro,
            "factura": factura,
            "repetido": False,
        }
        with self._bloqueo:
            resultado = self._preparados.setdefault(pedido_id, resultado)
        logger.info("Pedido %s listo con factura %s", pedido_id, factura["numero"])
        return resultado

    def resumen(self) -> dict[str, object]:
        with self._bloqueo:
            preparados = len(self._preparados)
        return {
            "pedidos_preparados": preparados,
            **self.caja.resumen(),
            "facturas": self.facturacion.cantidad(),
        }

    def atender(self, mensaje: object) -> dict[str, object]:
        if not isinstance(mensaje, dict):
            return {"estado": "error", "motivo": "El mensaje debe ser un objeto JSON"}

        tipo = mensaje.get("tipo")
        if tipo == "pedido":
            try:
                return self.preparar(mensaje.get("pedido"))
            except ValueError as error:
                return {"estado": "rechazado", "motivo": str(error)}
        if tipo == "resumen":
            return {"estado": "ok", **self.resumen()}
        return {"estado": "error", "motivo": f"Tipo de mensaje desconocido: {tipo!r}"}


class ManejadorCocina(socketserver.StreamRequestHandler):
    # Plazo para que el cliente envíe su mensaje; evita hilos bloqueados
    # por clientes que se conectan y no envían nada.
    timeout = 10

    def handle(self) -> None:
        origen = "%s:%s" % self.client_address[:2]
        try:
            linea = self.rfile.readline(TAMANO_MAXIMO + 1)
        except OSError as error:
            logger.warning("Conexión con %s perdida al leer: %s", origen, error)
            return

        if not linea:
            logger.info("%s se desconectó sin enviar datos", origen)
            return

        if len(linea) > TAMANO_MAXIMO:
            respuesta = {"estado": "error", "motivo": "Mensaje demasiado grande"}
        else:
            try:
                mensaje = json.loads(linea)
            except (UnicodeDecodeError, json.JSONDecodeError):
                respuesta = {"estado": "error", "motivo": "Mensaje JSON inválido"}
            else:
                try:
                    respuesta = self.server.cocina.atender(mensaje)
                except Exception:
                    logger.exception("Error inesperado al atender a %s", origen)
                    respuesta = {"estado": "error", "motivo": "Error interno de cocina"}

        try:
            self.wfile.write((json.dumps(respuesta, ensure_ascii=False) + "\n").encode("utf-8"))
        except OSError as error:
            logger.warning("%s se desconectó antes de recibir la respuesta: %s", origen, error)


class ServidorCocina(socketserver.ThreadingTCPServer):
    daemon_threads = True
    # En Windows SO_REUSEADDR permite que dos procesos usen el mismo puerto.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, direccion: tuple[str, int], cocina: Cocina) -> None:
        self.cocina = cocina
        super().__init__(direccion, ManejadorCocina)


def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor TCP de cocina")
    parser.add_argument("--host", default=os.environ.get("COCINA_HOST", "127.0.0.1"))
    parser.add_argument("--puerto", type=int, default=int(os.environ.get("COCINA_PUERTO", "9000")))
    parser.add_argument(
        "--demora", type=float, default=float(os.environ.get("COCINA_DEMORA", "2")),
        help="segundos que tarda en preparar cada pedido",
    )
    argumentos = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with ServidorCocina((argumentos.host, argumentos.puerto), Cocina(argumentos.demora)) as servidor:
        logger.info(
            "Cocina escuchando en %s:%s (demora %.1f s). Ctrl+C para detener.",
            argumentos.host, argumentos.puerto, argumentos.demora,
        )
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            logger.info("Cocina detenida")


if __name__ == "__main__":
    main()
