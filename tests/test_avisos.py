# Pruebas generadas con IA (Claude Code, modelo Claude Opus 5.5).
# Ver docs/bitacora-ia.md.

import asyncio
import json
import socket
import unittest
from threading import Thread
from time import monotonic, perf_counter, sleep
from unittest.mock import patch
from urllib.request import Request, urlopen
from uuid import uuid4

from uvicorn import Config, Server
from websockets.sync.client import connect

from app import main
from app.avisos import ConnectionManager, avisar_pedido_listo, manager
from app.cliente_cocina import crear_procesador
from app.main import app
from app.pedidos import bloqueo_pedidos, claves_idempotencia, pedidos
from cocina.servidor import Cocina, ServidorCocina


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


class CicloDeVidaTest(unittest.TestCase):
    def test_arranque_conecta_el_aviso_con_cocina(self):
        # Comprueba la conexión hecha en app/main.py: el procesador de cocina
        # recibe al_listo=avisar_pedido_listo y el bucle queda guardado.
        argumentos = {}

        def crear_falso(*args, **kwargs):
            argumentos.update(kwargs)
            return lambda pedido_id: None

        self.enterContext(patch.object(main, "crear_procesador", crear_falso))
        self.enterContext(patch.object(manager, "bucle", None))
        self.enterContext(patch.object(app.state, "procesar_pedido", None, create=True))

        async def arrancar():
            async with main.ciclo_de_vida(app):
                return manager.bucle is asyncio.get_running_loop()

        self.assertTrue(asyncio.run(arrancar()))
        self.assertIs(argumentos["al_listo"], avisar_pedido_listo)


