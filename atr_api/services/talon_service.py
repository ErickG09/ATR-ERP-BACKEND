# atr_api/services/talon_service.py

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import desc

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models.talon_series import TalonSeries
from atr_api.models.talon_series_counter import TalonSeriesCounter


_FOLIO_RE = re.compile(r"^[A-Z0-9]{2,8}$")
_TALON_RE = re.compile(r"^([A-Z0-9]{2,8})(\d{1,10})$")


def normalize_folio(folio: Any) -> str:
    s = (str(folio or "").strip().upper())
    if not s:
        raise ApiError("folio es obligatorio.", status_code=400)
    if not _FOLIO_RE.match(s):
        raise ApiError("folio inválido. Usa 2-8 caracteres A-Z/0-9.", status_code=400)
    return s


def format_talon(folio: str, seq: int, padding: int = 5) -> str:
    folio_n = normalize_folio(folio)
    try:
        seq_i = int(seq)
    except Exception:
        raise ApiError("Consecutivo inválido.", status_code=400)
    if seq_i <= 0:
        raise ApiError("Consecutivo debe ser >= 1.", status_code=400)

    pad = int(padding or 5)
    if pad < 1 or pad > 10:
        pad = 5

    return f"{folio_n}{seq_i:0{pad}d}"


def parse_talon(talon: Any) -> Tuple[str, int]:
    s = (str(talon or "").strip().upper())
    if not s:
        raise ApiError("talon_interno es obligatorio.", status_code=400)

    m = _TALON_RE.match(s)
    if not m:
        raise ApiError(
            "talon_interno inválido. Formato esperado: PREFIJO + NÚMERO (ej. ESP00036).",
            status_code=400,
        )
    folio = m.group(1)
    seq_str = m.group(2)

    if not _FOLIO_RE.match(folio):
        raise ApiError("Prefijo del talón inválido.", status_code=400)

    try:
        seq = int(seq_str)
    except Exception:
        raise ApiError("Consecutivo del talón inválido.", status_code=400)

    if seq <= 0:
        raise ApiError("Consecutivo del talón debe ser >= 1.", status_code=400)

    return folio, seq


def get_series(client_id: int, folio: str) -> Optional[TalonSeries]:
    folio_n = normalize_folio(folio)
    return (
        db.session.query(TalonSeries)
        .filter(
            TalonSeries.client_id == int(client_id),
            TalonSeries.folio == folio_n,
            TalonSeries.activo.is_(True),
        )
        .one_or_none()
    )


def require_series(client_id: int, folio: str) -> TalonSeries:
    s = get_series(client_id, folio)
    if not s:
        raise ApiError("Serie de talón no registrada para este cliente.", status_code=404)
    return s


def _get_or_init_counter_locked(client_id: int, folio: str) -> TalonSeriesCounter:
    """
    Obtiene el contador con lock (FOR UPDATE). Si no existe, lo crea.
    """
    folio_n = normalize_folio(folio)

    row = (
        db.session.query(TalonSeriesCounter)
        .filter(
            TalonSeriesCounter.client_id == int(client_id),
            TalonSeriesCounter.folio == folio_n,
        )
        .with_for_update()
        .one_or_none()
    )
    if row:
        return row

    # Crear inicial
    row = TalonSeriesCounter(client_id=int(client_id), folio=folio_n, seq=0)
    db.session.add(row)
    db.session.flush()

    # Releer con lock
    row2 = (
        db.session.query(TalonSeriesCounter)
        .filter(
            TalonSeriesCounter.client_id == int(client_id),
            TalonSeriesCounter.folio == folio_n,
        )
        .with_for_update()
        .one()
    )
    return row2


def _get_current_counter_value(client_id: int, folio: str) -> int:
    """
    Lee seq sin lock (para sugerencias). Si no existe, regresa 0.
    """
    folio_n = normalize_folio(folio)
    row = (
        db.session.query(TalonSeriesCounter)
        .filter(
            TalonSeriesCounter.client_id == int(client_id),
            TalonSeriesCounter.folio == folio_n,
        )
        .one_or_none()
    )
    return int(row.seq) if row else 0


