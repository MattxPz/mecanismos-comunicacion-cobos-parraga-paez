from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from .pedidos import datos_invalidos, router


app = FastAPI(title="Pedidos de cafetería")
app.add_exception_handler(RequestValidationError, datos_invalidos)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
