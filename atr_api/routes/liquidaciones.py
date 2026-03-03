# atr_api/routes/liquidaciones.py

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Tuple

from flask import Blueprint, jsonify, request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from atr_api.errors import ApiError
from atr_api.extensions import db

from atr_api.models.car import Car
from atr_api.models.client import Client
from atr_api.models.client_counter import ClientCounter
from atr_api.models.destination import Destination
from atr_api.models.deducciones_config import ClientDeduccionesConfig
from atr_api.models.liquidacion import LIQ_STATUS_CHOICES, Liquidacion
from atr_api.models.liquidacion_anticipo import LiquidacionAnticipo
from atr_api.models.liquidacion_deduccion import LiquidacionDeduccion
from atr_api.models.operator import Operator
from atr_api.models.operator_deduccion_extra import OperatorDeduccionExtra
from atr_api.models.operator_imss import OperatorIMSS  # IMSS mensual
from atr_api.models.talon_series import TalonSeries
from atr_api.models.talon_series_counter import TalonSeriesCounter

from atr_api.services.liquidaciones_excel_import_service import import_liquidaciones_from_excel
from atr_api.services.talon_service import (
    format_talon,
    normalize_folio,
    normalize_manual_talon_with_catalog,  # NO fuerza padding (talón manual)
)

liquidaciones_bp = Blueprint(
    "liquidaciones",
    __name__,
    url_prefix="/api/clients/<int:client_id>/liquidaciones",
)

# ---------------- helpers ----------------

# keys predefinidas (las “fijas” que tendrás en UI)
# NOTA: "impuestos" se calcula automáticamente (6%) y el backend lo "upsertea".
# NOTA 2: IMSS NO es PRESET. IMSS se inserta automáticamente desde OperatorIMSS (mensual).
PRESET_DED_KEYS = {
    "ayuda_escolar": "Ayuda escolar",
    "impuestos": "Impuestos",
    "infonavit": "Infonavit",
    "sindicato": "Sindicato",
    "fonacot": "FONACOT",
    "pension_alimenticia": "Pensión alimenticia",
}

# keys “fijas” que sí guardamos como renglón (impuestos NO: se recalcula en recalc_totals)
PRESET_KEYS_NO_TAX = [k for k in PRESET_DED_KEYS.keys() if k != "impuestos"]

# prefijos de keys para identificar deducciones generadas por config
CFG_EXTRA_KEY_PREFIX = "cfg_extra:"  # extras globales/override guardados en config
OP_EXTRA_KEY_PREFIX = "op_extra:"  # pagos aplicados a “deudas” del operador (tabla OperatorDeduccionExtra)

# -------------------------
# Campos de gastos (opcionales) para guardar lo capturado en el frontend.
# Deben existir como columnas en atr_api/models/liquidacion.py
# -------------------------
EXPENSE_FIELDS = [
    "gasto_autopistas",
    "gasto_rep_menores",
    "gasto_otros_c_comp",
    "gasto_ayudas",
    "gasto_dias_taller",
    "gasto_estancias",
    "gasto_gasolina",
    "gasto_infracciones",
    "gasto_pension",
    "gasto_permisos",
    "gasto_sanitizacion",
    "gasto_talachas",
    "gasto_taxis",
    "gasto_transitos",
    "gasto_aceites",
    "gasto_diesel",
    "gasto_estacionamiento",
    "gasto_hotel",
    "gasto_refacciones",
    "gasto_urea",
]

# IVA % por gasto que aplica IVA
EXPENSE_IVA_PCT_FIELDS = [
    "gasto_aceites_iva_pct",
    "gasto_diesel_iva_pct",
    "gasto_estacionamiento_iva_pct",
    "gasto_hotel_iva_pct",
    "gasto_refacciones_iva_pct",
    "gasto_urea_iva_pct",
]


def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


def _normalize_ct(v: str | None) -> str:
    return (v or "").strip().upper()


def _parse_bool(v):
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


