"""Registros básicos de caja y facturación, guardados en memoria.

Ambos registros son idempotentes por ID de pedido: si el mismo pedido llega
dos veces, se devuelve el cobro o la factura existente en lugar de crear otro.
"""

from decimal import Decimal
from threading import Lock


class Caja:
    def __init__(self) -> None:
        self._cobros: dict[str, dict[str, str]] = {}
        self._bloqueo = Lock()

    def registrar_cobro(self, pedido_id: str, cliente: str, importe: Decimal) -> dict[str, str]:
        with self._bloqueo:
            cobro = self._cobros.get(pedido_id)
            if cobro is None:
                cobro = {
                    "pedido_id": pedido_id,
                    "cliente": cliente,
                    "importe": f"{importe:.2f}",
                    "estado": "cobrado",
                }
                self._cobros[pedido_id] = cobro
            return dict(cobro)

    def resumen(self) -> dict[str, object]:
        with self._bloqueo:
            total = sum((Decimal(cobro["importe"]) for cobro in self._cobros.values()), Decimal("0"))
            return {"cobros": len(self._cobros), "total_cobrado": f"{total:.2f}"}


class Facturacion:
    def __init__(self) -> None:
        self._facturas: dict[str, dict[str, object]] = {}
        self._bloqueo = Lock()

    def emitir(
        self, pedido_id: str, cliente: str, productos: list[dict[str, object]], total: Decimal
    ) -> dict[str, object]:
        with self._bloqueo:
            factura = self._facturas.get(pedido_id)
            if factura is None:
                factura = {
                    "numero": f"F-{len(self._facturas) + 1:05d}",
                    "pedido_id": pedido_id,
                    "cliente": cliente,
                    "productos": productos,
                    "total": f"{total:.2f}",
                }
                self._facturas[pedido_id] = factura
            return dict(factura)

    def cantidad(self) -> int:
        with self._bloqueo:
            return len(self._facturas)
