# atr_api/routes/imss.py

from __future__ import annotations

from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

from atr_api.errors import ApiError
from atr_api.extensions import db
from atr_api.models.client import Client
from atr_api.models.operator_imss import OperatorIMSS
from atr_api.services.imss_excel_import_service import import_imss_from_excel


bp = Blueprint("imss", __name__, url_prefix="/api")


# ---------------- helpers ----------------

def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


def _validate_client(client_id: int) -> Client:
    c = db.session.get(Client, client_id)
    if not c:
        raise ApiError("Cliente no válido.", status_code=400)
    return c


def _parse_int(v: Any, name: str, allow_none: bool = False) -> Optional[int]:
    if v is None or v == "":
        return None if allow_none else 0
    try:
        return int(v)
    except Exception:
        raise ApiError(f"{name} inválido.", status_code=400)


def _parse_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "si", "s", "yes", "y"):
        return True
    if s in ("0", "false", "f", "no", "n"):
        return False
    return None


def _get_cuota(row: OperatorIMSS) -> float:
    try:
        return round(float(row.monto or 0), 2)
    except Exception:
        return 0.0


def _serialize_row(row: OperatorIMSS) -> Dict[str, Any]:
    return {
        "id": int(row.id),
        "client_id": int(row.client_id),
        "operator_id": int(row.operator_id),
        "year": int(row.year),
        "month": int(row.month),
        "cuota_imss": _get_cuota(row),
        "activo": bool(getattr(row, "activo")) if hasattr(row, "activo") else True,
        "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
        "updated_at": row.updated_at.isoformat() if getattr(row, "updated_at", None) else None,
    }


# ---------------- endpoints ----------------

@bp.get("/clients/<int:client_id>/imss/health")
def imss_health(client_id: int):
    try:
        _validate_client(client_id)
        return jsonify({"status": "ok", "client_id": client_id})
    except ApiError as e:
        return _err(str(e), e.status_code or 400)


@bp.post("/clients/<int:client_id>/imss/import-excel")
def import_imss_excel(client_id: int):
    try:
        _validate_client(client_id)

        file = request.files.get("file")
        if not file:
            raise ApiError("Debe enviar archivo Excel en campo 'file'.")

        year = request.form.get("year", type=int)
        if not year:
            raise ApiError("Debe enviar 'year' en el form-data.")

        dry_run = request.args.get("dry_run", "1") != "0"

        result = import_imss_from_excel(
            client_id=client_id,
            file_storage=file,
            year=year,
            dry_run=dry_run,
        )

        return jsonify(result)

    except ApiError as e:
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        return _err(f"No se pudo importar IMSS. {str(e)}", 400)


@bp.get("/clients/<int:client_id>/imss")
def list_imss(client_id: int):
    try:
        _validate_client(client_id)

        year = _parse_int(request.args.get("year"), "year")
        if not year:
            raise ApiError("year es obligatorio.", status_code=400)

        month = _parse_int(request.args.get("month"), "month", allow_none=True)
        operator_id = _parse_int(request.args.get("operator_id"), "operator_id", allow_none=True)

        q = (
            db.session.query(OperatorIMSS)
            .filter(
                OperatorIMSS.client_id == int(client_id),
                OperatorIMSS.year == int(year),
            )
        )

        if month is not None:
            if month < 1 or month > 12:
                raise ApiError("month inválido (1-12).", status_code=400)
            q = q.filter(OperatorIMSS.month == int(month))

        if operator_id is not None:
            q = q.filter(OperatorIMSS.operator_id == int(operator_id))

        q = q.order_by(OperatorIMSS.month.asc(), OperatorIMSS.operator_id.asc())
        items = q.all()

        return jsonify({
            "client_id": int(client_id),
            "year": int(year),
            "month": int(month) if month is not None else None,
            "total": len(items),
            "items": [_serialize_row(x) for x in items],
        })

    except ApiError as e:
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        return _err(f"No se pudo listar IMSS. {str(e)}", 400)


@bp.get("/clients/<int:client_id>/operators/<int:operator_id>/imss")
def get_operator_imss_year(client_id: int, operator_id: int):
    try:
        _validate_client(client_id)

        year = _parse_int(request.args.get("year"), "year")
        if not year:
            raise ApiError("year es obligatorio.", status_code=400)

        month = _parse_int(request.args.get("month"), "month", allow_none=True)

        q = (
            db.session.query(OperatorIMSS)
            .filter(
                OperatorIMSS.client_id == int(client_id),
                OperatorIMSS.operator_id == int(operator_id),
                OperatorIMSS.year == int(year),
            )
            .order_by(OperatorIMSS.month.asc())
        )

        if month is not None:
            if month < 1 or month > 12:
                raise ApiError("month inválido (1-12).", status_code=400)
            q = q.filter(OperatorIMSS.month == int(month))

        items = q.all()

        return jsonify({
            "client_id": int(client_id),
            "operator_id": int(operator_id),
            "year": int(year),
            "month": int(month) if month is not None else None,
            "total": len(items),
            "items": [_serialize_row(x) for x in items],
        })

    except ApiError as e:
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        return _err(f"No se pudo leer IMSS del operador. {str(e)}", 400)


@bp.delete("/clients/<int:client_id>/imss")
def delete_imss(client_id: int):
    try:
        _validate_client(client_id)

        confirm = _parse_bool(request.args.get("confirm"))
        if confirm is not True:
            raise ApiError("Acción peligrosa. Para confirmar usa ?confirm=1", status_code=400)

        year = _parse_int(request.args.get("year"), "year")
        if not year:
            raise ApiError("year es obligatorio.", status_code=400)

        month = _parse_int(request.args.get("month"), "month", allow_none=True)
        if month is not None and (month < 1 or month > 12):
            raise ApiError("month inválido (1-12).", status_code=400)

        q = db.session.query(OperatorIMSS).filter(
            OperatorIMSS.client_id == int(client_id),
            OperatorIMSS.year == int(year),
        )
        if month is not None:
            q = q.filter(OperatorIMSS.month == int(month))

        deleted = q.delete(synchronize_session=False)
        db.session.commit()

        return jsonify({
            "status": "deleted",
            "client_id": int(client_id),
            "year": int(year),
            "month": int(month) if month is not None else None,
            "deleted": int(deleted),
        })

    except ApiError as e:
        db.session.rollback()
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo borrar IMSS. {str(e)}", 400)