def _parse_date_yyyy_mm_dd(v: str):
    if not v:
        return None
    try:
        return datetime.strptime(v.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _num(v, default=0.0):
    if v is None:
        return default
    try:
        s = str(v).strip().replace(",", ".")
        return float(s)
    except Exception:
        return default


def _validate_client(client_id: int):
    c = db.session.get(Client, client_id)
    if not c:
        return None, _err("Cliente no válido.", 400)
    return c, None


def _get_operator_global(operator_id: int) -> Operator:
    op = db.session.get(Operator, operator_id)
    if not op:
        raise ApiError("Operador inválido.", status_code=400)
    return op


def _get_car_global(car_id: int) -> Car:
    car = db.session.get(Car, car_id)
    if not car:
        raise ApiError("Carro inválido.", status_code=400)
    return car


def _get_destination_by_client(client_id: int, destination_id: int) -> Destination:
    dest = db.session.get(Destination, destination_id)
    if not dest or int(dest.client_id) != int(client_id):
        raise ApiError("Destino inválido para este cliente.", status_code=400)
    return dest


def _enforce_operator_car_type_match(op: Operator, car: Car) -> str:
    """
    Regla CLAVE: El tipo del operador (tipo_carro) debe coincidir con el tipo del carro (tipo).
    Si falta alguno, fallamos para no guardar inconsistencias.
    """
    op_ct = _normalize_ct(getattr(op, "tipo_carro", ""))
    car_ct = _normalize_ct(getattr(car, "tipo", ""))

    if not op_ct:
        raise ApiError("Operador sin tipo de carro asignado.", status_code=400)
    if not car_ct:
        raise ApiError("Carro sin tipo asignado.", status_code=400)
    if op_ct != car_ct:
        raise ApiError(
            f"Tipo de carro no coincide: Operador={op_ct} vs Carro={car_ct}.",
            status_code=400,
        )
    return car_ct


def _derive_car_type(op: Operator, car: Car | None) -> str:
    """
    Define el car_type final:
    - Si hay carro: viene del carro (pero validado contra operador)
    - Si no hay carro: viene del operador
    """
    if car is not None:
        return _enforce_operator_car_type_match(op, car)

    op_ct = _normalize_ct(getattr(op, "tipo_carro", ""))
    if not op_ct:
        raise ApiError("Operador sin tipo de carro asignado.", status_code=400)
    return op_ct


def _validate_fk_belongs(client_id: int, operator_id: int, car_id, destination_id):
    """
    Operador y Carro: globales (solo existen).
    Destino: pertenece al cliente.
    Además calcula car_type_final de forma consistente.
    """
    try:
        op = _get_operator_global(operator_id)

        car = None
        if car_id is not None:
            car = _get_car_global(car_id)

        dest = None
        if destination_id is not None:
            dest = _get_destination_by_client(client_id, destination_id)

        car_type_final = _derive_car_type(op, car)
        return op, car, dest, car_type_final, None

    except ApiError as e:
        return None, None, None, None, _err(str(e), e.status_code or 400)


def _norm_key(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    if not s:
        return None
    s = "_".join(s.split())
    return s


def _validate_operator_slot(v) -> int:
    try:
        slot = int(v)
    except Exception:
        raise ApiError("operator_slot inválido.", status_code=400)
    if slot not in (1, 2):
        raise ApiError("operator_slot debe ser 1 o 2.", status_code=400)
    return slot


def _validate_deduccion_payload(item: dict, allow_id: bool = False):
    """
    Retorna (ded_id, slot, key, label, monto) con validaciones estrictas.
    """
    if not isinstance(item, dict):
        raise ApiError("Deducción inválida (debe ser objeto).", status_code=400)

    ded_id = None
    if allow_id and "id" in item:
        try:
            ded_id = int(item.get("id"))
        except Exception:
            raise ApiError("Deducción id inválido.", status_code=400)

    slot = _validate_operator_slot(item.get("operator_slot", 1))

    key = _norm_key(item.get("key"))
    label = (item.get("label") or "").strip()

    if (not label) and key and key in PRESET_DED_KEYS:
        label = PRESET_DED_KEYS[key]

    if not label:
        raise ApiError("Deducción requiere 'label'.", status_code=400)

    if len(label) > 120:
        raise ApiError("Deducción 'label' demasiado largo (máx 120).", status_code=400)

    monto = _num(item.get("monto"), None)
    if monto is None or not isinstance(monto, (int, float)):
        raise ApiError("Deducción 'monto' inválido.", status_code=400)

    if monto < 0:
        raise ApiError("Deducción 'monto' no puede ser negativa.", status_code=400)

    return ded_id, slot, key, label, round(float(monto), 2)


def _validate_anticipo_payload(item: dict):
    """
    Retorna (slot, importe, recibo) con validaciones estrictas.
    """
    if not isinstance(item, dict):
        raise ApiError("Anticipo inválido (debe ser objeto).", status_code=400)

    slot = _validate_operator_slot(item.get("operator_slot", 1))

    importe = _num(item.get("importe"), None)
    if importe is None or not isinstance(importe, (int, float)):
        raise ApiError("Anticipo 'importe' inválido.", status_code=400)
    if float(importe) < 0:
        raise ApiError("Anticipo 'importe' no puede ser negativo.", status_code=400)

    recibo = (item.get("recibo") or "").strip() or None
    if recibo and len(recibo) > 64:
        raise ApiError("Anticipo 'recibo' demasiado largo (máx 64).", status_code=400)

    return slot, round(float(importe), 2), recibo


# -------------------------
# TALÓN INTERNO (SERIE + CONTADOR)
# -------------------------

def _require_series(client_id: int, folio: str) -> TalonSeries:
    """
    Exige que la serie exista y esté activa para ese cliente.
    """
    folio_n = normalize_folio(folio)
    row = (
        db.session.query(TalonSeries)
        .filter(
            TalonSeries.client_id == int(client_id),
            TalonSeries.folio == folio_n,
            TalonSeries.activo.is_(True),
        )
        .one_or_none()
    )
    if not row:
        raise ApiError("Serie de talón no registrada o inactiva para este cliente.", status_code=404)
    return row


def _get_or_init_series_counter_locked(client_id: int, folio: str) -> TalonSeriesCounter:
    """
    Obtiene el contador con lock (FOR UPDATE). Si no existe, lo crea.
    seq guarda el último consecutivo utilizado.

    Maneja concurrencia:
    - intenta crear con SAVEPOINT; si choca, relee con lock.
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

    try:
        with db.session.begin_nested():
            db.session.add(TalonSeriesCounter(client_id=int(client_id), folio=folio_n, seq=0))
            db.session.flush()
    except IntegrityError:
        pass

    row2 = (
        db.session.query(TalonSeriesCounter)
        .filter(
            TalonSeriesCounter.client_id == int(client_id),
            TalonSeriesCounter.folio == folio_n,
        )
        .with_for_update()
        .one_or_none()
    )
    if not row2:
        raise ApiError("No se pudo inicializar el contador de la serie.", status_code=500)
    return row2


def _allocate_next_talon_locked(client_id: int, folio: str) -> tuple[str, str, int]:
    """
    Reserva el siguiente consecutivo de manera segura (lock) y regresa:
      (talon_interno, talon_folio, talon_seq)
    """
    series = _require_series(client_id, folio)
    ctr = _get_or_init_series_counter_locked(client_id, series.folio)

    last_used = int(ctr.seq or 0)
    next_seq = last_used + 1

    ctr.seq = int(next_seq)
    db.session.flush()

    # Para auto-sugerencia/asignación, sí respeta padding del catálogo
    talon = format_talon(series.folio, next_seq, int(series.padding or 5))
    return talon, series.folio, int(next_seq)


def _ensure_counter_at_least_locked(client_id: int, folio: str, seq_used: int) -> None:
    """
    Si el usuario mandó un talón manual (ej. NIC36), garantizamos que el contador
    quede >= seq_used para que el siguiente auto sea el siguiente consecutivo.
    """
    series = _require_series(client_id, folio)
    ctr = _get_or_init_series_counter_locked(client_id, series.folio)

    cur = int(ctr.seq or 0)
    if int(seq_used) > cur:
        ctr.seq = int(seq_used)
        db.session.flush()


# ------------------  IMSS MENSUAL (OperatorIMSS) ------------------

def _find_operator_imss_for_month(client_id: int, operator_id: int, fecha: date | None) -> OperatorIMSS | None:
    """
    Busca la cuota IMSS del operador para el mes/año de la fecha de la liquidación.
    Soporta columna 'activo' si existe en el modelo.
    """
    if not fecha:
        return None

    q = (
        db.session.query(OperatorIMSS)
        .filter(
            OperatorIMSS.client_id == int(client_id),
            OperatorIMSS.operator_id == int(operator_id),
            OperatorIMSS.year == int(fecha.year),
            OperatorIMSS.month == int(fecha.month),
        )
    )
    if hasattr(OperatorIMSS, "activo"):
        q = q.filter(OperatorIMSS.activo.is_(True))

    return q.one_or_none()


def _upsert_imss_deduccion_for_slot(liq: Liquidacion, client_id: int, slot: int, operator_id: int) -> None:
    """
    Inserta la deducción IMSS como renglón automático (key='imss') leyendo OperatorIMSS (mensual).
    Regla:
      - Si no hay registro mensual, no agrega nada.
      - Si la cuota <= 0, no agrega nada.
    """
    row = _find_operator_imss_for_month(client_id, operator_id, getattr(liq, "fecha", None))
    if not row:
        return

    cuota = None
    if hasattr(row, "cuota_imss"):
        cuota = getattr(row, "cuota_imss", None)
    elif hasattr(row, "cuota"):
        cuota = getattr(row, "cuota", None)

    monto = round(float(_num(cuota, 0.0)), 2)
    if monto <= 0:
        return

    liq.deducciones.append(
        LiquidacionDeduccion(
            operator_slot=slot,
            key="imss",
            label="IMSS",
            monto=monto,
        )
    )


def _strip_generated_imss_deducciones(liq: Liquidacion) -> None:
    """
    Quita renglones automáticos de IMSS (key='imss') para poder regenerarlos limpios.
    """
    kept: List[LiquidacionDeduccion] = []
    for d in (liq.deducciones or []):
        key = (d.key or "").strip()
        if key == "imss":
            continue
        kept.append(d)
    liq.deducciones = kept


# ------------------  DEDUCCIONES CONFIG (DB) ------------------

def _cfg_default() -> Dict[str, Any]:
    return {
        "global": {
            "ayuda_escolar": "0",
            "impuestos": "0",  # en liquidación se calcula, pero lo dejamos por compatibilidad
            "infonavit": "0",
            "sindicato": "0",
            "fonacot": "0",
            "pension_alimenticia": "0",
        },
        "global_extras": [],
        "per_operator": {},
    }


def _load_cfg(client_id: int) -> Dict[str, Any]:
    """
    El modelo real usa columnas:
      - global_json
      - per_operator_json
      - global_extras_json
    """
    row = (
        db.session.query(ClientDeduccionesConfig)
        .filter(ClientDeduccionesConfig.client_id == client_id)
        .one_or_none()
    )
    if not row:
        return _cfg_default()

    g = getattr(row, "global_json", None) or {}
    ge = getattr(row, "global_extras_json", None) or []
    po = getattr(row, "per_operator_json", None) or {}

    base = _cfg_default()
    if isinstance(g, dict):
        g2 = dict(g)
        g2.pop("imss", None)
        base["global"].update(g2)
    if isinstance(ge, list):
        base["global_extras"] = ge
    if isinstance(po, dict):
        po2 = {}
        for k, v in po.items():
            if not isinstance(v, dict):
                po2[k] = v
                continue
            vv = dict(v)
            if isinstance(vv.get("values"), dict) and "imss" in vv["values"]:
                vv_values = dict(vv["values"])
                vv_values.pop("imss", None)
                vv["values"] = vv_values
            po2[k] = vv
        base["per_operator"] = po2

    return base


def _to_float_money(v: Any) -> float:
    return round(_num(v, 0.0), 2)


def _resolve_effective_for_operator(
    cfg: Dict[str, Any], operator_id: int
) -> Tuple[Dict[str, float], List[Dict[str, Any]]]:
    """
    Retorna:
      - fields dict key->float (solo fijas)
      - extras list [{id,label,monto,enabled}]
    """
    global_fields = cfg.get("global") or {}
    global_extras = cfg.get("global_extras") or []
    per_operator = cfg.get("per_operator") or {}

    entry = per_operator.get(str(operator_id)) or {}
    enabled = bool(entry.get("enabled") is True)

    fields: Dict[str, float] = {}
    for k in PRESET_DED_KEYS.keys():
        fields[k] = _to_float_money(global_fields.get(k, 0))

    if enabled:
        values = entry.get("values") or {}
        if isinstance(values, dict):
            for k in PRESET_DED_KEYS.keys():
                if k in values and values.get(k) is not None:
                    fields[k] = _to_float_money(values.get(k))

    base_map: Dict[str, Dict[str, Any]] = {}
    if isinstance(global_extras, list):
        for g in global_extras:
            if not isinstance(g, dict):
                continue
            gid = str(g.get("id") or "").strip()
            if not gid:
                continue
            base_map[gid] = {
                "id": gid,
                "label": str(g.get("label") or "").strip(),
                "monto": _to_float_money(g.get("monto")),
                "enabled": (g.get("enabled") is not False),
            }

    if enabled:
        op_extras = entry.get("extras") or []
        if isinstance(op_extras, list):
            for o in op_extras:
                if not isinstance(o, dict):
                    continue
                oid = str(o.get("id") or "").strip()
                if not oid:
                    continue
                prev = base_map.get(oid, {"id": oid, "label": "", "monto": 0.0, "enabled": True})
                base_map[oid] = {
                    "id": oid,
                    "label": str(o.get("label") or prev.get("label") or "").strip(),
                    "monto": _to_float_money(
                        o.get("monto") if o.get("monto") is not None else prev.get("monto")
                    ),
                    "enabled": (
                        o.get("enabled") if o.get("enabled") is not None else prev.get("enabled", True)
                    ),
                }

    ordered: List[Dict[str, Any]] = []
    global_ids: List[str] = []
    if isinstance(global_extras, list):
        for g in global_extras:
            if isinstance(g, dict) and g.get("id"):
                global_ids.append(str(g.get("id")))

    seen = set()
    for gid in global_ids:
        if gid in base_map:
            ordered.append(base_map[gid])
            seen.add(gid)
    for k, v in base_map.items():
        if k not in seen:
            ordered.append(v)

    extras_final: List[Dict[str, Any]] = []
    for ex in ordered:
        if not ex.get("enabled", True):
            continue
        if float(ex.get("monto") or 0) <= 0:
            continue
        if not ex.get("label"):
            continue
        extras_final.append(ex)

    return fields, extras_final


def _strip_generated_cfg_deducciones(liq: Liquidacion):
    """
    Quita renglones “generados por config” para poder reinsertarlos limpios:
      - preset keys (except impuestos)
      - cfg_extra:*
    NO quita:
      - impuestos (lo maneja recalc_totals)
      - op_extra:* (pagos aplicados a saldos)
      - deducciones manuales (key=None o keys custom)
    """
    kept: List[LiquidacionDeduccion] = []
    for d in (liq.deducciones or []):
        key = (d.key or "").strip()
        if key in PRESET_KEYS_NO_TAX:
            continue
        if key.startswith(CFG_EXTRA_KEY_PREFIX):
            continue
        kept.append(d)
    liq.deducciones = kept


def _upsert_cfg_deducciones_for_slot(liq: Liquidacion, client_id: int, slot: int, operator_id: int):
    """
    Inserta deducciones “fijas” (ayuda_escolar, infonavit, etc) + extras globales/override,
    como renglones en LiquidacionDeduccion.
    """
    cfg = _load_cfg(client_id)
    fields, extras = _resolve_effective_for_operator(cfg, operator_id)

    try:
        op = db.session.get(Operator, operator_id)
        if op is not None:
            new_ae = round(float(fields.get("ayuda_escolar", 0.0) or 0.0), 2)
            cur_ae = round(float(getattr(op, "ayuda_escolar", 0) or 0.0), 2)
            if new_ae != cur_ae:
                op.ayuda_escolar = new_ae
    except Exception:
        pass

    for k in PRESET_KEYS_NO_TAX:
        monto = round(float(fields.get(k, 0.0) or 0.0), 2)
        if monto <= 0:
            continue
        liq.deducciones.append(
            LiquidacionDeduccion(
                operator_slot=slot,
                key=k,
                label=PRESET_DED_KEYS.get(k, k),
                monto=monto,
            )
        )

    for ex in extras:
        ex_id = str(ex.get("id") or "").strip()
        label = str(ex.get("label") or "").strip()
        monto = round(float(ex.get("monto") or 0.0), 2)
        if not ex_id or not label or monto <= 0:
            continue
        liq.deducciones.append(
            LiquidacionDeduccion(
                operator_slot=slot,
                key=f"{CFG_EXTRA_KEY_PREFIX}{ex_id}",
                label=label,
                monto=monto,
            )
        )


def _apply_operator_extra_payments(liq: Liquidacion, client_id: int, payments: List[Dict[str, Any]]):
    """
    OperatorDeduccionExtra usa:
      - activo
      - saldo_restante
    """
    if not payments:
        return

    if not isinstance(payments, list):
        raise ApiError("operator_extra_payments debe ser una lista.", status_code=400)

    for item in payments:
        if not isinstance(item, dict):
            raise ApiError("Pago de extra inválido (debe ser objeto).", status_code=400)

        slot = _validate_operator_slot(item.get("operator_slot", 1))

        extra_id_raw = item.get("extra_id")
        if extra_id_raw is None:
            raise ApiError("Pago de extra requiere extra_id.", status_code=400)
        try:
            extra_id = int(extra_id_raw)
        except Exception:
            raise ApiError("extra_id inválido.", status_code=400)

        monto_req = _num(item.get("monto"), None)
        if monto_req is None:
            raise ApiError("Pago de extra requiere monto.", status_code=400)
        monto_req = round(float(monto_req), 2)
        if monto_req <= 0:
            continue

        op_id = liq.operator_id if slot == 1 else getattr(liq, "operator2_id", None)
        if slot == 2 and not op_id:
            raise ApiError("No puedes aplicar pagos slot=2 sin operator2_id.", status_code=400)

        extra = (
            db.session.query(OperatorDeduccionExtra)
            .filter(
                OperatorDeduccionExtra.id == extra_id,
                OperatorDeduccionExtra.client_id == client_id,
                OperatorDeduccionExtra.operator_id == int(op_id),
                OperatorDeduccionExtra.activo.is_(True),
            )
            .one_or_none()
        )
        if not extra:
            raise ApiError("Deducción extra (deuda) no encontrada o no activa.", status_code=404)

        saldo = round(float(getattr(extra, "saldo_restante", 0) or 0.0), 2)
        if saldo <= 0:
            extra.saldo_restante = 0
            extra.activo = False
            continue

        aplicado = min(monto_req, saldo)
        aplicado = round(float(aplicado), 2)
        if aplicado <= 0:
            continue

        extra.saldo_restante = round(saldo - aplicado, 2)
        if float(extra.saldo_restante or 0) <= 0:
            extra.saldo_restante = 0
            extra.activo = False

        label = str(getattr(extra, "label", "") or "").strip() or "Deducción extra"
        liq.deducciones.append(
            LiquidacionDeduccion(
                operator_slot=slot,
                key=f"{OP_EXTRA_KEY_PREFIX}{extra_id}",
                label=label,
                monto=aplicado,
            )
        )


def _serialize_deduccion(d: LiquidacionDeduccion):
    return {
        "id": d.id,
        "operator_slot": int(getattr(d, "operator_slot", 1) or 1),
        "key": d.key,
        "label": d.label,
        "monto": float(d.monto or 0),
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _serialize_anticipo(a: LiquidacionAnticipo):
    return {
        "id": a.id,
        "operator_slot": int(getattr(a, "operator_slot", 1) or 1),
        "operator_id": int(a.operator_id) if a.operator_id else None,
        "importe": float(a.importe or 0),
        "recibo": a.recibo,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _serialize_detalle(det: Any) -> Dict[str, Any]:
    """
    Serializa LiquidacionDetalle si existe en tu modelo/relación.
    Esto es opcional y no rompe si el modelo no está presente en runtime.
    """
    return {
        "id": getattr(det, "id", None),
        "row_number": getattr(det, "row_number", None),
        "fecha": det.fecha.isoformat() if getattr(det, "fecha", None) else None,
        "factura_cp": getattr(det, "factura_cp", None),
        "carro": getattr(det, "carro", None),
        "dealer": getattr(det, "dealer", None),
        "unidades": getattr(det, "unidades", None),
        "kms": float(getattr(det, "kms", 0) or 0),
        "operador_1": getattr(det, "operador_1", None),
        "operador_2": getattr(det, "operador_2", None),
        "flete": float(getattr(det, "flete", 0) or 0),
        "iva": float(getattr(det, "iva", 0) or 0),
        "retencion": float(getattr(det, "retencion", 0) or 0),
        "total": float(getattr(det, "total", 0) or 0),
        "anticipo_1": float(getattr(det, "anticipo_1", 0) or 0),
        "recibo_1": getattr(det, "recibo_1", None),
        "anticipo_2": float(getattr(det, "anticipo_2", 0) or 0),
        "recibo_2": getattr(det, "recibo_2", None),
        "created_at": det.created_at.isoformat() if getattr(det, "created_at", None) else None,
        "updated_at": det.updated_at.isoformat() if getattr(det, "updated_at", None) else None,
    }


def _serialize(liq: Liquidacion):
    try:
        liq.recalc_totals()
    except Exception:
        pass

    data = {
        "id": liq.id,
        "client_id": liq.client_id,
        "folio_num": liq.folio_num,
        "folio": liq.folio,
        "fecha": liq.fecha.isoformat() if liq.fecha else None,
        "talon_interno": getattr(liq, "talon_interno", None),
        "talon_folio": getattr(liq, "talon_folio", None),
        "talon_seq": getattr(liq, "talon_seq", None),
        "operator_id": liq.operator_id,
        "operator2_id": getattr(liq, "operator2_id", None),
        "car_id": liq.car_id,
        "destination_id": liq.destination_id,
        "car_type": liq.car_type,
        "kms": float(liq.kms or 0),
        "tarifa": float(liq.tarifa or 0),
        "subtotal": float(liq.subtotal or 0),
        "aplica_iva": bool(liq.aplica_iva),
        "iva_pct": float(liq.iva_pct or 0),
        "iva_monto": float(liq.iva_monto or 0),
        "aplica_retencion": bool(liq.aplica_retencion),
        "retencion_pct": float(liq.retencion_pct or 0),
        "retencion_monto": float(liq.retencion_monto or 0),
        "total": float(liq.total or 0),
        "sueldo_base_op1": float(getattr(liq, "sueldo_base_op1", 0) or 0),
        "viaticos_base_op1": float(getattr(liq, "viaticos_base_op1", 0) or 0),
        "sueldo_base_op2": float(getattr(liq, "sueldo_base_op2", 0) or 0),
        "viaticos_base_op2": float(getattr(liq, "viaticos_base_op2", 0) or 0),
        "maniobra_op1": float(getattr(liq, "maniobra_op1", 0) or 0),
        "maniobra_op2": float(getattr(liq, "maniobra_op2", 0) or 0),
        "otros_ingresos_op1": float(getattr(liq, "otros_ingresos_op1", 0) or 0),
        "otros_ingresos_op2": float(getattr(liq, "otros_ingresos_op2", 0) or 0),
        "impuestos_op1": float(getattr(liq, "impuestos_op1", 0) or 0),
        "impuestos_op2": float(getattr(liq, "impuestos_op2", 0) or 0),
        "deducciones_total_op1": float(getattr(liq, "deducciones_total_op1", 0) or 0),
        "deducciones_total_op2": float(getattr(liq, "deducciones_total_op2", 0) or 0),
        "anticipos_total_op1": float(getattr(liq, "anticipos_total_op1", 0) or 0),
        "anticipos_total_op2": float(getattr(liq, "anticipos_total_op2", 0) or 0),
        "neto_op1": float(getattr(liq, "neto_op1", 0) or 0),
        "neto_op2": float(getattr(liq, "neto_op2", 0) or 0),
        "pago_final_op1": float(getattr(liq, "pago_final_op1", 0) or 0),
        "pago_final_op2": float(getattr(liq, "pago_final_op2", 0) or 0),
        "pago_final_total": float(getattr(liq, "pago_final_total", 0) or 0),
        "deducciones_total": float(liq.deducciones_total or 0),
        "neto_operador": float(liq.neto_operador or 0),
        "deducciones": [_serialize_deduccion(d) for d in (liq.deducciones or [])],
        "anticipos": [_serialize_anticipo(a) for a in (getattr(liq, "anticipos", None) or [])],
        "status": liq.status,
        "observaciones": liq.observaciones,
        "activo": bool(liq.activo),
        "created_at": liq.created_at.isoformat() if liq.created_at else None,
        "updated_at": liq.updated_at.isoformat() if liq.updated_at else None,
        "pagado": bool(liq.pagado),
        "pagado_at": liq.pagado_at.isoformat() if liq.pagado_at else None,
    }

    for f in EXPENSE_FIELDS:
        data[f] = float(getattr(liq, f, 0) or 0)

    for f in EXPENSE_IVA_PCT_FIELDS:
        data[f] = float(getattr(liq, f, 0) or 0)

    # Detalles (si existe relación Liquidacion.detalles)
    if hasattr(liq, "detalles") and getattr(liq, "detalles") is not None:
        try:
            data["detalles"] = [_serialize_detalle(d) for d in (liq.detalles or [])]
        except Exception:
            data["detalles"] = []

    try:
        giva = liq.calc_gastos_iva()
        data["gastos_iva_items"] = giva["items"]
        data["gastos_iva_total"] = giva["iva_total"]
        data["gastos_con_iva_total"] = giva["total_con_iva"]
    except Exception:
        data["gastos_iva_items"] = {}
        data["gastos_iva_total"] = 0.0
        data["gastos_con_iva_total"] = 0.0

    return data


def _get_or_init_counter_locked(client_id: int) -> ClientCounter:
    ctr = (
        db.session.query(ClientCounter)
        .filter(ClientCounter.client_id == client_id)
        .with_for_update()
        .one_or_none()
    )
    if not ctr:
        # tolerancia a carrera: savepoint
        try:
            with db.session.begin_nested():
                db.session.add(ClientCounter(client_id=client_id, liquidacion_folio_seq=0))
                db.session.flush()
        except IntegrityError:
            pass

        ctr = (
            db.session.query(ClientCounter)
            .filter(ClientCounter.client_id == client_id)
            .with_for_update()
            .one_or_none()
        )

    if not ctr:
        raise ApiError("No se pudo inicializar el contador del cliente.", status_code=500)

    return ctr


def _allocate_next_folio(client_id: int) -> tuple[int, str]:
    ctr = _get_or_init_counter_locked(client_id)
    ctr.liquidacion_folio_seq = int(ctr.liquidacion_folio_seq or 0) + 1
    folio_num = int(ctr.liquidacion_folio_seq)
    folio = Liquidacion.format_folio(folio_num)
    db.session.flush()
    return folio_num, folio


def _load_liq_full(client_id: int, liq_id: int) -> Liquidacion | None:
    """
    Carga liquidación con deducciones y anticipos (+ detalles si existe la relación).
    """
    opts = [
        selectinload(Liquidacion.deducciones),
        selectinload(Liquidacion.anticipos),
    ]
    if hasattr(Liquidacion, "detalles"):
        opts.append(selectinload(getattr(Liquidacion, "detalles")))

    return (
        db.session.query(Liquidacion)
        .options(*opts)
        .filter(Liquidacion.id == liq_id, Liquidacion.client_id == client_id)
        .one_or_none()
    )


# ---------------- endpoints ----------------

@liquidaciones_bp.get("/next-folio")
def next_folio(client_id: int):
    _, err = _validate_client(client_id)
    if err:
        return err

    ctr = db.session.query(ClientCounter).filter(ClientCounter.client_id == client_id).one_or_none()
    nxt = (int(ctr.liquidacion_folio_seq or 0) if ctr else 0) + 1
    return jsonify({"folio_num": int(nxt), "folio": Liquidacion.format_folio(int(nxt))})


@liquidaciones_bp.post("/import-excel")
def import_excel(client_id: int):
    """
    Importa/valida Excel de viajes por talón interno.

    - multipart/form-data con campo: file
    - query param: dry_run=1 para solo validar (no persiste ni actualiza contadores)
    """
    _, err = _validate_client(client_id)
    if err:
        return err

    dry_run = _parse_bool(request.args.get("dry_run"))
    dry_run = bool(dry_run is True)

    f = request.files.get("file")
    if not f:
        return _err("Falta archivo (campo 'file').", 400)

    try:
        result = import_liquidaciones_from_excel(
            client_id=int(client_id),
            file_storage=f,
            dry_run=dry_run,
        )
        return jsonify(result), 200
    except ApiError as e:
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        return _err(f"No se pudo importar el Excel. {str(e)}", 400)


@liquidaciones_bp.route("/", methods=["GET"], strict_slashes=False)
def list_liquidaciones(client_id: int):
    _, err = _validate_client(client_id)
    if err:
        return err

    page = int(request.args.get("page", 1) or 1)
    per_page = int(request.args.get("per_page", 50) or 50)
    per_page = max(1, min(per_page, 500))

    operator_id = request.args.get("operator_id")
    destination_id = request.args.get("destination_id")
    status = request.args.get("status")
    activo = _parse_bool(request.args.get("activo"))
    search = (request.args.get("search") or "").strip()

    # Por performance: listar trae deducciones/anticipos. Detalles solo en GET /<id>
    q = (
        db.session.query(Liquidacion)
        .options(
            selectinload(Liquidacion.deducciones),
            selectinload(Liquidacion.anticipos),
        )
        .filter(Liquidacion.client_id == client_id)
    )

    if operator_id:
        try:
            q = q.filter(Liquidacion.operator_id == int(operator_id))
        except Exception:
            return _err("operator_id inválido.", 400)

    if destination_id:
        try:
            q = q.filter(Liquidacion.destination_id == int(destination_id))
        except Exception:
            return _err("destination_id inválido.", 400)

    if status:
        if status not in LIQ_STATUS_CHOICES:
            return _err("status inválido.", 400)
        q = q.filter(Liquidacion.status == status)

    if activo is not None:
        q = q.filter(Liquidacion.activo == activo)

    if search:
        like = f"%{search.lower()}%"
        filters = [
            Liquidacion.folio.ilike(like),
            Liquidacion.car_type.ilike(like),
        ]
        if hasattr(Liquidacion, "talon_interno"):
            filters.append(Liquidacion.talon_interno.ilike(like))
        if hasattr(Liquidacion, "talon_folio"):
            filters.append(Liquidacion.talon_folio.ilike(like))
        q = q.filter(or_(*filters))

    q = q.order_by(Liquidacion.fecha.desc(), Liquidacion.id.desc())

    total = q.count()
    pages = (total + per_page - 1) // per_page
    items = q.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify(
        {
            "items": [_serialize(x) for x in items],
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": pages,
        }
    )


@liquidaciones_bp.post("")
@liquidaciones_bp.post("/")
def create_liquidacion(client_id: int):
    """
    TALÓN:
    - Si llega talon_interno: se normaliza CONTRA catálogo (serie activa) y se guarda TAL CUAL
      (sin forzar padding). Luego se asegura contador >= seq.
    - Si NO llega talon_interno y llega talon_folio/talon_series_folio: se reserva el siguiente consecutivo con lock,
      y se formatea con padding del catálogo.
    - Si no llega nada: se crea sin talón (legacy).

    IMSS:
    - IMSS se inserta automáticamente leyendo OperatorIMSS del mes/año de la fecha.
    """
    _, err = _validate_client(client_id)
    if err:
        return err

    body = request.get_json(silent=True) or {}

    fecha_in = (body.get("fecha") or "").strip()

    operator_id = body.get("operator_id")
    operator2_id = body.get("operator2_id", None)

    car_id = body.get("car_id", None)
    destination_id = body.get("destination_id", None)

    if operator_id is None:
        return _err("operator_id es obligatorio.", 400)

    try:
        operator_id = int(operator_id)
    except Exception:
        return _err("operator_id inválido.", 400)

    try:
        operator2_id = None if operator2_id in ("", None) else int(operator2_id)
    except Exception:
        return _err("operator2_id inválido.", 400)

    if operator2_id is not None and int(operator2_id) == int(operator_id):
        return _err("operator2_id no puede ser igual a operator_id.", 400)

    try:
        car_id = None if car_id in ("", None) else int(car_id)
    except Exception:
        return _err("car_id inválido.", 400)

    try:
        destination_id = None if destination_id in ("", None) else int(destination_id)
    except Exception:
        return _err("destination_id inválido.", 400)

    _, _, _, car_type_final, err_fk = _validate_fk_belongs(client_id, operator_id, car_id, destination_id)
    if err_fk:
        return err_fk

    try:
        op1 = _get_operator_global(operator_id)
        op2 = _get_operator_global(operator2_id) if operator2_id is not None else None
    except ApiError as e:
        return _err(str(e), e.status_code or 400)

    fecha = _parse_date_yyyy_mm_dd(fecha_in) if fecha_in else date.today()
    if not fecha:
        return _err("Fecha inválida. Usa YYYY-MM-DD.", 400)

    kms = _num(body.get("kms"), 0.0)
    tarifa = _num(body.get("tarifa"), 0.0)

    if kms < 0:
        return _err("Kms inválidos.", 400)
    if tarifa < 0:
        return _err("Tarifa inválida.", 400)

    aplica_iva = bool(body.get("aplica_iva") is True)
    iva_pct = _num(body.get("iva_pct"), 16.0 if aplica_iva else 0.0)

    aplica_ret = bool(body.get("aplica_retencion") is True)
    ret_pct = _num(body.get("retencion_pct"), 0.0)

    if aplica_iva and (iva_pct < 0 or iva_pct > 100):
        return _err("IVA % inválido (0 a 100).", 400)
    if aplica_ret and (ret_pct < 0 or ret_pct > 100):
        return _err("Retención % inválido (0 a 100).", 400)

    status = (body.get("status") or "draft").strip().lower()
    if status not in LIQ_STATUS_CHOICES:
        return _err("status inválido.", 400)

    observaciones = body.get("observaciones")
    observaciones = (observaciones.strip() if isinstance(observaciones, str) else None) or None

    activo = body.get("activo")
    activo = True if activo is None else bool(activo)

    if "car_type" in body and (body.get("car_type") not in (None, "", car_type_final)):
        return _err("No envíes 'car_type'. Se calcula automáticamente desde operador/carro.", 400)

    maniobra_op1 = _num(body.get("maniobra_op1"), 0.0)
    maniobra_op2 = _num(body.get("maniobra_op2"), 0.0)
    otros_op1 = _num(body.get("otros_ingresos_op1"), 0.0)
    otros_op2 = _num(body.get("otros_ingresos_op2"), 0.0)
    if min(maniobra_op1, maniobra_op2, otros_op1, otros_op2) < 0:
        return _err("Maniobra/otros ingresos no pueden ser negativos.", 400)

    expense_kwargs: Dict[str, Any] = {}
    for f in EXPENSE_FIELDS:
        if f in body:
            v = _num(body.get(f), 0.0)
            if v < 0:
                return _err(f"{f} no puede ser negativo.", 400)
            expense_kwargs[f] = round(float(v), 2)

    for f in EXPENSE_IVA_PCT_FIELDS:
        if f in body:
            v = _num(body.get(f), 16.0)
            if v < 0 or v > 100:
                return _err(f"{f} inválido (0 a 100).", 400)
            expense_kwargs[f] = round(float(v), 2)

    ded_list = body.get("deducciones") or []
    if not isinstance(ded_list, list):
        return _err("deducciones debe ser una lista.", 400)

    op_extra_payments = body.get("operator_extra_payments") or []
    if op_extra_payments is None:
        op_extra_payments = []

    ant_list = body.get("anticipos") or []
    if not isinstance(ant_list, list):
        return _err("anticipos debe ser una lista.", 400)

    # -------------------------
    # TALÓN: resolver (manual vs auto)
    # -------------------------
    talon_interno: str | None = None
    talon_folio: str | None = None
    talon_seq: int | None = None

    raw_talon_interno = body.get("talon_interno", None)

    raw_talon_folio = body.get("talon_folio", None)
    if raw_talon_folio in (None, "", 0):
        raw_talon_folio = body.get("talon_series_folio", None)

    try:
        if raw_talon_interno not in (None, ""):
            talon_interno, talon_folio, talon_seq = normalize_manual_talon_with_catalog(
                client_id=int(client_id),
                raw_talon=raw_talon_interno,
            )
        elif raw_talon_folio not in (None, ""):
            talon_interno, talon_folio, talon_seq = _allocate_next_talon_locked(client_id, str(raw_talon_folio))
        else:
            talon_interno, talon_folio, talon_seq = None, None, None
    except ApiError as e:
        return _err(str(e), e.status_code or 400)

    try:
        folio_num, folio_auto = _allocate_next_folio(client_id)

        liq = Liquidacion(
            client_id=client_id,
            folio_num=folio_num,
            folio=folio_auto,
            talon_interno=talon_interno,
            talon_folio=talon_folio,
            talon_seq=talon_seq,
            fecha=fecha,
            operator_id=operator_id,
            operator2_id=operator2_id,
            car_id=car_id,
            destination_id=destination_id,
            car_type=car_type_final,
            kms=round(kms, 2),
            tarifa=tarifa,
            aplica_iva=aplica_iva,
            iva_pct=iva_pct if aplica_iva else 0,
            aplica_retencion=aplica_ret,
            retencion_pct=ret_pct if aplica_ret else 0,
            status=status,
            observaciones=observaciones,
            activo=activo,
            sueldo_base_op1=round(float(getattr(op1, "sueldo_op_1", 0) or 0), 2),
            viaticos_base_op1=round(float(getattr(op1, "viaticos_op_1", 0) or 0), 2),
            sueldo_base_op2=round(float(getattr(op2, "sueldo_op_2", 0) or 0), 2) if op2 else 0,
            viaticos_base_op2=round(float(getattr(op2, "viaticos_op_2", 0) or 0), 2) if op2 else 0,
            maniobra_op1=round(maniobra_op1, 2),
            maniobra_op2=round(maniobra_op2, 2),
            otros_ingresos_op1=round(otros_op1, 2),
            otros_ingresos_op2=round(otros_op2, 2),
            **expense_kwargs,
        )

        _upsert_cfg_deducciones_for_slot(liq, client_id, 1, operator_id)
        if operator2_id is not None:
            _upsert_cfg_deducciones_for_slot(liq, client_id, 2, operator2_id)

        _upsert_imss_deduccion_for_slot(liq, client_id, 1, operator_id)
        if operator2_id is not None:
            _upsert_imss_deduccion_for_slot(liq, client_id, 2, operator2_id)

        for item in ded_list:
            _, slot, key, label, monto = _validate_deduccion_payload(item, allow_id=False)

            if slot == 2 and operator2_id is None:
                return _err("No puedes mandar deducciones operator_slot=2 sin operator2_id.", 400)

            if key in ("impuestos", "imss"):
                continue
            if key in PRESET_KEYS_NO_TAX:
                continue
            if key and str(key).startswith(CFG_EXTRA_KEY_PREFIX):
                continue

            liq.deducciones.append(
                LiquidacionDeduccion(
                    operator_slot=slot,
                    key=key,
                    label=label,
                    monto=monto,
                )
            )

        _apply_operator_extra_payments(liq, client_id, op_extra_payments)

        for item in ant_list:
            slot, importe, recibo = _validate_anticipo_payload(item)

            if slot == 2 and operator2_id is None:
                return _err("No puedes mandar anticipos operator_slot=2 sin operator2_id.", 400)

            snap_op_id = operator_id if slot == 1 else operator2_id

            liq.anticipos.append(
                LiquidacionAnticipo(
                    operator_slot=slot,
                    operator_id=snap_op_id,
                    importe=importe,
                    recibo=recibo,
                )
            )

        liq.recalc_totals()

        db.session.add(liq)
        db.session.flush()

        # Si fue talón manual, aseguramos que el contador quede “alcanzado”
        if raw_talon_interno not in (None, "") and talon_folio and talon_seq:
            _ensure_counter_at_least_locked(client_id, talon_folio, int(talon_seq))

        created = _serialize(liq)

        db.session.commit()
        return jsonify(created), 201

    except IntegrityError as e:
        db.session.rollback()
        msg = str(e.orig) if hasattr(e, "orig") else str(e)
        if "uq_liq_client_talon_interno" in msg or "uq_liq_client_talon_folio_seq" in msg:
            return _err("El talón interno ya existe para este cliente. Intenta de nuevo.", 409)
        return _err(f"No se pudo crear la liquidación. {msg}", 400)
    except ApiError as e:
        db.session.rollback()
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo crear la liquidación. {str(e)}", 400)


@liquidaciones_bp.get("/<int:liq_id>")
def get_liquidacion(client_id: int, liq_id: int):
    _, err = _validate_client(client_id)
    if err:
        return err

    liq = _load_liq_full(client_id, liq_id)
    if not liq:
        return _err("Liquidación no encontrada.", 404)

    return jsonify(_serialize(liq))


@liquidaciones_bp.patch("/<int:liq_id>")
def update_liquidacion(client_id: int, liq_id: int):
    """
    TALÓN (UPDATE):
    - Si llega talon_interno:
        - "" / None => limpia talón
        - valor => normaliza contra catálogo (serie activa) y guarda TAL CUAL (sin padding),
                  y asegura contador >= seq
    - Si llega talon_folio/talon_series_folio (y NO llega talon_interno):
        - genera y reserva el siguiente consecutivo (lock) y lo formatea con padding

    IMSS:
    - IMSS se regenera automático desde OperatorIMSS (mensual) cada vez que se hace PATCH.
    """
    _, err = _validate_client(client_id)
    if err:
        return err

    body = request.get_json(silent=True) or {}

    liq = _load_liq_full(client_id, liq_id)
    if not liq:
        return _err("Liquidación no encontrada.", 404)

    if "pagado" in body:
        liq.pagado = bool(body.get("pagado"))
        liq.pagado_at = datetime.utcnow() if liq.pagado else None

    if "car_type" in body:
        return _err("No envíes 'car_type'. Se calcula automáticamente desde operador/carro.", 400)

    if "fecha" in body:
        dt = _parse_date_yyyy_mm_dd(body.get("fecha") or "")
        if not dt:
            return _err("Fecha inválida. Usa YYYY-MM-DD.", 400)
        liq.fecha = dt

    if "destination_id" in body:
        raw = body.get("destination_id")
        try:
            did = None if raw in ("", None) else int(raw)
        except Exception:
            return _err("destination_id inválido.", 400)

        if did is not None:
            try:
                _get_destination_by_client(client_id, did)
            except ApiError as e:
                return _err(str(e), e.status_code or 400)

        liq.destination_id = did

    operator_changed = "operator_id" in body
    car_changed = "car_id" in body
    operator2_changed = "operator2_id" in body

    if operator_changed:
        try:
            op_id = int(body.get("operator_id"))
        except Exception:
            return _err("operator_id inválido.", 400)
        try:
            op_final = _get_operator_global(op_id)
        except ApiError as e:
            return _err(str(e), e.status_code or 400)
        liq.operator_id = op_id
        liq.sueldo_base_op1 = round(float(getattr(op_final, "sueldo_op_1", 0) or 0), 2)
        liq.viaticos_base_op1 = round(float(getattr(op_final, "viaticos_op_1", 0) or 0), 2)
    else:
        op_final = db.session.get(Operator, liq.operator_id)
        if not op_final:
            return _err("Operador inválido.", 400)

    op2_final = None
    if operator2_changed:
        raw = body.get("operator2_id")
        try:
            op2_id = None if raw in ("", None) else int(raw)
        except Exception:
            return _err("operator2_id inválido.", 400)

        if op2_id is not None and int(op2_id) == int(liq.operator_id):
            return _err("operator2_id no puede ser igual a operator_id.", 400)

        if op2_id is not None:
            try:
                op2_final = _get_operator_global(op2_id)
            except ApiError as e:
                return _err(str(e), e.status_code or 400)

        liq.operator2_id = op2_id

        if op2_final:
            liq.sueldo_base_op2 = round(float(getattr(op2_final, "sueldo_op_2", 0) or 0), 2)
            liq.viaticos_base_op2 = round(float(getattr(op2_final, "viaticos_op_2", 0) or 0), 2)
        else:
            liq.sueldo_base_op2 = 0
            liq.viaticos_base_op2 = 0
            liq.maniobra_op2 = 0
            liq.otros_ingresos_op2 = 0

            liq.deducciones = [
                d for d in (liq.deducciones or [])
                if int(getattr(d, "operator_slot", 1) or 1) != 2
            ]
            liq.anticipos = [
                a for a in (liq.anticipos or [])
                if int(getattr(a, "operator_slot", 1) or 1) != 2
            ]
    else:
        if getattr(liq, "operator2_id", None):
            op2_final = db.session.get(Operator, liq.operator2_id)

    if car_changed:
        raw = body.get("car_id")
        try:
            car_id = None if raw in ("", None) else int(raw)
        except Exception:
            return _err("car_id inválido.", 400)

        if car_id is not None:
            try:
                car_final = _get_car_global(car_id)
            except ApiError as e:
                return _err(str(e), e.status_code or 400)
        else:
            car_final = None

        liq.car_id = car_id
    else:
        car_final = db.session.get(Car, liq.car_id) if liq.car_id is not None else None
        if liq.car_id is not None and not car_final:
            return _err("Carro inválido.", 400)

    if operator_changed or car_changed:
        try:
            liq.car_type = _derive_car_type(op_final, car_final)
        except ApiError as e:
            return _err(str(e), e.status_code or 400)

    if "kms" in body:
        kms = _num(body.get("kms"), 0.0)
        if kms < 0:
            return _err("Kms inválidos.", 400)
        liq.kms = round(kms, 2)

    if "tarifa" in body:
        tarifa = _num(body.get("tarifa"), 0.0)
        if tarifa < 0:
            return _err("Tarifa inválida.", 400)
        liq.tarifa = tarifa

    if "aplica_iva" in body:
        liq.aplica_iva = bool(body.get("aplica_iva") is True)

    if "iva_pct" in body:
        iva_pct = _num(body.get("iva_pct"), 0.0)
        if liq.aplica_iva and (iva_pct < 0 or iva_pct > 100):
            return _err("IVA % inválido (0 a 100).", 400)
        liq.iva_pct = iva_pct if liq.aplica_iva else 0

    if "aplica_retencion" in body:
        liq.aplica_retencion = bool(body.get("aplica_retencion") is True)

    if "retencion_pct" in body:
        rp = _num(body.get("retencion_pct"), 0.0)
        if liq.aplica_retencion and (rp < 0 or rp > 100):
            return _err("Retención % inválido (0 a 100).", 400)
        liq.retencion_pct = rp if liq.aplica_retencion else 0

    if "status" in body:
        st = (body.get("status") or "").strip().lower()
        if st and st not in LIQ_STATUS_CHOICES:
            return _err("status inválido.", 400)
        if st:
            liq.status = st

    if "observaciones" in body:
        obs = body.get("observaciones")
        liq.observaciones = (obs.strip() if isinstance(obs, str) else None) or None

    if "activo" in body:
        liq.activo = bool(body.get("activo"))

    # -------------------------
    # TALÓN (PATCH)
    # -------------------------
    raw_talon_folio = body.get("talon_folio", None)
    if raw_talon_folio in (None, "", 0):
        raw_talon_folio = body.get("talon_series_folio", None)

    if "talon_interno" in body:
        try:
            raw = body.get("talon_interno", None)
            if raw in (None, ""):
                liq.talon_interno = None
                liq.talon_folio = None
                liq.talon_seq = None
            else:
                ti, tf, ts = normalize_manual_talon_with_catalog(
                    client_id=int(client_id),
                    raw_talon=raw,
                )
                liq.talon_interno = ti
                liq.talon_folio = tf
                liq.talon_seq = ts
                if tf and ts:
                    _ensure_counter_at_least_locked(client_id, tf, int(ts))
        except ApiError as e:
            return _err(str(e), e.status_code or 400)
    else:
        if raw_talon_folio not in (None, ""):
            try:
                ti, tf, ts = _allocate_next_talon_locked(client_id, str(raw_talon_folio))
                liq.talon_interno = ti
                liq.talon_folio = tf
                liq.talon_seq = ts
            except ApiError as e:
                return _err(str(e), e.status_code or 400)

    for f in ("maniobra_op1", "maniobra_op2", "otros_ingresos_op1", "otros_ingresos_op2"):
        if f in body:
            v = _num(body.get(f), 0.0)
            if v < 0:
                return _err(f"{f} no puede ser negativo.", 400)
            if f.endswith("_op2") and not getattr(liq, "operator2_id", None):
                return _err(f"No puedes enviar {f} sin operator2_id.", 400)
            setattr(liq, f, round(v, 2))

    for f in EXPENSE_FIELDS:
        if f in body:
            v = _num(body.get(f), 0.0)
            if v < 0:
                return _err(f"{f} no puede ser negativo.", 400)
            setattr(liq, f, round(float(v), 2))

    for f in EXPENSE_IVA_PCT_FIELDS:
        if f in body:
            v = _num(body.get(f), 16.0)
            if v < 0 or v > 100:
                return _err(f"{f} inválido (0 a 100).", 400)
            setattr(liq, f, round(float(v), 2))

    # ------------------  DEDUCCIONES / ANTICIPOS ------------------
    try:
        if "deducciones" in body:
            ded_list = body.get("deducciones") or []
            if not isinstance(ded_list, list):
                return _err("deducciones debe ser una lista.", 400)

            kept: List[LiquidacionDeduccion] = []
            for d in (liq.deducciones or []):
                key = (d.key or "").strip()
                if key.startswith(OP_EXTRA_KEY_PREFIX):
                    kept.append(d)
            liq.deducciones = kept
            db.session.flush()

            for item in ded_list:
                _, slot, key, label, monto = _validate_deduccion_payload(item, allow_id=False)
                if slot == 2 and not getattr(liq, "operator2_id", None):
                    return _err("No puedes mandar deducciones operator_slot=2 sin operator2_id.", 400)

                if key in ("impuestos", "imss"):
                    continue
                if key in PRESET_KEYS_NO_TAX:
                    continue
                if key and str(key).startswith(CFG_EXTRA_KEY_PREFIX):
                    continue

                liq.deducciones.append(
                    LiquidacionDeduccion(
                        operator_slot=slot,
                        key=key,
                        label=label,
                        monto=monto,
                    )
                )

        if "deduccion_add" in body and body.get("deduccion_add") is not None:
            _, slot, key, label, monto = _validate_deduccion_payload(body.get("deduccion_add"), allow_id=False)
            if slot == 2 and not getattr(liq, "operator2_id", None):
                return _err("No puedes mandar deducciones operator_slot=2 sin operator2_id.", 400)
            if key in ("impuestos", "imss"):
                return _err("La deducción 'impuestos' e 'imss' se calculan automáticamente.", 400)
            if key in PRESET_KEYS_NO_TAX or (key and str(key).startswith(CFG_EXTRA_KEY_PREFIX)):
                return _err("Esa deducción viene de la configuración (no se agrega manual).", 400)

            liq.deducciones.append(
                LiquidacionDeduccion(operator_slot=slot, key=key, label=label, monto=monto)
            )

        if "deduccion_update" in body and body.get("deduccion_update") is not None:
            upd = body.get("deduccion_update")
            ded_id, slot, key, label, monto = _validate_deduccion_payload(upd, allow_id=True)
            if not ded_id:
                return _err("deduccion_update requiere id.", 400)

            target = None
            for d in (liq.deducciones or []):
                if int(d.id) == int(ded_id):
                    target = d
                    break
            if not target:
                return _err("Deducción no encontrada en esta liquidación.", 404)

            tkey = (target.key or "").strip()

            if tkey in ("impuestos", "imss"):
                return _err("La deducción 'impuestos' e 'imss' se calculan automáticamente.", 400)
            if tkey in PRESET_KEYS_NO_TAX or tkey.startswith(CFG_EXTRA_KEY_PREFIX):
                return _err("Esa deducción viene de la configuración (no se edita manual).", 400)
            if tkey.startswith(OP_EXTRA_KEY_PREFIX):
                return _err("Esa deducción es un pago aplicado a una deuda (no se edita manual).", 400)

            if slot == 2 and not getattr(liq, "operator2_id", None):
                return _err("No puedes mandar deducciones operator_slot=2 sin operator2_id.", 400)

            if key in ("impuestos", "imss"):
                return _err("La deducción 'impuestos' e 'imss' se calculan automáticamente.", 400)
            if key in PRESET_KEYS_NO_TAX or (key and str(key).startswith(CFG_EXTRA_KEY_PREFIX)):
                return _err("No puedes convertirla a una deducción de configuración.", 400)

            target.operator_slot = slot
            target.key = key
            target.label = label
            target.monto = monto

        if "deduccion_delete_id" in body and body.get("deduccion_delete_id") is not None:
            try:
                did = int(body.get("deduccion_delete_id"))
            except Exception:
                return _err("deduccion_delete_id inválido.", 400)

            target = None
            for d in (liq.deducciones or []):
                if int(d.id) == int(did):
                    target = d
                    break
            if not target:
                return _err("Deducción no encontrada en esta liquidación.", 404)

            tkey = (target.key or "").strip()
            if tkey in ("impuestos", "imss"):
                return _err("La deducción 'impuestos' e 'imss' se calculan automáticamente.", 400)
            if tkey in PRESET_KEYS_NO_TAX or tkey.startswith(CFG_EXTRA_KEY_PREFIX):
                return _err("Esa deducción viene de la configuración (no se borra manual).", 400)
            if tkey.startswith(OP_EXTRA_KEY_PREFIX):
                return _err("Esa deducción es un pago aplicado (no se borra manual).", 400)

            db.session.delete(target)

        if "operator_extra_payments" in body and body.get("operator_extra_payments") is not None:
            _apply_operator_extra_payments(liq, client_id, body.get("operator_extra_payments") or [])

        if "anticipos" in body:
            ant_list = body.get("anticipos") or []
            if not isinstance(ant_list, list):
                return _err("anticipos debe ser una lista.", 400)

            liq.anticipos = []
            db.session.flush()

            for item in ant_list:
                slot, importe, recibo = _validate_anticipo_payload(item)
                if slot == 2 and not getattr(liq, "operator2_id", None):
                    return _err("No puedes mandar anticipos operator_slot=2 sin operator2_id.", 400)

                snap_op_id = liq.operator_id if slot == 1 else liq.operator2_id

                liq.anticipos.append(
                    LiquidacionAnticipo(
                        operator_slot=slot,
                        operator_id=snap_op_id,
                        importe=importe,
                        recibo=recibo,
                    )
                )

        if "anticipo_add" in body and body.get("anticipo_add") is not None:
            slot, importe, recibo = _validate_anticipo_payload(body.get("anticipo_add"))
            if slot == 2 and not getattr(liq, "operator2_id", None):
                return _err("No puedes mandar anticipos operator_slot=2 sin operator2_id.", 400)

            snap_op_id = liq.operator_id if slot == 1 else liq.operator2_id
            liq.anticipos.append(
                LiquidacionAnticipo(
                    operator_slot=slot,
                    operator_id=snap_op_id,
                    importe=importe,
                    recibo=recibo,
                )
            )

        if "anticipo_delete_id" in body and body.get("anticipo_delete_id") is not None:
            try:
                aid = int(body.get("anticipo_delete_id"))
            except Exception:
                return _err("anticipo_delete_id inválido.", 400)

            target = None
            for a in (liq.anticipos or []):
                if int(a.id) == int(aid):
                    target = a
                    break
            if not target:
                return _err("Anticipo no encontrado en esta liquidación.", 404)

            db.session.delete(target)

    except ApiError as e:
        return _err(str(e), e.status_code or 400)

    # Siempre re-sincroniza deducciones generadas por config (preset + cfg_extra) y regenera IMSS
    try:
        _strip_generated_cfg_deducciones(liq)
        _strip_generated_imss_deducciones(liq)

        _upsert_cfg_deducciones_for_slot(liq, client_id, 1, int(liq.operator_id))
        _upsert_imss_deduccion_for_slot(liq, client_id, 1, int(liq.operator_id))

        if getattr(liq, "operator2_id", None):
            _upsert_cfg_deducciones_for_slot(liq, client_id, 2, int(liq.operator2_id))
            _upsert_imss_deduccion_for_slot(liq, client_id, 2, int(liq.operator2_id))

    except ApiError as e:
        return _err(str(e), e.status_code or 400)

    liq.recalc_totals()

    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        msg = str(e.orig) if hasattr(e, "orig") else str(e)
        if "uq_liq_client_talon_interno" in msg or "uq_liq_client_talon_folio_seq" in msg:
            return _err("El talón interno ya existe para este cliente. Intenta de nuevo.", 409)
        return _err(f"No se pudo actualizar. {msg}", 400)
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo actualizar. {str(e)}", 400)

    liq2 = _load_liq_full(client_id, liq_id)
    return jsonify(_serialize(liq2 or liq))


@liquidaciones_bp.delete("/<int:liq_id>")
def delete_liquidacion(client_id: int, liq_id: int):
    _, err = _validate_client(client_id)
    if err:
        return err

    liq = _load_liq_full(client_id, liq_id)
    if not liq:
        return _err("Liquidación no encontrada.", 404)

    hard = _parse_bool(request.args.get("hard"))
    hard = bool(hard is True)

    try:
        if hard:
            db.session.delete(liq)
            db.session.commit()
            return jsonify({"status": "deleted", "id": liq_id})
        else:
            liq.activo = False
            db.session.commit()
            return jsonify({"status": "deactivated", "id": liq_id})
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo eliminar. {str(e)}", 400)


@liquidaciones_bp.get("/talon-series/<string:folio>/counter")
def get_talon_series_counter(client_id: int, folio: str):
    folio_n = normalize_folio(folio)

    row = (
        db.session.query(TalonSeriesCounter)
        .filter(
            TalonSeriesCounter.client_id == int(client_id),
            TalonSeriesCounter.folio == folio_n,
        )
        .one_or_none()
    )

    if not row:
        return jsonify(
            {
                "client_id": int(client_id),
                "folio": folio_n,
                "seq": 0,
            }
        )

    return jsonify(
        {
            "client_id": int(client_id),
            "folio": folio_n,
            "seq": int(row.seq or 0),
        }
    )