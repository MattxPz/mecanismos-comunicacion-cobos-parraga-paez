from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


TextoRequerido = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Producto(BaseModel):
    nombre: TextoRequerido
    cantidad: Annotated[int, Field(strict=True, gt=0, le=2_147_483_647)]
    precio: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]


class PedidoNuevo(BaseModel):
    cliente: TextoRequerido
    productos: Annotated[list[Producto], Field(min_length=1)]
