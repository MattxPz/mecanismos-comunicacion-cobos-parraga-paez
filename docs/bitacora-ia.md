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
- **Resultado inesperado.** La conexión rechazada tardó unos 2 s en Windows;
  se investigó y se documentó en la prueba y en el ADR.
- **Control humano.** Los commits los hizo la integrante; la IA no ejecutó
  comandos de Git ni accedió a GitHub.

