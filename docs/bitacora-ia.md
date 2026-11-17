# Bitácora de ayuda inicial de IA

Fecha: 2026-11-16. Herramienta: Codex.

Se preparó una base mínima con FastAPI, `GET /health`, dependencias y una guía
de ejecución en PowerShell.

## Cocina TCP (Veronica)

Fecha: 2026-11-16. Herramienta: Claude Code (modelo Claude Opus 5.5).

- **Uso.** Se pidió a la IA implementar la parte asignada a partir del reparto
  de tareas del grupo y del código existente de la API: servidor TCP de
  cocina con caja y facturación en memoria, cliente TCP con tiempo de espera
  para `app.state.procesar_pedido`, pruebas, mapa de microservicios, ADR de
  sockets TCP y documento de la prueba de cocina detenida.
- **Decisiones revisadas.** Protocolo de una línea JSON por conexión, plazo
  que cubre todo el intercambio, llamada de red fuera del bloqueo de pedidos,
  e idempotencia por ID en cocina, caja y facturación.
- **Ejecución y correcciones.** La IA ejecutó las pruebas en el equipo de la
  integrante. La primera ejecución falló por un error de la propia prueba:
  aplicar dos veces `patch.object` sobre `app.state` de Starlette provocaba un
  `KeyError` al limpiar. Se corrigió parcheando una sola vez. Después pasaron
  las 14 pruebas. Los resultados documentados son los de esas ejecuciones.
- **Integración.** La IA registró el cliente TCP en `app/main.py` mediante
  `lifespan` y comprobó el recorrido con la API y cocina como procesos
  separados, con cocina encendida y apagada.
- **Resultado inesperado.** La conexión rechazada tardó unos 2 s en Windows;
  se investigó y se documentó en la prueba y en el ADR.
- **Control humano.** Los commits los hizo la integrante; la IA no ejecutó
  comandos de Git ni accedió a GitHub.


## Página web, avisos WebSocket y estadísticas (Jonnathan)

Fecha: 2026-11-16. Herramienta: Claude Code (modelo Claude Opus 5.5).

- **Uso.** Se pidió a la IA implementar la parte asignada sobre el código
  existente de la API y de cocina: página HTML servida por la API con
  formulario y lista de pedidos (`fetch`), `GET /pedidos` para listar,
  endpoint `/ws` con `ConnectionManager`, aviso de pedido listo en la página,
  `GET /estadisticas`, la conexión del aviso con cocina mediante `al_listo`,
  pruebas, ADR de WebSockets, ADR comparativo de TCP y WebSockets y la prueba
  de cliente desconectado. También se pidió explicar cada parte para la
  defensa.
- **Código generado.** Los archivos `app/pagina.py`, `app/avisos.py`,
  `app/estadisticas.py` y `tests/test_avisos.py`, y la función
  `listar_pedidos` de `app/pedidos.py`, están marcados con un comentario que
  indica que se generaron con IA. También son de la IA los cambios de
  registro en `app/main.py`, las pruebas de la página y de estadísticas en
  `tests/test_pedidos.py` y los documentos citados en el punto anterior.
- **Decisiones revisadas.** Antes de escribir las estadísticas, la IA
  preguntó los nombres de los campos y el integrante confirmó `estado` con
  valor `"listo"` y `total` como importe. Otras decisiones: crear
  `GET /pedidos` porque solo existía la consulta por ID; mostrar datos con
  `textContent` para evitar inyección de HTML; sumar importes con `Decimal`;
  en `broadcast`, recorrer una copia de la lista y capturar el error de cada
  cliente dentro del bucle; y enviar el aviso desde el hilo de cocina con
  `asyncio.run_coroutine_threadsafe` sobre el bucle guardado al arrancar.
- **Ejecución y correcciones.** La IA ejecutó las pruebas en el equipo del
  integrante. El Python global no tenía las dependencias, así que se creó
  `.venv` con `requirements.txt`. Uvicorn no aceptaba WebSockets sin la
  librería `websockets`, que se agregó a `requirements.txt`. Una prueba
  generada por la IA tuvo un error de sintaxis en un f-string y se corrigió.
  Un reemplazo de texto de la IA dejó una frase mal redactada en el README,
  que se corrigió después. Al final pasaron las 28 pruebas.
- **Integración.** El botón temporal "Marcar listo" se usó para probar el
  aviso antes de conectarlo con cocina. Después se pasó
  `al_listo=avisar_pedido_listo` a `crear_procesador` en `app/main.py`, se
  retiraron el botón y su endpoint, y se comprobó el recorrido
  REST → TCP → WebSocket con la API y cocina como procesos separados.
- **Resultados inesperados.** Con el botón temporal, si se marcaba un pedido
  como listo antes de que fallara la conexión a cocina, el procesador guardaba
  `error_cocina` encima del `listo`. La IA lo comprobó con la API real antes
  de documentarlo; dejó de aplicar al retirar el botón. Al conectar con
  cocina, el aviso tardaba unos 2 s: se investigó y era la demora de
  preparación simulada de cocina (`--demora`), no un error.
- **Control humano.** Los commits, el push y los Pull Request los hizo el
  integrante. La IA creó las ramas locales y consultó el estado de Git, pero
  no hizo commits ni accedió a GitHub. La prueba con dos pestañas del
  navegador la realiza el integrante siguiendo la
  [prueba de cliente desconectado](prueba-cliente-desconectado.md).
