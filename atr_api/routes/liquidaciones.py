# atr_api/routes/liquidaciones.py

from datetime import date, datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from atr_api.extensions import db
from atr_api.errors import ApiError

from atr_api.models.liquidacion import Liquidacion, LIQ_STATUS_CHOICES
from atr_api.models.liquidacion_deduccion import LiquidacionDeduccion
from atr_api.models.liquidacion_anticipo import LiquidacionAnticipo  # ✅ NUEVO
from atr_api.models.client_counter import ClientCounter

from atr_api.models.operator import Operator
from atr_api.models.car import Car
from atr_api.models.destination import Destination
from atr_api.models.client import Client


liquidaciones_bp = Blueprint(
    "liquidaciones",
    __name__,
    url_prefix="/api/clients/<int:client_id>/liquidaciones",
)

# ---------------- helpers ----------------

# keys predefinidas (las “fijas” que tendrás en UI, incluyendo las nuevas)
# NOTA: "impuestos" se calcula automáticamente (6%) y el backend lo "upsertea".
PRESET_DED_KEYS = {
    "ayuda_escolar": "Ayuda escolar",
    "impuestos": "Impuestos",
    "infonavit": "Infonavit",
    "sindicato": "Sindicato",
    "imss": "IMSS",
    "fonacot": "FONACOT",
    "pension_alimenticia": "Pensión alimenticia",
}


def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


def _normalize_ct(v: str | None) -> str:
    return (v or "").strip().upper()


def _parse_bool(v):
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


