# Pedidos de cafetería

API REST de una práctica de sistemas distribuidos. Permite crear pedidos,
consultar su estado y repetir un envío sin duplicar el pedido dentro de un mismo
proceso. FastAPI define las rutas, Pydantic valida los datos y Uvicorn recibe las
solicitudes HTTP.

## Instalar y arrancar en Windows PowerShell

Necesitas **Python 3.13** disponible como `python`. La instalación de dependencias
requiere acceso al índice de paquetes que usa pip. Abre PowerShell en la raíz
del proyecto, donde están `requirements.txt` y la carpeta `app`:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\uvicorn.exe app.main:app
```

Uvicorn escucha en **`http://127.0.0.1:8000`**. Si el puerto está ocupado,
puedes arrancar en el **8001** y usar ese puerto también en `$api`:

```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --port 8001
```

Para detener tu servidor, pulsa `Ctrl+C` en la ventana donde lo arrancaste.
La opción `--reload` es útil al desarrollar. Reinicia la aplicación al detectar
cambios en el código y borra los pedidos y las claves guardados en memoria.

## Arrancar el servicio de cocina TCP

Cocina es un proceso aparte que recibe los pedidos por TCP, registra el cobro
en caja y emite la factura. En otra ventana de PowerShell, desde la raíz:

```powershell
.\.venv\Scripts\python.exe -m cocina.servidor --puerto 9000 --demora 2
```

`--demora` son los segundos que tarda en preparar cada pedido. Detenlo con
`Ctrl+C`. La API lo busca en `127.0.0.1:9000` y espera como máximo 5 s; se
puede cambiar con las variables `COCINA_HOST`, `COCINA_PUERTO` y
`COCINA_TIEMPO_ESPERA` antes de arrancar Uvicorn. El protocolo está descrito
en el [ADR de sockets TCP](docs/adr-sockets-tcp.md).

## Crear, consultar y repetir un pedido

En otra ventana de PowerShell ejecuta el bloque completo. Conserva la misma
clave y el mismo cuerpo durante el reintento:

```powershell
$api = 'http://127.0.0.1:8000'
curl.exe -i "$api/health"

$solicitud = @{
    Method = 'Post'
    ContentType = 'application/json'
    Headers = @{ 'Idempotency-Key' = [guid]::NewGuid().ToString() }
    Body = '{"cliente":"Ana","productos":[{"nombre":"Cafe","cantidad":2,"precio":"2.50"}]}'
}

$alta = iwr "$api/pedidos" @solicitud -UseBasicParsing
$pedido = $alta.Content | ConvertFrom-Json
$alta.StatusCode
$pedido

$consulta = iwr "$api/pedidos/$($pedido.id)" -UseBasicParsing
$consulta | Select-Object StatusCode, Content

$reintento = iwr "$api/pedidos" @solicitud -UseBasicParsing
$reintento.StatusCode
($reintento.Content | ConvertFrom-Json).id -eq $pedido.id
```

| Operación | Resultado esperado |
| --- | --- |
| `GET /health` | `200` con `{"status":"ok"}` |
| Crear con clave nueva | `201`, ID nuevo, estado `pendiente` y total `"5.00"` en el ejemplo |
| Consultar el ID creado | `200` con el pedido y su último estado guardado |
| Repetir la clave y los mismos datos validados | `200` con el mismo ID. La comparación del ejemplo imprime `True` |
| Reusar la clave con datos válidos distintos | `409` |
| Consultar un ID inexistente | `404` |
| Omitir la clave, enviarla en blanco o enviar datos inválidos | `422` |

Genera una clave nueva al crear otro pedido. Cada pedido requiere un cliente y
al menos un producto con nombre, cantidad entera entre 1 y 2 147 483 647 y
precio unitario positivo. El precio admite hasta diez dígitos enteros y dos
decimales. Usa texto como `"2.50"` para enviarlo con precisión. Los importes de
la respuesta son texto con dos decimales. La comparación usa los datos
validados. `"2.50"` y `2.5` representan el mismo precio. Cambiar el orden de
los productos sí cambia los datos. Consulta el contrato en `/docs` o
`/openapi.json` en el mismo puerto.

## Alcance y límites

- Los pedidos y las claves se pierden al detener, reiniciar o recargar Uvicorn.
  Varios workers tienen memorias independientes. Ejecuta un solo proceso para
  que todos los reintentos consulten el mismo registro.
- El servicio de cocina TCP con caja y facturación (`cocina/`) y su cliente
  (`app/cliente_cocina.py`) ya existen. Falta registrar el cliente en
  `app/main.py`. El cliente web, las notificaciones WebSocket y las
  estadísticas están pendientes.
- Un pedido queda `pendiente` mientras la aplicación carezca de un procesador
  registrado. Las pruebas sustituyen cocina para comprobar la llamada única
  y el estado `error_cocina` ante un fallo simulado. El recorrido completo
  con los módulos reales está pendiente.

## Contratos para integrar

La API guarda el pedido y su clave antes de programar, en segundo plano,
`app.state.procesar_pedido(pedido_id)`. La tarea se programa solo al crear.
Si el procesador lanza una excepción, la API guarda `error_cocina`, salvo
cuando el estado ya es `listo`.

| Módulo | Acuerdo pendiente con el equipo |
| --- | --- |
| Cocina TCP | Implementado. Registrar en `app/main.py` con `app.state.procesar_pedido = crear_procesador(pedidos, bloqueo_pedidos)` desde `app/cliente_cocina.py`. Estados: `pendiente` → `en_cocina` → `listo` (con `factura` y `cobro`) o `error_cocina` (con `error`). La llamada de red se hace fuera del bloqueo de pedidos. |
| Avisos WebSocket | Función y formato de `pedido_listo`, destinatario y manejo de fallos de envío. Guardar `listo` antes de enviar el aviso. `crear_procesador` acepta `al_listo(pedido)`, que se llama después de guardar `listo`; si lanza una excepción, se registra en el log y el pedido sigue `listo`. |
| Cliente web | Conservar el ID para consultar y la clave con el cuerpo para reintentar. Acordar el contrato de avisos y el origen web. La API aún no configura CORS para clientes en otro origen. |
| Estadísticas | Acordar cómo obtiene los pedidos, qué estados cuenta y cómo interpreta los importes de la API. Esta versión solo expone la consulta por ID. |

## Pruebas y documentos

Desde la raíz del proyecto:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

- [Evidencia de la prueba de pedido duplicado](docs/prueba-pedido-duplicado.md)
- [Evidencia de la prueba de cocina detenida](docs/prueba-cocina-detenida.md)
- [Mapa de microservicios](docs/mapa-microservicios.md)
- [ADR de sockets TCP](docs/adr-sockets-tcp.md)
- [Escenarios de calidad y mediciones](docs/escenarios-calidad.md)
- [Contexto C4](docs/contexto-c4.md)
- [ADR provisional de REST](docs/adr-rest.md)
- [Bitácora](docs/bitacora-ia.md)
