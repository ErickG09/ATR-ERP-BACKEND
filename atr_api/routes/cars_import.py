from __future__ import annotations

from flask import Blueprint, jsonify, request

from atr_api.errors import ApiError
from atr_api.services.cars_excel_import_service import import_cars_from_excel


bp = Blueprint("cars_import", __name__)


@bp.post("/clients/<int:client_id>/cars/import-excel")
def import_cars_excel(client_id: int):
    """
    Importa unidades (cars) desde un Excel.

    Form-data:
      - file: .xlsx

    Query params:
      - dry_run=1: valida pero no escribe en DB
      - upsert_by_code=1: si existe el mismo código, actualiza
    """
    dry_run = request.args.get("dry_run", "0").lower() in ("1", "true", "t", "yes", "y")
    upsert_by_code = request.args.get("upsert_by_code", "0").lower() in ("1", "true", "t", "yes", "y")

    if "file" not in request.files:
        raise ApiError("Falta el archivo. Manda form-data con campo 'file'.", status_code=400)

    f = request.files["file"]
    if not f or not f.filename:
        raise ApiError("Archivo inválido.", status_code=400)

    filename = (f.filename or "").lower()
    if not filename.endswith(".xlsx"):
        raise ApiError("Solo se acepta .xlsx", status_code=400)

    result = import_cars_from_excel(
        client_id=client_id,
        file_storage=f,
        dry_run=dry_run,
        upsert_by_code=upsert_by_code,
    )
    return jsonify(result), 200
