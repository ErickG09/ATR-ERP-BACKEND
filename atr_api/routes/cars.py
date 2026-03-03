from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError, OperationalError

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models import Car
from atr_api.schemas.car import sanitize_car_payload, serialize_car, calc_rendimiento_promedio

bp = Blueprint("cars", __name__)

# ---------------------------------------------------------------------
# Config paginación
# - Antes tenías max 100; por eso “no ves” más de 100.
# - Subimos max a 1000 para debugging/uso real.
# - per_page=0 significa “trae todo”, pero con tope de seguridad.
# ---------------------------------------------------------------------
DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 1000
MAX_PER_PAGE_ALL = 5000  # seguridad cuando piden per_page=0


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


def _parse_bool_arg(name: str, default: bool) -> bool:
    raw = request.args.get(name, None)
    if raw is None:
        return default
    return str(raw).lower() in ("1", "true", "t", "yes", "y", "si", "sí", "s")


def _apply_common_filters(query):
    # Filtro por activo
    activo_param = request.args.get("activo")
    if activo_param is not None:
        value = activo_param.lower()
        if value in ("true", "1", "t", "yes", "y", "si", "sí", "s"):
            query = query.filter_by(activo=True)
        elif value in ("false", "0", "f", "no", "n"):
            query = query.filter_by(activo=False)

    # Búsqueda por código u operador
    search = request.args.get("search")
    if search:
        like = f"%{search}%"
        query = query.filter((Car.codigo.ilike(like)) | (Car.operador.ilike(like)))

    return query


@bp.get("/clients/<int:client_id>/cars")
def list_cars(client_id: int):
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=DEFAULT_PER_PAGE, type=int)

    # Por defecto: GLOBAL (mantengo tu comportamiento)
    include_all = _parse_bool_arg("include_all", default=True)

    if include_all:
        query = Car.query
    else:
        query = Car.query.filter_by(client_id=client_id)

    query = _apply_common_filters(query)

    # per_page=0 => traer todo (con tope de seguridad)
    if per_page == 0:
        try:
            items = (
                query.order_by(Car.codigo.asc())
                .limit(MAX_PER_PAGE_ALL)
                .all()
            )
        except OperationalError:
            db.session.rollback()
            raise ApiError("Conexión a la base de datos interrumpida. Intenta de nuevo.", status_code=503)

        serialized = [serialize_car(c) for c in items]

        # Nota: cuando per_page=0, page/pages no aplican realmente.
        return jsonify(
            {
                "items": serialized,
                "page": 1,
                "per_page": 0,
                "total": len(serialized),
                "pages": 1,
                "note": f"per_page=0 trae todo con límite {MAX_PER_PAGE_ALL}.",
            }
        )

    # Normaliza rangos
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    page = max(1, page)

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


@bp.get("/clients/<int:client_id>/cars/count")
def count_cars(client_id: int):
    """
    Devuelve conteos de unidades.
    Respeta los mismos filtros que list_cars:
      - include_all=1/0
      - activo=true/false
      - search=...
    """
    include_all = _parse_bool_arg("include_all", default=True)

    if include_all:
        query = Car.query
    else:
        query = Car.query.filter_by(client_id=client_id)

    query = _apply_common_filters(query)

    try:
        total = query.count()
    except OperationalError:
        db.session.rollback()
        raise ApiError("Conexión a la base de datos interrumpida. Intenta de nuevo.", status_code=503)

    return jsonify(
        {
            "client_id": client_id,
            "include_all": include_all,
            "filters": {
                "activo": request.args.get("activo"),
                "search": request.args.get("search"),
            },
            "total": total,
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
    car.rendimiento_promedio = calc_rendimiento_promedio(car.km_acum, car.lt_dies_ac)

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

    car.rendimiento_promedio = calc_rendimiento_promedio(car.km_acum, car.lt_dies_ac)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Error al actualizar el carro.", status_code=500)

    return jsonify(serialize_car(car))


@bp.delete("/clients/<int:client_id>/cars/<int:car_id>")
def delete_car(client_id: int, car_id: int):
    car = _get_car_global(client_id, car_id)

    hard = _parse_bool_arg("hard", default=False)

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