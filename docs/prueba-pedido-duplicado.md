# Prueba de pedido duplicado

Esta prueba comprueba que, si el cliente repite un `POST /pedidos` con la misma
`Idempotency-Key` y el mismo cuerpo, la API conserva un solo pedido y programa
una sola llamada al procesamiento de cocina.

## Pasos reproducibles

1. Abre PowerShell en la raíz del proyecto, donde está `requirements.txt`.
   Prepara el entorno tal como indica el README.
2. Ejecuta la prueba aislada. La prueba arranca su propio servidor Uvicorn en
   un puerto local disponible y lo detiene al terminar.

   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_pedidos.py -k duplicado -v
   ```

3. La prueba empieza con registros vacíos, registra un sustituto de cocina que
   anota el ID recibido y envía el mismo `POST` dos veces. Espera a que terminen
   las tareas antes de contar pedidos y llamadas.

## Resultado esperado

El primer `POST` devuelve `201`. El segundo devuelve `200` con el mismo ID y
cuerpo. Quedan un pedido en memoria y una llamada al sustituto de cocina.

## Resultado observado y evidencia

La prueba aislada pasó el 16 de noviembre de 2026 en Windows con Python 3.13.14.
La salida registró un pedido guardado y una sola llamada al sustituto:

```text
test_pedido_duplicado_procesa_una_sola_vez (test_pedidos.PedidosTest.test_pedido_duplicado_procesa_una_sola_vez) ... ok
Duplicado: POST inicial=201, reintento=200, mismo ID=True, guardados=1, llamadas al sustituto de cocina=1

----------------------------------------------------------------------
Ran 1 test in 0.370s

OK
```

Las solicitudes HTTP se hicieron contra la API real. El sustituto se usó solo
para contar llamadas. Los módulos de cocina TCP y avisos WebSocket aún faltan
en el proyecto, por lo que la comprobación REST → TCP → WebSocket queda pendiente.

Para ejecutar los cinco casos, desde la raíz:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Preguntas para relacionar con el escenario de calidad

- Si el cliente pierde la primera respuesta, ¿qué debe conservar para reintentar?
- ¿Qué evidencia muestra que el reintento recuperó el pedido y no duplicó su procesamiento?
- ¿Qué cambia en tu escenario si se reinicia el proceso entre ambos intentos?
