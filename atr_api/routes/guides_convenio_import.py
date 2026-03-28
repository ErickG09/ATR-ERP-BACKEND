# atr_api/routes/guides_convenio_import.py
from __future__ import annotations

from flask import Blueprint, jsonify, request

from atr_api.errors import ApiError
from atr_api.models.guide_convenio import GuideConvenio
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


def _get_limit() -> int:
    v = (request.args.get("limit") or "100").strip()
    try:
        n = int(v)
        if n < 1:
            return 1
        if n > 1000:
            return 1000
        return n
    except Exception:
        raise ApiError("limit debe ser entero.", status_code=400)


def _get_offset() -> int:
    v = (request.args.get("offset") or "0").strip()
    try:
        n = int(v)
        return 0 if n < 0 else n
    except Exception:
        raise ApiError("offset debe ser entero.", status_code=400)


def _serialize_convenio(row: GuideConvenio) -> dict:
    return {
        "id": row.id,
        "client_id": row.client_id,
        "destination_codigo": row.destination_codigo,
        "kms": row.kms,
        "td": row.td,
        "destinatario_nombre": row.destinatario_nombre,
        "ciudad": row.ciudad,
    }


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


@bp.get("/clients/<int:client_id>/guides/convenio/import")
def review_guides_convenio_import(client_id: int):
    """
    Revisa en BD los registros de convenio cargados para un cliente.

    Query params opcionales:
      - destination_codigo: filtra por código exacto
      - td: filtra por tipo destino exacto
      - limit: default 100
      - offset: default 0
    """
    destination_codigo = (request.args.get("destination_codigo") or "").strip()
    td = (request.args.get("td") or "").strip().upper()
    limit = _get_limit()
    offset = _get_offset()

    q = GuideConvenio.query.filter(GuideConvenio.client_id == client_id)

    if destination_codigo:
        q = q.filter(GuideConvenio.destination_codigo == destination_codigo)

    if td:
        q = q.filter(GuideConvenio.td == td)

    total = q.count()

    rows = (
        q.order_by(
            GuideConvenio.destination_codigo.asc(),
            GuideConvenio.kms.asc(),
            GuideConvenio.td.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return jsonify(
        {
            "ok": True,
            "client_id": client_id,
            "filters": {
                "destination_codigo": destination_codigo or None,
                "td": td or None,
                "limit": limit,
                "offset": offset,
            },
            "total": total,
            "count": len(rows),
            "items": [_serialize_convenio(row) for row in rows],
        }
    ), 200