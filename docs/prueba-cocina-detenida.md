# Prueba de cocina detenida

Esta prueba comprueba que, si el servicio de cocina está detenido o no
responde, la API sigue aceptando pedidos, informa el problema en el estado del
pedido y no se cae. Se relaciona con el escenario
[Fallo del servicio de cocina](escenarios-calidad.md#fallo-del-servicio-de-cocina).

## Pasos reproducibles

1. Abre PowerShell en la raíz del proyecto y prepara el entorno como indica el
   README.
2. Ejecuta las pruebas de fallo de cocina. Cada prueba arranca su propia API
   (Uvicorn) y su propio servidor de cocina TCP en puertos libres, y los
   detiene al terminar.

   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_cocina_tcp.py -k cocina_detenida -k sin_respuesta -k apagada -k cocina_lenta -v
   ```

3. La prueba principal, `test_cocina_detenida_api_informa_sin_caerse`, hace lo
   siguiente con la API y el cliente TCP reales:
   1. Arranca una cocina, anota su puerto y la detiene. La API queda
      configurada para usar ese puerto, que ya no tiene servidor.
   2. Crea un pedido con `POST /pedidos` y consulta `GET /pedidos/{id}` hasta
      que deja de estar `pendiente` o `en_cocina`.
   3. Consulta `GET /health` y crea un segundo pedido.
   4. Arranca una cocina nueva, la registra en la API y crea un tercer pedido.

Las otras tres pruebas aíslan el comportamiento del cliente TCP: cocina
apagada sin pasar por la API, una cocina que acepta la conexión TCP pero
nunca contesta, y esa misma cocina muda usada a través de la API.

## Resultado esperado

| Situación | Esperado |
| --- | --- |
| `POST` con cocina detenida | `201` inmediato, sin esperar a cocina |
| Estado del pedido | `error_cocina` con el motivo en el campo `error` |
| `GET /health` durante el fallo | `200` |
| Segundo pedido con cocina detenida | `201` y `error_cocina`; la API sigue atendiendo |
| Tercer pedido con cocina recuperada | `201` y `listo` con factura |
| Cocina que no contesta, plazo 0,5 s | Error "Cocina no respondió en 0.5 s" en torno a 0,5 s |

## Resultado observado y evidencia

Ejecución del 16 de noviembre de 2026 en Windows 11 con Python 3.14.5. Las
cuatro pruebas pasaron:

```text
test_cocina_detenida_api_informa_sin_caerse (test_cocina_tcp.APIConCocinaTest.test_cocina_detenida_api_informa_sin_caerse) ...
Cocina detenida | POST=201 en 0.225 s | estado=error_cocina tras 2.276 s | error='No se pudo conectar con cocina en 127.0.0.1:58495 (ConnectionRefusedError)' | health=200 | segundo pedido=201/error_cocina | cocina recuperada=201/listo factura=F-00001
ok
test_cocina_lenta_queda_en_error_por_tiempo_de_espera (test_cocina_tcp.APIConCocinaTest.test_cocina_lenta_queda_en_error_por_tiempo_de_espera) ... ok
test_cocina_apagada_lanza_error_controlado (test_cocina_tcp.CocinaTCPTest.test_cocina_apagada_lanza_error_controlado) ...
Cocina apagada | error=No se pudo conectar con cocina en 127.0.0.1:58644 (ConnectionRefusedError) | segundos=2.028
ok
test_cocina_sin_respuesta_respeta_tiempo_de_espera (test_cocina_tcp.CocinaTCPTest.test_cocina_sin_respuesta_respeta_tiempo_de_espera) ...
Cocina sin respuesta | error=Cocina no respondió en 0.5 s | segundos=0.508
ok

----------------------------------------------------------------------
Ran 4 tests in 8.190s

OK
```

En una ejecución anterior de la suite completa (14 pruebas, todas correctas)
se obtuvieron valores similares: `POST` en 0,242 s, `error_cocina` a los
2,318 s, cocina apagada en 2,040 s y cocina muda en 0,506 s. Son los valores
citados en el [ADR de sockets TCP](adr-sockets-tcp.md).

| Medida | Ejecución aislada | Suite completa |
| --- | --- | --- |
| Respuesta del `POST` con cocina detenida | 0,225 s | 0,242 s |
| Tiempo hasta `error_cocina` | 2,276 s | 2,318 s |
| Conexión rechazada sin API | 2,028 s | 2,040 s |
| Plazo de 0,5 s con cocina muda | 0,508 s | 0,506 s |

## Explicación con los conceptos del capítulo

- **Fallo parcial.** En un sistema distribuido un componente puede fallar
  mientras los demás siguen funcionando. La API y cocina son procesos
  distintos: la caída de cocina se convierte en un estado del pedido
  (`error_cocina`), no en la caída de la API. `/health` respondió `200` y
  los pedidos siguientes se aceptaron con `201`.
- **Comunicación síncrona y acoplamiento temporal.** El intercambio TCP es
  síncrono: la API necesita que cocina esté activa en ese momento. Para que
  ese acoplamiento no llegue al estudiante, la llamada se hace en segundo
  plano después de responder. Por eso el `POST` tardó unos 0,23 s aunque la
  detección del fallo tardó más de 2 s.
- **Plazos (*timeouts*) como detector de fallos.** Un cliente sin plazo
  esperaría para siempre a una cocina que acepta la conexión pero no
  contesta. Con plazo de 0,5 s, el error llegó en 0,508 s. El plazo convierte
  "no sé si cocina responderá" en una decisión concreta.
- **No se distingue un servicio lento de uno caído.** El cliente solo sabe
  que no hubo respuesta a tiempo. Si cocina estuviera preparando el pedido y
  tardara más del plazo, la API también lo marcaría como `error_cocina`.
  Por eso cocina, caja y facturación son idempotentes por ID: un reenvío
  futuro del mismo pedido no lo cobraría dos veces.
- **Recuperación.** Al volver cocina, el tercer pedido llegó a `listo` con la
  factura `F-00001` sin reiniciar la API. No quedó ningún estado corrupto por
  los fallos anteriores.

## Resultado inesperado: la conexión rechazada tarda unos 2 segundos

Se esperaba que conectarse a un puerto sin servidor fallara de inmediato con
`ConnectionRefusedError`. En Windows tardó unos **2 s** en todas las
ejecuciones (2,028 s y 2,040 s sin API; 2,276 s y 2,318 s a través de la API).

La causa es el comportamiento de la pila TCP de Windows: cuando recibe un
rechazo (RST) a su solicitud de conexión (SYN), reintenta el SYN varias veces
antes de informar el error a la aplicación. En Linux el mismo caso suele
fallar en milisegundos. Consecuencias para el diseño:

- El plazo del cliente debe ser mayor que esos 2 s, o una cocina apagada
  se reportaría como "no respondió" y no como "no se pudo conectar". Por eso
  el plazo por defecto es de 5 s y la prueba usa 3 s.
- Esos 2 s no afectan al estudiante, porque el envío a cocina ocurre después
  de responder el `POST`.

## Limitaciones

- La prueba usa la API y la cocina reales en el mismo equipo, arrancadas por
  las pruebas. El registro del procesador en `app/main.py` está pendiente de
  integración, por eso la prueba lo registra con `patch.object`.
- Esta versión no reintenta automáticamente los pedidos en `error_cocina`.

## Preguntas para relacionar con el escenario de calidad

- ¿Por qué el `POST` responde rápido aunque cocina tarde más de 2 s en fallar?
- ¿Qué pasaría si el cliente TCP no tuviera plazo y cocina aceptara la
  conexión pero nunca contestara?
- ¿Qué cambiaría si la API reintentara automáticamente los pedidos en
  `error_cocina`? ¿Qué evita que se cobren dos veces?
