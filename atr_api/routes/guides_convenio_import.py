# atr_api/routes/guides_convenio_import.py
from __future__ import annotations

from flask import Blueprint, jsonify, request

from atr_api.errors import ApiError
from atr_api.services.guides_convenio_import_service import import_guide_convenio_excel

bp = Blueprint("guides_convenio_import", __name__)


def _get_mode() -> str:
    return (request.args.get("mode") or "dry_run").strip().lower()


def _get_replace() -> bool:
    v = (request.args.get("replace") or "").strip().lower()
    return v in ("1", "true", "t", "yes", "y", "si", "sí", "s")


def _get_codigo_pad_left() -> int:
    """
    padding para códigos numéricos (1 -> 0001).
    default 4.
    """
    v = (request.args.get("codigo_pad_left") or "").strip()
    if not v:
        return 4
    try:
        n = int(v)
        return 0 if n < 0 else n
    except Exception:
        raise ApiError("codigo_pad_left debe ser entero.", status_code=400)


@bp.post("/clients/<int:client_id>/guides/convenio/import")
def import_guides_convenio(client_id: int):
    """
    Importa CONVENIO desde Excel.

    Query params:
      - mode: dry_run | import
      - replace: 1|true => borra todo lo del cliente y vuelve a cargar
      - codigo_pad_left: entero (default 4)

    Body:
      multipart/form-data con field: file
    """
    mode = _get_mode()
    replace = _get_replace()
    codigo_pad_left = _get_codigo_pad_left()

    file = request.files.get("file")
    if not file:
        raise ApiError("Archivo requerido en form-data (field: file).", status_code=400)

    result = import_guide_convenio_excel(
        client_id=client_id,
        file=file,
        mode=mode,
        replace=replace,
        codigo_pad_left=codigo_pad_left,
    )

    return jsonify(result), 200