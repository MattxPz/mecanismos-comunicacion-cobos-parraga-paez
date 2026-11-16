# Pedidos de cafetería

Base mínima de una práctica de sistemas distribuidos con Python y FastAPI.
La ruta `GET /health` devuelve HTTP `200` y `{"status":"ok"}`.

Más adelante se añadirán pedidos, comunicación interna por sockets TCP, avisos
por WebSockets y datos en memoria.

## Archivos

- `app/main.py` · aplicación FastAPI y ruta de salud.
- `requirements.txt` · dependencias para arrancar.
- `.gitignore` · exclusiones de Python y configuración local.
- `README.md` · instalación y ejecución.
- `docs/bitacora-ia.md` · registro de la ayuda inicial de IA.

## Instalar y ejecutar en Windows PowerShell

Usa **Python 3.13** y verifica que `python --version` muestra esa versión.
Abre PowerShell en la carpeta que contiene `requirements.txt` y ejecuta:

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\uvicorn.exe app.main:app
```

Para comprobar la respuesta, abre otra ventana de PowerShell y ejecuta:

```powershell
curl.exe -i http://127.0.0.1:8000/health
```

La respuesta debe mostrar `200 OK` y `{"status":"ok"}`. También puedes abrir
[/health](http://127.0.0.1:8000/health) en el navegador.
Para detener el servidor, pulsa `Ctrl+C`.

