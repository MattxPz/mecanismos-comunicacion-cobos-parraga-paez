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

from app.main import app
from app.pedidos import claves_idempotencia, pedidos


class PedidosTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(pedidos, clear=True))
        self.enterContext(patch.dict(claves_idempotencia, clear=True))
        self.datos = {
            "cliente": "Ana",
            "productos": [{"nombre": "Cafe", "cantidad": 3, "precio": "0.10"}],
        }
        self.clave = str(uuid4())

        escucha = self.enterContext(socket.socket())
        escucha.bind(("127.0.0.1", 0))
        self.base = f"http://127.0.0.1:{escucha.getsockname()[1]}"
        self.servidor = Server(
            Config(app, log_level="critical", lifespan="off", ws="none",
                   timeout_graceful_shutdown=3)
        )
        self.hilo = Thread(
            target=self.servidor.run, kwargs={"sockets": [escucha]}, daemon=True
        )
        self.hilo.start()
        self.addCleanup(self.detener_servidor)

        limite = monotonic() + 5
        while not self.servidor.started and self.hilo.is_alive() and monotonic() < limite:
            sleep(0.01)
        self.assertTrue(self.servidor.started, "Uvicorn no arrancó")

    def detener_servidor(self):
        self.servidor.should_exit = True
        self.hilo.join(timeout=5)
        self.assertFalse(self.hilo.is_alive(), "Uvicorn no se detuvo")

    def solicitar(self, ruta, datos=None, clave=None):
        cuerpo = None if datos is None else json.dumps(datos).encode()
        headers = {"Content-Type": "application/json"} if cuerpo is not None else {}
        if clave is not None:
            headers["Idempotency-Key"] = clave
        peticion = Request(self.base + ruta, data=cuerpo, headers=headers)
        try:
            respuesta = urlopen(peticion, timeout=3)
        except HTTPError as error:
            respuesta = error
        with respuesta:
            return respuesta.status, json.load(respuesta)

    def test_crear_y_consultar_pedido(self):
        estado, pedido = self.solicitar("/pedidos", self.datos, self.clave)

        self.assertEqual(estado, 201)
        self.assertEqual(pedido["total"], "0.30")
        self.assertEqual(pedido["estado"], "pendiente")
        self.assertEqual(self.solicitar(f"/pedidos/{pedido['id']}"), (200, pedido))

    def test_listar_pedidos(self):
        self.assertEqual(self.solicitar("/pedidos"), (200, []))
        _, creado = self.solicitar("/pedidos", self.datos, self.clave)

        self.assertEqual(self.solicitar("/pedidos"), (200, [creado]))

    def test_pagina_html(self):
        with urlopen(self.base + "/", timeout=3) as respuesta:
            self.assertEqual(respuesta.status, 200)
            self.assertIn("text/html", respuesta.headers["Content-Type"])
            html = respuesta.read().decode()
        self.assertIn('fetch("/pedidos"', html)
        self.assertIn("Idempotency-Key", html)
        self.assertIn('"/ws"', html)
        self.assertIn("/marcar-listo", html)
        self.assertIn('fetch("/estadisticas")', html)

    def test_estadisticas_sin_pedidos(self):
        self.assertEqual(
            self.solicitar("/estadisticas"), (200, {"pedidos_listos": 0, "importe_total": "0.00"})
        )

    def test_estadisticas_cuentan_solo_listos(self):
        pedidos.update({
            "a": {"id": "a", "estado": "listo", "total": "0.10"},
            "b": {"id": "b", "estado": "listo", "total": "0.20"},
            "c": {"id": "c", "estado": "pendiente", "total": "9.99"},
            "d": {"id": "d", "estado": "error_cocina", "total": "5.00"},
        })

        self.assertEqual(
            self.solicitar("/estadisticas"), (200, {"pedidos_listos": 2, "importe_total": "0.30"})
        )

    def test_rechazar_datos_y_consultar_id_inexistente(self):
        datos_invalidos = {"cliente": " ", "productos": []}

        self.assertEqual(self.solicitar("/pedidos", datos_invalidos, self.clave)[0], 422)
        self.assertEqual(self.solicitar(f"/pedidos/{uuid4()}")[0], 404)
        self.assertEqual(len(pedidos), 0)

    def test_pedido_duplicado_procesa_una_sola_vez(self):
        llamadas_cocina = []
        self.enterContext(
            patch.object(app.state, "procesar_pedido", llamadas_cocina.append, create=True)
        )

        estado_nuevo, inicial = self.solicitar("/pedidos", self.datos, self.clave)
        estado_reintento, repetido = self.solicitar("/pedidos", self.datos, self.clave)
        self.detener_servidor()

        self.assertEqual((estado_nuevo, estado_reintento), (201, 200))
        self.assertEqual(repetido, inicial)
        self.assertEqual(list(pedidos), [inicial["id"]])
        self.assertEqual(llamadas_cocina, [inicial["id"]])
        print(
            f"Duplicado: POST inicial={estado_nuevo}, reintento={estado_reintento}, "
            f"mismo ID={inicial['id'] == repetido['id']}, guardados={len(pedidos)}, "
            f"llamadas al sustituto de cocina={len(llamadas_cocina)}",
            flush=True,
        )

    def test_misma_clave_con_datos_diferentes(self):
        distintos = {**self.datos, "cliente": "Luis"}

        self.assertEqual(self.solicitar("/pedidos", self.datos, self.clave)[0], 201)
        self.assertEqual(self.solicitar("/pedidos", distintos, self.clave)[0], 409)
        self.assertEqual(len(pedidos), 1)

    def test_fallo_de_cocina_conserva_pedido_y_salud(self):
        def cocina_con_fallo(pedido_id):
            raise ConnectionRefusedError("conexión rechazada simulada")

        self.enterContext(
            patch.object(app.state, "procesar_pedido", cocina_con_fallo, create=True)
        )

        with self.assertLogs("app.pedidos", level="ERROR") as log:
            estado, creado = self.solicitar("/pedidos", self.datos, self.clave)
            ruta = f"/pedidos/{creado['id']}"
            limite = monotonic() + 3
            codigo, consultado = self.solicitar(ruta)
            while consultado["estado"] == "pendiente" and monotonic() < limite:
                sleep(0.01)
                codigo, consultado = self.solicitar(ruta)

            self.assertEqual((estado, codigo), (201, 200))
            self.assertEqual(consultado, {**creado, "estado": "error_cocina"})
            self.assertEqual(self.solicitar("/health"), (200, {"status": "ok"}))
            self.detener_servidor()

        self.assertIn("ConnectionRefusedError", log.output[0])
