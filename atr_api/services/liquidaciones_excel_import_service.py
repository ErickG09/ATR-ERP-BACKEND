# atr_api/services/liquidaciones_excel_import_service.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import FileStorage

from atr_api.errors import ApiError
from atr_api.extensions import db

from atr_api.models.talon_series_counter import TalonSeriesCounter
from atr_api.models.client_counter import ClientCounter
from atr_api.models.liquidacion import Liquidacion
from atr_api.models.liquidacion_detalle import LiquidacionDetalle
from atr_api.models.operator import Operator
from atr_api.models.car import Car

from atr_api.schemas.liquidaciones_excel_import import parse_excel_liquidaciones
from atr_api.services.talon_service import (
    ensure_counter_at_least,
    normalize_folio,
    normalize_manual_talon_with_catalog,
)


@dataclass
class RowError:
    row_number: int
    message: str
    data: Dict[str, Any]


def _compact_upper(value: Any) -> str:
    return "".join(str(value or "").strip().split()).upper()


def _get_or_init_series_counter_locked(client_id: int, folio: str) -> TalonSeriesCounter:
    """
    Obtiene el contador con lock (FOR UPDATE). Si no existe, lo crea con tolerancia a carrera.
    Se usa para reportar before/after; la actualización real se hace con ensure_counter_at_least().
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


def _ensure_counter_at_least_locked(client_id: int, folio: str, seq_used: int) -> Dict[str, Any]:
    """
    Asegura contador >= seq_used (con lock). Retorna before/after para reportar.
    """
    folio_n = normalize_folio(folio)
    ctr = _get_or_init_series_counter_locked(client_id, folio_n)
    before = int(ctr.seq or 0)

    ensure_counter_at_least(int(client_id), folio_n, int(seq_used or 0))

    after = int(ctr.seq or 0)
    return {"folio": folio_n, "seq_before": before, "seq_after": after}


# --------------------------
# Helpers: resolver catálogos
# --------------------------

def _q_by_client_if_exists(model, client_id: int):
    q = db.session.query(model)
    if hasattr(model, "client_id"):
        q = q.filter(getattr(model, "client_id") == int(client_id))
    return q


def _resolve_operator_id_from_excel(client_id: int, raw_name: Any) -> Optional[int]:
    """
    Intenta resolver operator_id a partir del texto del Excel (operador_1 / operador_2).

    Estrategia:
      1) Exact match por nombre/alias comunes (si existen columnas).
      2) Fallback por ilike en columnas típicas.

    Si no se puede resolver, regresa None.
    """
    name = (str(raw_name or "")).strip()
    if not name:
        return None

    name_u = name.strip()
    q = _q_by_client_if_exists(Operator, client_id)

    # Intentar columnas típicas si existen
    candidates_cols = []
    for col in ("nombre", "name", "full_name", "alias", "codigo", "code"):
        if hasattr(Operator, col):
            candidates_cols.append(getattr(Operator, col))

    # 1) exact
    for col in candidates_cols:
        row = q.filter(col == name_u).first()
        if row:
            return int(row.id)

    # 2) ilike
    like = f"%{name_u}%"
    for col in candidates_cols:
        try:
            row = q.filter(col.ilike(like)).first()
            if row:
                return int(row.id)
        except Exception:
            continue

    return None


def _resolve_car_id_from_excel(client_id: int, raw_car: Any) -> Optional[int]:
    """
    Resuelve car_id por texto del Excel (carro/unidad/placas).

    Se intenta por campos típicos: codigo/code/placas/nombre.
    Si no se puede resolver, regresa None.
    """
    s = (str(raw_car or "")).strip()
    if not s:
        return None

    q = _q_by_client_if_exists(Car, client_id)

    candidates_cols = []
    for col in ("codigo", "code", "placas", "nombre", "name"):
        if hasattr(Car, col):
            candidates_cols.append(getattr(Car, col))

    # exact
    for col in candidates_cols:
        row = q.filter(col == s).first()
        if row:
            return int(row.id)

    # ilike
    like = f"%{s}%"
    for col in candidates_cols:
        try:
            row = q.filter(col.ilike(like)).first()
            if row:
                return int(row.id)
        except Exception:
            continue

    return None


def _parse_iso_date_to_date(v: Any) -> Optional[date]:
    """
    v viene del parser como 'YYYY-MM-DD' o None.
    """
    if not v:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


# --------------------------
# Helpers: folio Liquidacion
# --------------------------

def _get_or_init_client_counter_locked(client_id: int) -> ClientCounter:
    ctr = (
        db.session.query(ClientCounter)
        .filter(ClientCounter.client_id == int(client_id))
        .with_for_update()
        .one_or_none()
    )
    if ctr:
        return ctr

    # tolerar carrera
    try:
        with db.session.begin_nested():
            db.session.add(ClientCounter(client_id=int(client_id), liquidacion_folio_seq=0))
            db.session.flush()
    except IntegrityError:
        pass

    ctr2 = (
        db.session.query(ClientCounter)
        .filter(ClientCounter.client_id == int(client_id))
        .with_for_update()
        .one_or_none()
    )
    if not ctr2:
        raise ApiError("No se pudo inicializar el contador de liquidación.", status_code=500)
    return ctr2


def _allocate_next_liquidacion_folio_locked(client_id: int) -> Tuple[int, str]:
    ctr = _get_or_init_client_counter_locked(client_id)
    ctr.liquidacion_folio_seq = int(ctr.liquidacion_folio_seq or 0) + 1
    folio_num = int(ctr.liquidacion_folio_seq)
    folio = Liquidacion.format_folio(folio_num)
    db.session.flush()
    return folio_num, folio


# --------------------------
# Persistencia (cabecera + detalles)
# --------------------------

def _find_liquidacion_by_talon(client_id: int, talon_interno: str) -> Optional[Liquidacion]:
    return (
        db.session.query(Liquidacion)
        .filter(
            Liquidacion.client_id == int(client_id),
            Liquidacion.talon_interno == talon_interno,
        )
        .one_or_none()
    )


def _replace_detalles_for_liquidacion(
    *,
    client_id: int,
    liq: Liquidacion,
    details: List[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Reemplaza todos los detalles de una liquidación por los del import actual.
    Retorna contadores {deleted, inserted}.
    """
    deleted = (
        db.session.query(LiquidacionDetalle)
        .filter(
            LiquidacionDetalle.client_id == int(client_id),
            LiquidacionDetalle.liquidacion_id == int(liq.id),
        )
        .delete(synchronize_session=False)
    )

    inserted = 0
    for d in details:
        det = LiquidacionDetalle(
            client_id=int(client_id),
            liquidacion_id=int(liq.id),
            row_number=int(d.get("_row_number") or 0) or None,
            fecha=_parse_iso_date_to_date(d.get("fecha")),
            factura_cp=(d.get("factura_cp") or None),
            carro=(d.get("carro") or None),
            dealer=(d.get("dealer") or None),
            unidades=d.get("unidades"),
            kms=d.get("kms"),
            operador_1=(d.get("operador_1") or None),
            operador_2=(d.get("operador_2") or None),
            flete=d.get("flete"),
            iva=d.get("iva"),
            retencion=d.get("retencion"),
            total=d.get("total"),
            anticipo_1=d.get("anticipo_1"),
            recibo_1=(d.get("recibo_1") or None),
            anticipo_2=d.get("anticipo_2"),
            recibo_2=(d.get("recibo_2") or None),
        )
        db.session.add(det)
        inserted += 1

    db.session.flush()
    return {"deleted": int(deleted or 0), "inserted": int(inserted or 0)}


