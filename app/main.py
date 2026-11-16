from fastapi import FastAPI


app = FastAPI(title="Pedidos de cafetería")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
