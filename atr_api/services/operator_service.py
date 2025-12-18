from __future__ import annotations

from sqlalchemy import desc

from atr_api.extensions import db
from atr_api.models import Operator
from atr_api.utils.code_generator import generate_operator_code_prefix


def get_next_operator_code(client_id: int, full_name: str) -> str:
    """
    Genera el siguiente código de operador para un cliente dado.

    Regla:
    - Prefijo = primera letra del primer apellido (ej. 'B').
    - Código en formato: <LETRA><consecutivo de 3 dígitos>, ej. 'B001', 'B010', 'B011'.
    - El consecutivo se calcula por cliente y por letra.
    """

    prefix = generate_operator_code_prefix(full_name)
    if not prefix.isalpha():
        prefix = "X"

    # Buscar el último código existente con ese prefijo para ese cliente
    last = (
        db.session.query(Operator.codigo)
        .filter(
            Operator.client_id == client_id,
            Operator.codigo.like(f"{prefix}%"),
        )
        .order_by(desc(Operator.codigo))
        .first()
    )

    if not last or not last[0]:
        next_seq = 1
    else:
        last_code = last[0]
        # Suponemos formato LETRA + 3 dígitos; si no coincide, reiniciamos
        numeric_part = last_code[1:]
        try:
            next_seq = int(numeric_part) + 1
        except ValueError:
            next_seq = 1

    return f"{prefix}{next_seq:03d}"
