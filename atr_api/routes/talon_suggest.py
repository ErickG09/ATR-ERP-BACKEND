# atr_api/routes/talon_suggest.py

from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request

from atr_api.errors import ApiError
from atr_api.extensions import db
from atr_api.models.client import Client

from atr_api.services.talon_service import normalize_folio, suggest_talon_payload


bp = Blueprint(
    "talon_suggest",
    __name__,
    url_prefix="/api/clients/<int:client_id>/talon",
)


def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


def _parse_bool(v) -> bool | None:
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


def _validate_client(client_id: int):
    c = db.session.get(Client, client_id)
    if not c:
        return None, _err("Cliente no válido.", 400)
    return c, None


@bp.get("/suggest")
def suggest_next_talon(client_id: int):
    """
    Sugiere last/next talón para una serie (NO reserva consecutivo).

    Query params:
      - folio: prefijo/serie (ej. ESP, NIC, VWP) [requerido]
      - include_prefill: 1/0 (opcional, default 1) -> incluye prefill_liquidacion_id

    Response:
      {
        client_id, folio, padding,
        last_seq, last_talon,
        next_seq, next_talon,
        prefill_liquidacion_id
      }

    Notas:
      - El padding lo dicta TalonSeries (catálogo). Ya soporta hasta 12.
      - Este endpoint NO impone formato ni “corrige” talones manuales; solo sugiere.
      - NO avanza contador; es solo lectura.
    """
    _, err = _validate_client(client_id)
    if err:
        return err

    folio_raw = request.args.get("folio")
    if not folio_raw:
        return _err("folio es obligatorio.", 400)

    try:
        folio = normalize_folio(folio_raw)
    except ApiError as e:
        return _err(str(e), e.status_code or 400)

    include_prefill_raw = request.args.get("include_prefill")
    include_prefill = _parse_bool(include_prefill_raw)
    include_prefill = True if include_prefill is None else bool(include_prefill)

    try:
        payload: Dict[str, Any] = suggest_talon_payload(
            client_id=int(client_id),
            folio=folio,
            include_prefill=include_prefill,
        )
        return jsonify(payload), 200

    except ApiError as e:
        return _err(str(e), e.status_code or 400)

    except Exception as e:
        return _err(f"Error inesperado sugiriendo talón: {e}", 500)