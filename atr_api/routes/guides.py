# atr_api/routes/guides.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Tuple

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models import Guide, Operator, Car, Destination
from atr_api.models.guide_convenio import GuideConvenio
from atr_api.models.guide_factor import GuideFactor
from atr_api.schemas.guide import sanitize_guide_payload, serialize_guide

bp = Blueprint("guides", __name__)

# --- helpers globales para consistencia ---


def _normalize_ct(v: str | None) -> str:
    return (v or "").strip().upper()


def _get_operator_global(operator_id: int) -> Operator:
    op = db.session.get(Operator, operator_id)
    if not op:
        raise ApiError("Operador inválido.", status_code=400)
    return op


def _get_car_global(car_id: int) -> Car:
    car = db.session.get(Car, car_id)
    if not car:
        raise ApiError("Carro inválido.", status_code=400)
    return car


def _get_destination_by_client(client_id: int, destination_id: int) -> Destination:
    dest = Destination.query.filter_by(client_id=client_id, id=destination_id).first()
    if not dest:
        raise ApiError("Destinatario inválido para este cliente.", status_code=400)
    return dest


def _enforce_operator_car_type_match(op: Operator, car: Car) -> str:
    op_ct = _normalize_ct(getattr(op, "tipo_carro", ""))
    car_ct = _normalize_ct(getattr(car, "tipo", ""))
    if not op_ct or not car_ct:
        raise ApiError("Operador/Carro sin tipo de carro asignado.", status_code=400)
    if op_ct != car_ct:
        raise ApiError(
            f"Tipo de carro no coincide: Operador={op_ct} vs Carro={car_ct}.",
            status_code=400,
        )
    return car_ct


def _bool_param(name: str) -> bool | None:
    v = request.args.get(name)
    if v is None:
        return None
    s = v.strip().lower()
    if s in ("1", "true", "t", "yes", "y", "si", "sí", "s"):
        return True
    if s in ("0", "false", "f", "no", "n"):
        return False
    return None


# -----------------------------------------------------------------------------
# Tarifa/kms auto (CONVENIO + FACTORES)
# -----------------------------------------------------------------------------
def _lookup_convenio(client_id: int, destination_codigo: str) -> GuideConvenio | None:
    codigo = (destination_codigo or "").strip().upper()
    if not codigo:
        return None
    return (
        GuideConvenio.query.filter_by(client_id=client_id, destination_codigo=codigo, activo=True)
        .limit(1)
        .first()
    )


def _lookup_factor(client_id: int, carro: str, td: str, kms: int) -> GuideFactor | None:
    carro = (carro or "").strip().upper()
    td = (td or "").strip().upper()
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


def _should_try_autocalc(data: Dict[str, Any], partial: bool) -> bool:
    """
    Regla:
      - Si el payload trae kms o tarifa explícitos => manual (NO autocalcular).
      - Si NO trae kms ni tarifa => intentamos autocalcular (si hay destination + car_type).
    En PATCH parcial, si no vienen, también podemos intentar autocalcular SOLO si cambió
    destination_id/car_id/car_type (lo controlamos afuera).
    """
    if "kms" in data or "tarifa" in data:
        return False
    return True


def _apply_destination_tax_defaults(dest: Destination, data: Dict[str, Any], *, partial: bool):
    """
    Si el usuario no envía flags/pcts, los tomamos del destinatario.
    No pisamos valores explícitos del payload.
    """
    if "aplica_iva" not in data:
        data["aplica_iva"] = bool(getattr(dest, "aplica_iva", False))
    if "iva_pct" not in data:
        data["iva_pct"] = float(getattr(dest, "iva_pct", 0) or 0)

    if "aplica_retencion" not in data:
        data["aplica_retencion"] = bool(getattr(dest, "aplica_retencion", False))
    if "retencion_pct" not in data:
        data["retencion_pct"] = float(getattr(dest, "retencion_pct", 0) or 0)


