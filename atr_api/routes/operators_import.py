from __future__ import annotations

from flask import Blueprint, jsonify, request

from atr_api.errors import ApiError
from atr_api.services.operators_excel_import_service import import_operators_from_excel

bp = Blueprint("operators_import", __name__)


@bp.post("/clients/<int:client_id>/operators/import-excel")
def import_operators_excel(client_id: int):
    """
    Importa operadores desde un Excel.

    Form-data:
      - file: .xlsx

    Query params:
      - dry_run=1: valida pero no escribe en DB
      - upsert_by_name=1: si existe nombre igual, actualiza (fallback cuando NO hay código)
    """
    dry_run = request.args.get("dry_run", "0").lower() in ("1", "true", "t", "yes", "y")
    upsert_by_name = request.args.get("upsert_by_name", "0").lower() in (
        "1",
        "true",
        "t",
        "yes",
        "y",
    )

    if "file" not in request.files:
        raise ApiError("Falta el archivo. Manda form-data con campo 'file'.", status_code=400)

    f = request.files["file"]
    if not f or not f.filename:
        raise ApiError("Archivo inválido.", status_code=400)

    filename = (f.filename or "").lower()
    if not filename.endswith(".xlsx"):
        raise ApiError("Solo se acepta .xlsx", status_code=400)

    result = import_operators_from_excel(
        client_id=client_id,
        file_storage=f,
        dry_run=dry_run,
        upsert_by_name=upsert_by_name,
    )
    return jsonify(result), 200
