from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models import Operator
from atr_api.schemas.operator import (
    sanitize_operator_payload,
    serialize_operator_brief,
    serialize_operator_detail,
)
from atr_api.services.operator_service import get_next_operator_code

bp = Blueprint("operators", __name__)


@bp.get("/health")
def health_check():
    """Endpoint sencillo para verificar que la API está viva."""
    return jsonify({"status": "ok"})


# --------------------------------------------------------------------
# Listar operadores por cliente (con filtros básicos)
# --------------------------------------------------------------------
@bp.get("/clients/<int:client_id>/operators")
def list_operators(client_id: int):
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=50, type=int)
    per_page = min(max(per_page, 1), 100)

    # Si no se manda include_all, por defecto mostramos TODOS los operadores
    # (globales). Si algún día quieres segmentar, llamas con ?include_all=0
    include_all = request.args.get("include_all", "1").lower() in ("1", "true", "t", "yes", "y")

    if include_all:
        query = Operator.query  # 👈 SIN filtro por client_id
    else:
        query = Operator.query.filter_by(client_id=client_id)

    # Filtro por activo (true / false)
    activo_param = request.args.get("activo")
    if activo_param is not None:
        value = activo_param.lower()
        if value in ("true", "1", "t", "yes", "y"):
            query = query.filter_by(activo=True)
        elif value in ("false", "0", "f", "no", "n"):
            query = query.filter_by(activo=False)

    # Búsqueda sencilla por nombre o código
    search = request.args.get("search")
    if search:
        like = f"%{search}%"
        query = query.filter(
            (Operator.nombre.ilike(like)) | (Operator.codigo.ilike(like))
        )

    pagination = query.order_by(Operator.codigo.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = [serialize_operator_brief(op) for op in pagination.items]

    return jsonify(
        {
            "items": items,
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        }
    )



# --------------------------------------------------------------------
# Obtener detalle de un operador
# --------------------------------------------------------------------
@bp.get("/clients/<int:client_id>/operators/<int:operator_id>")
def get_operator(client_id: int, operator_id: int):
    op = (
        Operator.query.filter_by(client_id=client_id, id=operator_id)
        .limit(1)
        .first()
    )
    if not op:
        raise ApiError("Operador no encontrado.", status_code=404)

    return jsonify(serialize_operator_detail(op))


# --------------------------------------------------------------------
# Obtener el siguiente código sugerido según el nombre
# --------------------------------------------------------------------
@bp.get("/clients/<int:client_id>/operators/next-code")
def get_next_code(client_id: int):
    full_name = request.args.get("full_name", "").strip()
    if not full_name:
        raise ApiError(
            "El parámetro 'full_name' es obligatorio para sugerir el código.",
            status_code=400,
        )

    code = get_next_operator_code(client_id=client_id, full_name=full_name)
    return jsonify({"codigo": code})


# --------------------------------------------------------------------
# Crear operador
# --------------------------------------------------------------------
@bp.post("/clients/<int:client_id>/operators")
def create_operator(client_id: int):
    json_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not json_data:
        raise ApiError("Se requiere un cuerpo JSON.", status_code=400)

    # Normalizamos/validamos datos de entrada
    data = sanitize_operator_payload(json_data, partial=False)

    # Generar código si no vino o vino vacío
    codigo = data.get("codigo", "").strip()
    if not codigo:
        codigo = get_next_operator_code(client_id=client_id, full_name=data["nombre"])
        data["codigo"] = codigo

    # Asigna client_id
    data["client_id"] = client_id

    op = Operator(**data)

    try:
        db.session.add(op)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        # Esto cubre principalmente el unique (client_id, codigo)
        raise ApiError(
            "Ya existe un operador con ese código para este cliente.",
            status_code=409,
        )

    return jsonify(serialize_operator_detail(op)), 201


# --------------------------------------------------------------------
# Actualizar operador (parcial, PATCH)
# --------------------------------------------------------------------
@bp.patch("/clients/<int:client_id>/operators/<int:operator_id>")
def update_operator(client_id: int, operator_id: int):
    op = (
        Operator.query.filter_by(client_id=client_id, id=operator_id)
        .limit(1)
        .first()
    )
    if not op:
        raise ApiError("Operador no encontrado.", status_code=404)

    json_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not json_data:
        raise ApiError("Se requiere un cuerpo JSON.", status_code=400)

    data = sanitize_operator_payload(json_data, partial=True)

    # Si se envía un 'codigo' nuevo, se valida unique
    if "codigo" in data:
        new_codigo = data["codigo"].strip()
        if new_codigo and new_codigo != op.codigo:
            existing = (
                Operator.query.filter_by(
                    client_id=client_id,
                    codigo=new_codigo,
                )
                .with_entities(Operator.id)
                .first()
            )
            if existing:
                raise ApiError(
                    "Ya existe un operador con ese código para este cliente.",
                    status_code=409,
                )
            op.codigo = new_codigo

    # Otros campos
    for key, value in data.items():
        if key == "codigo":
            continue
        setattr(op, key, value)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Error al actualizar el operador.", status_code=500)

    return jsonify(serialize_operator_detail(op))


# --------------------------------------------------------------------
# "Eliminar" operador → lo marcamos inactivo (activo = False)
# --------------------------------------------------------------------
@bp.delete("/clients/<int:client_id>/operators/<int:operator_id>")
def delete_operator(client_id: int, operator_id: int):
    op = (
        Operator.query.filter_by(client_id=client_id, id=operator_id)
        .limit(1)
        .first()
    )
    if not op:
        raise ApiError("Operador no encontrado.", status_code=404)

    hard = request.args.get("hard", "0").lower() in ("1", "true", "t", "yes", "y")

    try:
        if hard:
            db.session.delete(op)        
        else:
            op.activo = False            
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Error al inactivar/eliminar el operador.", status_code=500)

    return jsonify({"status": "deleted" if hard else "inactivo", "id": op.id})

