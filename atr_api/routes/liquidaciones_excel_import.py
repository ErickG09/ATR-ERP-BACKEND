# atr_api/routes/liquidaciones_excel_import.py

from __future__ import annotations

from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request
from werkzeug.datastructures import FileStorage

from atr_api.errors import ApiError
from atr_api.extensions import db
from atr_api.models.client import Client
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

    # soporta tu UI (modo)
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
    Validación ligera por extensión (evita errores comunes).
    """
    name = (filename or "").strip().lower()
    if not name:
        return

    allowed = (".xlsx", ".xlsm", ".xltx", ".xltm")
    if not name.endswith(allowed):
        raise ApiError("Formato inválido. Solo se acepta Excel .xlsx/.xlsm.", status_code=400)


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

    # leer inputs (query tiene prioridad sobre form)
    mode_raw = request.args.get("mode")
    dry_run_raw = request.args.get("dry_run")

    if mode_raw is None:
        mode_raw = request.form.get("mode")
    if dry_run_raw is None:
        dry_run_raw = request.form.get("dry_run")

    # prioridad: mode si viene, si no dry_run
    val = mode_raw if mode_raw is not None else dry_run_raw
    dry_run = _parse_bool(val)

    # default: True
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