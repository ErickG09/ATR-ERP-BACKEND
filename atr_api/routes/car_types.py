from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models import CarTypeConfig
from atr_api.schemas.car_type_config import (
    CAR_TYPE_CHOICES,
    sanitize_car_type_config_payload,
    serialize_car_type_config,
)

bp = Blueprint("car_types", __name__)


def _normalize_car_type(raw: str) -> str:
    ct = (raw or "").strip().upper()
    if ct not in CAR_TYPE_CHOICES:
        raise ApiError(
            f"Tipo de carro inválido '{ct}'. Debe ser uno de: {', '.join(sorted(CAR_TYPE_CHOICES))}.",
            status_code=400,
        )
    return ct


def _empty_config_dict(client_id: int, car_type: str) -> Dict[str, Any]:
    # Cero en todos los campos para tipos sin registro en BD
    base = {
        "id": None,
        "client_id": client_id,
        "car_type": car_type,
    }
    zeros: Dict[str, float] = {
        "sueldo_por_km": 0.0,
        "viaticos_por_km": 0.0,
        "sueldo_ayudante": 0.0,
        "viaticos_ayudante": 0.0,
        "viaje_especial": 0.0,
        "mexico": 0.0,
        "exp_ver": 0.0,
        "exp_lc": 0.0,
        "exp_tux": 0.0,
        "importado": 0.0,
        "local": 0.0,
        "patios": 0.0,
        "slp_altamira": 0.0,
        "ramos_altamira": 0.0,
        "slp_lc": 0.0,
        "sal_lzc": 0.0,
        "sal_ver": 0.0,
        "sal_altamira": 0.0,
        "resguardo": 0.0,
    }
    base.update(zeros)
    return base


@bp.get("/clients/<int:client_id>/car-types-config")
def list_car_type_configs(client_id: int):
    """
    Devuelve todas las configuraciones de tipos de carro para un cliente.
    Siempre regresa todos los tipos conocidos (CA, FU, NO, UR, HI)
    aunque alguno no exista aún en la base (en cuyo caso va en 0).
    """
    rows = CarTypeConfig.query.filter_by(client_id=client_id).all()
    by_type: Dict[str, Dict[str, Any]] = {
        row.car_type: serialize_car_type_config(row) for row in rows
    }

    result: Dict[str, Dict[str, Any]] = {}
    for ct in sorted(CAR_TYPE_CHOICES):
        result[ct] = by_type.get(ct) or _empty_config_dict(client_id, ct)

    return jsonify({"client_id": client_id, "configs": result})


@bp.get("/clients/<int:client_id>/car-types-config/<string:car_type>")
def get_car_type_config(client_id: int, car_type: str):
    ct = _normalize_car_type(car_type)

    cfg = (
        CarTypeConfig.query.filter_by(client_id=client_id, car_type=ct)
        .limit(1)
        .first()
    )
    if not cfg:
        # Si no existe en BD, regresamos todo en 0 (para que el front rellene)
        return jsonify(_empty_config_dict(client_id, ct))

    return jsonify(serialize_car_type_config(cfg))


@bp.put("/clients/<int:client_id>/car-types-config/<string:car_type>")
def upsert_car_type_config(client_id: int, car_type: str):
    """
    Crea o actualiza la configuración de un tipo de carro para un cliente.
    """
    ct = _normalize_car_type(car_type)

    json_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not json_data:
        raise ApiError("Se requiere un cuerpo JSON.", status_code=400)

    data = sanitize_car_type_config_payload(json_data, partial=False)

    cfg = (
        CarTypeConfig.query.filter_by(client_id=client_id, car_type=ct)
        .limit(1)
        .first()
    )

    if not cfg:
        cfg = CarTypeConfig(client_id=client_id, car_type=ct)

    for key, value in data.items():
        setattr(cfg, key, value)

    try:
        db.session.add(cfg)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError(
            "Error al guardar la configuración de tipo de carro.",
            status_code=500,
        )

    return jsonify(serialize_car_type_config(cfg))
