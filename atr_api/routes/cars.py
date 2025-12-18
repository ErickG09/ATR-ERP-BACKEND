from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError, OperationalError

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models import Car
from atr_api.schemas.car import sanitize_car_payload, serialize_car

bp = Blueprint("cars", __name__)


def _get_car_global(client_id: int, car_id: int) -> Car:
    """
    Carros son 'globales' (se listan desde cualquier cliente),
    pero conservan su client_id original en BD.

    1) intenta por (client_id, id) por compatibilidad
    2) si no existe, intenta por id global (sin validar client)
    """
    car = Car.query.filter_by(client_id=client_id, id=car_id).first()
    if car:
        return car

    car = db.session.get(Car, car_id)
    if not car:
        raise ApiError("Carro no encontrado.", status_code=404)

    return car


@bp.get("/clients/<int:client_id>/cars")
def list_cars(client_id: int):
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=50, type=int)
    per_page = min(max(per_page, 1), 100)

    # Por defecto: GLOBAL
    include_all = request.args.get("include_all", "1").lower() in ("1", "true", "t", "yes", "y")

    if include_all:
        query = Car.query
    else:
        query = Car.query.filter_by(client_id=client_id)

    # Filtro por activo
    activo_param = request.args.get("activo")
    if activo_param is not None:
        value = activo_param.lower()
        if value in ("true", "1", "t", "yes", "y"):
            query = query.filter_by(activo=True)
        elif value in ("false", "0", "f", "no", "n"):
            query = query.filter_by(activo=False)

    # Búsqueda por código u operador
    search = request.args.get("search")
    if search:
        like = f"%{search}%"
        query = query.filter((Car.codigo.ilike(like)) | (Car.operador.ilike(like)))

    try:
        pagination = query.order_by(Car.codigo.asc()).paginate(
            page=page,
            per_page=per_page,
            error_out=False,
        )
    except OperationalError:
        db.session.rollback()
        raise ApiError("Conexión a la base de datos interrumpida. Intenta de nuevo.", status_code=503)

    items = [serialize_car(c) for c in pagination.items]

    return jsonify(
        {
            "items": items,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        }
    )


@bp.get("/clients/<int:client_id>/cars/<int:car_id>")
def get_car(client_id: int, car_id: int):
    car = _get_car_global(client_id, car_id)
    return jsonify(serialize_car(car))


@bp.post("/clients/<int:client_id>/cars")
def create_car(client_id: int):
    json_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not json_data:
        raise ApiError("Se requiere un cuerpo JSON.", status_code=400)

    data = sanitize_car_payload(json_data, partial=False)
    data["client_id"] = client_id

    car = Car(**data)

    try:
        db.session.add(car)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Ya existe un carro con ese código para este cliente.", status_code=409)

    return jsonify(serialize_car(car)), 201


@bp.patch("/clients/<int:client_id>/cars/<int:car_id>")
def update_car(client_id: int, car_id: int):
    car = _get_car_global(client_id, car_id)

    json_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not json_data:
        raise ApiError("Se requiere un cuerpo JSON.", status_code=400)

    data = sanitize_car_payload(json_data, partial=True)

    # Validar cambio de código (unique por client_id REAL del registro)
    if "codigo" in data:
        new_codigo = data["codigo"].strip().upper()
        if new_codigo and new_codigo != car.codigo:
            scope_client_id = int(car.client_id)
            existing = (
                Car.query.filter_by(client_id=scope_client_id, codigo=new_codigo)
                .with_entities(Car.id)
                .first()
            )
            if existing and int(existing.id) != int(car.id):
                raise ApiError("Ya existe un carro con ese código para este cliente.", status_code=409)
            car.codigo = new_codigo

    for key, value in data.items():
        if key == "codigo":
            continue
        setattr(car, key, value)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Error al actualizar el carro.", status_code=500)

    return jsonify(serialize_car(car))


@bp.delete("/clients/<int:client_id>/cars/<int:car_id>")
def delete_car(client_id: int, car_id: int):
    car = _get_car_global(client_id, car_id)

    hard = request.args.get("hard", "0").lower() in ("1", "true", "t", "yes", "y")

    try:
        if hard:
            db.session.delete(car)
        else:
            car.activo = False
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Error al inactivar/eliminar el carro.", status_code=500)

    return jsonify({"status": "deleted" if hard else "inactivo", "id": car.id})
