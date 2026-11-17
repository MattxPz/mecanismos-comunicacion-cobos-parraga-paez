import json
import socket
import unittest
from threading import Thread
from time import monotonic, sleep
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from uvicorn import Config, Server

from app.cliente_cocina import (
    CocinaNoDisponible,
    PedidoRechazado,
    consultar_resumen,
    crear_procesador,
    enviar_a_cocina,
)
from app.main import app
from app.pedidos import bloqueo_pedidos, claves_idempotencia, pedidos
from cocina.servidor import Cocina, ServidorCocina


HOST = "127.0.0.1"
PEDIDO = {
    "id": "pedido-1",
    "cliente": "Ana",
    "productos": [{"nombre": "Cafe", "cantidad": 2, "precio": "2.50"}],
    "total": "5.00",
}


def iniciar_cocina(test, demora=0.0):
    """Arranca un servidor de cocina real en un puerto libre y devuelve (puerto, detener)."""
    servidor = ServidorCocina((HOST, 0), Cocina(demora=demora))
    hilo = Thread(target=servidor.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    hilo.start()
    detenido = []

    def detener():
        if not detenido:
            detenido.append(True)
            servidor.shutdown()
            servidor.server_close()
            hilo.join(timeout=5)

    test.addCleanup(detener)
    return servidor.server_address[1], detener


def puerto_cerrado(test):
    """Puerto en el que hubo una cocina que ya se detuvo."""
    puerto, detener = iniciar_cocina(test)
    detener()
    return puerto


def cocina_sin_respuesta(test):
    """Socket que acepta conexiones a nivel TCP pero nunca contesta."""
    escucha = test.enterContext(socket.socket())
    escucha.bind((HOST, 0))
    escucha.listen(5)
    return escucha.getsockname()[1]


class CocinaTCPTest(unittest.TestCase):
    """Cliente y servidor TCP sin pasar por la API."""

    def test_pedido_listo_registra_caja_y_factura(self):
        puerto, _ = iniciar_cocina(self)

        resultado = enviar_a_cocina(PEDIDO, HOST, puerto, 2)

        self.assertEqual(resultado["estado"], "listo")
        self.assertEqual(resultado["factura"]["numero"], "F-00001")
        self.assertEqual(resultado["factura"]["total"], "5.00")
        self.assertEqual(resultado["cobro"], {
            "pedido_id": "pedido-1", "cliente": "Ana", "importe": "5.00", "estado": "cobrado",
        })

    def test_mismo_pedido_dos_veces_se_cobra_una_vez(self):
        puerto, _ = iniciar_cocina(self)

        primero = enviar_a_cocina(PEDIDO, HOST, puerto, 2)
        segundo = enviar_a_cocina(PEDIDO, HOST, puerto, 2)
        resumen = consultar_resumen(HOST, puerto, 2)

        self.assertFalse(primero["repetido"])
        self.assertTrue(segundo["repetido"])
        self.assertEqual(segundo["factura"], primero["factura"])
        self.assertEqual(
            (resumen["pedidos_preparados"], resumen["cobros"], resumen["facturas"]), (1, 1, 1)
        )
        self.assertEqual(resumen["total_cobrado"], "5.00")

    def test_pedido_incompleto_es_rechazado(self):
        puerto, _ = iniciar_cocina(self)

        with self.assertRaises(PedidoRechazado) as contexto:
            enviar_a_cocina({**PEDIDO, "productos": []}, HOST, puerto, 2)

        self.assertIn("no tiene productos", str(contexto.exception))
        self.assertEqual(consultar_resumen(HOST, puerto, 2)["cobros"], 0)

    def test_mensajes_invalidos_y_desconexiones_no_detienen_cocina(self):
        puerto, _ = iniciar_cocina(self)

        with socket.create_connection((HOST, puerto), timeout=2) as conexion:
            conexion.sendall(b"esto no es json\n")
            respuesta = json.loads(conexion.makefile("rb").readline())
        self.assertEqual(respuesta, {"estado": "error", "motivo": "Mensaje JSON inválido"})

        with socket.create_connection((HOST, puerto), timeout=2):
            pass  # Se conecta y se va sin enviar nada.

        with socket.create_connection((HOST, puerto), timeout=2) as conexion:
            conexion.sendall(b'{"tipo": "ped')  # Se va a mitad del mensaje.

        self.assertEqual(enviar_a_cocina(PEDIDO, HOST, puerto, 2)["estado"], "listo")

    def test_cocina_apagada_lanza_error_controlado(self):
        puerto = puerto_cerrado(self)

        inicio = monotonic()
        with self.assertRaises(CocinaNoDisponible) as contexto:
            enviar_a_cocina(PEDIDO, HOST, puerto, 3)
        duracion = monotonic() - inicio

        self.assertLess(duracion, 4)
        print(f"\nCocina apagada | error={contexto.exception} | segundos={duracion:.3f}", flush=True)

    def test_cocina_sin_respuesta_respeta_tiempo_de_espera(self):
        puerto = cocina_sin_respuesta(self)

        inicio = monotonic()
        with self.assertRaises(CocinaNoDisponible) as contexto:
            enviar_a_cocina(PEDIDO, HOST, puerto, 0.5)
        duracion = monotonic() - inicio

        self.assertIn("no respondió en 0.5 s", str(contexto.exception))
        self.assertGreaterEqual(duracion, 0.45)
        self.assertLess(duracion, 1.5)
        print(f"\nCocina sin respuesta | error={contexto.exception} | segundos={duracion:.3f}", flush=True)


class APIConCocinaTest(unittest.TestCase):
    """Recorrido REST → TCP con la API y la cocina reales."""

    def setUp(self):
        self.enterContext(patch.dict(pedidos, clear=True))
        self.enterContext(patch.dict(claves_idempotencia, clear=True))

        escucha = self.enterContext(socket.socket())
        escucha.bind((HOST, 0))
        self.base = f"http://{HOST}:{escucha.getsockname()[1]}"
        self.servidor = Server(
            Config(app, log_level="critical", lifespan="off", ws="none",
                   timeout_graceful_shutdown=5)
        )
        self.hilo = Thread(target=self.servidor.run, kwargs={"sockets": [escucha]}, daemon=True)
        self.hilo.start()
        self.addCleanup(self.detener_api)

        limite = monotonic() + 5
        while not self.servidor.started and self.hilo.is_alive() and monotonic() < limite:
            sleep(0.01)
        self.assertTrue(self.servidor.started, "Uvicorn no arrancó")

    def detener_api(self):
        self.servidor.should_exit = True
        self.hilo.join(timeout=8)
        self.assertFalse(self.hilo.is_alive(), "Uvicorn no se detuvo")

    def usar_cocina(self, puerto, tiempo_espera):
        procesador = crear_procesador(pedidos, bloqueo_pedidos, HOST, puerto, tiempo_espera)
        if getattr(self, "cocina_registrada", False):
            # Ya hay un patch activo que restaurará app.state al terminar.
            app.state.procesar_pedido = procesador
            return
        self.enterContext(patch.object(app.state, "procesar_pedido", procesador, create=True))
        self.cocina_registrada = True

    def solicitar(self, ruta, datos=None):
        cuerpo = None if datos is None else json.dumps(datos).encode()
        headers = {}
        if cuerpo is not None:
            headers = {"Content-Type": "application/json", "Idempotency-Key": str(uuid4())}
        try:
            respuesta = urlopen(Request(self.base + ruta, data=cuerpo, headers=headers), timeout=3)
        except HTTPError as error:
            respuesta = error
        with respuesta:
            return respuesta.status, json.load(respuesta)

    def crear(self, cliente="Ana"):
        datos = {"cliente": cliente, "productos": [{"nombre": "Cafe", "cantidad": 2, "precio": "2.50"}]}
        return self.solicitar("/pedidos", datos)

    def esperar_resultado(self, pedido_id, limite=8):
        fin = monotonic() + limite
        codigo, pedido = self.solicitar(f"/pedidos/{pedido_id}")
        while pedido["estado"] in ("pendiente", "en_cocina") and monotonic() < fin:
            sleep(0.02)
            codigo, pedido = self.solicitar(f"/pedidos/{pedido_id}")
        return codigo, pedido

    def test_pedido_recorre_api_y_cocina(self):
        puerto, _ = iniciar_cocina(self, demora=0.2)
        self.usar_cocina(puerto, 2)

        estado, creado = self.crear()
        codigo, pedido = self.esperar_resultado(creado["id"])

        self.assertEqual((estado, creado["estado"]), (201, "pendiente"))
        self.assertEqual((codigo, pedido["estado"]), (200, "listo"))
        self.assertEqual((pedido["factura"], pedido["cobro"]), ("F-00001", "cobrado"))
        self.assertEqual(consultar_resumen(HOST, puerto, 2)["total_cobrado"], "5.00")

    def test_cocina_detenida_api_informa_sin_caerse(self):
        self.usar_cocina(puerto_cerrado(self), 3)

        with self.assertLogs("app.pedidos", level="ERROR") as log:
            inicio = monotonic()
            estado1, creado1 = self.crear("Ana")
            respuesta_post = monotonic() - inicio
            codigo1, pedido1 = self.esperar_resultado(creado1["id"])
            deteccion = monotonic() - inicio

            salud = self.solicitar("/health")
            estado2, creado2 = self.crear("Luis")
            codigo2, pedido2 = self.esperar_resultado(creado2["id"])

            # Cocina vuelve a estar disponible: los pedidos nuevos se completan.
            puerto, _ = iniciar_cocina(self)
            self.usar_cocina(puerto, 3)
            estado3, creado3 = self.crear("Eva")
            codigo3, pedido3 = self.esperar_resultado(creado3["id"])
            self.detener_api()

        self.assertEqual((estado1, codigo1, pedido1["estado"]), (201, 200, "error_cocina"))
        self.assertIn("cocina", pedido1["error"].lower())
        self.assertEqual(salud, (200, {"status": "ok"}))
        self.assertEqual((estado2, codigo2, pedido2["estado"]), (201, 200, "error_cocina"))
        self.assertEqual((estado3, codigo3, pedido3["estado"]), (201, 200, "listo"))
        self.assertEqual(len(log.records), 2)
        self.assertIn("CocinaNoDisponible", log.output[0])
        print(
            f"\nCocina detenida | POST={estado1} en {respuesta_post:.3f} s | "
            f"estado={pedido1['estado']} tras {deteccion:.3f} s | error={pedido1['error']!r} | "
            f"health={salud[0]} | segundo pedido={estado2}/{pedido2['estado']} | "
            f"cocina recuperada={estado3}/{pedido3['estado']} factura={pedido3['factura']}",
            flush=True,
        )

    def test_cocina_lenta_queda_en_error_por_tiempo_de_espera(self):
        self.usar_cocina(cocina_sin_respuesta(self), 0.5)

        with self.assertLogs("app.pedidos", level="ERROR"):
            estado, creado = self.crear()
            codigo, pedido = self.esperar_resultado(creado["id"])
            self.detener_api()

        self.assertEqual((estado, codigo, pedido["estado"]), (201, 200, "error_cocina"))
        self.assertEqual(pedido["error"], "Cocina no respondió en 0.5 s")
