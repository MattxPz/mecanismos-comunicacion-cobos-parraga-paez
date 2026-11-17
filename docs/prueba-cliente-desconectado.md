# Prueba de cliente WebSocket desconectado

Esta prueba comprueba que, si un cliente WebSocket se desconecta (por ejemplo,
se cierra una pestaña), los demás clientes siguen recibiendo el aviso de
pedido listo y el servidor no se cae. Se relaciona con el escenario
[Cliente WebSocket desconectado](escenarios-calidad.md#cliente-websocket-desconectado).

## Qué se prueba

Dos clientes conectados a `/ws` representan dos pestañas abiertas de la
página. Se desconecta uno, se marca un pedido como listo y se comprueba que:

1. El otro cliente recibe el aviso `{"id": ..., "estado": "listo"}`.
2. `GET /health` sigue respondiendo `200`.
3. El pedido queda guardado como `listo`.
4. La API sigue aceptando pedidos nuevos (`201`).
5. El proceso del servidor sigue activo.

Se prueban tres formas de desconexión:

| Caso | Qué simula | Qué hace el servidor |
| --- | --- | --- |
| Cierre normal | Cerrar la pestaña: el navegador envía el cierre WebSocket. | El endpoint `/ws` recibe `WebSocketDisconnect` y quita al cliente. |
| Corte sin cierre | El navegador se cuelga o se pierde la red: la conexión TCP se corta sin enviar el cierre WebSocket. | El endpoint `/ws` detecta la conexión cortada y quita al cliente. |
| Cliente muerto aún en la lista | El servidor todavía no notó la desconexión cuando llega el aviso. | `broadcast` falla al enviarle, lo quita de la lista y sigue con el otro cliente. |

## Pasos reproducibles

### 1. Pruebas automáticas

En PowerShell, desde la raíz del proyecto, con el entorno preparado como
indica el README:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_avisos.py -k cliente -v
```

Cada prueba arranca su propia API con Uvicorn en un puerto libre y conecta dos
clientes WebSocket reales con la librería `websockets`. Las pruebas están en
`tests/test_avisos.py`:

- `test_cliente_cierra_y_el_otro_recibe_el_aviso`: cierre normal.
- `test_cliente_cortado_y_el_otro_recibe_el_aviso`: corte sin cierre.
- `test_cliente_muerto_aun_en_la_lista_no_afecta_a_los_demas`: se vuelve a
  poner en la lista el WebSocket del servidor de un cliente ya cerrado y se
  envía un aviso. El envío a ese cliente falla de verdad.
- `test_cliente_que_se_va_no_afecta_a_los_demas`: un cliente se va y el otro
  recibe un `broadcast`.

### 2. Prueba en el navegador

1. Arranca solo la API, **sin** el servicio de cocina:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
   ```

2. Abre `http://127.0.0.1:8000/` en **dos pestañas** (A y B). Las dos deben
   mostrar "Avisos: conectado".
3. En la pestaña B, crea un pedido.
4. Espera unos 3 segundos y pulsa **Actualizar**. El pedido debe mostrar
   `error_cocina`, porque cocina está apagada. Hay que esperar a este estado
   antes de marcarlo (ver "Hallazgo" más abajo).
5. Cierra la pestaña A.
6. En la pestaña B, pulsa **Marcar listo** en ese pedido.
7. Comprueba que en la pestaña B aparece el aviso verde, la fila pasa a
   `listo` y las estadísticas suben.
8. Abre `http://127.0.0.1:8000/health` y comprueba que responde
   `{"status":"ok"}`. Revisa la terminal de Uvicorn: no debe aparecer ningún
   error relacionado con el WebSocket.

## Resultado esperado

| Comprobación | Esperado |
| --- | --- |
| Clientes registrados tras la desconexión | 1 |
| `POST /pedidos/{id}/marcar-listo` | `200` |
| Aviso en el cliente que sigue conectado | `{"id": "<id>", "estado": "listo"}` en menos de 1 s |
| `GET /health` | `200` |
| Estado guardado del pedido | `listo` |
| Pedido nuevo después de la desconexión | `201` |
| Proceso del servidor | Sigue activo |

## Resultado observado

Ejecución del 16 de noviembre de 2026 en Windows 11 con Python 3.12.10.

### Pruebas automáticas

Las cuatro pruebas pasaron:

```text
test_cliente_cierra_y_el_otro_recibe_el_aviso (test_avisos.WebSocketTest.test_cliente_cierra_y_el_otro_recibe_el_aviso) ...
Cliente desconectado (cierre normal) | clientes tras desconectar=1 | marcar-listo=200 | aviso al otro cliente=listo en 4.6 ms | health=200 | pedido=listo | pedido nuevo=201 | servidor activo=True
ok
test_cliente_cortado_y_el_otro_recibe_el_aviso (test_avisos.WebSocketTest.test_cliente_cortado_y_el_otro_recibe_el_aviso) ...
Cliente desconectado (corte sin cierre) | clientes tras desconectar=1 | marcar-listo=200 | aviso al otro cliente=listo en 3.7 ms | health=200 | pedido=listo | pedido nuevo=201 | servidor activo=True
ok
test_cliente_muerto_aun_en_la_lista_no_afecta_a_los_demas (test_avisos.WebSocketTest.test_cliente_muerto_aun_en_la_lista_no_afecta_a_los_demas) ... ok
test_cliente_que_se_va_no_afecta_a_los_demas (test_avisos.WebSocketTest.test_cliente_que_se_va_no_afecta_a_los_demas) ... ok

----------------------------------------------------------------------
Ran 4 tests in 1.325s

OK
```

En la prueba del cliente muerto, el log registró el aviso "Se quita un
cliente WebSocket que no recibió el aviso". Eso confirma que el envío falló de
verdad y que `broadcast` lo manejó sin interrumpir el envío al otro cliente.

### Proceso real de Uvicorn

También se arrancó la API como proceso aparte (`python -m uvicorn
app.main:app`), sin cocina, igual que en la prueba del navegador. Dos clientes
WebSocket se conectaron a `/ws` y se siguieron los pasos 3 a 8:

| Caso | Estado antes | `marcar-listo` | Aviso al otro cliente | `/health` | Estado final | Pedido nuevo | Proceso activo |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Cierre normal | `error_cocina` | `200` | `listo` en 4,4 ms | `200` | `listo` | `201` | Sí |
| Corte sin cierre | `error_cocina` | `200` | `listo` en 12,7 ms | `200` | `listo` | `201` | Sí |

Al final, `GET /estadisticas` devolvió `{"pedidos_listos": 2, "importe_total":
"6.00"}` y el proceso seguía activo. El log de Uvicorn mostró las cuatro
conexiones WebSocket aceptadas y cuatro errores `Fallo al procesar el pedido`
con `ConnectionRefusedError`. Esos errores vienen de los cuatro pedidos
enviados a cocina, que estaba apagada a propósito. No apareció ningún error
del WebSocket.

## Relación con el escenario de calidad

El atributo es **disponibilidad** (tolerancia a fallos): la falla de un
cliente no debe afectar al servicio ni a los demás clientes.

- **Fallo aislado.** Cada cliente tiene su propia conexión y su propia
  corrutina en el servidor. Cuando un cliente se va, solo termina su
  corrutina. El otro cliente recibió el aviso en todos los casos.
- **Detección de la desconexión.** El endpoint `/ws` está siempre esperando
  mensajes del cliente con `receive_text()`. Cuando el cliente se va, esa
  espera termina con `WebSocketDisconnect` y el cliente se quita de la lista.
  Pasó tanto con el cierre normal como con el corte sin cierre.
- **Red de seguridad en `broadcast`.** Si el servidor todavía no notó la
  desconexión, el envío a ese cliente falla. El `try/except` está dentro del
  bucle `for`, así que solo se descarta ese cliente y el bucle sigue con los
  demás. Sin ese `try/except`, la excepción cortaría el bucle y los clientes
  siguientes no recibirían el aviso.
- **El servidor no se cae.** En todos los casos `/health` respondió `200`, se
  aceptaron pedidos nuevos y el proceso siguió activo.
- **Medida.** El escenario pide que el aviso llegue al otro cliente en menos
  de 1 s. Los tiempos observados fueron de 3,7 ms a 12,7 ms en local.

## Hallazgo: el botón temporal compite con el flujo de cocina

Con la API real y cocina apagada, se creó un pedido y se marcó como listo de
inmediato, antes de que fallara la conexión a cocina. Justo después del
`marcar-listo` el pedido estaba en `listo`, pero 4 s después estaba en
`error_cocina`: el procesador de cocina guardó su error encima del `listo`.
El aviso se envía igual, pero el estado final del pedido no queda en `listo`.

La causa es que, cuando cocina falla, `app/cliente_cocina.py` guarda
`error_cocina` sin mirar el estado que tiene el pedido en ese momento. En el
flujo real esto no pasa, porque solo cocina pone `listo`. Solo afecta al botón
temporal **Marcar listo**. Por eso los pasos de la prueba esperan a ver
`error_cocina` antes de pulsar el botón.

## Limitaciones

- La medida de tiempo es local: API y clientes en el mismo equipo.
- Las pruebas automáticas usan clientes WebSocket de Python en lugar de
  pestañas del navegador. El protocolo es el mismo. La prueba en el navegador
  se describe en los pasos de arriba.
- El aviso lo dispara el botón temporal **Marcar listo**. Falta repetir la
  prueba cuando el aviso esté conectado a la cocina real (`al_listo` en
  `app/main.py`).
- Un cliente que estaba desconectado cuando se envió el aviso no lo recibe
  después. Ve el estado al recargar la lista.
