# atr_api/routes/talon_series.py

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models.client import Client
from atr_api.models.talon_series import TalonSeries
from atr_api.services.talon_service import normalize_folio


bp = Blueprint(
    "talon_series",
    __name__,
    url_prefix="/api/clients/<int:client_id>/talon-series",
)

# Padding permitido (catálogo)
# Antes: 1..10
# Ahora: 1..12 (para permitir talones con hasta 12 dígitos en el consecutivo)
PADDING_MIN = 1
PADDING_MAX = 12


def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


def _validate_client(client_id: int):
    c = db.session.get(Client, client_id)
    if not c:
        return None, _err("Cliente no válido.", 400)
    return c, None


def _serialize(row: TalonSeries) -> Dict[str, Any]:
    # Si hay datos viejos con padding fuera de rango, no tronamos: lo “clamp” para respuesta.
    try:
        pad = int(row.padding or 5)
    except Exception:
        pad = 5
    if pad < PADDING_MIN:
        pad = PADDING_MIN
    if pad > PADDING_MAX:
        pad = PADDING_MAX

    return {
        "id": int(row.id),
        "client_id": int(row.client_id),
        "folio": row.folio,
        "cliente_nombre": row.cliente_nombre,
        "padding": pad,
        "activo": bool(row.activo),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@bp.get("")
def list_series(client_id: int):
    _, err = _validate_client(client_id)
    if err:
        return err

    activo = request.args.get("activo")
    q = db.session.query(TalonSeries).filter(TalonSeries.client_id == client_id)

    if activo is not None:
        s = str(activo).strip().lower()
        if s in ("1", "true", "t", "si", "s", "yes", "y"):
            q = q.filter(TalonSeries.activo.is_(True))
        elif s in ("0", "false", "f", "no", "n"):
            q = q.filter(TalonSeries.activo.is_(False))

    items = q.order_by(TalonSeries.folio.asc()).all()
    return jsonify({"items": [_serialize(x) for x in items]})


@bp.post("")
def create_series(client_id: int):
    _, err = _validate_client(client_id)
    if err:
        return err

    body = request.get_json(silent=True) or {}
    try:
        folio = normalize_folio(body.get("folio"))
    except ApiError as e:
        return _err(str(e), e.status_code or 400)

    cliente_nombre = (body.get("cliente_nombre") or "").strip() or None
    if cliente_nombre and len(cliente_nombre) > 120:
        return _err("cliente_nombre demasiado largo (máx 120).", 400)

    # padding
    try:
        padding = int(body.get("padding") or 5)
    except Exception:
        return _err("padding inválido.", 400)

    if padding < PADDING_MIN or padding > PADDING_MAX:
        return _err(f"padding inválido ({PADDING_MIN} a {PADDING_MAX}).", 400)

    activo = bool(body.get("activo") is not False)

    exists = (
        db.session.query(TalonSeries)
        .filter(
            TalonSeries.client_id == int(client_id),
            TalonSeries.folio == folio,
        )
        .one_or_none()
    )
    if exists:
        return _err("Esa serie ya existe para este cliente.", 409)

    row = TalonSeries(
        client_id=int(client_id),
        folio=folio,
        cliente_nombre=cliente_nombre,
        padding=padding,
        activo=activo,
    )
    db.session.add(row)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo crear la serie. {str(e)}", 400)

    return jsonify(_serialize(row)), 201


@bp.patch("/<int:series_id>")
def update_series(client_id: int, series_id: int):
    _, err = _validate_client(client_id)
    if err:
        return err

    row = (
        db.session.query(TalonSeries)
        .filter(TalonSeries.id == int(series_id), TalonSeries.client_id == int(client_id))
        .one_or_none()
    )
    if not row:
        return _err("Serie no encontrada.", 404)

    body = request.get_json(silent=True) or {}

    # folio (solo si lo quieres permitir; si no, se puede bloquear)
    if "folio" in body:
        try:
            folio2 = normalize_folio(body.get("folio"))
        except ApiError as e:
            return _err(str(e), e.status_code or 400)

        # evitar colisión
        exists = (
            db.session.query(TalonSeries)
            .filter(
                TalonSeries.client_id == int(client_id),
                TalonSeries.folio == folio2,
                TalonSeries.id != int(series_id),
            )
            .one_or_none()
        )
        if exists:
            return _err("Ya existe otra serie con ese folio.", 409)

        row.folio = folio2

    if "cliente_nombre" in body:
        cn = (body.get("cliente_nombre") or "").strip() or None
        if cn and len(cn) > 120:
            return _err("cliente_nombre demasiado largo (máx 120).", 400)
        row.cliente_nombre = cn

    if "padding" in body:
        try:
            padding = int(body.get("padding") or 5)
        except Exception:
            return _err("padding inválido.", 400)
        if padding < PADDING_MIN or padding > PADDING_MAX:
            return _err(f"padding inválido ({PADDING_MIN} a {PADDING_MAX}).", 400)
        row.padding = padding

    if "activo" in body:
        row.activo = bool(body.get("activo") is True)

    row.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo actualizar. {str(e)}", 400)

    return jsonify(_serialize(row))


@bp.delete("/<int:series_id>")
def delete_series(client_id: int, series_id: int):
    """
    Borrado suave por defecto: activo=false.
    Si quieres hard delete: ?hard=1
    """
    _, err = _validate_client(client_id)
    if err:
        return err

    row = (
        db.session.query(TalonSeries)
        .filter(TalonSeries.id == int(series_id), TalonSeries.client_id == int(client_id))
        .one_or_none()
    )
    if not row:
        return _err("Serie no encontrada.", 404)

    hard = str(request.args.get("hard") or "0").strip().lower() in ("1", "true", "t", "yes", "y")

    try:
        if hard:
            db.session.delete(row)
        else:
            row.activo = False
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo eliminar. {str(e)}", 400)

    return jsonify({"status": "deleted" if hard else "inactive", "id": int(series_id)})