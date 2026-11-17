from decimal import Decimal

from fastapi import APIRouter

from .pedidos import bloqueo_pedidos, pedidos


router = APIRouter()


@router.get("/estadisticas")
def estadisticas() -> dict[str, object]:
    # Se copian los pedidos listos dentro del bloqueo porque el hilo de cocina
    # puede cambiar el almacén mientras se recorre.
    with bloqueo_pedidos:
        listos = [pedido for pedido in pedidos.values() if pedido["estado"] == "listo"]

    # "total" es texto con dos decimales. Decimal suma sin errores de redondeo
    # (con float, 0.10 + 0.20 da 0.30000000000000004).
    importe = sum((Decimal(pedido["total"]) for pedido in listos), Decimal("0"))
    return {"pedidos_listos": len(listos), "importe_total": f"{importe:.2f}"}
