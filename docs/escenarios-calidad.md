# Escenarios de calidad de la API de pedidos

Los objetivos recogen la propuesta para el grupo. La evidencia corresponde a una
ejecución local del 16 de noviembre de 2026 en Windows con Python 3.13.14.
Se usaron solicitudes HTTP reales contra Uvicorn en un puerto local disponible.

## Reintentos sin duplicación

| Elemento | Escenario |
| --- | --- |
| Estímulo | El cliente pierde la respuesta del envío inicial y reenvía `POST /pedidos` cinco veces seguidas, con la misma `Idempotency-Key` y los mismos datos. Envía después datos válidos diferentes con la misma clave para comprobar el conflicto. |
| Entorno | Un proceso de Uvicorn en local, con pedidos y claves en memoria y sin reiniciar durante la prueba. |
| Respuesta | El envío inicial crea el pedido (`201`). Cada reintento devuelve el mismo pedido (`200`). Reutilizar la clave con datos distintos devuelve `409`. |
| Medida verificable | Un solo ID en las seis respuestas válidas, un pedido guardado y una llamada a cocina para ese ID. El envío con datos distintos devuelve `409`. |

La [prueba de pedido duplicado](prueba-pedido-duplicado.md) cubre un envío y un
reintento con un sustituto de cocina. La ejecución ampliada confirmó el mismo
ID y contenido en cinco reintentos, un pedido guardado y una sola llamada al
sustituto. Para comparar las respuestas, la prueba recibió la respuesta inicial
y realizó luego los cinco reintentos consecutivos. Queda pendiente verificar
el envío a cocina real. Un reinicio borra los pedidos y las claves en memoria
y queda fuera del escenario.

## Consulta del estado del pedido

| Elemento | Escenario |
| --- | --- |
| Estímulo | Un cliente envía `GET /pedidos/{id}` para un pedido existente. |
| Entorno | Ejecución local con un proceso de Uvicorn, un cliente y un pedido cuyo estado guardado se conoce. |
| Respuesta | La API devuelve `200` con el pedido y el último estado guardado. |
| Medida verificable | Cada consulta tarda menos de 1 s desde que el cliente inicia el envío del GET hasta que recibe el cuerpo HTTP completo. |

Se realizaron diez consultas consecutivas al mismo pedido con un solo cliente
HTTP. Las diez devolvieron `200` y el estado guardado `pendiente`. La mayor
duración fue **1,201 ms** en esta ejecución. La medición incluye el envío y la
recepción del GET. El tiempo de preparación en cocina queda fuera de la medición.
El cambio a `listo` por la integración TCP queda por comprobar.

## Evidencia de la ejecución

```text
test_cinco_reintentos (__main__.EscenariosCalidad.test_cinco_reintentos) ... ok
Duplicados | inicial=201, reintentos=[200, 200, 200, 200, 200], mismo ID=True, pedidos=1, llamadas al sustituto=1, conflicto=409
test_tiempo_de_consulta (__main__.EscenariosCalidad.test_tiempo_de_consulta) ... Consulta | 10 respuestas HTTP 200 con estado pendiente; milisegundos=[1.201, 0.561, 0.612, 0.537, 0.545, 0.669, 0.705, 0.565, 0.544, 0.48]; maximo=1.201
ok

----------------------------------------------------------------------
Ran 2 tests in 0.642s

OK
```

<details>
<summary>Comando reproducible desde PowerShell en la raíz del proyecto</summary>

```powershell
@'
import json
import sys
import unittest
from contextlib import closing
from http.client import HTTPConnection
from time import perf_counter
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, "tests")
from test_pedidos import PedidosTest, app, pedidos


class EscenariosCalidad(PedidosTest):
    def test_cinco_reintentos(self):
        llamadas = []
        self.enterContext(
            patch.object(app.state, "procesar_pedido", llamadas.append, create=True)
        )
        ruta = "/pedidos"
        estado, original = self.solicitar(ruta, self.datos, self.clave)
        self.assertEqual(estado, 201)
        estados_reintento = []
        for _ in range(5):
            codigo, repetido = self.solicitar(ruta, self.datos, self.clave)
            self.assertEqual((codigo, repetido), (200, original))
            estados_reintento.append(codigo)
        distintos = {**self.datos, "cliente": "Luis"}
        conflicto, _ = self.solicitar(ruta, distintos, self.clave)
        self.assertEqual(conflicto, 409)
        self.detener_servidor()
        self.assertEqual(list(pedidos), [original["id"]])
        self.assertEqual(llamadas, [original["id"]])
        print(
            f"Duplicados | inicial={estado}, reintentos={estados_reintento}, "
            f"mismo ID=True, pedidos={len(pedidos)}, "
            f"llamadas al sustituto={len(llamadas)}, conflicto={conflicto}",
            flush=True,
        )

    def test_tiempo_de_consulta(self):
        estado, creado = self.solicitar("/pedidos", self.datos, self.clave)
        self.assertEqual(estado, 201)
        self.assertEqual(creado["estado"], "pendiente")
        ruta = f"/pedidos/{creado['id']}"
        destino = urlsplit(self.base)
        tiempos = []
        with closing(HTTPConnection(destino.hostname, destino.port, timeout=3)) as cliente:
            for _ in range(10):
                inicio = perf_counter()
                cliente.request("GET", ruta)
                respuesta = cliente.getresponse()
                cuerpo = respuesta.read()
                tiempos.append((perf_counter() - inicio) * 1000)
                self.assertEqual((respuesta.status, json.loads(cuerpo)), (200, creado))
        print(
            "Consulta | 10 respuestas HTTP 200 con estado pendiente; "
            f"milisegundos={[round(t, 3) for t in tiempos]}; maximo={max(tiempos):.3f}",
            flush=True,
        )
        self.assertLess(max(tiempos), 1000)


suite = unittest.TestSuite(
    EscenariosCalidad(nombre)
    for nombre in ("test_cinco_reintentos", "test_tiempo_de_consulta")
)
resultado = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not resultado.wasSuccessful())
'@ | .\.venv\Scripts\python.exe -B -
```

</details>

## Fallo del servicio de cocina

| Elemento | Escenario |
| --- | --- |
| Estímulo | El servicio de cocina TCP está detenido, o acepta la conexión pero no responde, cuando la API le envía un pedido. |
| Entorno | Un proceso de Uvicorn y un servidor de cocina en local, con datos en memoria. La API envía el pedido a cocina en segundo plano, después de responder al cliente. |
| Respuesta | La API acepta el pedido, deja de esperar a cocina al vencer el plazo o al rechazarse la conexión, guarda el pedido como `error_cocina` con el motivo y sigue atendiendo solicitudes. Cuando cocina vuelve, los pedidos nuevos se completan. |
| Medida verificable | `POST /pedidos` responde `201` en menos de 1 s con cocina detenida. El pedido pasa a `error_cocina` en menos de 5 s (plazo por defecto). `GET /health` responde `200` durante el fallo. Con plazo de 0,5 s y cocina muda, el error llega en menos de 1,5 s. |

En la ejecución del 16 de noviembre de 2026 (Windows 11, Python 3.14.5), el
`POST` respondió `201` en 0,225 s, el pedido pasó a `error_cocina` a los
2,276 s, `/health` respondió `200`, un segundo pedido también se aceptó y,
con cocina recuperada, un tercer pedido llegó a `listo` con factura. Con
cocina muda el plazo de 0,5 s se cumplió en 0,508 s. Los 2 s de la conexión
rechazada son un comportamiento de Windows explicado en la
[prueba de cocina detenida](prueba-cocina-detenida.md), donde está la
evidencia completa.
