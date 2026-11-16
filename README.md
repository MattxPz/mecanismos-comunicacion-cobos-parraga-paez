# Pedidos de cafetería

Base mínima de una práctica de sistemas distribuidos con Python y FastAPI.
Actualmente solo funciona `GET /health`, que devuelve `{"status":"ok"}`.

Más adelante se añadirán pedidos, comunicación interna por sockets TCP, avisos
por WebSockets y datos en memoria. Esas funciones todavía no están implementadas.

## Archivos

- `app/main.py`: aplicación FastAPI y ruta de salud.
- `requirements.txt`: dependencias para arrancar.
- `.gitignore`: exclusiones de Python y configuración local.
- `README.md`: instalación y ejecución.
- `docs/bitacora-ia.md`: registro de la ayuda inicial de IA.
- `blame.md`: identificación de los archivos generados con ayuda de IA.

## Instalar y ejecutar en Windows PowerShell

Requisito: Python 3.11 o posterior. Abrir PowerShell en la carpeta
`MecanismosComunicacion` y ejecutar:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

No hace falta activar el entorno virtual. Para detener el servidor: `Ctrl+C`.

En otra terminal PowerShell:

```powershell
$respuesta = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing
$respuesta.StatusCode
$respuesta.Content
```

Resultado esperado: código `200` y cuerpo `{"status":"ok"}`.
También se puede abrir [la ruta de salud](http://127.0.0.1:8000/health)
en el navegador.