def import_liquidaciones_from_excel(
    *,
    client_id: int,
    file_storage: FileStorage,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Import/validación de Excel de VIAJES por talón interno.

    Reglas:
      - Acepta talones con consecutivo libre (1..12 dígitos) sin forzar padding.
      - Talón repetido en el Excel NO es error: representa el mismo viaje con varios renglones/detalles.
      - NO reasigna consecutivos.
      - Si dry_run=False:
          1) crea/actualiza Liquidacion (cabecera) por talón
          2) reemplaza detalles (LiquidacionDetalle) por lo que venga en el Excel
          3) sube TalonSeriesCounter.seq al máximo consecutivo visto por folio.
    """
    try:
        parsed_rows = parse_excel_liquidaciones(file_storage)
    except ApiError:
        raise
    except Exception as e:
        raise ApiError(f"No se pudo leer el Excel: {e}", status_code=400)

    errors: List[RowError] = []
    rows_out: List[Dict[str, Any]] = []

    # Agrupación por viaje (talón)
    trips_map: Dict[str, Dict[str, Any]] = {}

    # Máximo consecutivo por folio
    max_seq_by_folio: Dict[str, int] = {}

    for item in parsed_rows:
        row_number = int(item.get("_row_number") or 0)
        payload = dict(item.get("payload") or {})

        talon_raw = (payload.get("talon_interno") or "").strip()
        if not talon_raw:
            errors.append(
                RowError(
                    row_number=row_number,
                    message="Falta TALON/TALON-VIAJE (talon_interno).",
                    data=payload,
                )
            )
            continue

        try:
            talon_norm, folio, seq = normalize_manual_talon_with_catalog(
                client_id=int(client_id),
                raw_talon=talon_raw,
            )
        except ApiError as e:
            errors.append(RowError(row_number=row_number, message=str(e), data=payload))
            continue
        except Exception:
            errors.append(
                RowError(
                    row_number=row_number,
                    message="talon_interno inválido (no se pudo normalizar con catálogo).",
                    data=payload,
                )
            )
            continue

        if not talon_norm or not folio or not seq:
            errors.append(
                RowError(
                    row_number=row_number,
                    message="talon_interno inválido (vacío o incompleto).",
                    data=payload,
                )
            )
            continue

        folio_n = normalize_folio(folio)
        seq_i = int(seq)

        # máximo por folio
        prev_max = int(max_seq_by_folio.get(folio_n, 0))
        if seq_i > prev_max:
            max_seq_by_folio[folio_n] = seq_i

        # fila plana (útil para depuración/UI)
        payload["_row_number"] = row_number
        payload["_talon_provided"] = _compact_upper(talon_raw)
        payload["_folio"] = folio_n
        payload["_seq"] = seq_i

        # talón final (sin padding)
        payload["talon_interno"] = talon_norm

        rows_out.append(payload)

        # agrupar por talón (viaje)
        trip = trips_map.get(talon_norm)
        if not trip:
            trip = {
                "talon_interno": talon_norm,
                "talon_folio": folio_n,
                "talon_seq": seq_i,
                "rows_count": 0,
                "details": [],
            }
            trips_map[talon_norm] = trip

        trip["rows_count"] = int(trip["rows_count"] or 0) + 1

        # detalle/renglón del Excel (lo que persistiremos en LiquidacionDetalle)
        trip["details"].append(
            {
                "_row_number": row_number,
                "fecha": payload.get("fecha") or None,
                "factura_cp": payload.get("factura_cp") or None,
                "carro": payload.get("carro") or None,
                "dealer": payload.get("dealer") or None,
                "unidades": payload.get("unidades"),
                "kms": payload.get("kms"),
                "operador_1": payload.get("operador_1") or None,
                "operador_2": payload.get("operador_2") or None,
                "flete": payload.get("flete"),
                "iva": payload.get("iva"),
                "retencion": payload.get("retencion"),
                "total": payload.get("total"),
                "anticipo_1": payload.get("anticipo_1"),
                "recibo_1": payload.get("recibo_1") or None,
                "anticipo_2": payload.get("anticipo_2"),
                "recibo_2": payload.get("recibo_2") or None,
            }
        )

    # Si todo falló y solo hay errores
    if errors and not rows_out:
        return {
            "dry_run": dry_run,
            "total_rows": len(parsed_rows),
            "folios_count": 0,
            "folios": [],
            "rows_out": [],
            "trips_count": 0,
            "trips": [],
            "duplicates_count": 0,
            "duplicates": [],
            "errors_count": len(errors),
            "errors": [{"row": e.row_number, "message": e.message, "data": e.data} for e in errors],
            "updated_counters": [],
            "summary_by_folio": [],
            "persist": {
                "created_liquidaciones": 0,
                "updated_liquidaciones": 0,
                "replaced_detalles": 0,
                "inserted_detalles": 0,
                "deleted_detalles": 0,
            },
        }

    # “Duplicados” informativos: mismo talón con múltiples renglones
    duplicates: List[Dict[str, Any]] = []
    for talon, trip in trips_map.items():
        if int(trip.get("rows_count") or 0) > 1:
            details = trip.get("details") or []
            first_row = int(details[0].get("_row_number") or 0) if details else 0
            duplicates.append(
                {
                    "talon_interno": talon,
                    "first_row": first_row,
                    "dup_rows": [int(d.get("_row_number") or 0) for d in details[1:]],
                    "reason": "Mismo viaje con varias cartas porte / dealers (válido).",
                }
            )

    folios = sorted(list(max_seq_by_folio.keys()))

    # -------------------------
    # Persistencia: cabecera + detalles (solo si NO dry_run)
    # -------------------------
    created_liqs = 0
    updated_liqs = 0
    replaced_detalles = 0
    inserted_detalles = 0
    deleted_detalles = 0
    persisted: List[Dict[str, Any]] = []

    if not dry_run:
        try:
            # 1) Crear/actualizar liquidaciones por talón + guardar detalles
            for talon, trip in trips_map.items():
                talon_interno = str(trip.get("talon_interno") or "").strip()
                talon_folio = str(trip.get("talon_folio") or "").strip()
                talon_seq = int(trip.get("talon_seq") or 0) or None
                details = list(trip.get("details") or [])

                if not talon_interno or not talon_folio or not talon_seq:
                    continue

                liq = _find_liquidacion_by_talon(int(client_id), talon_interno)

                # Resolver campos “mínimos razonables” desde el primer renglón
                first = details[0] if details else {}
                fecha_dt = _parse_iso_date_to_date(first.get("fecha")) or date.today()

                op1_id = _resolve_operator_id_from_excel(client_id, first.get("operador_1"))
                op2_id = _resolve_operator_id_from_excel(client_id, first.get("operador_2"))
                car_id = _resolve_car_id_from_excel(client_id, first.get("carro"))

                # Si tu tabla Liquidacion exige operator_id NOT NULL, esto debe resolverse.
                # Si no se puede, lo marcamos como error “de viaje” y NO lo persistimos.
                if not op1_id:
                    errors.append(
                        RowError(
                            row_number=int(first.get("_row_number") or 0),
                            message=f"No se pudo resolver operator_id desde Excel (operador_1='{first.get('operador_1') or ''}'). "
                                    f"Registra el operador en el catálogo o ajusta el texto del Excel.",
                            data={"talon_interno": talon_interno, "operador_1": first.get("operador_1")},
                        )
                    )
                    continue

                if liq is None:
                    folio_num, folio_auto = _allocate_next_liquidacion_folio_locked(int(client_id))

                    liq = Liquidacion(
                        client_id=int(client_id),
                        folio_num=int(folio_num),
                        folio=str(folio_auto),
                        fecha=fecha_dt,
                        talon_interno=talon_interno,
                        talon_folio=normalize_folio(talon_folio),
                        talon_seq=int(talon_seq),
                        operator_id=int(op1_id),
                        operator2_id=int(op2_id) if op2_id else None,
                        car_id=int(car_id) if car_id else None,
                        destination_id=None,
                        # Campos numéricos básicos (no forzamos cálculos aquí)
                        kms=0,
                        tarifa=0,
                        aplica_iva=False,
                        iva_pct=0,
                        aplica_retencion=False,
                        retencion_pct=0,
                        status="draft",
                        activo=True,
                    )
                    db.session.add(liq)
                    db.session.flush()
                    created_liqs += 1
                    action = "created"
                else:
                    # Actualiza campos “snap” si estaban vacíos o si quieres sincronizar
                    # (lo dejamos conservador para no pisar capturas manuales ya hechas).
                    if not getattr(liq, "fecha", None):
                        liq.fecha = fecha_dt
                    if not getattr(liq, "operator_id", None):
                        liq.operator_id = int(op1_id)
                    if op2_id and not getattr(liq, "operator2_id", None):
                        liq.operator2_id = int(op2_id)
                    if car_id and not getattr(liq, "car_id", None):
                        liq.car_id = int(car_id)

                    # Asegurar talón_folio/talon_seq consistentes
                    liq.talon_interno = talon_interno
                    liq.talon_folio = normalize_folio(talon_folio)
                    liq.talon_seq = int(talon_seq)

                    db.session.flush()
                    updated_liqs += 1
                    action = "updated"

                # Reemplazar detalles del viaje (talón)
                rep = _replace_detalles_for_liquidacion(
                    client_id=int(client_id),
                    liq=liq,
                    details=details,
                )
                replaced_detalles += 1
                deleted_detalles += int(rep["deleted"])
                inserted_detalles += int(rep["inserted"])

                persisted.append(
                    {
                        "talon_interno": talon_interno,
                        "liquidacion_id": int(liq.id),
                        "action": action,
                        "detalles_deleted": int(rep["deleted"]),
                        "detalles_inserted": int(rep["inserted"]),
                    }
                )

            # 2) Actualizar contadores de series (talón) al máximo visto
            updated_counters: List[Dict[str, Any]] = []
            for folio in folios:
                max_seq = int(max_seq_by_folio.get(folio, 0) or 0)
                if max_seq <= 0:
                    continue
                info = _ensure_counter_at_least_locked(int(client_id), folio, max_seq)
                updated_counters.append(info)

            db.session.commit()

        except IntegrityError as e:
            db.session.rollback()
            msg = str(e.orig) if hasattr(e, "orig") else str(e)
            raise ApiError(
                f"Error de integridad importando Excel. Revisa datos/duplicados. Detalle: {msg}",
                status_code=409,
            )
        except ApiError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            raise ApiError(f"Error inesperado importando Excel: {e}", status_code=500)

    else:
        updated_counters = []

    # Resumen por folio
    summary_by_folio: List[Dict[str, Any]] = []
    for folio in folios:
        summary_by_folio.append(
            {
                "folio": folio,
                "max_seq_seen_in_excel": int(max_seq_by_folio.get(folio, 0) or 0),
                "rows_count": len([r for r in rows_out if str(r.get("_folio") or "") == folio]),
                "trips_count": len([t for t in trips_map.values() if str(t.get("talon_folio") or "") == folio]),
            }
        )

    rows_sorted = sorted(rows_out, key=lambda x: int(x.get("_row_number") or 0))
    trips_sorted = sorted(
        trips_map.values(),
        key=lambda x: (str(x.get("talon_folio") or ""), int(x.get("talon_seq") or 0)),
    )

    return {
        "dry_run": dry_run,
        "total_rows": len(parsed_rows),
        "folios_count": len(folios),
        "folios": folios,
        "rows_out": rows_sorted,
        "trips_count": len(trips_sorted),
        "trips": trips_sorted,
        "duplicates_count": len(duplicates),
        "duplicates": duplicates,
        "errors_count": len(errors),
        "errors": [{"row": e.row_number, "message": e.message, "data": e.data} for e in errors],
        "summary_by_folio": summary_by_folio,
        "updated_counters": updated_counters,
        # Nuevo: resumen de persistencia para que el frontend/tu debug vea qué guardó
        "persist": {
            "created_liquidaciones": int(created_liqs),
            "updated_liquidaciones": int(updated_liqs),
            "replaced_detalles": int(replaced_detalles),
            "inserted_detalles": int(inserted_detalles),
            "deleted_detalles": int(deleted_detalles),
            "items": persisted,
        },
    }