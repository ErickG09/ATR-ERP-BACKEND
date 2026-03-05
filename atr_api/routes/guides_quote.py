# atr_api/routes/guides_quote.py
from __future__ import annotations

from flask import Blueprint, jsonify, request

from atr_api.errors import ApiError
from atr_api.models import Car, Destination
from atr_api.models.guide_convenio import GuideConvenio
from atr_api.models.guide_factor import GuideFactor
from atr_api.extensions import db

bp = Blueprint("guides_quote", __name__)


def _normalize(v: str | None) -> str:
    return (v or "").strip().upper()


def _get_destination_by_client(client_id: int, destination_id: int) -> Destination:
    dest = Destination.query.filter_by(client_id=client_id, id=destination_id).first()
    if not dest:
        raise ApiError("Destinatario inválido para este cliente.", status_code=400)
    return dest


def _get_car_global(car_id: int) -> Car:
    car = db.session.get(Car, car_id)
    if not car:
        raise ApiError("Carro inválido.", status_code=400)
    return car


def _lookup_convenio(client_id: int, destination_codigo: str) -> GuideConvenio | None:
    codigo = _normalize(destination_codigo)
    if not codigo:
        return None
    return (
        GuideConvenio.query.filter_by(
            client_id=client_id,
            destination_codigo=codigo,
            activo=True,
        )
        .limit(1)
        .first()
    )


def _lookup_factor(client_id: int, carro: str, td: str, kms: int) -> GuideFactor | None:
    carro = _normalize(carro)
    td = _normalize(td)
    return (
        GuideFactor.query.filter_by(
            client_id=client_id,
            carro=carro,
            td=td,
            kms=int(kms),
            activo=True,
        )
        .limit(1)
        .first()
    )


@bp.get("/clients/<int:client_id>/guides/quote")
def quote_guide(client_id: int):
    """
    Sugiere kms/td/tarifa basado en:
      - destination_id (obligatorio)
      - car_type (opcional) o car_id (opcional)

    Query:
      destination_id=<int>   (requerido)
      car_type=<str>         (opcional)
      car_id=<int>           (opcional)

    Devuelve:
      {
        "ok": bool,
        "destination_id": int,
        "destination_codigo": str|None,
        "car_type": str|None,
        "kms": int|None,
        "td": str|None,
        "tarifa": float|None,
        "found_convenio": bool,
        "found_factor": bool,
        "notes": [ ... ]
      }
    """
    destination_id = request.args.get("destination_id", type=int)
    if not destination_id:
        raise ApiError("destination_id es requerido.", status_code=400)

    car_id = request.args.get("car_id", type=int)
    car_type = _normalize(request.args.get("car_type"))

    if car_id and car_type:
        raise ApiError("Envía car_id o car_type, no ambos.", status_code=400)

    dest = _get_destination_by_client(client_id, destination_id)
    dest_codigo = _normalize(getattr(dest, "codigo", "")) or None

    # Derivar car_type si viene car_id
    if car_id:
        car = _get_car_global(car_id)
        car_type = _normalize(getattr(car, "tipo", ""))

    if not car_type:
        # se puede pedir quote solo de convenio (kms/td) sin factor
        car_type = None

    notes: list[str] = []
    kms: int | None = None
    td: str | None = None
    tarifa: float | None = None

    found_convenio = False
    found_factor = False

    convenio = None
    if dest_codigo:
        convenio = _lookup_convenio(client_id, dest_codigo)

    if convenio:
        found_convenio = True
        kms = int(getattr(convenio, "kms", 0) or 0)
        td = _normalize(getattr(convenio, "td", "")) or None
    else:
        notes.append(
            "No se encontró CONVENIO para este destinatario. "
            "Podrás capturar KMS/TD manualmente en la guía."
        )

    if car_type and td is not None and kms is not None:
        factor = _lookup_factor(client_id, car_type, td, kms)
        if factor:
            found_factor = True
            tarifa = float(getattr(factor, "importe", 0) or 0)
        else:
            notes.append(
                "No se encontró FACTOR para (car_type, TD, KMS). "
                "Podrás capturar TARIFA manualmente en la guía."
            )
    else:
        if not car_type:
            notes.append("No se proporcionó car_type/car_id: no se puede buscar FACTOR.")
        if td is None or kms is None:
            notes.append("Sin convenio (TD/KMS), no se puede buscar FACTOR.")

    ok = found_convenio and found_factor

    return jsonify(
        {
            "ok": ok,
            "destination_id": destination_id,
            "destination_codigo": dest_codigo,
            "car_type": car_type,
            "kms": kms,
            "td": td,
            "tarifa": tarifa,
            "found_convenio": found_convenio,
            "found_factor": found_factor,
            "notes": notes,
        }
    )