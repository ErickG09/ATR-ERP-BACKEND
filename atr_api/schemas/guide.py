# atr_api/schemas/guide.py
from __future__ import annotations

from datetime import date
from typing import Any, Dict

from atr_api.errors import ApiError
from atr_api.models import Guide


def _to_bool(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "si", "sí", "s"):
        return True
    if s in ("0", "false", "f", "no", "n"):
        return False
    return None


def _to_num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ".").strip())
    except Exception:
        return None


def _to_int_strict(v: Any) -> int | None:
    """
    Convierte a int, rechazando flotantes y strings con decimales.
    Acepta: 10, "10", " 10 "
    Rechaza: 10.0, "10.0", "10,0", "10.5"
    """
    if v is None or v == "":
        return None

    # bool es subclass de int en Python: evítalo
    if isinstance(v, bool):
        return None

    if isinstance(v, int):
        return v

    # float explícitamente no permitido (aunque sea .0)
    if isinstance(v, float):
        return None

    s = str(v).strip()
    if not s:
        return None

    # si trae separadores decimales, lo rechazamos
    if "." in s or "," in s:
        return None

    try:
        return int(s)
    except Exception:
        return None


def _to_date(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    try:
        # "YYYY-MM-DD"
        parts = s.split("-")
        if len(parts) != 3:
            return None
        y, m, d = (int(parts[0]), int(parts[1]), int(parts[2]))
        return date(y, m, d)
    except Exception:
        return None


ALLOWED_STATUS = {"draft", "posted", "liquidated", "cancelled"}


def sanitize_guide_payload(json_data: Dict[str, Any], partial: bool) -> Dict[str, Any]:
    data: Dict[str, Any] = {}

    # requeridos al crear
    if not partial:
        if not (json_data.get("folio") or "").strip():
            raise ApiError("El campo 'folio' es obligatorio.", status_code=400)
        if not (json_data.get("fecha") or "").strip():
            raise ApiError(
                "El campo 'fecha' (YYYY-MM-DD) es obligatorio.", status_code=400
            )
        if json_data.get("operator_id") in (None, ""):
            raise ApiError("El campo 'operator_id' es obligatorio.", status_code=400)

        # 'carros' NO lo hago obligatorio para permitir flujo legacy/fallback.
        # Si quieres hacerlo obligatorio, descomenta:
        # if json_data.get("carros") in (None, ""):
        #     raise ApiError("El campo 'carros' es obligatorio.", status_code=400)

    # folio
    if "folio" in json_data:
        folio = str(json_data.get("folio") or "").strip().upper()
        if not partial and not folio:
            raise ApiError("El campo 'folio' es obligatorio.", status_code=400)
        if folio:
            data["folio"] = folio

    # fecha
    if "fecha" in json_data:
        dt = _to_date(json_data.get("fecha"))
        if not dt:
            raise ApiError("Fecha inválida. Usa formato YYYY-MM-DD.", status_code=400)
        data["fecha"] = dt

    # ids
    for k in ("operator_id", "car_id", "destination_id"):
        if k in json_data:
            v = json_data.get(k)
            if v in (None, ""):
                data[k] = None
            else:
                try:
                    data[k] = int(v)
                except Exception:
                    raise ApiError(f"'{k}' debe ser numérico.", status_code=400)

    # car_type
    if "car_type" in json_data:
        data["car_type"] = str(json_data.get("car_type") or "").strip().upper()

    # carros (entero estricto, no decimales)
    if "carros" in json_data:
        v = json_data.get("carros")
        if v in (None, ""):
            # Si prefieres forzar 0 cuando venga vacío, cámbialo a: data["carros"] = 0
            data["carros"] = 0
        else:
            n = _to_int_strict(v)
            if n is None:
                raise ApiError("'carros' debe ser entero (sin decimales).", status_code=400)
            if n < 0:
                raise ApiError("'carros' debe ser >= 0.", status_code=400)
            data["carros"] = n

    # numéricos
    for k in (
        "kms",
        "tarifa",
        "subtotal",
        "iva_pct",
        "iva_monto",
        "retencion_pct",
        "retencion_monto",
        "total",
    ):
        if k in json_data:
            n = _to_num(json_data.get(k))
            if n is None:
                raise ApiError(f"'{k}' debe ser numérico.", status_code=400)
            data[k] = n

    # flags
    for k in ("aplica_iva", "aplica_retencion", "activo"):
        if k in json_data:
            b = _to_bool(json_data.get(k))
            if b is None:
                raise ApiError(f"'{k}' debe ser booleano.", status_code=400)
            data[k] = b

    # status
    if "status" in json_data:
        st = str(json_data.get("status") or "").strip().lower()
        if st not in ALLOWED_STATUS:
            raise ApiError(
                "Status inválido. Usa: draft | posted | liquidated | cancelled.",
                status_code=400,
            )
        data["status"] = st

    # texto
    if "observaciones" in json_data:
        data["observaciones"] = (json_data.get("observaciones") or "").strip() or None

    return data


def serialize_guide(g: Guide) -> Dict[str, Any]:
    return {
        "id": g.id,
        "client_id": g.client_id,
        "operator_id": g.operator_id,
        "car_id": g.car_id,
        "destination_id": g.destination_id,
        "folio": g.folio,
        "fecha": g.fecha.isoformat() if g.fecha else None,
        "car_type": g.car_type,
        "carros": int(getattr(g, "carros", 0) or 0),
        "kms": float(g.kms or 0),
        "tarifa": float(g.tarifa or 0),
        "subtotal": float(g.subtotal or 0),
        "aplica_iva": bool(g.aplica_iva),
        "iva_pct": float(g.iva_pct or 0),
        "iva_monto": float(g.iva_monto or 0),
        "aplica_retencion": bool(g.aplica_retencion),
        "retencion_pct": float(g.retencion_pct or 0),
        "retencion_monto": float(g.retencion_monto or 0),
        "total": float(g.total or 0),
        "status": g.status,
        "observaciones": g.observaciones,
        "activo": bool(g.activo),
    }