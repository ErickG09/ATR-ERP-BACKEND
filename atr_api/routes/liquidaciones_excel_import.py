# atr_api/routes/liquidaciones_excel_import.py

from __future__ import annotations

from typing import Any, Dict, Optional, List

from flask import Blueprint, jsonify, request
from werkzeug.datastructures import FileStorage

from atr_api.errors import ApiError
from atr_api.extensions import db
from atr_api.models.client import Client
from atr_api.models.liquidacion import Liquidacion
from atr_api.models.liquidacion_detalle import LiquidacionDetalle
from atr_api.services.liquidaciones_excel_import_service import import_liquidaciones_from_excel


bp = Blueprint(
    "liquidaciones_excel_import",
    __name__,
    url_prefix="/api/clients/<int:client_id>/liquidaciones",
)


def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


def _parse_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()

    if s in ("dry_run", "preview", "validate"):
        return True
    if s in ("import", "persist", "save", "commit"):
        return False

    if s in ("1", "true", "t", "si", "s", "yes", "y"):
        return True
    if s in ("0", "false", "f", "no", "n"):
        return False
    return None


def _validate_client(client_id: int):
    c = db.session.get(Client, int(client_id))
    if not c:
        return None, _err("Cliente no válido.", 400)
    return c, None


def _get_file_from_request() -> Optional[FileStorage]:
    """
    Acepta multipart/form-data con campo 'file' o 'excel'.
    """
    if "file" in request.files:
        return request.files.get("file")
    if "excel" in request.files:
        return request.files.get("excel")
    return None


def _validate_excel_filename(filename: Optional[str]) -> None:
    """
    Validación ligera por extensión.
    """
    name = (filename or "").strip().lower()
    if not name:
        return

    allowed = (".xlsx", ".xlsm", ".xltx", ".xltm", ".xls")  # extensiones comunes de Excel
    if not name.endswith(allowed):
        raise ApiError("Formato inválido. Solo se acepta Excel .xlsx/.xlsm.", status_code=400)


def _serialize_liquidacion(liq: Liquidacion) -> Dict[str, Any]:
    return {
        "id": int(liq.id),
        "client_id": int(liq.client_id),
        "folio_num": int(liq.folio_num) if liq.folio_num is not None else None,
        "folio": liq.folio,
        "fecha": liq.fecha.isoformat() if getattr(liq, "fecha", None) else None,
        "talon_interno": liq.talon_interno,
        "talon_folio": liq.talon_folio,
        "talon_seq": int(liq.talon_seq) if liq.talon_seq is not None else None,
        "operator_id": int(liq.operator_id) if liq.operator_id is not None else None,
        "operator2_id": int(liq.operator2_id) if liq.operator2_id is not None else None,
        "car_id": int(liq.car_id) if liq.car_id is not None else None,
        "destination_id": int(liq.destination_id) if getattr(liq, "destination_id", None) is not None else None,
        "kms": float(liq.kms) if getattr(liq, "kms", None) is not None else None,
        "tarifa": float(liq.tarifa) if getattr(liq, "tarifa", None) is not None else None,
        "aplica_iva": bool(liq.aplica_iva) if getattr(liq, "aplica_iva", None) is not None else None,
        "iva_pct": float(liq.iva_pct) if getattr(liq, "iva_pct", None) is not None else None,
        "aplica_retencion": bool(liq.aplica_retencion) if getattr(liq, "aplica_retencion", None) is not None else None,
        "retencion_pct": float(liq.retencion_pct) if getattr(liq, "retencion_pct", None) is not None else None,
        "status": getattr(liq, "status", None),
        "activo": bool(liq.activo) if getattr(liq, "activo", None) is not None else None,
    }


def _serialize_detalle(det: LiquidacionDetalle) -> Dict[str, Any]:
    return {
        "id": int(det.id),
        "client_id": int(det.client_id),
        "liquidacion_id": int(det.liquidacion_id),
        "row_number": int(det.row_number) if det.row_number is not None else None,
        "fecha": det.fecha.isoformat() if getattr(det, "fecha", None) else None,
        "factura_cp": det.factura_cp,
        "carro": det.carro,
        "dealer": det.dealer,
        "unidades": int(det.unidades) if det.unidades is not None else None,
        "kms": float(det.kms) if det.kms is not None else None,
        "operador_1": det.operador_1,
        "operador_2": det.operador_2,
        "flete": float(det.flete) if det.flete is not None else None,
        "iva": float(det.iva) if det.iva is not None else None,
        "retencion": float(det.retencion) if det.retencion is not None else None,
        "total": float(det.total) if det.total is not None else None,
        "anticipo_1": float(det.anticipo_1) if det.anticipo_1 is not None else None,
        "recibo_1": det.recibo_1,
        "anticipo_2": float(det.anticipo_2) if det.anticipo_2 is not None else None,
        "recibo_2": det.recibo_2,
    }