def _parse_date_yyyy_mm_dd(v: str):
    if not v:
        return None
    try:
        return datetime.strptime(v.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _num(v, default=0.0):
    if v is None:
        return default
    try:
        s = str(v).strip().replace(",", ".")
        return float(s)
    except Exception:
        return default


def _validate_client(client_id: int):
    c = db.session.get(Client, client_id)
    if not c:
        return None, _err("Cliente no válido.", 400)
    return c, None


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
    dest = db.session.get(Destination, destination_id)
    if not dest or int(dest.client_id) != int(client_id):
        raise ApiError("Destino inválido para este cliente.", status_code=400)
    return dest


def _enforce_operator_car_type_match(op: Operator, car: Car) -> str:
    """
    Regla CLAVE: El tipo del operador (tipo_carro) debe coincidir con el tipo del carro (tipo).
    Si falta alguno, fallamos para no guardar inconsistencias.
    """
    op_ct = _normalize_ct(getattr(op, "tipo_carro", ""))
    car_ct = _normalize_ct(getattr(car, "tipo", ""))

    if not op_ct:
        raise ApiError("Operador sin tipo de carro asignado.", status_code=400)
    if not car_ct:
        raise ApiError("Carro sin tipo asignado.", status_code=400)
    if op_ct != car_ct:
        raise ApiError(
            f"Tipo de carro no coincide: Operador={op_ct} vs Carro={car_ct}.",
            status_code=400,
        )
    return car_ct


def _derive_car_type(op: Operator, car: Car | None) -> str:
    """
    Define el car_type final:
    - Si hay carro: viene del carro (pero validado contra operador)
    - Si no hay carro: viene del operador
    """
    if car is not None:
        return _enforce_operator_car_type_match(op, car)

    op_ct = _normalize_ct(getattr(op, "tipo_carro", ""))
    if not op_ct:
        raise ApiError("Operador sin tipo de carro asignado.", status_code=400)
    return op_ct


def _validate_fk_belongs(client_id: int, operator_id: int, car_id, destination_id):
    """
    Operador y Carro: globales (solo existen).
    Destino: pertenece al cliente.
    Además calcula car_type_final de forma consistente.
    """
    try:
        op = _get_operator_global(operator_id)

        car = None
        if car_id is not None:
            car = _get_car_global(car_id)

        dest = None
        if destination_id is not None:
            dest = _get_destination_by_client(client_id, destination_id)

        car_type_final = _derive_car_type(op, car)

        return op, car, dest, car_type_final, None

    except ApiError as e:
        return None, None, None, None, _err(str(e), e.status_code or 400)


def _norm_key(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    if not s:
        return None
    # normaliza espacios a _
    s = "_".join(s.split())
    return s


def _validate_operator_slot(v) -> int:
    try:
        slot = int(v)
    except Exception:
        raise ApiError("operator_slot inválido.", status_code=400)
    if slot not in (1, 2):
        raise ApiError("operator_slot debe ser 1 o 2.", status_code=400)
    return slot


def _validate_deduccion_payload(item: dict, allow_id: bool = False):
    """
    Retorna (ded_id, slot, key, label, monto) con validaciones estrictas.
    - operator_slot: 1 o 2
    - monto: >= 0
    - label: obligatorio (si no viene y key es preset, se infiere)
    - key: opcional
    """
    if not isinstance(item, dict):
        raise ApiError("Deducción inválida (debe ser objeto).", status_code=400)

    ded_id = None
    if allow_id and "id" in item:
        try:
            ded_id = int(item.get("id"))
        except Exception:
            raise ApiError("Deducción id inválido.", status_code=400)

    slot = _validate_operator_slot(item.get("operator_slot", 1))

    key = _norm_key(item.get("key"))
    label = (item.get("label") or "").strip()

    # si es preset y no mandan label, lo inferimos
    if (not label) and key and key in PRESET_DED_KEYS:
        label = PRESET_DED_KEYS[key]

    if not label:
        raise ApiError("Deducción requiere 'label'.", status_code=400)

    if len(label) > 120:
        raise ApiError("Deducción 'label' demasiado largo (máx 120).", status_code=400)

    monto = _num(item.get("monto"), None)
    if monto is None or not isinstance(monto, (int, float)):
        raise ApiError("Deducción 'monto' inválido.", status_code=400)

    if monto < 0:
        raise ApiError("Deducción 'monto' no puede ser negativa.", status_code=400)

    return ded_id, slot, key, label, round(float(monto), 2)


def _validate_anticipo_payload(item: dict):
    """
    Retorna (slot, importe, recibo) con validaciones estrictas.
    """
    if not isinstance(item, dict):
        raise ApiError("Anticipo inválido (debe ser objeto).", status_code=400)

    slot = _validate_operator_slot(item.get("operator_slot", 1))

    importe = _num(item.get("importe"), None)
    if importe is None or not isinstance(importe, (int, float)):
        raise ApiError("Anticipo 'importe' inválido.", status_code=400)
    if float(importe) < 0:
        raise ApiError("Anticipo 'importe' no puede ser negativo.", status_code=400)

    recibo = (item.get("recibo") or "").strip() or None
    if recibo and len(recibo) > 64:
        raise ApiError("Anticipo 'recibo' demasiado largo (máx 64).", status_code=400)

    return slot, round(float(importe), 2), recibo


def _serialize_deduccion(d: LiquidacionDeduccion):
    return {
        "id": d.id,
        "operator_slot": int(getattr(d, "operator_slot", 1) or 1),
        "key": d.key,
        "label": d.label,
        "monto": float(d.monto or 0),
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _serialize_anticipo(a: LiquidacionAnticipo):
    return {
        "id": a.id,
        "operator_slot": int(getattr(a, "operator_slot", 1) or 1),
        "operator_id": int(a.operator_id) if a.operator_id else None,
        "importe": float(a.importe or 0),
        "recibo": a.recibo,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _serialize(liq: Liquidacion):
    # fuerza recálculo “in-memory” por si hay cambios cargados
    try:
        liq.recalc_totals()
    except Exception:
        pass

    return {
        "id": liq.id,
        "client_id": liq.client_id,
        "folio_num": liq.folio_num,
        "folio": liq.folio,
        "fecha": liq.fecha.isoformat() if liq.fecha else None,

        "operator_id": liq.operator_id,
        "operator2_id": getattr(liq, "operator2_id", None),

        "car_id": liq.car_id,
        "destination_id": liq.destination_id,
        "car_type": liq.car_type,

        "kms": float(liq.kms or 0),
        "tarifa": float(liq.tarifa or 0),
        "subtotal": float(liq.subtotal or 0),

        "aplica_iva": bool(liq.aplica_iva),
        "iva_pct": float(liq.iva_pct or 0),
        "iva_monto": float(liq.iva_monto or 0),

        "aplica_retencion": bool(liq.aplica_retencion),
        "retencion_pct": float(liq.retencion_pct or 0),
        "retencion_monto": float(liq.retencion_monto or 0),

        "total": float(liq.total or 0),

        # snapshots + extras por operador
        "sueldo_base_op1": float(getattr(liq, "sueldo_base_op1", 0) or 0),
        "viaticos_base_op1": float(getattr(liq, "viaticos_base_op1", 0) or 0),
        "sueldo_base_op2": float(getattr(liq, "sueldo_base_op2", 0) or 0),
        "viaticos_base_op2": float(getattr(liq, "viaticos_base_op2", 0) or 0),

        "maniobra_op1": float(getattr(liq, "maniobra_op1", 0) or 0),
        "maniobra_op2": float(getattr(liq, "maniobra_op2", 0) or 0),
        "otros_ingresos_op1": float(getattr(liq, "otros_ingresos_op1", 0) or 0),
        "otros_ingresos_op2": float(getattr(liq, "otros_ingresos_op2", 0) or 0),

        # cálculo por operador (incluye impuestos 6% como deducción automática)
        "impuestos_op1": float(getattr(liq, "impuestos_op1", 0) or 0),
        "impuestos_op2": float(getattr(liq, "impuestos_op2", 0) or 0),

        "deducciones_total_op1": float(getattr(liq, "deducciones_total_op1", 0) or 0),
        "deducciones_total_op2": float(getattr(liq, "deducciones_total_op2", 0) or 0),

        "anticipos_total_op1": float(getattr(liq, "anticipos_total_op1", 0) or 0),
        "anticipos_total_op2": float(getattr(liq, "anticipos_total_op2", 0) or 0),

        "neto_op1": float(getattr(liq, "neto_op1", 0) or 0),
        "neto_op2": float(getattr(liq, "neto_op2", 0) or 0),

        "pago_final_op1": float(getattr(liq, "pago_final_op1", 0) or 0),
        "pago_final_op2": float(getattr(liq, "pago_final_op2", 0) or 0),
        "pago_final_total": float(getattr(liq, "pago_final_total", 0) or 0),

        # compatibilidad anterior
        "deducciones_total": float(liq.deducciones_total or 0),
        "neto_operador": float(liq.neto_operador or 0),

        # detalle
        "deducciones": [_serialize_deduccion(d) for d in (liq.deducciones or [])],
        "anticipos": [_serialize_anticipo(a) for a in (getattr(liq, "anticipos", None) or [])],

        "status": liq.status,
        "observaciones": liq.observaciones,
        "activo": bool(liq.activo),

        "created_at": liq.created_at.isoformat() if liq.created_at else None,
        "updated_at": liq.updated_at.isoformat() if liq.updated_at else None,

        "pagado": bool(liq.pagado),
        "pagado_at": liq.pagado_at.isoformat() if liq.pagado_at else None,
    }


def _get_or_init_counter_locked(client_id: int) -> ClientCounter:
    ctr = (
        db.session.query(ClientCounter)
        .filter(ClientCounter.client_id == client_id)
        .with_for_update()
        .one_or_none()
    )
    if not ctr:
        ctr = ClientCounter(client_id=client_id, liquidacion_folio_seq=0)
        db.session.add(ctr)
        db.session.flush()
        ctr = (
            db.session.query(ClientCounter)
            .filter(ClientCounter.client_id == client_id)
            .with_for_update()
            .one()
        )
    return ctr


def _allocate_next_folio(client_id: int) -> tuple[int, str]:
    ctr = _get_or_init_counter_locked(client_id)
    ctr.liquidacion_folio_seq = int(ctr.liquidacion_folio_seq) + 1
    folio_num = int(ctr.liquidacion_folio_seq)
    folio = Liquidacion.format_folio(folio_num)
    return folio_num, folio


def _load_liq_full(client_id: int, liq_id: int) -> Liquidacion | None:
    """
    Carga liquidación con deducciones y anticipos.
    """
    return (
        db.session.query(Liquidacion)
        .options(
            selectinload(Liquidacion.deducciones),
            selectinload(Liquidacion.anticipos),
        )
        .filter(Liquidacion.id == liq_id, Liquidacion.client_id == client_id)
        .one_or_none()
    )


# ---------------- endpoints ----------------

@liquidaciones_bp.get("/next-folio")
def next_folio(client_id: int):
    _, err = _validate_client(client_id)
    if err:
        return err

    ctr = db.session.query(ClientCounter).filter(ClientCounter.client_id == client_id).one_or_none()
    nxt = (ctr.liquidacion_folio_seq if ctr else 0) + 1
    return jsonify({"folio_num": int(nxt), "folio": Liquidacion.format_folio(int(nxt))})


@liquidaciones_bp.get("")
def list_liquidaciones(client_id: int):
    _, err = _validate_client(client_id)
    if err:
        return err

    page = int(request.args.get("page", 1) or 1)
    per_page = int(request.args.get("per_page", 50) or 50)
    per_page = max(1, min(per_page, 500))

    operator_id = request.args.get("operator_id")
    destination_id = request.args.get("destination_id")
    status = request.args.get("status")
    activo = _parse_bool(request.args.get("activo"))
    search = (request.args.get("search") or "").strip()

    q = (
        db.session.query(Liquidacion)
        .options(
            selectinload(Liquidacion.deducciones),
            selectinload(Liquidacion.anticipos),
        )
        .filter(Liquidacion.client_id == client_id)
    )

    if operator_id:
        try:
            q = q.filter(Liquidacion.operator_id == int(operator_id))
        except Exception:
            return _err("operator_id inválido.", 400)

    if destination_id:
        try:
            q = q.filter(Liquidacion.destination_id == int(destination_id))
        except Exception:
            return _err("destination_id inválido.", 400)

    if status:
        if status not in LIQ_STATUS_CHOICES:
            return _err("status inválido.", 400)
        q = q.filter(Liquidacion.status == status)

    if activo is not None:
        q = q.filter(Liquidacion.activo == activo)

    if search:
        like = f"%{search.lower()}%"
        q = q.filter(
            or_(
                Liquidacion.folio.ilike(like),
                Liquidacion.car_type.ilike(like),
            )
        )

    q = q.order_by(Liquidacion.fecha.desc(), Liquidacion.id.desc())

    total = q.count()
    pages = (total + per_page - 1) // per_page

    items = q.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        "items": [_serialize(x) for x in items],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
    })


@liquidaciones_bp.post("")
def create_liquidacion(client_id: int):
    _, err = _validate_client(client_id)
    if err:
        return err

    body = request.get_json(silent=True) or {}

    fecha_in = (body.get("fecha") or "").strip()

    operator_id = body.get("operator_id")
    operator2_id = body.get("operator2_id", None)

    car_id = body.get("car_id", None)
    destination_id = body.get("destination_id", None)

    if operator_id is None:
        return _err("operator_id es obligatorio.", 400)

    try:
        operator_id = int(operator_id)
    except Exception:
        return _err("operator_id inválido.", 400)

    try:
        operator2_id = None if operator2_id in ("", None) else int(operator2_id)
    except Exception:
        return _err("operator2_id inválido.", 400)

    if operator2_id is not None and int(operator2_id) == int(operator_id):
        return _err("operator2_id no puede ser igual a operator_id.", 400)

    try:
        car_id = None if car_id in ("", None) else int(car_id)
    except Exception:
        return _err("car_id inválido.", 400)

    try:
        destination_id = None if destination_id in ("", None) else int(destination_id)
    except Exception:
        return _err("destination_id inválido.", 400)

    # car_type se deriva con operador principal y carro
    _, _, _, car_type_final, err_fk = _validate_fk_belongs(
        client_id, operator_id, car_id, destination_id
    )
    if err_fk:
        return err_fk

    # Validar existencia de operadores (op2 solo existencia)
    try:
        op1 = _get_operator_global(operator_id)
        op2 = _get_operator_global(operator2_id) if operator2_id is not None else None
    except ApiError as e:
        return _err(str(e), e.status_code or 400)

    fecha = _parse_date_yyyy_mm_dd(fecha_in) if fecha_in else date.today()
    if not fecha:
        return _err("Fecha inválida. Usa YYYY-MM-DD.", 400)

    kms = _num(body.get("kms"), 0.0)
    tarifa = _num(body.get("tarifa"), 0.0)

    if kms < 0:
        return _err("Kms inválidos.", 400)
    if tarifa < 0:
        return _err("Tarifa inválida.", 400)

    aplica_iva = bool(body.get("aplica_iva") is True)
    iva_pct = _num(body.get("iva_pct"), 16.0 if aplica_iva else 0.0)

    aplica_ret = bool(body.get("aplica_retencion") is True)
    ret_pct = _num(body.get("retencion_pct"), 0.0)

    if aplica_iva and (iva_pct < 0 or iva_pct > 100):
        return _err("IVA % inválido (0 a 100).", 400)
    if aplica_ret and (ret_pct < 0 or ret_pct > 100):
        return _err("Retención % inválido (0 a 100).", 400)

    status = (body.get("status") or "draft").strip().lower()
    if status not in LIQ_STATUS_CHOICES:
        return _err("status inválido.", 400)

    observaciones = body.get("observaciones")
    observaciones = (observaciones.strip() if isinstance(observaciones, str) else None) or None

    activo = body.get("activo")
    activo = True if activo is None else bool(activo)

    # NO permitir car_type manual (se deriva siempre)
    if "car_type" in body and (body.get("car_type") not in (None, "", car_type_final)):
        return _err("No envíes 'car_type'. Se calcula automáticamente desde operador/carro.", 400)

    # extras por operador (opcionales)
    maniobra_op1 = _num(body.get("maniobra_op1"), 0.0)
    maniobra_op2 = _num(body.get("maniobra_op2"), 0.0)
    otros_op1 = _num(body.get("otros_ingresos_op1"), 0.0)
    otros_op2 = _num(body.get("otros_ingresos_op2"), 0.0)
    if min(maniobra_op1, maniobra_op2, otros_op1, otros_op2) < 0:
        return _err("Maniobra/otros ingresos no pueden ser negativos.", 400)

    # deducciones opcionales
    ded_list = body.get("deducciones") or []
    if not isinstance(ded_list, list):
        return _err("deducciones debe ser una lista.", 400)

    # anticipos opcionales
    ant_list = body.get("anticipos") or []
    if not isinstance(ant_list, list):
        return _err("anticipos debe ser una lista.", 400)

    try:
        folio_num, folio_auto = _allocate_next_folio(client_id)

        liq = Liquidacion(
            client_id=client_id,
            folio_num=folio_num,
            folio=folio_auto,
            fecha=fecha,

            operator_id=operator_id,
            operator2_id=operator2_id,

            car_id=car_id,
            destination_id=destination_id,
            car_type=car_type_final,

            kms=round(kms, 2),
            tarifa=tarifa,

            aplica_iva=aplica_iva,
            iva_pct=iva_pct if aplica_iva else 0,
            aplica_retencion=aplica_ret,
            retencion_pct=ret_pct if aplica_ret else 0,

            status=status,
            observaciones=observaciones,
            activo=activo,

            # snapshots (op1 usa sueldo_op_1/viaticos_op_1; op2 usa sueldo_op_2/viaticos_op_2)
            sueldo_base_op1=round(float(getattr(op1, "sueldo_op_1", 0) or 0), 2),
            viaticos_base_op1=round(float(getattr(op1, "viaticos_op_1", 0) or 0), 2),

            sueldo_base_op2=round(float(getattr(op2, "sueldo_op_2", 0) or 0), 2) if op2 else 0,
            viaticos_base_op2=round(float(getattr(op2, "viaticos_op_2", 0) or 0), 2) if op2 else 0,

            maniobra_op1=round(maniobra_op1, 2),
            maniobra_op2=round(maniobra_op2, 2),
            otros_ingresos_op1=round(otros_op1, 2),
            otros_ingresos_op2=round(otros_op2, 2),
        )

        # insertar deducciones (permitimos, excepto impuestos: el backend lo recalcula)
        for item in ded_list:
            _, slot, key, label, monto = _validate_deduccion_payload(item, allow_id=False)

            if slot == 2 and operator2_id is None:
                return _err("No puedes mandar deducciones operator_slot=2 sin operator2_id.", 400)

            # si mandan impuestos manual, lo ignoramos (se recalcula)
            if key == "impuestos":
                continue

            liq.deducciones.append(
                LiquidacionDeduccion(
                    operator_slot=slot,
                    key=key,
                    label=label,
                    monto=monto,
                )
            )

        # insertar anticipos
        for item in ant_list:
            slot, importe, recibo = _validate_anticipo_payload(item)

            if slot == 2 and operator2_id is None:
                return _err("No puedes mandar anticipos operator_slot=2 sin operator2_id.", 400)

            snap_op_id = operator_id if slot == 1 else operator2_id

            liq.anticipos.append(
                LiquidacionAnticipo(
                    operator_slot=slot,
                    operator_id=snap_op_id,
                    importe=importe,
                    recibo=recibo,
                )
            )

        liq.recalc_totals()

        db.session.add(liq)
        db.session.flush()

        created = _serialize(liq)

        db.session.commit()
        return jsonify(created), 201

    except ApiError as e:
        db.session.rollback()
        return _err(str(e), e.status_code or 400)
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo crear la liquidación. {str(e)}", 400)


@liquidaciones_bp.get("/<int:liq_id>")
def get_liquidacion(client_id: int, liq_id: int):
    _, err = _validate_client(client_id)
    if err:
        return err

    liq = _load_liq_full(client_id, liq_id)
    if not liq:
        return _err("Liquidación no encontrada.", 404)

    return jsonify(_serialize(liq))


@liquidaciones_bp.patch("/<int:liq_id>")
def update_liquidacion(client_id: int, liq_id: int):
    _, err = _validate_client(client_id)
    if err:
        return err

    body = request.get_json(silent=True) or {}

    liq = _load_liq_full(client_id, liq_id)
    if not liq:
        return _err("Liquidación no encontrada.", 404)

    # ✅ Pago (FIX: body ya existe)
    if "pagado" in body:
        liq.pagado = bool(body.get("pagado"))
        liq.pagado_at = datetime.utcnow() if liq.pagado else None

    # Bloquear car_type manual
    if "car_type" in body:
        return _err("No envíes 'car_type'. Se calcula automáticamente desde operador/carro.", 400)

    # Fecha
    if "fecha" in body:
        dt = _parse_date_yyyy_mm_dd(body.get("fecha") or "")
        if not dt:
            return _err("Fecha inválida. Usa YYYY-MM-DD.", 400)
        liq.fecha = dt

    # Destino (pertenece al cliente)
    if "destination_id" in body:
        raw = body.get("destination_id")
        try:
            did = None if raw in ("", None) else int(raw)
        except Exception:
            return _err("destination_id inválido.", 400)

        if did is not None:
            try:
                _get_destination_by_client(client_id, did)
            except ApiError as e:
                return _err(str(e), e.status_code or 400)

        liq.destination_id = did

    # Cambios potenciales de operador/carro (car_type depende de operador principal)
    operator_changed = "operator_id" in body
    car_changed = "car_id" in body
    operator2_changed = "operator2_id" in body

    # Resolver operador principal final
    if operator_changed:
        try:
            op_id = int(body.get("operator_id"))
        except Exception:
            return _err("operator_id inválido.", 400)
        try:
            op_final = _get_operator_global(op_id)
        except ApiError as e:
            return _err(str(e), e.status_code or 400)
        liq.operator_id = op_id
        # refrescar snapshots op1
        liq.sueldo_base_op1 = round(float(getattr(op_final, "sueldo_op_1", 0) or 0), 2)
        liq.viaticos_base_op1 = round(float(getattr(op_final, "viaticos_op_1", 0) or 0), 2)
    else:
        op_final = db.session.get(Operator, liq.operator_id)
        if not op_final:
            return _err("Operador inválido.", 400)

    # Resolver operador 2 final
    op2_final = None
    if operator2_changed:
        raw = body.get("operator2_id")
        try:
            op2_id = None if raw in ("", None) else int(raw)
        except Exception:
            return _err("operator2_id inválido.", 400)

        if op2_id is not None and int(op2_id) == int(liq.operator_id):
            return _err("operator2_id no puede ser igual a operator_id.", 400)

        if op2_id is not None:
            try:
                op2_final = _get_operator_global(op2_id)
            except ApiError as e:
                return _err(str(e), e.status_code or 400)

        liq.operator2_id = op2_id

        if op2_final:
            liq.sueldo_base_op2 = round(float(getattr(op2_final, "sueldo_op_2", 0) or 0), 2)
            liq.viaticos_base_op2 = round(float(getattr(op2_final, "viaticos_op_2", 0) or 0), 2)
        else:
            # si se elimina op2, limpiar snapshots y renglones slot 2
            liq.sueldo_base_op2 = 0
            liq.viaticos_base_op2 = 0
            liq.maniobra_op2 = 0
            liq.otros_ingresos_op2 = 0

            liq.deducciones = [
                d for d in (liq.deducciones or [])
                if int(getattr(d, "operator_slot", 1) or 1) != 2
            ]
            liq.anticipos = [
                a for a in (liq.anticipos or [])
                if int(getattr(a, "operator_slot", 1) or 1) != 2
            ]
    else:
        if getattr(liq, "operator2_id", None):
            op2_final = db.session.get(Operator, liq.operator2_id)

    # Resolver carro final
    if car_changed:
        raw = body.get("car_id")
        try:
            car_id = None if raw in ("", None) else int(raw)
        except Exception:
            return _err("car_id inválido.", 400)

        if car_id is not None:
            try:
                car_final = _get_car_global(car_id)
            except ApiError as e:
                return _err(str(e), e.status_code or 400)
        else:
            car_final = None

        liq.car_id = car_id
    else:
        car_final = db.session.get(Car, liq.car_id) if liq.car_id is not None else None
        if liq.car_id is not None and not car_final:
            return _err("Carro inválido.", 400)

    if operator_changed or car_changed:
        try:
            liq.car_type = _derive_car_type(op_final, car_final)
        except ApiError as e:
            return _err(str(e), e.status_code or 400)

    # Kms / tarifa
    if "kms" in body:
        kms = _num(body.get("kms"), 0.0)
        if kms < 0:
            return _err("Kms inválidos.", 400)
        liq.kms = round(kms, 2)

    if "tarifa" in body:
        tarifa = _num(body.get("tarifa"), 0.0)
        if tarifa < 0:
            return _err("Tarifa inválida.", 400)
        liq.tarifa = tarifa

    # IVA / retención
    if "aplica_iva" in body:
        liq.aplica_iva = bool(body.get("aplica_iva") is True)

    if "iva_pct" in body:
        iva_pct = _num(body.get("iva_pct"), 0.0)
        if liq.aplica_iva and (iva_pct < 0 or iva_pct > 100):
            return _err("IVA % inválido (0 a 100).", 400)
        liq.iva_pct = iva_pct if liq.aplica_iva else 0

    if "aplica_retencion" in body:
        liq.aplica_retencion = bool(body.get("aplica_retencion") is True)

    if "retencion_pct" in body:
        rp = _num(body.get("retencion_pct"), 0.0)
        if liq.aplica_retencion and (rp < 0 or rp > 100):
            return _err("Retención % inválido (0 a 100).", 400)
        liq.retencion_pct = rp if liq.aplica_retencion else 0

    # status / observaciones / activo
    if "status" in body:
        st = (body.get("status") or "").strip().lower()
        if st and st not in LIQ_STATUS_CHOICES:
            return _err("status inválido.", 400)
        if st:
            liq.status = st

    if "observaciones" in body:
        obs = body.get("observaciones")
        liq.observaciones = (obs.strip() if isinstance(obs, str) else None) or None

    if "activo" in body:
        liq.activo = bool(body.get("activo"))

    # extras por operador
    for f in ("maniobra_op1", "maniobra_op2", "otros_ingresos_op1", "otros_ingresos_op2"):
        if f in body:
            v = _num(body.get(f), 0.0)
            if v < 0:
                return _err(f"{f} no puede ser negativo.", 400)
            if f.endswith("_op2") and not getattr(liq, "operator2_id", None):
                return _err(f"No puedes enviar {f} sin operator2_id.", 400)
            setattr(liq, f, round(v, 2))

    # ------------------ ✅ DEDUCCIONES / ANTICIPOS ------------------

    try:
        # replace completo deducciones
        if "deducciones" in body:
            ded_list = body.get("deducciones") or []
            if not isinstance(ded_list, list):
                return _err("deducciones debe ser una lista.", 400)

            liq.deducciones = []
            db.session.flush()

            for item in ded_list:
                _, slot, key, label, monto = _validate_deduccion_payload(item, allow_id=False)
                if slot == 2 and not getattr(liq, "operator2_id", None):
                    return _err("No puedes mandar deducciones operator_slot=2 sin operator2_id.", 400)

                # impuestos se ignora (se recalcula)
                if key == "impuestos":
                    continue

                liq.deducciones.append(
                    LiquidacionDeduccion(
                        operator_slot=slot,
                        key=key,
                        label=label,
                        monto=monto,
                    )
                )

        # add 1 deducción
        if "deduccion_add" in body and body.get("deduccion_add") is not None:
            _, slot, key, label, monto = _validate_deduccion_payload(body.get("deduccion_add"), allow_id=False)
            if slot == 2 and not getattr(liq, "operator2_id", None):
                return _err("No puedes mandar deducciones operator_slot=2 sin operator2_id.", 400)
            if key != "impuestos":
                liq.deducciones.append(
                    LiquidacionDeduccion(operator_slot=slot, key=key, label=label, monto=monto)
                )

        # update 1 deducción (por id)
        if "deduccion_update" in body and body.get("deduccion_update") is not None:
            upd = body.get("deduccion_update")
            ded_id, slot, key, label, monto = _validate_deduccion_payload(upd, allow_id=True)
            if not ded_id:
                return _err("deduccion_update requiere id.", 400)

            target = None
            for d in (liq.deducciones or []):
                if int(d.id) == int(ded_id):
                    target = d
                    break
            if not target:
                return _err("Deducción no encontrada en esta liquidación.", 404)

            # no permitimos modificar impuestos manualmente
            if key == "impuestos":
                return _err("La deducción 'impuestos' se calcula automáticamente.", 400)

            if slot == 2 and not getattr(liq, "operator2_id", None):
                return _err("No puedes mandar deducciones operator_slot=2 sin operator2_id.", 400)

            target.operator_slot = slot
            target.key = key
            target.label = label
            target.monto = monto

        # delete 1 deducción (por id)
        if "deduccion_delete_id" in body and body.get("deduccion_delete_id") is not None:
            try:
                did = int(body.get("deduccion_delete_id"))
            except Exception:
                return _err("deduccion_delete_id inválido.", 400)

            target = None
            for d in (liq.deducciones or []):
                if int(d.id) == int(did):
                    target = d
                    break
            if not target:
                return _err("Deducción no encontrada en esta liquidación.", 404)

            # no permitimos borrar impuestos (se recalcula)
            if target.key == "impuestos":
                return _err("La deducción 'impuestos' se calcula automáticamente.", 400)

            db.session.delete(target)

        # replace completo anticipos
        if "anticipos" in body:
            ant_list = body.get("anticipos") or []
            if not isinstance(ant_list, list):
                return _err("anticipos debe ser una lista.", 400)

            liq.anticipos = []
            db.session.flush()

            for item in ant_list:
                slot, importe, recibo = _validate_anticipo_payload(item)
                if slot == 2 and not getattr(liq, "operator2_id", None):
                    return _err("No puedes mandar anticipos operator_slot=2 sin operator2_id.", 400)

                snap_op_id = liq.operator_id if slot == 1 else liq.operator2_id

                liq.anticipos.append(
                    LiquidacionAnticipo(
                        operator_slot=slot,
                        operator_id=snap_op_id,
                        importe=importe,
                        recibo=recibo,
                    )
                )

        # add 1 anticipo
        if "anticipo_add" in body and body.get("anticipo_add") is not None:
            slot, importe, recibo = _validate_anticipo_payload(body.get("anticipo_add"))
            if slot == 2 and not getattr(liq, "operator2_id", None):
                return _err("No puedes mandar anticipos operator_slot=2 sin operator2_id.", 400)

            snap_op_id = liq.operator_id if slot == 1 else liq.operator2_id
            liq.anticipos.append(
                LiquidacionAnticipo(
                    operator_slot=slot,
                    operator_id=snap_op_id,
                    importe=importe,
                    recibo=recibo,
                )
            )

        # delete 1 anticipo
        if "anticipo_delete_id" in body and body.get("anticipo_delete_id") is not None:
            try:
                aid = int(body.get("anticipo_delete_id"))
            except Exception:
                return _err("anticipo_delete_id inválido.", 400)

            target = None
            for a in (liq.anticipos or []):
                if int(a.id) == int(aid):
                    target = a
                    break
            if not target:
                return _err("Anticipo no encontrado en esta liquidación.", 404)

            db.session.delete(target)

    except ApiError as e:
        return _err(str(e), e.status_code or 400)

    # Recalcular totales siempre (aquí se vuelve a generar impuestos 6% como deducción)
    liq.recalc_totals()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo actualizar. {str(e)}", 400)

    liq2 = _load_liq_full(client_id, liq_id)
    return jsonify(_serialize(liq2 or liq))


@liquidaciones_bp.delete("/<int:liq_id>")
def delete_liquidacion(client_id: int, liq_id: int):
    _, err = _validate_client(client_id)
    if err:
        return err

    liq = _load_liq_full(client_id, liq_id)
    if not liq:
        return _err("Liquidación no encontrada.", 404)

    hard = _parse_bool(request.args.get("hard"))
    hard = bool(hard is True)

    try:
        if hard:
            db.session.delete(liq)
            db.session.commit()
            return jsonify({"status": "deleted", "id": liq_id})
        else:
            liq.activo = False
            db.session.commit()
            return jsonify({"status": "deactivated", "id": liq_id})
    except Exception as e:
        db.session.rollback()
        return _err(f"No se pudo eliminar. {str(e)}", 400)
