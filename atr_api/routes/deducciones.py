from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models.client import Client
from atr_api.models.operator import Operator
from atr_api.models.deducciones_config import ClientDeduccionesConfig
from atr_api.models.operator_deduccion_extra import OperatorDeduccionExtra


bp = Blueprint(
    "deducciones",
    __name__,
    url_prefix="/api/clients/<int:client_id>/deducciones",
)

# Keys preset configurables (IMSS eliminado — ahora viene de tabla mensual)
PRESET_KEYS = (
    "ayuda_escolar",
    "infonavit",
    "sindicato",
    "fonacot",
    "pension_alimenticia",
)

# ---------------- helpers ----------------

def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


def _num(v, default=None):
    if v is None:
        return default
    try:
        s = str(v).strip().replace(",", ".")
        if s == "":
            return default
        return float(s)
    except Exception:
        return default


def _validate_client(client_id: int) -> Client:
    c = db.session.get(Client, client_id)
    if not c:
        raise ApiError("Cliente no válido.", status_code=400)
    return c


def _get_operator_global(operator_id: int) -> Operator:
    op = db.session.get(Operator, operator_id)
    if not op:
        raise ApiError("Operador inválido.", status_code=400)
    return op


def _get_operator_for_client_if_available(client_id: int, operator_id: int) -> Operator:
    op = _get_operator_global(operator_id)

    if hasattr(op, "client_id"):
        if op.client_id is None or int(op.client_id) != int(client_id):
            raise ApiError("Operador inválido para este cliente.", status_code=400)

    return op


def _default_config_payload():
    return {
        "global": {
            "ayuda_escolar": "0",
            "impuestos": "0",  # informativo en UI (liquidación lo calcula automático)
            "infonavit": "0",
            "sindicato": "0",
            "fonacot": "0",
            "pension_alimenticia": "0",
        },
        "global_extras": [],
        "per_operator": {},
        "updated_at": None,
    }


def _serialize_config(row: ClientDeduccionesConfig):
    return {
        "global": row.global_json or {},
        "global_extras": row.global_extras_json or [],
        "per_operator": row.per_operator_json or {},
        "updated_at": (
            row.updated_at.isoformat()
            if row.updated_at
            else (row.created_at.isoformat() if row.created_at else None)
        ),
    }


def _serialize_extra(x: OperatorDeduccionExtra):
    return {
        "id": int(x.id),
        "client_id": int(x.client_id),
        "operator_id": int(x.operator_id),
        "label": x.label,
        "saldo_original": float(x.saldo_original or 0),
        "saldo_restante": float(x.saldo_restante or 0),
        "activo": bool(x.activo),
        "created_at": x.created_at.isoformat() if x.created_at else None,
        "updated_at": x.updated_at.isoformat() if x.updated_at else None,
    }


# ---------------- ayuda escolar sync ----------------

def _sync_ayuda_escolar_to_operators(client_id: int, payload: dict):

    global_obj = payload.get("global") or {}
    per_op = payload.get("per_operator") or {}

    g_help = _num(global_obj.get("ayuda_escolar"), 0.0)
    if g_help is None:
        g_help = 0.0

    if hasattr(Operator, "client_id"):
        ops = Operator.query.filter_by(client_id=client_id).all()
        for op in ops:
            key = str(op.id)
            entry = per_op.get(key) or {}
            enabled = bool(entry.get("enabled") is True)
            values = entry.get("values") or {}

            if enabled and ("ayuda_escolar" in values):
                v = _num(values.get("ayuda_escolar"), g_help)
                op.ayuda_escolar = round(float(v or g_help), 2)
            else:
                op.ayuda_escolar = round(float(g_help), 2)
        return

    # fallback operadores globales
    for op_id_str, entry in (per_op or {}).items():
        try:
            op_id = int(op_id_str)
        except Exception:
            continue

        op = db.session.get(Operator, op_id)
        if not op:
            continue

        entry = entry or {}
        enabled = bool(entry.get("enabled") is True)
        values = entry.get("values") or {}

        if enabled and ("ayuda_escolar" in values):
            v = _num(values.get("ayuda_escolar"), g_help)
            op.ayuda_escolar = round(float(v or g_help), 2)


