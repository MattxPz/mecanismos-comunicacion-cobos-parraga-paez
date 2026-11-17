"""Cliente TCP que la API usa para enviar pedidos al servicio de cocina.

La comunicación es síncrona (petición y respuesta en la misma conexión) y
siempre tiene un plazo máximo: si cocina no acepta la conexión o no responde
a tiempo, se lanza ``CocinaNoDisponible`` en lugar de esperar indefinidamente.

Integración con la API::

    from .cliente_cocina import crear_procesador
    from .pedidos import bloqueo_pedidos, pedidos

    app.state.procesar_pedido = crear_procesador(pedidos, bloqueo_pedidos)

Configuración por variables de entorno: ``COCINA_HOST`` (127.0.0.1),
``COCINA_PUERTO`` (9000) y ``COCINA_TIEMPO_ESPERA`` en segundos (5).
"""

import json
import logging
import os
import socket
from collections.abc import Callable, MutableMapping
from threading import Lock
from time import monotonic


logger = logging.getLogger(__name__)
TAMANO_MAXIMO = 64 * 1024


class ErrorCocina(Exception):
    """Fallo al comunicarse con cocina o al procesar el pedido."""


class CocinaNoDisponible(ErrorCocina):
    """Cocina rechazó la conexión, la cerró o no respondió dentro del plazo."""


class RespuestaCocinaInvalida(ErrorCocina):
    """Cocina respondió algo que no cumple el protocolo."""


class PedidoRechazado(ErrorCocina):
    """Cocina recibió el pedido y lo rechazó."""


def configuracion() -> tuple[str, int, float]:
    return (
        os.environ.get("COCINA_HOST", "127.0.0.1"),
        int(os.environ.get("COCINA_PUERTO", "9000")),
        float(os.environ.get("COCINA_TIEMPO_ESPERA", "5")),
    )


def _leer_linea(conexion: socket.socket, limite: float) -> bytes:
    datos = bytearray()
    while b"\n" not in datos:
        restante = limite - monotonic()
        if restante <= 0:
            raise TimeoutError
        conexion.settimeout(restante)
        bloque = conexion.recv(4096)
        if not bloque:
            if datos:
                break
            raise CocinaNoDisponible("Cocina cerró la conexión sin responder")
        datos += bloque
        if len(datos) > TAMANO_MAXIMO:
            raise RespuestaCocinaInvalida("La respuesta de cocina excede el tamaño permitido")
    return bytes(datos).split(b"\n", 1)[0]


def _intercambiar(mensaje: dict[str, object], host: str, puerto: int, tiempo_espera: float) -> dict:
    """Envía un mensaje y espera una respuesta. El plazo cubre todo el intercambio."""
    limite = monotonic() + tiempo_espera
    linea = (json.dumps(mensaje, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        with socket.create_connection((host, puerto), timeout=tiempo_espera) as conexion:
            conexion.sendall(linea)
            respuesta = _leer_linea(conexion, limite)
    except TimeoutError as error:
        raise CocinaNoDisponible(f"Cocina no respondió en {tiempo_espera:g} s") from error
    except OSError as error:
        raise CocinaNoDisponible(
            f"No se pudo conectar con cocina en {host}:{puerto} ({type(error).__name__})"
        ) from error

    try:
        datos = json.loads(respuesta)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RespuestaCocinaInvalida("Cocina respondió con JSON inválido") from error
    if not isinstance(datos, dict):
        raise RespuestaCocinaInvalida("Cocina respondió con un formato inesperado")
    return datos


def enviar_a_cocina(
    pedido: dict[str, object], host: str, puerto: int, tiempo_espera: float
) -> dict[str, object]:
    """Envía el pedido a cocina y devuelve el resultado con cobro y factura."""
    mensaje = {
        "tipo": "pedido",
        "pedido": {campo: pedido[campo] for campo in ("id", "cliente", "productos", "total")},
    }
    resultado = _intercambiar(mensaje, host, puerto, tiempo_espera)

    estado = resultado.get("estado")
    if estado != "listo":
        raise PedidoRechazado(f"Cocina rechazó el pedido: {resultado.get('motivo', estado)}")
    try:
        resultado["factura"]["numero"]
        resultado["cobro"]["estado"]
    except (KeyError, TypeError) as error:
        raise RespuestaCocinaInvalida("La respuesta de cocina no incluye cobro y factura") from error
    return resultado


def consultar_resumen(host: str, puerto: int, tiempo_espera: float) -> dict[str, object]:
    """Pide a cocina el total de pedidos preparados, cobros y facturas."""
    resultado = _intercambiar({"tipo": "resumen"}, host, puerto, tiempo_espera)
    if resultado.get("estado") != "ok":
        raise RespuestaCocinaInvalida(f"Resumen no disponible: {resultado.get('motivo')}")
    return resultado


def crear_procesador(
    pedidos: MutableMapping[str, dict[str, object]],
    bloqueo: Lock,
    host: str | None = None,
    puerto: int | None = None,
    tiempo_espera: float | None = None,
    al_listo: Callable[[dict[str, object]], object] | None = None,
) -> Callable[[str], None]:
    """Crea la función ``procesar_pedido(pedido_id)`` que registra la API.

    Estados del pedido: ``pendiente`` → ``en_cocina`` → ``listo``. Si cocina
    falla, el pedido queda en ``error_cocina`` con el campo ``error`` y se
    relanza la excepción para que la API la registre en el log.
    ``al_listo`` recibe el pedido ya guardado como ``listo`` (avisos WebSocket).
    """
    host_defecto, puerto_defecto, espera_defecto = configuracion()
    host = host or host_defecto
    puerto = puerto or puerto_defecto
    tiempo_espera = tiempo_espera or espera_defecto

    def procesar_pedido(pedido_id: str) -> None:
        # La llamada de red se hace fuera del bloqueo para no frenar a la API.
        with bloqueo:
            pedido = {**pedidos[pedido_id], "estado": "en_cocina"}
            pedidos[pedido_id] = pedido

        try:
            resultado = enviar_a_cocina(pedido, host, puerto, tiempo_espera)
        except ErrorCocina as error:
            with bloqueo:
                pedidos[pedido_id] = {**pedidos[pedido_id], "estado": "error_cocina", "error": str(error)}
            raise

        with bloqueo:
            listo = {
                **pedidos[pedido_id],
                "estado": "listo",
                "factura": resultado["factura"]["numero"],
                "cobro": resultado["cobro"]["estado"],
            }
            listo.pop("error", None)
            pedidos[pedido_id] = listo

        if al_listo is not None:
            try:
                al_listo(listo)
            except Exception:
                # Un fallo en el aviso no debe deshacer un pedido ya preparado.
                logger.exception("No se pudo avisar que el pedido %s está listo", pedido_id)

    return procesar_pedido
