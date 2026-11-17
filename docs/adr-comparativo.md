# ADR · Comparación: por qué TCP y WebSockets

## Contexto

El sistema tiene tres comunicaciones distintas, y cada una tiene necesidades
distintas:

| Comunicación | Quién habla con quién | Qué necesita |
| --- | --- | --- |
| Crear y consultar pedidos | Navegador → API | Que el navegador pueda llamarla directamente. Ver [ADR de REST](adr-rest.md). |
| Enviar el pedido a cocina | API → Cocina | Mensaje corto entre dos servicios internos, con respuesta (listo o rechazado) y un límite de espera. |
| Avisar que el pedido está listo | API → Navegador | Que el **servidor** pueda escribirle al navegador sin que este pregunte. |

Este documento compara, para las dos últimas, el mecanismo elegido con sus
alternativas. Cada decisión tiene su propio ADR con el detalle:
[sockets TCP](adr-sockets-tcp.md) y [WebSockets](adr-websockets.md).

## Decisión

- **API → Cocina:** sockets TCP con un mensaje JSON por línea.
- **API → Navegador:** WebSocket.

No se usa un solo mecanismo para todo porque los dos casos son diferentes: en
el primero la API pregunta y espera una respuesta; en el segundo el servidor
avisa cuando ocurre algo.

## Alternativas para API → Cocina

| Opción | ¿Hay que instalar algo? | ¿La API recibe respuesta? | Si cocina está caída | Resumen |
| --- | --- | --- | --- | --- |
| **Sockets TCP** (elegida) | No. Usa `socket` y `socketserver` de Python. | Sí, por la misma conexión. | La conexión falla o se agota el plazo. El pedido queda en `error_cocina` y la API sigue funcionando. | Simple y con control total de los errores. El formato del mensaje lo define el equipo. |
| REST interno (HTTP) | No, ya se usa en la API. | Sí. | Igual que TCP: error de conexión o de plazo. | Funcionaría, pero repite el mismo mecanismo de la API pública. |
| gRPC | Sí: `grpcio`, un archivo `.proto` y código generado. | Sí. | Errores y plazos ya incluidos. | Bueno para muchos servicios y mensajes. Demasiado montaje para un solo mensaje corto. |
| RPC (por ejemplo XML-RPC) | No en Python. | Sí. | Un fallo de red parece una excepción local, y es fácil olvidar el plazo. | Oculta la red, justo lo que este tramo necesita controlar. |
| Cola de mensajes (Kafka, RabbitMQ) | Sí: un servidor de mensajería aparte. | No directamente. Haría falta una segunda cola para la respuesta. | El pedido espera en la cola hasta que cocina vuelva. | Muy buena si se necesita no perder mensajes, pero añade un servidor más que instalar y mantener. |

**Por qué TCP:** la API necesita una respuesta concreta (el número de factura)
para guardar el pedido como `listo`. TCP lo da con petición y respuesta en
una sola conexión, sin instalar nada y decidiendo qué pasa en cada fallo:
conexión rechazada, cocina que no contesta o respuesta inválida. Las pruebas
lo muestran en la [prueba de cocina detenida](prueba-cocina-detenida.md).

## Alternativas para API → Navegador

| Opción | ¿Quién inicia? | ¿Cuándo llega el aviso? | Carga en el servidor | Resumen |
| --- | --- | --- | --- | --- |
| **WebSocket** (elegida) | El servidor envía cuando quiere. | En el momento. | Una conexión abierta por página. | El navegador lo trae incluido. Sirve en los dos sentidos. |
| Consultar cada N segundos (*polling*) | El navegador pregunta. | Con retraso de hasta N segundos. | Muchas consultas, casi todas sin novedades. | La más fácil, pero lenta e ineficiente. |
| *Long polling* | El navegador pregunta y el servidor espera a tener novedades para responder. | Casi en el momento. | Una petición abierta que hay que volver a abrir tras cada aviso. | Funciona, pero es más complicado que un WebSocket para lo mismo. |
| Server-Sent Events (SSE) | El servidor envía cuando quiere. | En el momento. | Una conexión abierta por página. | Buena opción también. Solo va del servidor al navegador. |
| Socket TCP directo | — | — | — | No sirve: una página web normal no puede abrir sockets TCP. |

**Por qué WebSocket:** es la forma estándar en que el servidor le escribe al
navegador en el momento, sin consultas repetidas y sin librerías en la página.
SSE habría servido igual para este aviso; se eligió WebSocket porque es el
mecanismo del diseño del grupo y permite comunicación en los dos sentidos si
luego hace falta.

## Por qué no usar TCP para el navegador ni WebSocket para cocina

- **TCP para el navegador:** el navegador no deja abrir sockets TCP desde una
  página normal. WebSocket existe justamente para eso: es una conexión
  permanente que el navegador sí permite.
- **WebSocket para cocina:** cocina no necesita una conexión permanente ni
  recibir avisos por su cuenta. Solo recibe un pedido y responde. Un socket
  TCP simple hace eso con menos piezas.

## Consecuencias

- **Ventaja.** Cada comunicación usa el mecanismo que mejor encaja con lo que
  necesita, sin servidores extra ni librerías en el navegador.
- **Ventaja.** Los fallos quedan aislados: si cocina cae, la API sigue
  atendiendo; si un navegador se desconecta, los demás siguen recibiendo
  avisos.
- **Limitación.** El equipo mantiene un protocolo TCP propio, sin contrato
  formal más allá del [ADR de sockets TCP](adr-sockets-tcp.md).
- **Limitación.** Ni TCP ni WebSocket guardan mensajes si el otro lado no está
  disponible. Un pedido con cocina caída queda en `error_cocina`, y un aviso
  enviado con la página cerrada se pierde. Para esos casos haría falta una
  cola de mensajes, que se descartó por alcance.

## Estado

Ambas decisiones están aplicadas y funcionan como un solo flujo: el pedido
entra por REST, va a cocina por TCP y, cuando cocina lo deja listo, el aviso
sale por WebSocket (`al_listo=avisar_pedido_listo` en `app/main.py`). TCP está
en `cocina/servidor.py` y `app/cliente_cocina.py`; WebSocket, en
`app/avisos.py` y `app/pagina.py`.
