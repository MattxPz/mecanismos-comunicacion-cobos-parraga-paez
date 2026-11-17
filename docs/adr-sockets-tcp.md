# ADR · Sockets TCP entre la API y cocina

## Contexto

Cada pedido creado en la API debe llegar a cocina, que lo prepara, registra el
cobro en caja y emite la factura. Es una comunicación interna entre dos
servicios del mismo sistema: el mensaje es corto (ID, cliente, productos y
total), la API necesita una respuesta concreta (listo con factura o rechazo)
y el cliente web nunca se comunica con cocina directamente.

El requisito de calidad más importante en este tramo es que una cocina caída
o lenta no detenga la API ni deje pedidos esperando indefinidamente
([escenario de fallo de cocina](escenarios-calidad.md#fallo-del-servicio-de-cocina)).

## Decisión

Usar sockets TCP con un protocolo propio: una conexión por pedido, un mensaje
JSON en UTF-8 terminado en salto de línea y una respuesta con el mismo
formato. El cliente (`app/cliente_cocina.py`) impone un plazo máximo a todo
el intercambio y la API lo invoca en segundo plano, después de responder al
estudiante.

| Mensaje | Respuesta |
| --- | --- |
| `{"tipo": "pedido", "pedido": {"id", "cliente", "productos", "total"}}` | `{"estado": "listo", "id", "cobro", "factura", "repetido"}` o `{"estado": "rechazado", "motivo"}` |
| `{"tipo": "resumen"}` | `{"estado": "ok", "pedidos_preparados", "cobros", "total_cobrado", "facturas"}` |
| Cualquier otro mensaje o JSON inválido | `{"estado": "error", "motivo"}` |

## Alternativas

| Opción | Acoplamiento y contrato | Mantenibilidad | Rendimiento | Manejo de errores |
| --- | --- | --- | --- | --- |
| **Sockets TCP con JSON por línea** | El contrato lo define el equipo; ambos servicios deben acordar formato y delimitación. | Sin dependencias externas (`socket` y `socketserver` de Python). El equipo mantiene el protocolo. | Una conexión corta por pedido con mensajes pequeños; sin capas HTTP adicionales. | TCP garantiza entrega ordenada mientras la conexión existe. La aplicación define plazos, rechazos y errores de protocolo. |
| gRPC | Contrato tipado en `.proto` con generación de código. | Requiere `grpcio`, compilar el `.proto` y mantener el código generado. | HTTP/2 y Protocol Buffers; eficiente con muchos mensajes. | Códigos de estado y *deadlines* por llamada incluidos. |
| RPC/RMI (XML-RPC en Python) | Llamada remota con apariencia de función local. | Simple en Python; RMI solo aplica a Java. | XML sobre HTTP, más pesado que JSON por línea. | Oculta la red: un fallo remoto se parece a una excepción local, lo que puede llevar a ignorar los plazos. |
| Kafka | Productor y consumidor desacoplados en el tiempo mediante un tópico. | Requiere ejecutar y administrar un broker. | Alto volumen y durabilidad de mensajes. | Si cocina está caída, el pedido espera en el tópico; la respuesta a la API necesitaría otro tópico. |
| REST interno | Mismo estilo que la API pública. | Ya conocido por el equipo. | Encabezados HTTP en cada mensaje. | Códigos HTTP estándar. Repetiría el mecanismo obligatorio sin aportar un tercero. |

Referencias: [TCP, RFC 9293](https://www.rfc-editor.org/rfc/rfc9293.html),
[módulo `socket`](https://docs.python.org/3/library/socket.html),
[módulo `socketserver`](https://docs.python.org/3/library/socketserver.html),
[gRPC](https://grpc.io/docs/what-is-grpc/core-concepts/) y
[Kafka](https://kafka.apache.org/documentation/#introduction).

## Justificación

- **Comunicación interna con respuesta inmediata.** La API necesita saber si
  cocina preparó el pedido para guardarlo como `listo` con su factura. Un
  intercambio petición-respuesta sobre una conexión TCP resuelve eso sin
  broker ni generación de código. Kafka aportaría durabilidad, pero obligaría
  a operar un broker y a montar un canal de vuelta para el resultado.
- **Control explícito de los fallos.** Con sockets el equipo decide qué hacer
  en cada caso: conexión rechazada, cocina que acepta pero no contesta,
  conexión cerrada sin respuesta o JSON inválido. Todos terminan en una
  excepción `ErrorCocina` y el pedido queda en `error_cocina` con el motivo.
  En las pruebas, con cocina detenida, la API respondió `201` en 0,242 s,
  detectó el fallo a los 2,318 s y `/health` siguió en `200`. Con una cocina
  que no contesta, el plazo de 0,5 s se cumplió en 0,506 s.
  [Prueba de cocina detenida](prueba-cocina-detenida.md).
- **Desacoplar al estudiante de la cocina.** El envío TCP es síncrono entre
  API y cocina, pero se ejecuta en segundo plano. El estudiante recibe su
  `201` sin esperar el tiempo de preparación y luego consulta el estado o
  recibe el aviso por WebSocket.
- **Valor didáctico.** Programar el protocolo obliga a resolver problemas que
  otros mecanismos ocultan: delimitar mensajes en un flujo de bytes, limitar
  su tamaño, fijar plazos y atender a varios clientes con hilos.

## Consecuencias

- **Ventaja.** Sin dependencias ni infraestructura adicional. Una conexión
  inválida o un cliente que se desconecta solo afectan a su propia conexión:
  el servidor atiende cada una en un hilo y sigue recibiendo pedidos.
- **Ventaja.** Cocina, caja y facturación son idempotentes por ID de pedido.
  Si el mismo pedido llega dos veces, se devuelve el resultado anterior y no
  se cobra ni se factura de nuevo.
- **Limitación.** El protocolo es propio: no hay versionado ni contrato
  formal más allá de este ADR. Un cambio de formato exige actualizar cliente
  y servidor a la vez.
- **Limitación.** Hay acoplamiento temporal: si cocina está caída, el pedido
  no se prepara y queda en `error_cocina`. Esta versión no reintenta ni guarda
  una cola de pendientes.
- **Riesgo conocido.** Si cocina prepara el pedido pero su respuesta llega
  después del plazo, la API lo marca como `error_cocina` aunque caja ya lo
  haya cobrado. Es el problema clásico de no poder distinguir un servicio
  lento de uno caído. La idempotencia de cocina permitiría reenviarlo sin
  cobrar dos veces.
- **Observación en Windows.** Conectarse a un puerto sin servidor no falla de
  inmediato: Windows reintenta la conexión y tarda unos 2 s en informar
  `ConnectionRefusedError`. Por eso el plazo por defecto es de 5 s y no menor.

## Estado

Decisión aplicada en `cocina/servidor.py` y `app/cliente_cocina.py`, con
pruebas en `tests/test_cocina_tcp.py`. La API registra el cliente TCP al
arrancar en `app/main.py`.
