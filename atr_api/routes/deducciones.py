# atr_api/routes/deducciones.py
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

# Keys "preset" que existen en tu liquidaciones.py (menos impuestos que es automático)
PRESET_KEYS = (
    "ayuda_escolar",
    "infonavit",
    "sindicato",
    "imss",
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


def _get_operator_for_client(client_id: int, operator_id: int) -> Operator:
    op = db.session.get(Operator, operator_id)
    if not op or int(op.client_id) != int(client_id):
        raise ApiError("Operador inválido para este cliente.", status_code=400)
    return op


def _default_config_payload():
    # forma compatible con tu store: { global, global_extras, per_operator, updated_at }
    return {
        "global": {
            "ayuda_escolar": "0",
            "impuestos": "0",  # UI puede mostrarlo, pero NO se usa (en liq es auto 6%)
            "infonavit": "0",
            "sindicato": "0",
            "imss": "0",
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
        "updated_at": row.updated_at.isoformat() if row.updated_at else (row.created_at.isoformat() if row.created_at else None),
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


def _sync_ayuda_escolar_to_operators(client_id: int, payload: dict):
    """
    REGLA:
    - Si per_operator[opId].enabled y trae values.ayuda_escolar => ese manda para ese operador.
    - Si no hay override, usa global.ayuda_escolar para ese operador.
    Solo actualizamos operadores del client_id actual.
    """
    global_obj = payload.get("global") or {}
    per_op = payload.get("per_operator") or {}

    g_help = _num(global_obj.get("ayuda_escolar"), 0.0)
    if g_help is None:
        g_help = 0.0

    # carga operadores del cliente
    ops = Operator.query.filter_by(client_id=client_id).all()

    for op in ops:
        key = str(op.id)
        entry = per_op.get(key) or {}
        enabled = bool(entry.get("enabled") is True)
        values = entry.get("values") or {}

        if enabled and ("ayuda_escolar" in values):
            v = _num(values.get("ayuda_escolar"), g_help)
            if v is None:
                v = g_help
            op.ayuda_escolar = round(float(v), 2)
        else:
            # usa global
            op.ayuda_escolar = round(float(g_help), 2)


def _validate_config_payload(body: dict) -> dict:
    """
    Validación mínima para no romper tu UI:
    - global: dict
    - per_operator: dict
    - global_extras: list
    Además normalizamos montos a string (para que tu UI los mantenga como texto).
    """
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

    # normaliza keys conocidas a string num (sin forzar, pero asegura que existan si quieres)
    def _as_money_string(v):
        if v is None:
            return "0"
        s = str(v).strip()
        return s if s != "" else "0"

    for k in list(global_obj.keys()):
        # permitimos que UI mande "impuestos" pero backend no lo usa como config real
        global_obj[k] = _as_money_string(global_obj.get(k))

    # per_operator: { "123": { enabled: bool, values: {..}, extras:[..] } }
    for op_id, entry in per_operator.items():
        if not isinstance(entry, dict):
            raise ApiError("per_operator tiene una entrada inválida.", status_code=400)
        enabled = bool(entry.get("enabled") is True)
        values = entry.get("values") or {}
        extras = entry.get("extras") or []

        if not isinstance(values, dict):
            raise ApiError("per_operator.values debe ser objeto.", status_code=400)
        if not isinstance(extras, list):
            raise ApiError("per_operator.extras debe ser lista.", status_code=400)

        # normaliza values a strings
        for k2 in list(values.keys()):
            values[k2] = _as_money_string(values.get(k2))

        per_operator[str(op_id)] = {
            "enabled": enabled,
            "values": values,
            "extras": extras,
        }

    # extras globales: solo validamos forma ligera
    cleaned_global_extras = []
    for ex in global_extras:
        if not isinstance(ex, dict):
            continue
        ex_id = str(ex.get("id") or "").strip()
        label = str(ex.get("label") or "").strip()
        monto = _as_money_string(ex.get("monto"))
        enabled = bool(ex.get("enabled") is not False)  # default True

        if not ex_id or not label:
            continue
        cleaned_global_extras.append(
            {"id": ex_id, "label": label, "monto": monto, "enabled": enabled}
        )

    return {
        "global": global_obj,
        "per_operator": per_operator,
        "global_extras": cleaned_global_extras,
    }

# ---------------- endpoints: CONFIG ----------------

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

        # ✅ requisito tuyo: ayuda_escolar se refleja en tabla operators
        _sync_ayuda_escolar_to_operators(client_id, payload)

        db.session.commit()
        return jsonify(_serialize_config(row))
    except ApiError as e:
        db.session.rollback()
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo guardar config. {str(e)}", 400)

# ---------------- endpoints: EXTRAS "DEUDA" POR OPERADOR ----------------

@bp.get("/operators/<int:operator_id>/extras")
def list_operator_extras(client_id: int, operator_id: int):
    try:
        _validate_client(client_id)
        _get_operator_for_client(client_id, operator_id)

        activo = request.args.get("activo")
        q = OperatorDeduccionExtra.query.filter_by(client_id=client_id, operator_id=operator_id)

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


@bp.post("/operators/<int:operator_id>/extras")
def create_operator_extra(client_id: int, operator_id: int):
    try:
        _validate_client(client_id)
        _get_operator_for_client(client_id, operator_id)

        body = request.get_json(silent=True) or {}
        label = str(body.get("label") or "").strip()
        if not label:
            raise ApiError("label es obligatorio.", status_code=400)
        if len(label) > 140:
            raise ApiError("label demasiado largo (máx 140).", status_code=400)

        monto = _num(body.get("monto"), None)
        if monto is None:
            raise ApiError("monto inválido.", status_code=400)
        if monto < 0:
            raise ApiError("monto no puede ser negativo.", status_code=400)

        # saldo_restante opcional, si no viene = monto
        saldo_restante = _num(body.get("saldo_restante"), monto)
        if saldo_restante is None:
            saldo_restante = monto
        if saldo_restante < 0:
            raise ApiError("saldo_restante no puede ser negativo.", status_code=400)

        activo = bool(body.get("activo") is not False)

        x = OperatorDeduccionExtra(
            client_id=client_id,
            operator_id=operator_id,
            label=label,
            saldo_original=round(float(monto), 2),
            saldo_restante=round(float(saldo_restante), 2),
            activo=activo,
        )
        db.session.add(x)
        db.session.commit()
        return jsonify(_serialize_extra(x)), 201
    except ApiError as e:
        db.session.rollback()
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo crear extra. {str(e)}", 400)


@bp.patch("/operators/<int:operator_id>/extras/<int:extra_id>")
def update_operator_extra(client_id: int, operator_id: int, extra_id: int):
    try:
        _validate_client(client_id)
        _get_operator_for_client(client_id, operator_id)

        x = OperatorDeduccionExtra.query.filter_by(
            id=extra_id, client_id=client_id, operator_id=operator_id
        ).one_or_none()
        if not x:
            raise ApiError("Extra no encontrada.", status_code=404)

        body = request.get_json(silent=True) or {}

        if "label" in body:
            label = str(body.get("label") or "").strip()
            if not label:
                raise ApiError("label inválido.", status_code=400)
            if len(label) > 140:
                raise ApiError("label demasiado largo (máx 140).", status_code=400)
            x.label = label

        if "saldo_restante" in body:
            sr = _num(body.get("saldo_restante"), None)
            if sr is None:
                raise ApiError("saldo_restante inválido.", status_code=400)
            if sr < 0:
                raise ApiError("saldo_restante no puede ser negativo.", status_code=400)
            x.saldo_restante = round(float(sr), 2)
            if float(x.saldo_restante or 0) <= 0:
                x.activo = False

        if "activo" in body:
            x.activo = bool(body.get("activo") is True)

        db.session.commit()
        return jsonify(_serialize_extra(x))
    except ApiError as e:
        db.session.rollback()
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo actualizar extra. {str(e)}", 400)


@bp.delete("/operators/<int:operator_id>/extras/<int:extra_id>")
def delete_operator_extra(client_id: int, operator_id: int, extra_id: int):
    try:
        _validate_client(client_id)
        _get_operator_for_client(client_id, operator_id)

        x = OperatorDeduccionExtra.query.filter_by(
            id=extra_id, client_id=client_id, operator_id=operator_id
        ).one_or_none()
        if not x:
            raise ApiError("Extra no encontrada.", status_code=404)

        hard = str(request.args.get("hard") or "0").strip().lower() in ("1", "true", "t", "yes", "y")
        if hard:
            db.session.delete(x)
        else:
            x.activo = False

        db.session.commit()
        return jsonify({"status": "deleted" if hard else "inactive", "id": int(extra_id)})
    except ApiError as e:
        db.session.rollback()
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo eliminar extra. {str(e)}", 400)
