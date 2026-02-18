# atr_api/services/liquidaciones_excel_import_service.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from werkzeug.datastructures import FileStorage
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError

from atr_api.extensions import db
from atr_api.errors import ApiError

from atr_api.models.talon_series_counter import TalonSeriesCounter
from atr_api.models.talon_series import TalonSeries
from atr_api.models.liquidacion import Liquidacion

from atr_api.schemas.liquidaciones_excel_import import parse_excel_liquidaciones
from atr_api.services.talon_service import (
    normalize_folio,
    parse_talon,
    format_talon,
    require_series,
)


@dataclass
class RowError:
    row_number: int
    message: str
    data: Dict[str, Any]


def _get_current_counter_value(client_id: int, folio: str) -> int:
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

    row = TalonSeriesCounter(client_id=int(client_id), folio=folio_n, seq=0)
    db.session.add(row)
    db.session.flush()

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


def _get_last_liquidacion_seq_for_folio(client_id: int, folio: str) -> int:
    """
    Regresa el máximo talon_seq en liquidaciones para ese (client_id, folio).
    Si no hay, regresa 0.
    """
    folio_n = normalize_folio(folio)

    # Ruta robusta: usa columnas nuevas
    q = (
        db.session.query(Liquidacion)
        .filter(
            Liquidacion.client_id == int(client_id),
            Liquidacion.talon_folio == folio_n,
            Liquidacion.talon_seq.isnot(None),
        )
        .order_by(desc(Liquidacion.talon_seq), desc(Liquidacion.id))
    )
    liq = q.first()
    if not liq:
        return 0
    try:
        return int(liq.talon_seq or 0)
    except Exception:
        return 0


def _build_series_map(client_id: int, folios: List[str]) -> Dict[str, TalonSeries]:
    """
    Valida que todas las series existan y estén activas.
    Regresa dict folio->TalonSeries.
    """
    out: Dict[str, TalonSeries] = {}
    for f in folios:
        s = require_series(client_id, f)
        out[s.folio] = s
    return out