def _validate_config_payload(body: dict) -> dict:

    if not isinstance(body, dict):
        raise ApiError("Cuerpo JSON inválido.", status_code=400)

    global_obj = body.get("global") or {}
    per_operator = body.get("per_operator") or {}
    global_extras = body.get("global_extras") or []

    if not isinstance(global_obj, dict):
        raise ApiError("'global' debe ser objeto.", status_code=400)
    if not isinstance(per_operator, dict):
        raise ApiError("'per_operator' debe ser objeto.", status_code=400)
    if not isinstance(global_extras, list):
        raise ApiError("'global_extras' debe ser lista.", status_code=400)

    def _as_money_string(v):
        if v is None:
            return "0"
        s = str(v).strip()
        return s if s != "" else "0"

    # Normalizar solo keys válidas
    for k in list(global_obj.keys()):
        if k not in PRESET_KEYS and k != "impuestos":
            global_obj.pop(k)
            continue
        global_obj[k] = _as_money_string(global_obj.get(k))

    cleaned_per_operator: dict = {}
    for op_id, entry in per_operator.items():
        if not isinstance(entry, dict):
            raise ApiError("per_operator inválido.", status_code=400)

        enabled = bool(entry.get("enabled") is True)
        values = entry.get("values") or {}
        extras = entry.get("extras") or []

        if not isinstance(values, dict):
            raise ApiError("per_operator.values debe ser objeto.", status_code=400)
        if not isinstance(extras, list):
            raise ApiError("per_operator.extras debe ser lista.", status_code=400)

        for k2 in list(values.keys()):
            if k2 not in PRESET_KEYS:
                values.pop(k2)
                continue
            values[k2] = _as_money_string(values.get(k2))

        cleaned_per_operator[str(op_id)] = {
            "enabled": enabled,
            "values": values,
            "extras": extras,
        }

    cleaned_global_extras = []
    for ex in global_extras:
        if not isinstance(ex, dict):
            continue

        ex_id = str(ex.get("id") or "").strip()
        label = str(ex.get("label") or "").strip()
        monto = _as_money_string(ex.get("monto"))
        enabled = bool(ex.get("enabled") is not False)

        if not ex_id or not label:
            continue

        cleaned_global_extras.append(
            {"id": ex_id, "label": label, "monto": monto, "enabled": enabled}
        )

    return {
        "global": global_obj,
        "per_operator": cleaned_per_operator,
        "global_extras": cleaned_global_extras,
    }


# ---------------- endpoints CONFIG ----------------

@bp.get("/config")
def get_config(client_id: int):
    try:
        _validate_client(client_id)
        row = ClientDeduccionesConfig.query.filter_by(client_id=client_id).one_or_none()
        if not row:
            return jsonify(_default_config_payload())
        return jsonify(_serialize_config(row))
    except ApiError as e:
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        return _err(f"No se pudo leer config. {str(e)}", 400)


@bp.put("/config")
def put_config(client_id: int):
    try:
        _validate_client(client_id)
        body = request.get_json(silent=True) or {}
        payload = _validate_config_payload(body)

        row = ClientDeduccionesConfig.query.filter_by(client_id=client_id).one_or_none()
        if not row:
            row = ClientDeduccionesConfig(client_id=client_id)
            db.session.add(row)
            db.session.flush()

        row.global_json = payload["global"]
        row.per_operator_json = payload["per_operator"]
        row.global_extras_json = payload["global_extras"]
        row.updated_at = datetime.utcnow()

        _sync_ayuda_escolar_to_operators(client_id, payload)

        db.session.commit()
        return jsonify(_serialize_config(row))

    except ApiError as e:
        db.session.rollback()
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo guardar config. {str(e)}", 400)


# ---------------- endpoints EXTRAS ----------------

@bp.get("/operators/<int:operator_id>/extras")
def list_operator_extras(client_id: int, operator_id: int):
    try:
        _validate_client(client_id)
        _get_operator_for_client_if_available(client_id, operator_id)

        activo = request.args.get("activo")
        q = OperatorDeduccionExtra.query.filter_by(
            client_id=client_id,
            operator_id=operator_id,
        )

        if activo is not None:
            s = str(activo).strip().lower()
            if s in ("1", "true", "t", "si", "s", "yes", "y"):
                q = q.filter(OperatorDeduccionExtra.activo.is_(True))
            elif s in ("0", "false", "f", "no", "n"):
                q = q.filter(OperatorDeduccionExtra.activo.is_(False))

        items = q.order_by(OperatorDeduccionExtra.id.desc()).all()
        return jsonify({"items": [_serialize_extra(x) for x in items]})

    except ApiError as e:
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        return _err(f"No se pudieron listar extras. {str(e)}", 400)