def _recalc_amounts(data: Dict[str, Any], *, existing: Guide | None = None) -> Dict[str, Any]:
    """
    Recalcula subtotal/iva/retención/total usando:
      - tarifa (obligatorio para cálculo; default 0)
      - carros (si existe; default 0)
      - aplica_iva + iva_pct
      - aplica_retencion + retencion_pct

    Nota: Aquí se asume que 'tarifa' representa un importe base por carro (muy común en tu UI legacy).
          subtotal = tarifa * carros (si carros > 0), si no subtotal = tarifa.
          Si en tu negocio 'tarifa' es total ya calculado, entonces carros=1 y funciona igual.
    """
    def _get_num(key: str, default: float = 0.0) -> Decimal:
        if key in data:
            return Decimal(str(data.get(key) or default))
        if existing is not None:
            return Decimal(str(getattr(existing, key, default) or default))
        return Decimal(str(default))

    def _get_bool(key: str, default: bool = False) -> bool:
        if key in data:
            return bool(data.get(key))
        if existing is not None:
            return bool(getattr(existing, key, default))
        return bool(default)

    tarifa = _get_num("tarifa", 0)
    carros = Decimal(str(int(data.get("carros", getattr(existing, "carros", 0) if existing else 0) or 0)))

    # subtotal base: tarifa * carros (si carros > 0), si no tarifa
    if carros > 0:
        subtotal = (tarifa * carros).quantize(Decimal("0.01"))
    else:
        subtotal = tarifa.quantize(Decimal("0.01"))

    aplica_iva = _get_bool("aplica_iva", False)
    iva_pct = _get_num("iva_pct", 0)
    iva_monto = Decimal("0.00")
    if aplica_iva and iva_pct > 0:
        iva_monto = (subtotal * (iva_pct / Decimal("100"))).quantize(Decimal("0.01"))

    aplica_ret = _get_bool("aplica_retencion", False)
    ret_pct = _get_num("retencion_pct", 0)
    ret_monto = Decimal("0.00")
    if aplica_ret and ret_pct > 0:
        ret_monto = (subtotal * (ret_pct / Decimal("100"))).quantize(Decimal("0.01"))

    total = (subtotal + iva_monto - ret_monto).quantize(Decimal("0.01"))

    data["subtotal"] = float(subtotal)
    data["iva_monto"] = float(iva_monto)
    data["retencion_monto"] = float(ret_monto)
    data["total"] = float(total)
    return data


def _ensure_kms_tarifa_present_on_create(data: Dict[str, Any]):
    """
    Para CREATE: si no se pudo autocalcular, exigimos que el usuario mande kms+tarifa.
    """
    if data.get("kms") is None or data.get("tarifa") is None:
        raise ApiError(
            "No se pudo autocalcular (faltó CONVENIO/FACTOR). "
            "Envía 'kms' y 'tarifa' manualmente para guardar la guía.",
            status_code=400,
        )