def _group_rows_by_folio(
    client_id: int,
    rows: List[Dict[str, Any]],
    errors: List[RowError],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Agrupa filas por folio detectado desde talon_interno.
    Adjunta en cada fila:
      _folio
      _seq_provided
      _talon_provided
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    for item in rows:
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
            folio, seq = parse_talon(talon_raw)
        except ApiError as e:
            errors.append(RowError(row_number=row_number, message=str(e), data=payload))
            continue
        except Exception:
            errors.append(
                RowError(
                    row_number=row_number,
                    message="talon_interno inválido (no se pudo parsear).",
                    data=payload,
                )
            )
            continue

        folio_n = normalize_folio(folio)

        payload["_row_number"] = row_number
        payload["_talon_provided"] = talon_raw.strip().upper()
        payload["_folio"] = folio_n
        payload["_seq_provided"] = int(seq)

        grouped.setdefault(folio_n, []).append(payload)

    return grouped


def _assign_expected_seqs_for_folio(
    *,
    series: TalonSeries,
    start_last_seq: int,
    rows_for_folio: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Asigna secuencias esperadas a las filas (en el orden en que aparecen en el Excel).
    Corrige consecutivos si el usuario se saltó números.

    Retorna:
      - filas enriquecidas con:
          _seq_expected
          talon_interno_corrected
          talon_interno_final
          _was_corrected (bool)
      - lista de correcciones
    """
    padding = int(series.padding or 5)
    folio = series.folio

    corrections: List[Dict[str, Any]] = []
    enriched: List[Dict[str, Any]] = []

    expected = int(start_last_seq) + 1

    for r in rows_for_folio:
        row_number = int(r.get("_row_number") or 0)
        provided_talon = str(r.get("_talon_provided") or "").strip().upper()
        provided_seq = int(r.get("_seq_provided") or 0)

        corrected_talon = format_talon(folio, expected, padding)

        was_corrected = (provided_seq != expected) or (provided_talon != corrected_talon)

        if was_corrected:
            corrections.append(
                {
                    "row": row_number,
                    "folio": folio,
                    "provided": provided_talon,
                    "provided_seq": provided_seq,
                    "expected_seq": expected,
                    "corrected": corrected_talon,
                    "reason": (
                        "Consecutivo no coincide con el esperado (se reasignó para mantener continuidad)."
                    ),
                }
            )

        r2 = dict(r)
        r2["_seq_expected"] = expected
        r2["talon_interno_corrected"] = corrected_talon
        r2["talon_interno_final"] = corrected_talon  # por ahora final = corrected
        r2["_was_corrected"] = bool(was_corrected)

        enriched.append(r2)
        expected += 1

    return enriched, corrections


def import_liquidaciones_from_excel(
    *,
    client_id: int,
    file_storage: FileStorage,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Import/validación de Excel de VIAJES por talón interno.

    Qué hace HOY (backend fino para el Excel):
      - Lee Excel.
      - Valida que talon_interno tenga formato PREFIJO+NÚMERO.
      - Valida que el PREFIJO exista y esté activo en TalonSeries del cliente.
      - Calcula el 'last_seq' real por folio usando:
          max(ultimo talon_seq guardado en liquidaciones, contador actual)
      - Reasigna consecutivos esperados en continuidad para las filas del Excel (por folio),
        y genera talon_interno_corrected.
      - Detecta duplicados dentro del archivo después de corrección.
      - Si dry_run=0:
          - actualiza TalonSeriesCounter.seq por folio al último consecutivo resultante,
            usando lock FOR UPDATE para concurrencia.

    Qué NO hace aún:
      - No crea Liquidaciones (porque todavía no definimos dónde persistir los campos del Excel
        como FACTURA/DEALER/etc). Esto solo deja listo el motor de validación y el contador.
    """
    try:
        parsed_rows = parse_excel_liquidaciones(file_storage)
    except ApiError:
        raise
    except Exception as e:
        raise ApiError(f"No se pudo leer el Excel: {e}", status_code=400)

    errors: List[RowError] = []
    grouped = _group_rows_by_folio(client_id, parsed_rows, errors)

    if errors and not grouped:
        # Si no hay ni una fila utilizable, cortamos temprano
        return {
            "dry_run": dry_run,
            "total_rows": len(parsed_rows),
            "folios_count": 0,
            "folios": [],
            "rows_out": [],
            "corrections_count": 0,
            "corrections": [],
            "duplicates_count": 0,
            "duplicates": [],
            "errors_count": len(errors),
            "errors": [{"row": e.row_number, "message": e.message, "data": e.data} for e in errors],
            "updated_counters": [],
        }

    folios = sorted(grouped.keys())

    # Valida catálogo de series (todas deben existir)
    try:
        series_map = _build_series_map(client_id, folios)
    except ApiError as e:
        # Error de catálogo es global, pero lo reportamos como error general
        raise ApiError(str(e), status_code=e.status_code or 400)

    # -------------------------------------------------------------------------
    # Paso 1: calcular last_seq por folio (sin lock; para pre-validación)
    # -------------------------------------------------------------------------
    pre_last_seq: Dict[str, int] = {}
    for folio in folios:
        last_from_liq = _get_last_liquidacion_seq_for_folio(client_id, folio)
        last_from_ctr = _get_current_counter_value(client_id, folio)
        pre_last_seq[folio] = max(int(last_from_liq or 0), int(last_from_ctr or 0))

    # -------------------------------------------------------------------------
    # Paso 2: asignar expected seq y corregir talones (por folio)
    # -------------------------------------------------------------------------
    all_rows_out: List[Dict[str, Any]] = []
    all_corrections: List[Dict[str, Any]] = []

    for folio in folios:
        series = series_map[folio]
        rows_for_folio = grouped[folio]
        enriched, corrections = _assign_expected_seqs_for_folio(
            series=series,
            start_last_seq=pre_last_seq[folio],
            rows_for_folio=rows_for_folio,
        )
        all_rows_out.extend(enriched)
        all_corrections.extend(corrections)

    # -------------------------------------------------------------------------
    # Paso 3: detectar duplicados dentro del archivo (después de corrección)
    # -------------------------------------------------------------------------
    seen: Dict[str, int] = {}
    duplicates: List[Dict[str, Any]] = []
    for r in all_rows_out:
        t = str(r.get("talon_interno_final") or "").strip().upper()
        if not t:
            continue
        if t in seen:
            duplicates.append(
                {
                    "talon_interno": t,
                    "first_row": seen[t],
                    "dup_row": int(r.get("_row_number") or 0),
                    "reason": "Talón duplicado dentro del archivo (después de corrección).",
                }
            )
        else:
            seen[t] = int(r.get("_row_number") or 0)

    if duplicates:
        # Si hay duplicados, no debemos actualizar counters (porque el set resultante no es válido)
        return {
            "dry_run": dry_run,
            "total_rows": len(parsed_rows),
            "folios_count": len(folios),
            "folios": folios,
            "rows_out": sorted(all_rows_out, key=lambda x: int(x.get("_row_number") or 0)),
            "corrections_count": len(all_corrections),
            "corrections": sorted(all_corrections, key=lambda x: int(x.get("row") or 0)),
            "duplicates_count": len(duplicates),
            "duplicates": duplicates,
            "errors_count": len(errors),
            "errors": [{"row": e.row_number, "message": e.message, "data": e.data} for e in errors],
            "updated_counters": [],
        }

    # -------------------------------------------------------------------------
    # Paso 4: persistir actualización de contadores (si NO dry_run)
    #         Con lock para proteger concurrencia.
    #         Si el contador avanzó entre el Paso 1 y aquí, reajustamos para ese folio.
    # -------------------------------------------------------------------------
    updated_counters: List[Dict[str, Any]] = []

    if not dry_run:
        try:
            # Procesamos folio por folio para tener locks acotados.
            for folio in folios:
                series = series_map[folio]
                padding = int(series.padding or 5)

                # Lock del contador
                ctr = _get_or_init_counter_locked(client_id, folio)

                last_from_liq = _get_last_liquidacion_seq_for_folio(client_id, folio)
                last_locked = max(int(ctr.seq or 0), int(last_from_liq or 0))

                # Tomamos las filas de este folio, en el orden del Excel
                rows_this = [r for r in all_rows_out if str(r.get("_folio") or "") == folio]
                rows_this_sorted = sorted(rows_this, key=lambda x: int(x.get("_row_number") or 0))

                # Si cambió el start por concurrencia, recalculamos los talones finales de este folio
                desired_start = last_locked + 1
                expected = desired_start

                for r in rows_this_sorted:
                    final_talon = format_talon(folio, expected, padding)

                    # Si esto cambia vs lo que ya traíamos, lo anotamos como corrección adicional
                    prev_final = str(r.get("talon_interno_final") or "").strip().upper()
                    if prev_final != final_talon:
                        all_corrections.append(
                            {
                                "row": int(r.get("_row_number") or 0),
                                "folio": folio,
                                "provided": str(r.get("_talon_provided") or "").strip().upper(),
                                "provided_seq": int(r.get("_seq_provided") or 0),
                                "expected_seq": expected,
                                "corrected": final_talon,
                                "reason": "El contador avanzó por concurrencia; se reasignó el rango para evitar colisiones.",
                            }
                        )

                    r["_seq_expected"] = expected
                    r["talon_interno_final"] = final_talon
                    expected += 1

                # El último usado será expected-1
                last_used_after_import = expected - 1
                if last_used_after_import < int(ctr.seq or 0):
                    # No debería pasar, pero por seguridad no retrocedemos
                    last_used_after_import = int(ctr.seq or 0)

                before = int(ctr.seq or 0)
                ctr.seq = int(last_used_after_import)
                db.session.flush()

                updated_counters.append(
                    {
                        "folio": folio,
                        "seq_before": before,
                        "seq_after": int(ctr.seq or 0),
                        "rows_count": len(rows_this_sorted),
                        "range_assigned": (
                            f"{format_talon(folio, desired_start, padding)}"
                            f" .. "
                            f"{format_talon(folio, int(ctr.seq or 0), padding)}"
                            if len(rows_this_sorted) > 0
                            else None
                        ),
                    }
                )

            db.session.commit()

        except IntegrityError:
            db.session.rollback()
            raise ApiError(
                "Error de integridad actualizando contadores de talón. Revisa el archivo y vuelve a intentar.",
                status_code=409,
            )
        except ApiError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            raise ApiError(f"Error inesperado importando Excel: {e}", status_code=500)

    # Resumen final por folio (con lo que quedó en rows_out / counters)
    summary_by_folio: List[Dict[str, Any]] = []
    rows_sorted = sorted(all_rows_out, key=lambda x: int(x.get("_row_number") or 0))

    # Recomputa last seq final por folio según lo asignado (sin depender del counter)
    final_max_seq: Dict[str, int] = {f: 0 for f in folios}
    for r in rows_sorted:
        f = str(r.get("_folio") or "")
        if not f:
            continue
        try:
            s = int(r.get("_seq_expected") or 0)
        except Exception:
            s = 0
        final_max_seq[f] = max(final_max_seq.get(f, 0), s)

    for folio in folios:
        series = series_map[folio]
        padding = int(series.padding or 5)

        start_last = pre_last_seq.get(folio, 0)
        next_seq_start = int(start_last) + 1
        end_seq = final_max_seq.get(folio, 0)

        if end_seq <= 0:
            next_after = next_seq_start
        else:
            next_after = end_seq + 1

        summary_by_folio.append(
            {
                "folio": folio,
                "padding": padding,
                "last_seq_before": int(start_last),
                "next_seq_assigned_start": int(next_seq_start),
                "last_seq_assigned_end": int(end_seq) if end_seq > 0 else int(start_last),
                "next_seq_after_import": int(next_after),
                "next_talon_after_import": format_talon(folio, int(next_after), padding),
                "rows_count": len([r for r in rows_sorted if str(r.get("_folio") or "") == folio]),
            }
        )

    return {
        "dry_run": dry_run,
        "total_rows": len(parsed_rows),
        "folios_count": len(folios),
        "folios": folios,
        "rows_out": rows_sorted,
        "corrections_count": len(all_corrections),
        "corrections": sorted(all_corrections, key=lambda x: int(x.get("row") or 0)),
        "duplicates_count": 0,
        "duplicates": [],
        "errors_count": len(errors),
        "errors": [{"row": e.row_number, "message": e.message, "data": e.data} for e in errors],
        "summary_by_folio": summary_by_folio,
        "updated_counters": updated_counters,
    }
