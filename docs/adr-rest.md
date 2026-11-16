# ADR · REST para crear y consultar pedidos

## Contexto

La cafetería necesita registrar pedidos y consultar por ID el último estado
guardado. El enunciado de la Práctica 01 exige REST para ambas operaciones.
La tabla es un análisis técnico para el ADR. La exigencia del enunciado fija
la decisión y la comparación queda documentada como análisis posterior.

## Decisión

Usar REST sobre HTTP con JSON. `POST /pedidos` crea un pedido y
`GET /pedidos/{id}` consulta su estado.

## Alternativas

| Opción | Integración con el cliente web | Mantenibilidad | Rendimiento | Manejo de errores |
| --- | --- | --- | --- | --- |
| REST sobre HTTP con JSON | El navegador puede llamar a la API con `fetch`. | Rutas, JSON y OpenAPI facilitan documentar y probar el contrato. | JSON es fácil de inspeccionar y puede ocupar más que un formato binario. | Códigos HTTP estándar y detalles de error en el cuerpo. |
| gRPC | Una página convencional necesita un cliente gRPC-Web y un servidor compatible o un intermediario. | El archivo `.proto` centraliza el contrato tipado. Hay que mantener la generación de código y la capa web. | La codificación binaria con Protocol Buffers puede reducir el tamaño de los mensajes. El intermediario también influye en la latencia. | Códigos propios de gRPC y plazos por llamada. |
| Sockets TCP | Una página convencional requiere un intermediario para acceder al socket. | El equipo debe definir y mantener el formato, la delimitación y la versión de los mensajes. | Permiten controlar el formato y su sobrecarga. El rendimiento depende del protocolo diseñado. | TCP transporta bytes en orden. La aplicación debe definir errores de negocio, plazos y recuperación de la operación. |

La comparación de rendimiento es cualitativa. La evidencia del proyecto mide
la implementación REST en local. [HTTP](https://www.rfc-editor.org/rfc/rfc9110.html),
[Fetch](https://fetch.spec.whatwg.org/), [gRPC-Web](https://grpc.io/docs/platforms/web/basics/),
[conceptos de gRPC](https://grpc.io/docs/what-is-grpc/core-concepts/),
[errores de gRPC](https://grpc.io/docs/guides/error/),
[TCP](https://www.rfc-editor.org/rfc/rfc9293.html) y
[acceso a sockets en el navegador](https://developer.chrome.com/docs/iwa/direct-sockets).

## Justificación

- **Integración y mantenibilidad.** HTTP y JSON permiten probar ambas
  operaciones con herramientas comunes y definir un contrato para la futura
  página web. Pydantic valida cliente, productos, cantidades y precios. La
  API responde `422` ante datos inválidos.
- **Consulta de estado y tiempo de respuesta.** El GET devuelve `200` con el
  último estado guardado o `404` si el ID no existe. El escenario fija un
  objetivo inferior a 1 s con un cliente local. Las diez consultas registradas
  devolvieron `pendiente` y la más lenta tardó **1,201 ms**. La medición cubre
  la consulta HTTP. [Escenarios de calidad](escenarios-calidad.md#consulta-del-estado-del-pedido).
- **Reintentos sin duplicación.** La API guarda la `Idempotency-Key` y el
  pedido bajo un bloqueo. Con la misma clave y los mismos datos devuelve
  `200` con el pedido existente. Con datos distintos devuelve `409`. En el
  escenario de cinco reintentos consecutivos se observó un solo pedido,
  un solo ID y una sola llamada al sustituto de cocina. La protección del
  POST y la tolerancia a fallos dependen de las medidas de la aplicación.
  REST por sí solo no las garantiza. [Escenario de reintentos](escenarios-calidad.md#reintentos-sin-duplicación).

## Consecuencias

- **Ventaja.** El cliente puede crear y consultar pedidos con un contrato
  HTTP fácil de inspeccionar y probar.
- **Limitación.** Pedidos y claves viven en la memoria de un proceso. Se
  pierden al reiniciar y no se comparten entre procesos. La protección
  comprobada cubre los reintentos dentro del mismo proceso.
- **Compromiso de alcance.** REST cubre la creación y la consulta. El diseño
  reserva TCP para el intercambio con cocina y WebSockets para el aviso de
  pedido listo. La integración con los módulos reales sigue pendiente.

## Estado

Decisión aplicada en la API. ADR actualizado al formato indicado de la
Práctica 01.
