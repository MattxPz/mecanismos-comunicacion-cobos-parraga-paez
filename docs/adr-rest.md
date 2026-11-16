# ADR provisional · REST para crear y consultar pedidos

## Contexto

El enunciado de la práctica exige usar REST para crear y consultar pedidos.
El grupo necesita probar esas operaciones y conectarlas con una página web.

## Decisión

Usar REST sobre HTTP con JSON para crear pedidos con `POST /pedidos` y
consultarlos con `GET /pedidos/{id}`. Para avisar que un pedido está listo,
el diseño del grupo contempla WebSockets.

## Consecuencias

HTTP y JSON facilitan probar las operaciones e integrarlas con la página web.
El cliente pide el estado mediante una consulta REST. El aviso espontáneo de
pedido listo se enviará mediante el canal WebSocket previsto.

La API ya expone las dos rutas REST. La página web y el envío de avisos por
WebSocket quedan pendientes en el proyecto.

## Estado

Borrador provisional. Pendiente de adaptar a la plantilla de la Práctica 01
cuando esté disponible.
