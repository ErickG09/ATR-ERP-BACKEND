from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict

from atr_api.errors import ApiError
from atr_api.models import Car


NUMERIC_FIELDS = ["capacidad", "km_acum", "lt_dies_ac", "ingre_acum"]
DATE_OPTIONAL = ["fec_u_sal"]


def _parse_date(value: Any, field_name: str) -> date | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None

    if isinstance(value, date):
        return value

    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ApiError(
            f"El campo '{field_name}' debe tener formato 'YYYY-MM-DD'.", 400
        )


def _parse_numeric(value: Any, field_name: str) -> Decimal:
    if value is None or (isinstance(value, str) and not value.strip()):
        return Decimal("0")

    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ApiError(
            f"El campo '{field_name}' debe ser numérico (ej. 1234.56).", 400
        )


def _decimal_to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def sanitize_car_payload(
    payload: Dict[str, Any],
    *,
    partial: bool = False,
) -> Dict[str, Any]:
    """
    Normaliza y valida el payload de carros.
    """

    data: Dict[str, Any] = {}

    # codigo (obligatorio en alta)
    if not partial or "codigo" in payload:
        raw = payload.get("codigo")
        if not raw or not str(raw).strip():
            raise ApiError("El campo 'codigo' es obligatorio.", 400)
        data["codigo"] = str(raw).strip().upper()

    # tipo (obligatorio en alta)
    if not partial or "tipo" in payload:
        raw = payload.get("tipo")
        if not raw or not str(raw).strip():
            raise ApiError("El campo 'tipo' es obligatorio.", 400)
        data["tipo"] = str(raw).strip().upper()

    # Fecha opcional
    for field in DATE_OPTIONAL:
        if partial and field not in payload:
            continue
        raw = payload.get(field)
        data[field] = _parse_date(raw, field)

    # Numéricos
    for field in NUMERIC_FIELDS:
        if partial and field not in payload:
            continue
        raw = payload.get(field)
        data[field] = _parse_numeric(raw, field)

    # Operador (texto)
    if not partial or "operador" in payload:
        raw = payload.get("operador")
        data["operador"] = "" if raw is None else str(raw).strip()

    # activo (opcional, default True)
    if not partial or "activo" in payload:
        if "activo" not in payload:
            data["activo"] = True
        else:
            raw_activo = payload.get("activo")
            if isinstance(raw_activo, bool):
                data["activo"] = raw_activo
            else:
                raise ApiError("El campo 'activo' debe ser booleano.", 400)

    return data


def serialize_car(car: Car) -> Dict[str, Any]:
    """
    Representación para el catálogo de carros.
    """
    return {
        "id": car.id,
        "client_id": car.client_id,
        "codigo": car.codigo,
        "tipo": car.tipo,
        "capacidad": _decimal_to_float(car.capacidad),
        "km_acum": _decimal_to_float(car.km_acum),
        "fec_u_sal": car.fec_u_sal.isoformat() if car.fec_u_sal else None,
        "lt_dies_ac": _decimal_to_float(car.lt_dies_ac),
        "ingre_acum": _decimal_to_float(car.ingre_acum),
        "operador": car.operador,
        "activo": car.activo,
    }