class WebSocketTest(unittest.TestCase):
    """API y cocina TCP reales: REST, luego TCP y luego el aviso WebSocket."""

    def setUp(self):
        self.enterContext(patch.object(manager, "conexiones", []))
        self.enterContext(patch.dict(pedidos, clear=True))
        self.enterContext(patch.dict(claves_idempotencia, clear=True))
        self.iniciar_cocina()

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

    def iniciar_cocina(self):
        # Cocina TCP real en un puerto libre, con el mismo registro que hace
        # app/main.py al arrancar: al_listo=avisar_pedido_listo. Sin demora
        # de preparación, para medir solo el recorrido TCP y el aviso.
        cocina = ServidorCocina(("127.0.0.1", 0), Cocina(demora=0))
        hilo = Thread(target=cocina.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        hilo.start()

        def detener():
            cocina.shutdown()
            cocina.server_close()
            hilo.join(timeout=5)

        self.addCleanup(detener)
        procesador = crear_procesador(
            pedidos, bloqueo_pedidos, "127.0.0.1", cocina.server_address[1], 3,
            al_listo=avisar_pedido_listo,
        )
        self.enterContext(patch.object(app.state, "procesar_pedido", procesador, create=True))

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

    def post(self, ruta, datos):
        headers = {"Content-Type": "application/json", "Idempotency-Key": str(uuid4())}
        peticion = Request(self.base + ruta, data=json.dumps(datos).encode(), headers=headers)
        with urlopen(peticion, timeout=3) as respuesta:
            return respuesta.status, json.load(respuesta)

    def obtener(self, ruta):
        with urlopen(self.base + ruta, timeout=3) as respuesta:
            return respuesta.status, json.load(respuesta)

    def datos(self, cliente="Ana"):
        return {"cliente": cliente, "productos": [{"nombre": "Cafe", "cantidad": 1, "precio": "1.50"}]}

    def test_pedido_listo_en_cocina_avisa_por_websocket(self):
        with connect(self.url) as cliente:
            self.esperar(lambda: len(manager.conexiones) == 1, "No se registró el cliente")

            estado, creado = self.post("/pedidos", self.datos())
            aviso = json.loads(cliente.recv(timeout=3))

        self.assertEqual((estado, creado["estado"]), (201, "pendiente"))
        self.assertEqual(aviso, {"id": creado["id"], "estado": "listo"})
        _, consultado = self.obtener(f"/pedidos/{creado['id']}")
        self.assertEqual((consultado["estado"], consultado["factura"]), ("listo", "F-00001"))

    def test_aviso_desde_hilo_como_el_procesador_de_cocina(self):
        with connect(self.url) as cliente:
            self.esperar(lambda: len(manager.conexiones) == 1, "No se registró el cliente")
            pedido = {"id": "abc", "cliente": "Ana", "estado": "listo", "factura": "F-00001"}

            hilo = Thread(target=avisar_pedido_listo, args=(pedido,))
            hilo.start()
            hilo.join(timeout=3)

            self.assertEqual(json.loads(cliente.recv(timeout=3)), {"id": "abc", "estado": "listo"})

    def test_cliente_que_se_va_no_afecta_a_los_demas(self):
        with connect(self.url) as cliente_a, connect(self.url) as cliente_b:
            self.esperar(lambda: len(manager.conexiones) == 2, "No se registraron 2 clientes")

            cliente_a.close()
            self.esperar(lambda: len(manager.conexiones) == 1, "No se quitó al cliente cerrado")

            aviso = {"evento": "pedido_listo", "id": "1"}
            asyncio.run_coroutine_threadsafe(manager.broadcast(aviso), self.bucle).result(3)

            self.assertEqual(json.loads(cliente_b.recv(timeout=3)), aviso)

    def comprobar_cliente_desconectado(self, desconectar, caso):
        """Escenario: un cliente WebSocket se va y el otro sigue recibiendo avisos.

        Simula dos pestañas abiertas: se desconecta una, se crea un pedido,
        cocina lo deja listo y se comprueba que la otra recibe el aviso y que
        la API sigue atendiendo.
        """
        with connect(self.url) as pestana_a, connect(self.url) as pestana_b:
            self.esperar(lambda: len(manager.conexiones) == 2, "No se registraron 2 clientes")

            desconectar(pestana_a)
            self.esperar(lambda: len(manager.conexiones) == 1, "No se quitó al cliente desconectado")

            inicio = perf_counter()
            estado_creado, creado = self.post("/pedidos", self.datos())
            aviso = json.loads(pestana_b.recv(timeout=3))
            milisegundos = (perf_counter() - inicio) * 1000

            salud = self.obtener("/health")
            _, consultado = self.obtener(f"/pedidos/{creado['id']}")
            estado_nuevo, _ = self.post("/pedidos", self.datos("Luis"))
            aviso_nuevo = json.loads(pestana_b.recv(timeout=3))

        self.assertEqual(estado_creado, 201)
        self.assertEqual(aviso, {"id": creado["id"], "estado": "listo"})
        self.assertEqual(salud, (200, {"status": "ok"}))
        self.assertEqual(consultado["estado"], "listo")
        self.assertEqual((estado_nuevo, aviso_nuevo["estado"]), (201, "listo"))
        self.assertTrue(self.hilo.is_alive(), "El servidor se detuvo")
        print(
            f"\nCliente desconectado ({caso}) | clientes tras desconectar=1 | "
            f"POST={estado_creado} | aviso al otro cliente={aviso['estado']} "
            f"en {milisegundos:.1f} ms | health={salud[0]} | pedido={consultado['estado']} "
            f"factura={consultado['factura']} | pedido nuevo={estado_nuevo}/{aviso_nuevo['estado']} | "
            f"servidor activo={self.hilo.is_alive()}",
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
        # El servidor todavía no notó la desconexión cuando cocina deja el
        # pedido listo: broadcast() falla al enviarle, lo quita y sigue con
        # el otro cliente.
        with connect(self.url) as pestana_a:
            self.esperar(lambda: len(manager.conexiones) == 1, "No se registró el cliente A")
            servidor_a = manager.conexiones[0]
            with connect(self.url) as pestana_b:
                self.esperar(lambda: len(manager.conexiones) == 2, "No se registró el cliente B")
                pestana_a.close()
                self.esperar(lambda: len(manager.conexiones) == 1, "No se quitó al cliente A")
                manager.conexiones.insert(0, servidor_a)

                with self.assertLogs("app.avisos", level="WARNING"):
                    _, creado = self.post("/pedidos", self.datos())
                    aviso = json.loads(pestana_b.recv(timeout=3))

                self.assertEqual(aviso, {"id": creado["id"], "estado": "listo"})
                self.assertEqual(len(manager.conexiones), 1)
                self.assertNotIn(servidor_a, manager.conexiones)
                self.assertEqual(self.obtener("/health"), (200, {"status": "ok"}))
