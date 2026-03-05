# atr_api/routes/guides_factors_import.py
from __future__ import annotations

from flask import Blueprint, jsonify, request

from atr_api.errors import ApiError
from atr_api.services.guides_factors_import_service import import_guide_factors_excel

bp = Blueprint("guides_factors_import", __name__)


def _get_mode() -> str:
    return (request.args.get("mode") or "dry_run").strip().lower()


def _get_replace() -> bool:
    v = (request.args.get("replace") or "").strip().lower()
    return v in ("1", "true", "t", "yes", "y", "si", "sí", "s")


@bp.post("/clients/<int:client_id>/guides/factors/import")
def import_guides_factors(client_id: int):
    """
    Importa FACTORES (tarifas) desde Excel.

    Query params:
      - mode: dry_run | import
      - replace: 1|true => borra todo lo del cliente y vuelve a cargar

    Body:
      multipart/form-data con field: file
    """
    mode = _get_mode()
    replace = _get_replace()

    file = request.files.get("file")
    if not file:
        raise ApiError("Archivo requerido en form-data (field: file).", status_code=400)

    result = import_guide_factors_excel(
        client_id=client_id,
        file=file,
        mode=mode,
        replace=replace,
    )

    # Si es preview con errores, regresamos 200 con ok=false (más fácil para UI)
    return jsonify(result), 200