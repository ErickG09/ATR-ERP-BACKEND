from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict

from atr_api.errors import ApiError
from atr_api.models import Operator


# Campos agrupados para normalizar
NUMERIC_FIELDS = [
    "sueldo_op_1",
    "viaticos_op_1",
    "sueldo_op_2",
    "viaticos_op_2",
    "viaje_especial",
    "kms_acumulados",
    "viaticos_por_km",
    "sueldo_por_km",
]

TEXT_FIELDS = [
    "domicilio",
    "telefono",
    "no_imss",
    "rfc",
    "no_licencia",
    "mexico",
    "exp_ver",
    "exp_lc",
    "exp_tux",
    "importado",
    "local",
    "patios",
    "slp_altamira",
    "ramos_altamira",
    "slp_lc",
    "sal_lzc",
    "sal_ver",
    "sal_altamira",
    "resguardo",
    "ayuda_escolar",
    "tipo_carro",
    "observaciones",
]

DATE_REQUIRED = ["fecha_ingreso"]
DATE_OPTIONAL = ["fecha_venc_licencia"]


def _parse_date(value: Any, field_name: str, required: bool) -> date | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ApiError(f"El campo '{field_name}' es obligatorio.", 400)
        return None

    if isinstance(value, date):
        return value

    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ApiError(
            f"El campo '{field_name}' debe tener formato 'YYYY-MM-DD'.", 400
        )


def _parse_numeric(value: Any, field_name: str) -> Decimal:
    if value is None or (isinstance(value, str) and not value.strip()):
        return Decimal("0")

    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ApiError(
            f"El campo '{field_name}' debe ser numérico (ej. 1234.56).", 400
        )


def sanitize_operator_payload(
    payload: Dict[str, Any],
    *,
    partial: bool = False,
) -> Dict[str, Any]:
    """
    Normaliza y valida el payload de operadores.

    - Convierte vacíos "" a 0 en numéricos.
    - Convierte vacíos "" a "" en texto.
    - Convierte fechas string a date.
    - Valida obligatorios en creación (partial=False).
    """
    data: Dict[str, Any] = {}

    # nombre (obligatorio en alta)
    if not partial or "nombre" in payload:
        raw_nombre = payload.get("nombre")
        if not raw_nombre or not str(raw_nombre).strip():
            raise ApiError("El campo 'nombre' es obligatorio.", 400)
        data["nombre"] = str(raw_nombre).strip()

    # codigo (opcional, si no viene lo generamos después)
    if "codigo" in payload:
        raw_codigo = payload.get("codigo") or ""
        data["codigo"] = str(raw_codigo).strip()

    # activo (booleano real)
    if not partial or "activo" in payload:
        if "activo" not in payload:
            # Alta sin mandar 'activo' → asumimos True
            data["activo"] = True
        else:
            raw_activo = payload.get("activo")
            if isinstance(raw_activo, bool):
                data["activo"] = raw_activo
            else:
                raise ApiError("El campo 'activo' debe ser booleano (true/false).", 400)

    # Fechas requeridas
    for field in DATE_REQUIRED:
        if partial and field not in payload:
            continue
        raw = payload.get(field)
        data[field] = _parse_date(raw, field, required=not partial)

    # Fechas opcionales
    for field in DATE_OPTIONAL:
        if partial and field not in payload:
            continue
        raw = payload.get(field)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            data[field] = None
        else:
            data[field] = _parse_date(raw, field, required=False)

    # Campos numéricos
    for field in NUMERIC_FIELDS:
        if partial and field not in payload:
            continue
        raw = payload.get(field)
        data[field] = _parse_numeric(raw, field)

    # Campos de texto
    for field in TEXT_FIELDS:
        if partial and field not in payload:
            continue
        raw = payload.get(field)
        if raw is None:
            data[field] = ""
        else:
            data[field] = str(raw).strip()

    return data


def _decimal_to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def serialize_operator_brief(op: Operator) -> Dict[str, Any]:
    """
    Representación breve para el catálogo de contabilidad.
    """
    return {
        "id": op.id,
        "client_id": op.client_id,
        "codigo": op.codigo,
        "nombre": op.nombre,
        "fecha_ingreso": op.fecha_ingreso.isoformat()
        if op.fecha_ingreso
        else None,
        "activo": op.activo,

        # NUEVOS para el catálogo
        "domicilio": op.domicilio,
        "kms_acumulados": _decimal_to_float(op.kms_acumulados),

        "sueldo_op_1": _decimal_to_float(op.sueldo_op_1),
        "viaticos_op_1": _decimal_to_float(op.viaticos_op_1),
        "sueldo_op_2": _decimal_to_float(op.sueldo_op_2),
        "viaticos_op_2": _decimal_to_float(op.viaticos_op_2),
        "viaje_especial": _decimal_to_float(op.viaje_especial),
        "mexico": op.mexico,
        "exp_ver": op.exp_ver,
        "exp_lc": op.exp_lc,
        "exp_tux": op.exp_tux,
        "importado": op.importado,
        "local": op.local,
        "patios": op.patios,
        "slp_altamira": op.slp_altamira,
        "ramos_altamira": op.ramos_altamira,
        "slp_lc": op.slp_lc,
        "sal_lzc": op.sal_lzc,
        "sal_ver": op.sal_ver,
        "sal_altamira": op.sal_altamira,
        "resguardo": op.resguardo,
        "ayuda_escolar": op.ayuda_escolar,
        "tipo_carro": op.tipo_carro,
    }



def serialize_operator_detail(op: Operator) -> Dict[str, Any]:
    """
    Representación completa para el formulario de alta / edición.
    """
    data = serialize_operator_brief(op)
    data.update(
        {
            "domicilio": op.domicilio,
            "telefono": op.telefono,
            "no_imss": op.no_imss,
            "rfc": op.rfc,
            "no_licencia": op.no_licencia,
            "fecha_venc_licencia": op.fecha_venc_licencia.isoformat()
            if op.fecha_venc_licencia
            else None,
            "kms_acumulados": _decimal_to_float(op.kms_acumulados),
            "viaticos_por_km": _decimal_to_float(op.viaticos_por_km),
            "sueldo_por_km": _decimal_to_float(op.sueldo_por_km),
            "observaciones": op.observaciones,
            "status_display": op.status_display,
        }
    )
    return data