def _get_last_liquidacion_for_folio(client_id: int, folio: str):
    """
    Encuentra la última liquidación asociada a un folio/prefijo.
    Soporta 2 escenarios:
      A) Si Liquidacion tiene columnas talon_folio/talon_seq (recomendado)
      B) Si NO existen, hace fallback por talon_interno LIKE 'FOLIO%' (menos robusto)
    """
    from atr_api.models.liquidacion import Liquidacion  # import local para evitar ciclos

    folio_n = normalize_folio(folio)

    # Escenario A: columnas nuevas
    if hasattr(Liquidacion, "talon_folio") and hasattr(Liquidacion, "talon_seq"):
        return (
            db.session.query(Liquidacion)
            .filter(
                Liquidacion.client_id == int(client_id),
                Liquidacion.talon_folio == folio_n,
                Liquidacion.talon_seq.isnot(None),
            )
            .order_by(desc(Liquidacion.talon_seq), desc(Liquidacion.id))
            .first()
        )

    # Escenario B: string like + orden por id desc
    like = f"{folio_n}%"
    return (
        db.session.query(Liquidacion)
        .filter(
            Liquidacion.client_id == int(client_id),
            Liquidacion.talon_interno.isnot(None),
            Liquidacion.talon_interno.ilike(like),
        )
        .order_by(desc(Liquidacion.id))
        .first()
    )


def _extract_seq_from_liq(liq, folio: str) -> int:
    """
    Dado una liquidación, intenta extraer el seq.
    """
    from atr_api.models.liquidacion import Liquidacion  # local

    folio_n = normalize_folio(folio)

    if liq is None:
        return 0

    # Si hay columnas nuevas
    if hasattr(Liquidacion, "talon_folio") and hasattr(Liquidacion, "talon_seq"):
        try:
            if (liq.talon_folio or "").strip().upper() == folio_n and liq.talon_seq is not None:
                return int(liq.talon_seq)
        except Exception:
            pass

    # Fallback: parse string
    try:
        ti = getattr(liq, "talon_interno", None)
        if not ti:
            return 0
        f2, seq2 = parse_talon(ti)
        if f2 == folio_n:
            return int(seq2)
        return 0
    except Exception:
        return 0


def suggest_talon_payload(
    client_id: int,
    folio: str,
    include_prefill: bool = True,
) -> Dict[str, Any]:
    """
    NO reserva consecutivo. Solo sugiere:
      - last_talon
      - next_talon
      - prefill_liquidacion_id (y opcionalmente el objeto completo lo serializa el route)
    """
    series = require_series(client_id, folio)
    padding = int(series.padding or 5)

    last_liq = _get_last_liquidacion_for_folio(client_id, series.folio)
    last_seq_from_liq = _extract_seq_from_liq(last_liq, series.folio)

    # counter actual (por si por alguna razón el contador va más adelante)
    counter_seq = _get_current_counter_value(client_id, series.folio)

    last_seq = max(int(last_seq_from_liq or 0), int(counter_seq or 0))

    last_talon = format_talon(series.folio, last_seq, padding) if last_seq > 0 else None
    next_talon = format_talon(series.folio, last_seq + 1, padding)

    payload: Dict[str, Any] = {
        "client_id": int(client_id),
        "folio": series.folio,
        "padding": padding,
        "last_seq": int(last_seq),
        "last_talon": last_talon,
        "next_seq": int(last_seq + 1),
        "next_talon": next_talon,
        "prefill_liquidacion_id": int(getattr(last_liq, "id", 0) or 0) if (include_prefill and last_liq) else None,
    }
    return payload


def ensure_counter_at_least(client_id: int, folio: str, seq_used: int) -> None:
    """
    Asegura que el contador quede en >= seq_used (con lock).
    Útil cuando el usuario manda talones manuales y quieres que el sistema “alcance” el mayor.
    """
    folio_n = normalize_folio(folio)
    try:
        seq_i = int(seq_used)
    except Exception:
        raise ApiError("seq_used inválido.", status_code=400)
    if seq_i < 0:
        seq_i = 0

    ctr = _get_or_init_counter_locked(client_id, folio_n)
    cur = int(ctr.seq or 0)
    if seq_i > cur:
        ctr.seq = int(seq_i)
        db.session.flush()


def lookup_liquidacion_by_talon(client_id: int, talon: str):
    """
    Busca una liquidación por talon_interno exacto (normalizado).
    """
    from atr_api.models.liquidacion import Liquidacion  # local import

    ti = (str(talon or "").strip().upper())
    if not ti:
        raise ApiError("talon es obligatorio.", status_code=400)

    return (
        db.session.query(Liquidacion)
        .filter(
            Liquidacion.client_id == int(client_id),
            Liquidacion.talon_interno == ti,
        )
        .first()
    )