@bp.get("/clients/<int:client_id>/guides")
def list_guides(client_id: int):
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=50, type=int)
    per_page = min(max(per_page, 1), 200)

    q = Guide.query.filter_by(client_id=client_id)

    # filtros
    operator_id = request.args.get("operator_id", type=int)
    if operator_id:
        q = q.filter(Guide.operator_id == operator_id)

    destination_id = request.args.get("destination_id", type=int)
    if destination_id:
        q = q.filter(Guide.destination_id == destination_id)

    status = (request.args.get("status") or "").strip().lower()
    if status:
        q = q.filter(Guide.status == status)

    activo = _bool_param("activo")
    if activo is not None:
        q = q.filter(Guide.activo == activo)

    search = (request.args.get("search") or "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(Guide.folio.ilike(like))

    pagination = q.order_by(Guide.fecha.desc(), Guide.folio.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify(
        {
            "items": [serialize_guide(g) for g in pagination.items],
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        }
    )


@bp.get("/clients/<int:client_id>/guides/<int:guide_id>")
def get_guide(client_id: int, guide_id: int):
    g = Guide.query.filter_by(client_id=client_id, id=guide_id).limit(1).first()
    if not g:
        raise ApiError("Guía no encontrada.", status_code=404)
    return jsonify(serialize_guide(g))


@bp.post("/clients/<int:client_id>/guides")
def create_guide(client_id: int):
    json_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not json_data:
        raise ApiError("Se requiere un cuerpo JSON.", status_code=400)

    data = sanitize_guide_payload(json_data, partial=False)
    data["client_id"] = client_id

    # --- Validaciones FK consistentes ---
    op = _get_operator_global(data["operator_id"])

    dest_obj: Destination | None = None
    if data.get("destination_id") is not None:
        dest_obj = _get_destination_by_client(client_id, data["destination_id"])
        _apply_destination_tax_defaults(dest_obj, data, partial=False)

    # Carro global + regla de consistencia tipo
    if data.get("car_id") is not None:
        car = _get_car_global(data["car_id"])
        car_ct = _enforce_operator_car_type_match(op, car)
        data["car_type"] = car_ct  # fuerza car_type desde carro
    else:
        data["car_type"] = _normalize_ct(getattr(op, "tipo_carro", "")) or data.get("car_type", "")

    # --- Autocalcular kms/tarifa (si el payload NO trae kms/tarifa) ---
    if _should_try_autocalc(data, partial=False) and dest_obj is not None:
        convenio = _lookup_convenio(client_id, getattr(dest_obj, "codigo", ""))
        if convenio:
            factor = _lookup_factor(
                client_id,
                data.get("car_type", ""),
                getattr(convenio, "td", ""),
                int(getattr(convenio, "kms", 0) or 0),
            )
            if factor:
                data["kms"] = int(getattr(convenio, "kms", 0) or 0)
                data["tarifa"] = float(getattr(factor, "importe", 0) or 0)

    # Si no se pudo autocalcular, exigimos manual para CREATE
    _ensure_kms_tarifa_present_on_create(data)

    # Recalcula montos siempre (manual o auto)
    _recalc_amounts(data, existing=None)

    g = Guide(**data)

    try:
        db.session.add(g)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Ya existe una guía con ese folio para este cliente.", status_code=409)

    return jsonify(serialize_guide(g)), 201


@bp.patch("/clients/<int:client_id>/guides/<int:guide_id>")
def update_guide(client_id: int, guide_id: int):
    g = Guide.query.filter_by(client_id=client_id, id=guide_id).limit(1).first()
    if not g:
        raise ApiError("Guía no encontrada.", status_code=404)

    if g.status == "liquidated":
        raise ApiError("La guía está liquidada y no puede modificarse.", status_code=409)

    json_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not json_data:
        raise ApiError("Se requiere un cuerpo JSON.", status_code=400)

    data = sanitize_guide_payload(json_data, partial=True)

    # validar folio unique si cambia
    if "folio" in data and data["folio"] != g.folio:
        existing = (
            Guide.query.filter_by(client_id=client_id, folio=data["folio"])
            .with_entities(Guide.id)
            .first()
        )
        if existing:
            raise ApiError("Ya existe otra guía con ese folio.", status_code=409)

    # --- Validaciones FK consistentes (global) ---
    if "operator_id" in data and data["operator_id"] is not None:
        op = _get_operator_global(data["operator_id"])
    else:
        op = _get_operator_global(g.operator_id)

    # Destino (si cambia)
    dest_obj: Destination | None = None
    destination_changed = False
    if "destination_id" in data:
        destination_changed = True
        if data["destination_id"] is not None:
            dest_obj = _get_destination_by_client(client_id, data["destination_id"])
            _apply_destination_tax_defaults(dest_obj, data, partial=True)
        else:
            dest_obj = None
    else:
        # no cambió: usamos el actual si existe
        if g.destination_id is not None:
            dest_obj = _get_destination_by_client(client_id, g.destination_id)

    # Carro (si cambia)
    car_changed = False
    if "car_id" in data:
        car_changed = True
        if data["car_id"] is not None:
            car = _get_car_global(data["car_id"])
            car_ct = _enforce_operator_car_type_match(op, car)
            data["car_type"] = car_ct
        else:
            data["car_type"] = _normalize_ct(getattr(op, "tipo_carro", "")) or g.car_type
    else:
        # Si no cambia carro pero sí cambió operador, revalidar coherencia con el carro actual
        if ("operator_id" in data) and (g.car_id is not None):
            car = _get_car_global(g.car_id)
            car_ct = _enforce_operator_car_type_match(op, car)
            data["car_type"] = car_ct

    # --- Autocalcular kms/tarifa en PATCH SOLO si:
    #     - no vienen kms/tarifa en payload (manual gana)
    #     - y cambió destination/car/car_type (algo relevante)
    # ---
    if _should_try_autocalc(data, partial=True) and dest_obj is not None and (
        destination_changed or car_changed or ("car_type" in data)
    ):
        convenio = _lookup_convenio(client_id, getattr(dest_obj, "codigo", ""))
        if convenio:
            ct = data.get("car_type") or g.car_type
            factor = _lookup_factor(
                client_id,
                ct,
                getattr(convenio, "td", ""),
                int(getattr(convenio, "kms", 0) or 0),
            )
            if factor:
                data["kms"] = int(getattr(convenio, "kms", 0) or 0)
                data["tarifa"] = float(getattr(factor, "importe", 0) or 0)
        # Si no encuentra, NO forzamos error en PATCH (para no romper edición).
        # El usuario puede mandar kms/tarifa manuales en otra petición.

    # Recalcula montos:
    # - si viene tarifa/kms/carros o flags/pcts, recalculamos con data+existing
    # - si no viene nada relacionado, no tocamos montos
    touches_amounts = any(
        k in data
        for k in (
            "tarifa",
            "kms",
            "carros",
            "aplica_iva",
            "iva_pct",
            "aplica_retencion",
            "retencion_pct",
        )
    ) or ("tarifa" in data) or ("kms" in data)

    if touches_amounts:
        _recalc_amounts(data, existing=g)

    for k, v in data.items():
        setattr(g, k, v)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Error al actualizar la guía.", status_code=500)

    return jsonify(serialize_guide(g))


@bp.delete("/clients/<int:client_id>/guides/<int:guide_id>")
def delete_guide(client_id: int, guide_id: int):
    g = Guide.query.filter_by(client_id=client_id, id=guide_id).limit(1).first()
    if not g:
        raise ApiError("Guía no encontrada.", status_code=404)

    if g.status == "liquidated":
        raise ApiError("No puedes borrar una guía liquidada.", status_code=409)

    hard = (request.args.get("hard", "0").lower() in ("1", "true", "t", "yes", "y"))

    try:
        if hard:
            db.session.delete(g)
        else:
            g.activo = False
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Error al inactivar/eliminar la guía.", status_code=500)

    return jsonify({"status": "deleted" if hard else "inactivo", "id": g.id})