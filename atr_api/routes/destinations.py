# atr_api/routes/destinations.py
from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models.destination import Destination
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

bp = Blueprint("destinations", __name__)


def _to_bool(v: str | None):
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "si", "sí", "s", "y", "yes"):
        return True
    if s in ("0", "false", "f", "no", "n"):
        return False
    return None


def _to_num(v, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    try:
        return float(str(v).replace(",", ".").strip())
    except Exception:
        return default


@bp.get("/clients/<int:client_id>/destinations")
def list_destinations(client_id: int):
    page = request.args.get("page", default=1, type=int)

    # acepta per_page o perPage
    per_page = request.args.get("per_page", type=int)
    if per_page is None:
        per_page = request.args.get("perPage", default=200, type=int)
    per_page = min(max(per_page, 1), 500)

    query = Destination.query.filter_by(client_id=client_id)

    activo_param = request.args.get("activo")
    b = _to_bool(activo_param)
    if b is not None:
        query = query.filter_by(activo=b)

    search = (request.args.get("search") or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(
            (Destination.codigo.ilike(like))
            | (Destination.nombre.ilike(like))
            | (Destination.plaza.ilike(like))
            | (Destination.ciudad.ilike(like))
            | (Destination.estado.ilike(like))
        )

    pagination = query.order_by(Destination.codigo.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify(
        {
            "items": [d.to_dict() for d in pagination.items],
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        }
    )


@bp.get("/clients/<int:client_id>/destinations/by-code/<string:codigo>")
def get_destination_by_code(client_id: int, codigo: str):
    codigo = (codigo or "").strip().upper()
    d = (
        Destination.query.filter_by(client_id=client_id, codigo=codigo)
        .limit(1)
        .first()
    )
    if not d:
        raise ApiError("Destinatario no encontrado.", status_code=404)
    return jsonify(d.to_dict())


@bp.post("/clients/<int:client_id>/destinations")
def create_destination(client_id: int):
    json_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not json_data:
        raise ApiError("Se requiere un cuerpo JSON.", status_code=400)

    codigo = (json_data.get("codigo") or "").strip().upper()
    nombre = (json_data.get("nombre") or "").strip()

    if not codigo:
        raise ApiError("El campo 'codigo' es obligatorio.", status_code=400)
    if not nombre:
        raise ApiError("El campo 'nombre' es obligatorio.", status_code=400)

    d = Destination(
        client_id=client_id,
        codigo=codigo,
        nombre=nombre,
        plaza=(json_data.get("plaza") or "").strip() or None,
        ciudad=(json_data.get("ciudad") or "").strip() or None,
        estado=(json_data.get("estado") or "").strip() or None,
        aplica_iva=bool(json_data.get("aplica_iva", True)),
        iva_pct=_to_num(json_data.get("iva_pct"), 16.0),
        aplica_retencion=bool(json_data.get("aplica_retencion", False)),
        retencion_pct=_to_num(json_data.get("retencion_pct"), 0.0),
        activo=bool(json_data.get("activo", True)),
    )

    try:
        db.session.add(d)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        # Puede ser UNIQUE (client_id, codigo) o una UNIQUE vieja (codigo)
        raise ApiError(
            "Ya existe un destinatario con ese código (revisa que tu UNIQUE sea por cliente).",
            status_code=409,
        )

    return jsonify(d.to_dict()), 201


@bp.patch("/clients/<int:client_id>/destinations/<int:destination_id>")
def update_destination(client_id: int, destination_id: int):
    d = (
        Destination.query.filter_by(client_id=client_id, id=destination_id)
        .limit(1)
        .first()
    )
    if not d:
        raise ApiError("Destinatario no encontrado.", status_code=404)

    json_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not json_data:
        raise ApiError("Se requiere un cuerpo JSON.", status_code=400)

    if "codigo" in json_data:
        new_codigo = (json_data.get("codigo") or "").strip().upper()
        if not new_codigo:
            raise ApiError("El campo 'codigo' no puede estar vacío.", status_code=400)

        if new_codigo != d.codigo:
            existing = (
                Destination.query.filter_by(client_id=client_id, codigo=new_codigo)
                .with_entities(Destination.id)
                .first()
            )
            if existing:
                raise ApiError(
                    "Ya existe un destinatario con ese código para este cliente.",
                    status_code=409,
                )
            d.codigo = new_codigo

    if "nombre" in json_data:
        new_nombre = (json_data.get("nombre") or "").strip()
        if not new_nombre:
            raise ApiError("El campo 'nombre' no puede estar vacío.", status_code=400)
        d.nombre = new_nombre

    for k in ("plaza", "ciudad", "estado"):
        if k in json_data:
            v = (json_data.get(k) or "").strip()
            setattr(d, k, v or None)

    if "aplica_iva" in json_data:
        d.aplica_iva = bool(json_data.get("aplica_iva"))
    if "iva_pct" in json_data:
        d.iva_pct = _to_num(json_data.get("iva_pct"), float(d.iva_pct or 0))

    if "aplica_retencion" in json_data:
        d.aplica_retencion = bool(json_data.get("aplica_retencion"))
    if "retencion_pct" in json_data:
        d.retencion_pct = _to_num(json_data.get("retencion_pct"), float(d.retencion_pct or 0))

    if "activo" in json_data:
        d.activo = bool(json_data.get("activo"))

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Error al actualizar el destinatario.", status_code=500)

    return jsonify(d.to_dict())


@bp.delete("/clients/<int:client_id>/destinations/<int:destination_id>")
def delete_destination(client_id: int, destination_id: int):
    d = (
        Destination.query.filter_by(client_id=client_id, id=destination_id)
        .limit(1)
        .first()
    )
    if not d:
        raise ApiError("Destinatario no encontrado.", status_code=404)

    # usa tu helper (acepta 1/true/t/yes/si)
    hard = _to_bool(request.args.get("hard")) is True

    try:
        if hard:
            # --- Precheck de dependencias (evita IntegrityError/FK) ---
            # Nota: ajusta nombres de tabla si en tu BD son distintos.
            # Aquí asumo: guides y liquidaciones.
            has_guide = db.session.execute(
                text(
                    """
                    SELECT 1
                    FROM guides
                    WHERE client_id = :cid AND destination_id = :did
                    LIMIT 1
                    """
                ),
                {"cid": client_id, "did": destination_id},
            ).first() is not None

            has_liq = db.session.execute(
                text(
                    """
                    SELECT 1
                    FROM liquidaciones
                    WHERE client_id = :cid AND destination_id = :did
                    LIMIT 1
                    """
                ),
                {"cid": client_id, "did": destination_id},
            ).first() is not None

            if has_guide or has_liq:
                raise ApiError(
                    "No se puede eliminar definitivamente: este destinatario está ligado a "
                    "Guías y/o Liquidaciones. Inactívalo (activo=false) para conservar historial.",
                    status_code=409,
                )

            db.session.delete(d)
            db.session.commit()
            return jsonify({"ok": True, "status": "deleted", "id": destination_id})

        # soft delete: inactivar
        d.activo = False
        db.session.commit()
        return jsonify({"ok": True, "status": "inactivo", "id": destination_id})

    except IntegrityError:
        db.session.rollback()
        # Si cae aquí, casi seguro es FK/UNIQUE/constraint => NO debe ser 500
        raise ApiError(
            "No se pudo eliminar: el destinatario está referenciado por otros registros. "
            "Inactívalo (activo=false) o elimina primero sus dependencias.",
            status_code=409,
        )
