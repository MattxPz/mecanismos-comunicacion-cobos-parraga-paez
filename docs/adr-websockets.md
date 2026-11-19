# ADR · WebSockets para avisar que un pedido está listo

## Contexto

Cuando un estudiante crea un pedido, la API responde `201` de inmediato y el
pedido queda `pendiente`. La cocina lo prepara después, en segundo plano. El
estudiante no sabe cuándo termina la cocina: necesita que la página le avise
en el momento en que el pedido pasa a `listo`.

El problema es que en HTTP normal el que pregunta siempre es el navegador. El
servidor no puede escribirle a la página por su cuenta. Hace falta un
mecanismo para que el servidor **empuje** el aviso al navegador.

## Decisión

Usar WebSockets. La página abre una conexión a `ws://<servidor>/ws` al
cargarse y la deja abierta. Cuando un pedido queda `listo`, la API envía por
esa conexión el mensaje:

```json
{"id": "<id del pedido>", "estado": "listo"}
```

La página muestra un aviso, recarga la lista de pedidos y actualiza las
estadísticas.

Piezas en el código:

| Pieza | Archivo | Qué hace |
| --- | --- | --- |
| Endpoint `/ws` | `app/avisos.py` | Acepta la conexión y la mantiene abierta. Si el cliente se va, lo quita de la lista. |
| `ConnectionManager` | `app/avisos.py` | Guarda los clientes conectados. `broadcast` envía el aviso a todos. |
| `avisar_pedido_listo` | `app/avisos.py` | Arma el mensaje y lo envía. Se puede llamar desde el hilo de cocina. |
| Cliente en la página | `app/pagina.py` | Abre el WebSocket, muestra el aviso y se reconecta cada 2 s si se corta. |

## Alternativas

| Opción | Cómo funciona | Ventaja | Desventaja |
| --- | --- | --- | --- |
| **WebSocket** | Una conexión abierta en los dos sentidos. El servidor escribe cuando quiere. | El aviso llega en cuanto ocurre. El navegador lo trae incluido, sin librerías. | El servidor debe guardar la lista de clientes conectados y manejar sus desconexiones. |
| Consultar cada pocos segundos (*polling*) | La página repite `GET /pedidos` cada N segundos. | Muy simple: usa la API REST que ya existe. | El aviso llega con retraso de hasta N segundos. La mayoría de consultas no traen nada nuevo y cargan al servidor sin necesidad. |
| *Long polling* | La página hace un GET y el servidor no responde hasta que haya novedad. | Aviso casi inmediato sin protocolo nuevo. | Hay que volver a abrir la petición después de cada aviso y controlar peticiones colgadas. Es más complicado que un WebSocket para el mismo resultado. |
| Server-Sent Events (SSE) | Una conexión HTTP abierta donde solo el servidor escribe. | Simple y pensado justo para avisos del servidor al navegador. Se reconecta solo. | Solo va en un sentido. Si más adelante la página necesita enviar algo por el mismo canal, no sirve. |

Referencias: [protocolo WebSocket, RFC 6455](https://www.rfc-editor.org/rfc/rfc6455.html),
[WebSockets en FastAPI](https://fastapi.tiangolo.com/advanced/websockets/),
[API WebSocket del navegador](https://developer.mozilla.org/es/docs/Web/API/WebSocket) y
[Server-Sent Events](https://developer.mozilla.org/es/docs/Web/API/Server-sent_events).

## Justificación

- **El aviso llega en el momento.** Con *polling* el estudiante esperaría
  hasta el siguiente ciclo de consulta. Con WebSocket el servidor envía el
  aviso en cuanto guarda el estado `listo`.
- **Sin consultas inútiles.** La conexión se abre una vez. El servidor solo
  envía datos cuando hay un aviso.
- **Sin librerías en el navegador.** `new WebSocket(...)` viene incluido en el
  navegador. En el servidor, FastAPI lo soporta y Uvicorn solo necesita la
  librería `websockets`, agregada en `requirements.txt`.
- **SSE también serviría.** Hoy el aviso va solo del servidor al navegador.
  Se eligió WebSocket porque es el mecanismo del diseño del grupo
  ([mapa de microservicios](mapa-microservicios.md)) y deja abierto el envío
  en los dos sentidos.

## Cómo se manejan los fallos

- **Un cliente se desconecta.** El endpoint `/ws` recibe `WebSocketDisconnect`
  y quita al cliente de la lista.
- **Un cliente falla justo al enviarle el aviso.** `broadcast` captura el
  error de ese cliente, lo quita y sigue con los demás. Un cliente caído no
  impide que los otros reciban el aviso.
- **El aviso falla por completo.** El pedido ya quedó guardado como `listo`
  antes del aviso, así que no se pierde. El estudiante lo ve igual al pulsar
  **Actualizar** o al recargar la página.
- **El servidor se reinicia.** La página detecta que se cerró la conexión y
  vuelve a conectarse cada 2 s.

## Consecuencias

- **Ventaja.** El estudiante ve el aviso sin recargar la página.
- **Limitación.** La lista de clientes vive en la memoria del proceso de la
  API. Con varios procesos de la API, cada uno avisaría solo a sus clientes.
- **Limitación.** Si la página estaba cerrada cuando el pedido quedó listo, no
  recibe el aviso después. Tiene que ver el estado en la lista.
- **Detalle técnico.** El procesador de cocina corre en un hilo aparte y
  llama a `al_listo` (es decir, a `avisar_pedido_listo`) cuando guarda el
  pedido como `listo`. El envío WebSocket, en cambio, corre en el bucle de
  eventos de Uvicorn, que la app guarda en `manager.bucle` al arrancar. Por
  eso el aviso pasa por `asyncio.run_coroutine_threadsafe`: le entrega el
  envío a ese bucle sin bloquear el hilo de cocina.

## Estado

Implementado en `app/avisos.py` y `app/pagina.py`, con pruebas en
`tests/test_avisos.py`. Conectado al flujo real: `app/main.py` pasa
`al_listo=avisar_pedido_listo` a `crear_procesador`, así que el aviso sale
cuando cocina deja el pedido `listo`. El recorrido REST → TCP → WebSocket se
comprobó con API y cocina como procesos separados en la
[prueba de cliente desconectado](prueba-cliente-desconectado.md).
