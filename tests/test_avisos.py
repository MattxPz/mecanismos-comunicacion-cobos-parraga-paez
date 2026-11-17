import asyncio
import json
import socket
import unittest
from threading import Thread
from time import monotonic, sleep
from unittest.mock import patch

from uvicorn import Config, Server
from websockets.sync.client import connect

from app.avisos import ConnectionManager, manager
from app.main import app


class ClienteFalso:
    def __init__(self, falla: bool = False):
        self.falla = falla
        self.recibidos: list[dict[str, object]] = []

    async def send_json(self, mensaje: dict[str, object]) -> None:
        if self.falla:
            raise RuntimeError("cliente desconectado simulado")
        self.recibidos.append(mensaje)


class ConnectionManagerTest(unittest.TestCase):
    def test_broadcast_quita_al_que_falla_y_sigue_con_los_demas(self):
        gestor = ConnectionManager()
        primero, caido, ultimo = ClienteFalso(), ClienteFalso(falla=True), ClienteFalso()
        gestor.conexiones = [caido, primero, ultimo]
        aviso = {"evento": "pedido_listo", "id": "1"}

        with self.assertLogs("app.avisos", level="WARNING"):
            asyncio.run(gestor.broadcast(aviso))

        self.assertEqual(gestor.conexiones, [primero, ultimo])
        self.assertEqual((primero.recibidos, ultimo.recibidos), ([aviso], [aviso]))

    def test_desconectar_dos_veces_no_falla(self):
        gestor = ConnectionManager()
        cliente = ClienteFalso()
        gestor.conexiones = [cliente]

        gestor.desconectar(cliente)
        gestor.desconectar(cliente)

        self.assertEqual(gestor.conexiones, [])


class WebSocketTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(manager, "conexiones", []))
        escucha = self.enterContext(socket.socket())
        escucha.bind(("127.0.0.1", 0))
        self.url = f"ws://127.0.0.1:{escucha.getsockname()[1]}/ws"
        self.servidor = Server(Config(app, log_level="critical", lifespan="off"))
        # El bucle es propio para poder ejecutar broadcast() dentro de él.
        self.bucle = asyncio.new_event_loop()
        self.hilo = Thread(
            target=self.bucle.run_until_complete,
            args=(self.servidor.serve(sockets=[escucha]),),
            daemon=True,
        )
        self.hilo.start()
        self.addCleanup(self.detener_servidor)
        self.esperar(lambda: self.servidor.started, "Uvicorn no arrancó")

    def detener_servidor(self):
        self.servidor.should_exit = True
        self.hilo.join(timeout=5)
        self.assertFalse(self.hilo.is_alive(), "Uvicorn no se detuvo")
        self.bucle.close()

    def esperar(self, condicion, mensaje):
        limite = monotonic() + 3
        while not condicion() and monotonic() < limite:
            sleep(0.01)
        self.assertTrue(condicion(), mensaje)

    def test_cliente_que_se_va_no_afecta_a_los_demas(self):
        with connect(self.url) as cliente_a, connect(self.url) as cliente_b:
            self.esperar(lambda: len(manager.conexiones) == 2, "No se registraron 2 clientes")

            cliente_a.close()
            self.esperar(lambda: len(manager.conexiones) == 1, "No se quitó al cliente cerrado")

            aviso = {"evento": "pedido_listo", "id": "1"}
            asyncio.run_coroutine_threadsafe(manager.broadcast(aviso), self.bucle).result(3)

            self.assertEqual(json.loads(cliente_b.recv(timeout=3)), aviso)
