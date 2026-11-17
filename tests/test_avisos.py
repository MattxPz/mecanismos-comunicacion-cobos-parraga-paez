import asyncio
import json
import socket
import unittest
from threading import Thread
from time import monotonic, perf_counter, sleep
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from uvicorn import Config, Server
from websockets.sync.client import connect

from app.avisos import ConnectionManager, avisar_pedido_listo, manager
from app.main import app
from app.pedidos import claves_idempotencia, pedidos


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

    def test_aviso_sin_bucle_no_falla(self):
        gestor = ConnectionManager()

        with self.assertLogs("app.avisos", level="WARNING"):
            gestor.broadcast_desde_hilo({"id": "1", "estado": "listo"})


class WebSocketTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(manager, "conexiones", []))
        self.enterContext(patch.dict(pedidos, clear=True))
        self.enterContext(patch.dict(claves_idempotencia, clear=True))
        escucha = self.enterContext(socket.socket())
        escucha.bind(("127.0.0.1", 0))
        self.base = f"http://127.0.0.1:{escucha.getsockname()[1]}"
        self.url = f"ws://127.0.0.1:{escucha.getsockname()[1]}/ws"
        self.servidor = Server(Config(app, log_level="critical", lifespan="off"))
        # El bucle es propio para poder ejecutar broadcast() dentro de él.
        self.bucle = asyncio.new_event_loop()
        # Con lifespan="off" no corre ciclo_de_vida; se asigna el bucle a mano.
        self.enterContext(patch.object(manager, "bucle", self.bucle))
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

    def post(self, ruta, datos=None):
        cuerpo = json.dumps(datos).encode() if datos is not None else b""
        headers = {"Content-Type": "application/json", "Idempotency-Key": str(uuid4())}
        try:
            respuesta = urlopen(Request(self.base + ruta, data=cuerpo, headers=headers), timeout=3)
        except HTTPError as error:
            respuesta = error
        with respuesta:
            return respuesta.status, json.load(respuesta)

    def conectar_cliente(self):
        cliente = self.enterContext(connect(self.url))
        self.esperar(lambda: len(manager.conexiones) == 1, "No se registró el cliente")
        return cliente

    def test_marcar_listo_avisa_por_websocket(self):
        cliente = self.conectar_cliente()
        datos = {"cliente": "Ana", "productos": [{"nombre": "Cafe", "cantidad": 1, "precio": "1.00"}]}
        _, creado = self.post("/pedidos", datos)

        estado, listo = self.post(f"/pedidos/{creado['id']}/marcar-listo")

        self.assertEqual((estado, listo["estado"]), (200, "listo"))
        self.assertEqual(pedidos[creado["id"]]["estado"], "listo")
        self.assertEqual(json.loads(cliente.recv(timeout=3)), {"id": creado["id"], "estado": "listo"})

    def test_marcar_listo_id_inexistente(self):
        self.assertEqual(self.post(f"/pedidos/{uuid4()}/marcar-listo")[0], 404)

    def test_aviso_desde_hilo_como_el_procesador_de_cocina(self):
        cliente = self.conectar_cliente()
        pedido = {"id": "abc", "cliente": "Ana", "estado": "listo", "factura": "F-00001"}

        hilo = Thread(target=avisar_pedido_listo, args=(pedido,))
        hilo.start()
        hilo.join(timeout=3)

        self.assertEqual(json.loads(cliente.recv(timeout=3)), {"id": "abc", "estado": "listo"})

    def obtener(self, ruta):
        with urlopen(self.base + ruta, timeout=3) as respuesta:
            return respuesta.status, json.load(respuesta)

    def comprobar_cliente_desconectado(self, desconectar, caso):
        """Escenario: un cliente WebSocket se va y el otro sigue recibiendo avisos.

        Simula dos pestañas abiertas: se desconecta una, se marca un pedido
        como listo y se comprueba que la otra recibe el aviso y que la API
        sigue atendiendo.
        """
        datos = {"cliente": "Ana", "productos": [{"nombre": "Cafe", "cantidad": 1, "precio": "1.50"}]}
        with connect(self.url) as pestana_a, connect(self.url) as pestana_b:
            self.esperar(lambda: len(manager.conexiones) == 2, "No se registraron 2 clientes")
            _, creado = self.post("/pedidos", datos)

            desconectar(pestana_a)
            self.esperar(lambda: len(manager.conexiones) == 1, "No se quitó al cliente desconectado")

            inicio = perf_counter()
            estado_listo, _ = self.post(f"/pedidos/{creado['id']}/marcar-listo")
            aviso = json.loads(pestana_b.recv(timeout=3))
            milisegundos = (perf_counter() - inicio) * 1000

            salud = self.obtener("/health")
            _, consultado = self.obtener(f"/pedidos/{creado['id']}")
            estado_nuevo, _ = self.post("/pedidos", {**datos, "cliente": "Luis"})

        self.assertEqual(estado_listo, 200)
        self.assertEqual(aviso, {"id": creado["id"], "estado": "listo"})
        self.assertEqual(salud, (200, {"status": "ok"}))
        self.assertEqual(consultado["estado"], "listo")
        self.assertEqual(estado_nuevo, 201)
        self.assertTrue(self.hilo.is_alive(), "El servidor se detuvo")
        print(
            f"\nCliente desconectado ({caso}) | clientes tras desconectar=1 | "
            f"marcar-listo={estado_listo} | aviso al otro cliente={aviso['estado']} "
            f"en {milisegundos:.1f} ms | health={salud[0]} | pedido={consultado['estado']} | "
            f"pedido nuevo={estado_nuevo} | servidor activo={self.hilo.is_alive()}",
            flush=True,
        )

    def test_cliente_cierra_y_el_otro_recibe_el_aviso(self):
        # Como cerrar una pestaña: el navegador envía el cierre WebSocket.
        self.comprobar_cliente_desconectado(lambda cliente: cliente.close(), "cierre normal")

    def test_cliente_cortado_y_el_otro_recibe_el_aviso(self):
        # Como un navegador que se cuelga o pierde la red: se corta la
        # conexión TCP sin enviar el cierre WebSocket.
        def cortar(cliente):
            cliente.socket.shutdown(socket.SHUT_RDWR)
            cliente.socket.close()

        self.comprobar_cliente_desconectado(cortar, "corte sin cierre")

    def test_cliente_muerto_aun_en_la_lista_no_afecta_a_los_demas(self):
        # El servidor todavía no notó la desconexión cuando llega el aviso:
        # broadcast() falla al enviarle, lo quita y sigue con el otro cliente.
        with connect(self.url) as pestana_a:
            self.esperar(lambda: len(manager.conexiones) == 1, "No se registró el cliente A")
            servidor_a = manager.conexiones[0]
            with connect(self.url) as pestana_b:
                self.esperar(lambda: len(manager.conexiones) == 2, "No se registró el cliente B")
                pestana_a.close()
                self.esperar(lambda: len(manager.conexiones) == 1, "No se quitó al cliente A")
                manager.conexiones.insert(0, servidor_a)

                aviso = {"id": "abc", "estado": "listo"}
                with self.assertLogs("app.avisos", level="WARNING"):
                    asyncio.run_coroutine_threadsafe(manager.broadcast(aviso), self.bucle).result(3)

                self.assertEqual(json.loads(pestana_b.recv(timeout=3)), aviso)
                self.assertEqual(len(manager.conexiones), 1)
                self.assertNotIn(servidor_a, manager.conexiones)
                self.assertEqual(self.obtener("/health"), (200, {"status": "ok"}))
