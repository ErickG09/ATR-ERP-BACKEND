from __future__ import annotations

import re

from atr_api.extensions import db
from atr_api.models import Operator
from atr_api.utils.code_generator import generate_operator_code_prefix

_CODE_RE = re.compile(r"^([A-Z])(\d+)$")


def get_next_operator_code(client_id: int, full_name: str) -> str:
    """
    Genera el siguiente código de operador para un cliente dado, llenando huecos.

    Regla:
    - Prefijo = primera letra del primer apellido (según generate_operator_code_prefix).
    - Código en formato: <LETRA><consecutivo de 3 dígitos>, ej. 'B001'.
    - En vez de usar "máximo + 1", busca el MENOR disponible:
        Si existen A006 y A010 -> sugerirá A001 (luego A002... A005, A007, A008, A009, A011...).
    """

    prefix = (generate_operator_code_prefix(full_name) or "").strip().upper()
    if not prefix.isalpha():
        prefix = "X"
    prefix = prefix[0]

    like = f"{prefix}%"

    existing_codes = (
        db.session.query(Operator.codigo)
        .filter(Operator.client_id == client_id)
        .filter(Operator.codigo.ilike(like))
        .all()
    )

    used: set[int] = set()
    for (code,) in existing_codes:
        if not code:
            continue
        m = _CODE_RE.match(str(code).strip().upper())
        if not m:
            continue
        # asegura que el prefijo coincida
        if m.group(1) != prefix:
            continue
        try:
            used.add(int(m.group(2)))
        except Exception:
            continue

    n = 1
    while n in used:
        n += 1

    return f"{prefix}{n:03d}"
