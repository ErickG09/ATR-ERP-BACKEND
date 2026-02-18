# atr_api/routes/liquidaciones_excel_import.py

from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request
from werkzeug.datastructures import FileStorage

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models.client import Client

from atr_api.services.liquidaciones_excel_import_service import import_liquidaciones_from_excel


bp = Blueprint(
    "liquidaciones_excel_import",
    __name__,
    url_prefix="/api/clients/<int:client_id>/liquidaciones",
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


@bp.post("/import-excel")
def import_excel(client_id: int):
    """
    Importa/valida un Excel de viajes (liquidaciones) basado en talón interno.

    Request:
      - Content-Type: multipart/form-data
      - file: (campo) "file" o "excel"
      - dry_run: query param o form field (opcional) => 1/0

    Response:
      {
        dry_run, total_rows, folios, rows_out, corrections, duplicates, errors,
        summary_by_folio, updated_counters
      }
    """
    _, err = _validate_client(client_id)
    if err:
        return err

    # dry_run: puede venir en query o form
    dry_run_raw = request.args.get("dry_run")
    if dry_run_raw is None:
        dry_run_raw = request.form.get("dry_run")

    dry_run = _parse_bool(dry_run_raw)
    dry_run = True if dry_run is None else bool(dry_run)

    # archivo: acepta "file" o "excel"
    fs: FileStorage | None = None
    if "file" in request.files:
        fs = request.files.get("file")
    elif "excel" in request.files:
        fs = request.files.get("excel")

    if not fs:
        return _err("Falta archivo Excel. Envía multipart/form-data con campo 'file' (o 'excel').", 400)

    filename = (fs.filename or "").lower()
    if filename and not (filename.endswith(".xlsx") or filename.endswith(".xlsm") or filename.endswith(".xltx") or filename.endswith(".xltm")):
        return _err("Formato inválido. Solo se acepta Excel .xlsx/.xlsm.", 400)

    try:
        result: Dict[str, Any] = import_liquidaciones_from_excel(
            client_id=int(client_id),
            file_storage=fs,
            dry_run=bool(dry_run),
        )
        return jsonify(result), 200

    except ApiError as e:
        # Errores controlados
        code = int(getattr(e, "status_code", 400) or 400)
        return _err(str(e), code)

    except Exception as e:
        return _err(f"Error inesperado importando Excel: {e}", 500)
