# Pedidos de cafetería

Base mínima de una práctica de sistemas distribuidos con Python y FastAPI.
La ruta `GET /health` devuelve HTTP `200` y `{"status":"ok"}`.

Los pedidos se crean y consultan por REST. Se guardan en memoria y se pierden
al reiniciar el servidor. La comunicación por TCP y WebSockets se añadirá más
adelante.

## Herramientas

- **FastAPI** define las rutas REST, valida los datos de entrada y genera la
  documentación interactiva en `/docs`.
- **Uvicorn** es el servidor que ejecuta la aplicación FastAPI y recibe las
  peticiones HTTP.
- **Pydantic** define y valida los datos que recibe `POST /pedidos`.

## Archivos

- `app/main.py` · crea la aplicación, registra las rutas y ofrece `/health`.
- `app/pedidos.py` · rutas REST de pedidos, cálculo del total y almacenamiento en memoria.
- `app/modelos.py` · modelos de validación de productos y pedidos.
- `requirements.txt` · dependencias para arrancar.
- `.gitignore` · exclusiones de Python y configuración local.
- `README.md` · instalación y ejecución.
- `docs/bitacora-ia.md` · registro de la ayuda inicial de IA.

## Instalar y ejecutar en Windows PowerShell

Usa **Python 3.13** y verifica que `python --version` muestra esa versión.
Abre PowerShell en la raíz del proyecto, donde están `requirements.txt` y la
carpeta `app`, y ejecuta:

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```

`app.main:app` indica a Uvicorn que cargue el objeto `app` de `app/main.py`.
`--reload` reinicia la aplicación al detectar cambios en el código durante el
desarrollo. Cada reinicio borra los pedidos en memoria. Para detener el servidor,
pulsa `Ctrl+C` en la ventana donde lo arrancaste.

Por defecto escucha en `127.0.0.1:8000`. Si el puerto está ocupado, añade
`--port 8001` al comando y usa ese puerto en las consultas.

Para comprobar la respuesta, abre otra ventana de PowerShell y ejecuta:

```powershell
curl.exe -i http://127.0.0.1:8000/health
```

La respuesta debe mostrar `200 OK` y `{"status":"ok"}`. También puedes abrir
[/health](http://127.0.0.1:8000/health) en el navegador.

## Crear y consultar un pedido

Con el servidor en marcha, ejecuta en otra ventana de PowerShell:

```powershell
$api = "http://127.0.0.1:8000"
$json = '{"cliente":"Ana","productos":[{"nombre":"Cafe","cantidad":2,"precio":"2.50"}]}'
$pedido = irm "$api/pedidos" -Method Post -ContentType "application/json" -Body $json
irm "$api/pedidos/$($pedido.id)"
```

`POST /pedidos` devuelve `201` con un `id`, el total (`"5.00"` en el ejemplo)
y el estado `pendiente`. `GET /pedidos/{id}` devuelve el pedido con `200` o
`404` si el identificador no existe.

Envía un cliente y al menos un producto. Cada producto requiere un nombre,
una cantidad entera entre 1 y 2 147 483 647 y un precio unitario positivo con
hasta dos decimales y diez dígitos enteros. Usa texto como `"2.50"` para enviar el
precio con precisión. La respuesta representa el precio y el total como texto
con dos decimales. Los datos inválidos reciben `422`.