@bp.post("/import-excel")
def import_excel(client_id: int):
    """
    Importa/valida un Excel de viajes (liquidaciones) basado en talón interno.

    Request:
      - Content-Type: multipart/form-data
      - file: campo "file" o "excel"
      - dry_run: query param o form field (opcional) => 1/0 (default: 1)
      - mode: query param o form field (opcional) => 'dry_run'|'import' (o aliases)

    Nota:
      - mode tiene prioridad sobre dry_run si viene.
      - Por defecto: dry_run=True para evitar cambios accidentales.
    """
    _, err = _validate_client(client_id)
    if err:
        return err

    mode_raw = request.args.get("mode")
    dry_run_raw = request.args.get("dry_run")

    if mode_raw is None:
        mode_raw = request.form.get("mode")
    if dry_run_raw is None:
        dry_run_raw = request.form.get("dry_run")

    val = mode_raw if mode_raw is not None else dry_run_raw
    dry_run = _parse_bool(val)
    dry_run = True if dry_run is None else bool(dry_run)

    fs = _get_file_from_request()
    if not fs:
        return _err(
            "Falta archivo Excel. Envía multipart/form-data con campo 'file' (o 'excel').",
            400,
        )

    try:
        _validate_excel_filename(getattr(fs, "filename", None))
    except ApiError as e:
        return _err(str(e), int(getattr(e, "status_code", 400) or 400))

    try:
        result: Dict[str, Any] = import_liquidaciones_from_excel(
            client_id=int(client_id),
            file_storage=fs,
            dry_run=dry_run,
        )
        return jsonify(result), 200

    except ApiError as e:
        code = int(getattr(e, "status_code", 400) or 400)
        return _err(str(e), code)

    except Exception as e:
        return _err(f"Error inesperado importando Excel: {e}", 500)


@bp.get("/debug-saved")
def debug_saved_liquidacion(client_id: int):
    """
    Devuelve exactamente lo guardado en DB para una liquidación importada.

    Query params:
      - talon_interno=PRO2054123
      o
      - liquidacion_id=123

    Ejemplos:
      GET /api/clients/1/liquidaciones/debug-saved?talon_interno=PRO2054123
      GET /api/clients/1/liquidaciones/debug-saved?liquidacion_id=15
    """
    _, err = _validate_client(client_id)
    if err:
        return err

    talon_interno = (request.args.get("talon_interno") or "").strip()
    liquidacion_id_raw = (request.args.get("liquidacion_id") or "").strip()

    if not talon_interno and not liquidacion_id_raw:
        return _err("Envía 'talon_interno' o 'liquidacion_id' como query param.", 400)

    try:
        q = db.session.query(Liquidacion).filter(Liquidacion.client_id == int(client_id))

        if liquidacion_id_raw:
            try:
                liquidacion_id = int(liquidacion_id_raw)
            except ValueError:
                return _err("liquidacion_id inválido.", 400)

            liq = q.filter(Liquidacion.id == liquidacion_id).one_or_none()
        else:
            liq = q.filter(Liquidacion.talon_interno == talon_interno).one_or_none()

        if not liq:
            return _err("No se encontró una liquidación con esos parámetros.", 404)

        detalles: List[LiquidacionDetalle] = (
            db.session.query(LiquidacionDetalle)
            .filter(
                LiquidacionDetalle.client_id == int(client_id),
                LiquidacionDetalle.liquidacion_id == int(liq.id),
            )
            .order_by(LiquidacionDetalle.row_number.asc(), LiquidacionDetalle.id.asc())
            .all()
        )

        return jsonify(
            {
                "found": True,
                "lookup": {
                    "client_id": int(client_id),
                    "talon_interno": talon_interno or liq.talon_interno,
                    "liquidacion_id": int(liq.id),
                },
                "liquidacion": _serialize_liquidacion(liq),
                "detalles_count": len(detalles),
                "detalles": [_serialize_detalle(d) for d in detalles],
            }
        ), 200

    except Exception as e:
        return _err(f"Error consultando lo guardado: {e}", 500)