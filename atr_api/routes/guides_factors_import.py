# atr_api/routes/guides_factors_import.py
from __future__ import annotations

from flask import Blueprint, jsonify, request

from atr_api.errors import ApiError
from atr_api.models.guide_factor import GuideFactor
from atr_api.services.guides_factors_import_service import import_guide_factors_excel

bp = Blueprint("guides_factors_import", __name__)


def _get_mode() -> str:
    return (request.args.get("mode") or "dry_run").strip().lower()


def _get_replace() -> bool:
    v = (request.args.get("replace") or "").strip().lower()
    return v in ("1", "true", "t", "yes", "y", "si", "sí", "s")


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


def _serialize_factor(row: GuideFactor) -> dict:
    return {
        "id": row.id,
        "client_id": row.client_id,
        "carro": row.carro,
        "td": row.td,
        "kms": row.kms,
        "importe": float(row.importe) if row.importe is not None else None,
    }


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

    return jsonify(result), 200


@bp.get("/clients/<int:client_id>/guides/factors/import")
def review_guides_factors_import(client_id: int):
    """
    Revisa en BD los factores cargados para un cliente.

    Query params opcionales:
      - carro: filtra por carro exacto
      - td: filtra por tipo destino exacto
      - kms: filtra por kms exacto
      - limit: default 100
      - offset: default 0
    """
    carro = (request.args.get("carro") or "").strip().upper()
    td = (request.args.get("td") or "").strip().upper()
    kms_raw = (request.args.get("kms") or "").strip()
    limit = _get_limit()
    offset = _get_offset()

    q = GuideFactor.query.filter(GuideFactor.client_id == client_id)

    if carro:
        q = q.filter(GuideFactor.carro == carro)

    if td:
        q = q.filter(GuideFactor.td == td)

    if kms_raw:
        try:
            kms = int(kms_raw)
        except Exception:
            raise ApiError("kms debe ser entero.", status_code=400)
        q = q.filter(GuideFactor.kms == kms)

    total = q.count()

    rows = (
        q.order_by(
            GuideFactor.carro.asc(),
            GuideFactor.td.asc(),
            GuideFactor.kms.asc(),
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
                "carro": carro or None,
                "td": td or None,
                "kms": kms_raw or None,
                "limit": limit,
                "offset": offset,
            },
            "total": total,
            "count": len(rows),
            "items": [_serialize_factor(row) for row in rows],
        }
    ), 200