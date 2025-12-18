# atr_api/routes/guides.py
from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models import Guide, Operator, Car, Destination
from atr_api.schemas.guide import sanitize_guide_payload, serialize_guide

bp = Blueprint("guides", __name__)

# --- helpers globales para consistencia ---


def _normalize_ct(v: str | None) -> str:
    return (v or "").strip().upper()


def _get_operator_global(operator_id: int) -> Operator:
    op = db.session.get(Operator, operator_id)
    if not op:
        raise ApiError("Operador inválido.", status_code=400)
    return op


def _get_car_global(car_id: int) -> Car:
    car = db.session.get(Car, car_id)
    if not car:
        raise ApiError("Carro inválido.", status_code=400)
    return car


def _get_destination_by_client(client_id: int, destination_id: int) -> Destination:
    dest = Destination.query.filter_by(client_id=client_id, id=destination_id).first()
    if not dest:
        raise ApiError("Destinatario inválido para este cliente.", status_code=400)
    return dest


def _enforce_operator_car_type_match(op: Operator, car: Car) -> str:
    op_ct = _normalize_ct(getattr(op, "tipo_carro", ""))
    car_ct = _normalize_ct(getattr(car, "tipo", ""))
    if not op_ct or not car_ct:
        raise ApiError("Operador/Carro sin tipo de carro asignado.", status_code=400)
    if op_ct != car_ct:
        raise ApiError(
            f"Tipo de carro no coincide: Operador={op_ct} vs Carro={car_ct}.",
            status_code=400,
        )
    return car_ct


def _bool_param(name: str) -> bool | None:
    v = request.args.get(name)
    if v is None:
        return None
    s = v.strip().lower()
    if s in ("1", "true", "t", "yes", "y", "si", "sí", "s"):
        return True
    if s in ("0", "false", "f", "no", "n"):
        return False
    return None


@bp.get("/clients/<int:client_id>/guides")
def list_guides(client_id: int):
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=50, type=int)
    per_page = min(max(per_page, 1), 200)

    q = Guide.query.filter_by(client_id=client_id)

    # filtros
    operator_id = request.args.get("operator_id", type=int)
    if operator_id:
        q = q.filter(Guide.operator_id == operator_id)

    destination_id = request.args.get("destination_id", type=int)
    if destination_id:
        q = q.filter(Guide.destination_id == destination_id)

    status = (request.args.get("status") or "").strip().lower()
    if status:
        q = q.filter(Guide.status == status)

    activo = _bool_param("activo")
    if activo is not None:
        q = q.filter(Guide.activo == activo)

    search = (request.args.get("search") or "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(Guide.folio.ilike(like))

    pagination = q.order_by(Guide.fecha.desc(), Guide.folio.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify(
        {
            "items": [serialize_guide(g) for g in pagination.items],
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        }
    )


@bp.get("/clients/<int:client_id>/guides/<int:guide_id>")
def get_guide(client_id: int, guide_id: int):
    g = Guide.query.filter_by(client_id=client_id, id=guide_id).limit(1).first()
    if not g:
        raise ApiError("Guía no encontrada.", status_code=404)
    return jsonify(serialize_guide(g))


@bp.post("/clients/<int:client_id>/guides")
def create_guide(client_id: int):
    json_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not json_data:
        raise ApiError("Se requiere un cuerpo JSON.", status_code=400)

    data = sanitize_guide_payload(json_data, partial=False)
    data["client_id"] = client_id

    # --- Validaciones FK consistentes ---
    # Operador global (solo debe existir)
    op = _get_operator_global(data["operator_id"])

    # Destino sí es por cliente
    if data.get("destination_id") is not None:
        _get_destination_by_client(client_id, data["destination_id"])

    # Carro global + regla de consistencia tipo
    if data.get("car_id") is not None:
        car = _get_car_global(data["car_id"])
        car_ct = _enforce_operator_car_type_match(op, car)
        # Fuerza car_type desde el carro (no confíes en front)
        data["car_type"] = car_ct
    else:
        # Si no hay carro, usa el tipo del operador (evita inconsistencias)
        data["car_type"] = _normalize_ct(getattr(op, "tipo_carro", "")) or data.get(
            "car_type", ""
        )

    g = Guide(**data)

    try:
        db.session.add(g)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        # uq_guide_client_folio
        raise ApiError("Ya existe una guía con ese folio para este cliente.", status_code=409)

    return jsonify(serialize_guide(g)), 201


@bp.patch("/clients/<int:client_id>/guides/<int:guide_id>")
def update_guide(client_id: int, guide_id: int):
    g = Guide.query.filter_by(client_id=client_id, id=guide_id).limit(1).first()
    if not g:
        raise ApiError("Guía no encontrada.", status_code=404)

    # Bloqueo simple: si ya está liquidada, no se edita
    if g.status == "liquidated":
        raise ApiError("La guía está liquidada y no puede modificarse.", status_code=409)

    json_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not json_data:
        raise ApiError("Se requiere un cuerpo JSON.", status_code=400)

    data = sanitize_guide_payload(json_data, partial=True)

    # validar folio unique si cambia
    if "folio" in data and data["folio"] != g.folio:
        existing = (
            Guide.query.filter_by(client_id=client_id, folio=data["folio"])
            .with_entities(Guide.id)
            .first()
        )
        if existing:
            raise ApiError("Ya existe otra guía con ese folio.", status_code=409)

    # --- Validaciones FK consistentes (global) ---
    # Operador (si cambia)
    if "operator_id" in data and data["operator_id"] is not None:
        op = _get_operator_global(data["operator_id"])
    else:
        op = _get_operator_global(g.operator_id)

    # Destino (si cambia)
    if "destination_id" in data:
        if data["destination_id"] is not None:
            _get_destination_by_client(client_id, data["destination_id"])

    # Carro (si cambia)
    if "car_id" in data:
        if data["car_id"] is not None:
            car = _get_car_global(data["car_id"])
            car_ct = _enforce_operator_car_type_match(op, car)
            data["car_type"] = car_ct  # fuerza tipo
        else:
            # quitar carro: opcional -> vuelve al tipo del operador
            data["car_type"] = _normalize_ct(getattr(op, "tipo_carro", "")) or g.car_type
    else:
        # Si no cambia carro pero sí cambió operador, revalidar coherencia con el carro actual
        if ("operator_id" in data) and (g.car_id is not None):
            car = _get_car_global(g.car_id)
            car_ct = _enforce_operator_car_type_match(op, car)
            data["car_type"] = car_ct

    for k, v in data.items():
        setattr(g, k, v)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Error al actualizar la guía.", status_code=500)

    return jsonify(serialize_guide(g))


@bp.delete("/clients/<int:client_id>/guides/<int:guide_id>")
def delete_guide(client_id: int, guide_id: int):
    g = Guide.query.filter_by(client_id=client_id, id=guide_id).limit(1).first()
    if not g:
        raise ApiError("Guía no encontrada.", status_code=404)

    if g.status == "liquidated":
        raise ApiError("No puedes borrar una guía liquidada.", status_code=409)

    hard = (request.args.get("hard", "0").lower() in ("1", "true", "t", "yes", "y"))

    try:
        if hard:
            db.session.delete(g)
        else:
            g.activo = False
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Error al inactivar/eliminar la guía.", status_code=500)

    return jsonify({"status": "deleted" if hard else "inactivo", "id": g.id})
