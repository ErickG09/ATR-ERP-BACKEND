from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict

from atr_api.errors import ApiError
from atr_api.models import CarTypeConfig

# Tipos de carro permitidos (los mismos que en el front)
CAR_TYPE_CHOICES = {"CA", "FU", "NO", "UR", "HI"}

NUMERIC_FIELDS = [
    "sueldo_por_km",
    "viaticos_por_km",
    "sueldo_ayudante",
    "viaticos_ayudante",
    "viaje_especial",
    "mexico",
    "exp_ver",
    "exp_lc",
    "exp_tux",
    "importado",
    "local",
    "patios",
    "slp_altamira",
    "ramos_altamira",
    "slp_lc",
    "sal_lzc",
    "sal_ver",
    "sal_altamira",
    "resguardo",
]


def _parse_decimal(value: Any, field_name: str) -> Decimal:
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


def sanitize_car_type_config_payload(
    payload: Dict[str, Any],
    *,
    partial: bool = False,
) -> Dict[str, Any]:
    """
    Normaliza y valida payload de configuración de tipo de carro.
    El car_type se pasa por la URL, no se confía en el JSON.
    """
    data: Dict[str, Any] = {}

    for field in NUMERIC_FIELDS:
        if partial and field not in payload:
            continue
        raw = payload.get(field)
        data[field] = _parse_decimal(raw, field)

    return data


def serialize_car_type_config(cfg: CarTypeConfig) -> Dict[str, Any]:
    return {
        "id": cfg.id,
        "client_id": cfg.client_id,
        "car_type": cfg.car_type,
        "sueldo_por_km": _decimal_to_float(cfg.sueldo_por_km),
        "viaticos_por_km": _decimal_to_float(cfg.viaticos_por_km),
        "sueldo_ayudante": _decimal_to_float(cfg.sueldo_ayudante),
        "viaticos_ayudante": _decimal_to_float(cfg.viaticos_ayudante),
        "viaje_especial": _decimal_to_float(cfg.viaje_especial),
        "mexico": _decimal_to_float(cfg.mexico),
        "exp_ver": _decimal_to_float(cfg.exp_ver),
        "exp_lc": _decimal_to_float(cfg.exp_lc),
        "exp_tux": _decimal_to_float(cfg.exp_tux),
        "importado": _decimal_to_float(cfg.importado),
        "local": _decimal_to_float(cfg.local),
        "patios": _decimal_to_float(cfg.patios),
        "slp_altamira": _decimal_to_float(cfg.slp_altamira),
        "ramos_altamira": _decimal_to_float(cfg.ramos_altamira),
        "slp_lc": _decimal_to_float(cfg.slp_lc),
        "sal_lzc": _decimal_to_float(cfg.sal_lzc),
        "sal_ver": _decimal_to_float(cfg.sal_ver),
        "sal_altamira": _decimal_to_float(cfg.sal_altamira),
        "resguardo": _decimal_to_float(cfg.resguardo),
    }
