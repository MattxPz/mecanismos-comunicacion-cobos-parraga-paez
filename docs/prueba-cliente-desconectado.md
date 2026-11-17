# Prueba de cliente WebSocket desconectado

Esta prueba comprueba que, si un cliente WebSocket se desconecta (por ejemplo,
se cierra una pestaña), los demás clientes siguen recibiendo el aviso de
pedido listo y el servidor no se cae. Se relaciona con el escenario
[Cliente WebSocket desconectado](escenarios-calidad.md#cliente-websocket-desconectado).

El aviso sale del flujo real: el pedido entra por REST, cocina lo prepara por
TCP y, cuando lo deja `listo`, la API lo avisa por WebSocket.

## Qué se prueba

Dos clientes conectados a `/ws` representan dos pestañas abiertas de la
página. Se desconecta uno, se crea un pedido y, cuando cocina lo deja listo,
se comprueba que:

1. El otro cliente recibe el aviso `{"id": ..., "estado": "listo"}`.
2. `GET /health` sigue respondiendo `200`.
3. El pedido queda guardado como `listo` con su factura.
4. Un pedido nuevo se acepta (`201`) y también genera su aviso.
5. El proceso del servidor sigue activo.

Se prueban tres formas de desconexión:

| Caso | Qué simula | Qué hace el servidor |
| --- | --- | --- |
| Cierre normal | Cerrar la pestaña: el navegador envía el cierre WebSocket. | El endpoint `/ws` recibe `WebSocketDisconnect` y quita al cliente. |
| Corte sin cierre | El navegador se cuelga o se pierde la red: la conexión TCP se corta sin enviar el cierre WebSocket. | El endpoint `/ws` detecta la conexión cortada y quita al cliente. |
| Cliente muerto aún en la lista | El servidor todavía no notó la desconexión cuando cocina deja el pedido listo. | `broadcast` falla al enviarle, lo quita de la lista y sigue con el otro cliente. |

## Pasos reproducibles

### 1. Pruebas automáticas

En PowerShell, desde la raíz del proyecto, con el entorno preparado como
indica el README:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_avisos.py -k cliente -v
```

Cada prueba arranca su propia API con Uvicorn y su propia cocina TCP en
puertos libres. Registra el procesador de cocina con
`al_listo=avisar_pedido_listo`, igual que `app/main.py`, y conecta dos
clientes WebSocket reales con la librería `websockets`. La cocina de las
pruebas no tiene demora de preparación, para medir solo el recorrido TCP y
el aviso. Las pruebas están en `tests/test_avisos.py`:

- `test_cliente_cierra_y_el_otro_recibe_el_aviso`: cierre normal.
- `test_cliente_cortado_y_el_otro_recibe_el_aviso`: corte sin cierre.
- `test_cliente_muerto_aun_en_la_lista_no_afecta_a_los_demas`: se vuelve a
  poner en la lista el WebSocket del servidor de un cliente ya cerrado y se
  crea un pedido. Al quedar listo, el envío a ese cliente falla de verdad.
- `test_cliente_que_se_va_no_afecta_a_los_demas`: un cliente se va y el otro
  recibe un `broadcast`.

### 2. Prueba en el navegador

1. En una ventana de PowerShell, arranca cocina:

   ```powershell
   .\.venv\Scripts\python.exe -m cocina.servidor --puerto 9000 --demora 2
   ```

2. En otra ventana, arranca la API:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
   ```

3. Abre `http://127.0.0.1:8000/` en **dos pestañas** (A y B). Las dos deben
   mostrar "Avisos: conectado".
4. Cierra la pestaña A.
5. En la pestaña B, crea un pedido.
6. Unos 2 s después (la demora de cocina), comprueba que en la pestaña B
   aparece el aviso verde, la fila pasa a `listo` y las estadísticas suben.
7. Abre `http://127.0.0.1:8000/health` y comprueba que responde
   `{"status":"ok"}`. Revisa la terminal de Uvicorn: no debe aparecer ningún
   error relacionado con el WebSocket.

## Resultado esperado

| Comprobación | Esperado |
| --- | --- |
| Clientes registrados tras la desconexión | 1 |
| `POST /pedidos` | `201` |
| Aviso en el cliente que sigue conectado | `{"id": "<id>", "estado": "listo"}` en menos de 1 s desde que cocina deja el pedido listo |
| `GET /health` | `200` |
| Estado guardado del pedido | `listo` con factura |
| Pedido nuevo después de la desconexión | `201` y su aviso |
| Proceso del servidor | Sigue activo |

## Resultado observado

Ejecución del 16 de noviembre de 2026 en Windows 11 con Python 3.12.10.

### Pruebas automáticas

Las cuatro pruebas pasaron:

```text
test_cliente_cierra_y_el_otro_recibe_el_aviso (test_avisos.WebSocketTest.test_cliente_cierra_y_el_otro_recibe_el_aviso) ...
Cliente desconectado (cierre normal) | clientes tras desconectar=1 | POST=201 | aviso al otro cliente=listo en 117.4 ms | health=200 | pedido=listo factura=F-00001 | pedido nuevo=201/listo | servidor activo=True
ok
test_cliente_cortado_y_el_otro_recibe_el_aviso (test_avisos.WebSocketTest.test_cliente_cortado_y_el_otro_recibe_el_aviso) ...
Cliente desconectado (corte sin cierre) | clientes tras desconectar=1 | POST=201 | aviso al otro cliente=listo en 36.2 ms | health=200 | pedido=listo factura=F-00001 | pedido nuevo=201/listo | servidor activo=True
ok
test_cliente_muerto_aun_en_la_lista_no_afecta_a_los_demas (test_avisos.WebSocketTest.test_cliente_muerto_aun_en_la_lista_no_afecta_a_los_demas) ... ok
test_cliente_que_se_va_no_afecta_a_los_demas (test_avisos.WebSocketTest.test_cliente_que_se_va_no_afecta_a_los_demas) ... ok

----------------------------------------------------------------------
Ran 4 tests in 1.373s

OK
```

Los tiempos van desde el `POST` hasta que el otro cliente recibe el aviso, e
incluyen el intercambio TCP con cocina. En la prueba del cliente muerto, el
log registró el aviso "Se quita un cliente WebSocket que no recibió el
aviso". Eso confirma que el envío falló de verdad y que `broadcast` lo manejó
sin interrumpir el envío al otro cliente.

### Procesos reales

También se arrancaron cocina (`python -m cocina.servidor --demora 2`) y la API
(`python -m uvicorn app.main:app`) como procesos separados, igual que en la
prueba del navegador, sin parches de prueba. Dos clientes WebSocket se
conectaron a `/ws` y se siguieron los pasos 4 a 7:

| Caso | `POST` | Aviso al otro cliente (desde el `POST`) | Estado final | `/health` | Pedido nuevo | API y cocina activas |
| --- | --- | --- | --- | --- | --- | --- |
| Cierre normal | `201` en 0,020 s | `listo` a los 2,039 s | `listo`, factura `F-00001` | `200` | `201` con aviso | Sí |
| Corte sin cierre | `201` en 0,003 s | `listo` a los 2,014 s | `listo`, factura `F-00003` | `200` | `201` con aviso | Sí |

Los 2 s son la demora de preparación configurada en cocina. Descontándola, el
aviso llegó entre 14 ms y 39 ms después. En los dos casos el ID del aviso
coincidió con el del pedido creado. Al final, `GET /estadisticas` devolvió
`{"pedidos_listos": 4, "importe_total": "12.00"}`. El log de la API no tuvo
ningún error, y el de cocina registró los cuatro pedidos listos con las
facturas `F-00001` a `F-00004`.

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
- **El procesamiento sigue.** El aviso se envía después de guardar el pedido
  como `listo`, desde el hilo de cocina, sin esperar a los clientes. Un fallo
  al avisar no deshace el pedido ni frena a cocina: los pedidos siguientes se
  prepararon y facturaron con normalidad.
- **El servidor no se cae.** En todos los casos `/health` respondió `200`, se
  aceptaron pedidos nuevos y los procesos siguieron activos.
- **Medida.** El escenario pide que el aviso llegue al otro cliente en menos
  de 1 s desde que cocina deja el pedido listo. Los tiempos observados fueron
  de 14 ms a 117 ms en local.

## Limitaciones

- La medida de tiempo es local: API, cocina y clientes en el mismo equipo.
- Las pruebas automáticas y la ejecución con procesos usan clientes
  WebSocket de Python en lugar de pestañas del navegador. El protocolo es el
  mismo. La prueba en el navegador se describe en los pasos de arriba.
- Un cliente que estaba desconectado cuando se envió el aviso no lo recibe
  después. Ve el estado al recargar la lista.
