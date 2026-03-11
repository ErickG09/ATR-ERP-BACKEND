# atr_api/schemas/operator.py
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict

from atr_api.errors import ApiError
from atr_api.models import Operator


# -----------------------------------------------------------------------------
# Campos agrupados para normalizar
# -----------------------------------------------------------------------------

# Estos YA son numéricos en DB
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

# Tarifas/rates de catálogo (2 decimales)
CATALOG_RATE_FIELDS_2DP = [
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
]

# NUEVO: Maniobras (2 decimales)
MANIOBRA_FIELDS_2DP = [
    "man_nac",
    "man_esp",
    "man_df",
    "man_ver",
    "man_slp_altamira",
    "man_ramos_altamira",
    "man_slp_lzc",
    "man_salamanca_lzc",
    "man_salamanca_ver",
    "man_salamanca_altamira",
]

# También numérico (2 decimales)
CATALOG_MONEY_FIELDS_2DP = [
    "ayuda_escolar",
]

# Texto real
TEXT_FIELDS = [
    "domicilio",
    "telefono",
    "no_imss",
    "rfc",
    "no_licencia",
    "tipo_carro",
    "observaciones",
    "correo_electronico",
    "gafete_aduana",
]

DATE_REQUIRED = ["fecha_ingreso"]

DATE_OPTIONAL = [
    "fecha_venc_licencia",
    "apto_medico_licencia",
]

BOOL_OPTIONAL = [
    "tiene_seguro",
]


# -----------------------------------------------------------------------------
# Parsers
# -----------------------------------------------------------------------------

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
            f"El campo '{field_name}' debe tener formato 'YYYY-MM-DD'.",
            400,
        )


def _normalize_numeric_string(value: Any) -> str:
    """
    Normaliza strings tipo Excel/UI: "$1,234.50", "  12,3 ", etc.
    - Quita $ y comas
    - Quita espacios
    - Deja dígitos, punto y signo -
    """
    s = str(value).strip()
    s = s.replace("$", "").replace(",", "").replace(" ", "")
    return s


def _parse_decimal(value: Any, field_name: str) -> Decimal:
    """
    Convierte a Decimal:
    - None o "" => 0
    - Acepta strings con $ y comas
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return Decimal("0")

    try:
        if isinstance(value, (int, float, Decimal)):
            return Decimal(str(value))
        s = _normalize_numeric_string(value)
        return Decimal(s)
    except (InvalidOperation, ValueError):
        raise ApiError(
            f"El campo '{field_name}' debe ser numérico (ej. 1234.56).",
            400,
        )


def _quantize_2dp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _quantize_4dp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _decimal_to_float_2dp(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        d = Decimal(str(value))
        d = _quantize_2dp(d)
        return float(d)
    except (InvalidOperation, TypeError, ValueError):
        return 0.0


def _decimal_to_float_4dp(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        d = Decimal(str(value))
        d = _quantize_4dp(d)
        return float(d)
    except (InvalidOperation, TypeError, ValueError):
        return 0.0


# -----------------------------------------------------------------------------
# Sanitizer
# -----------------------------------------------------------------------------

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
            data["activo"] = True
        else:
            raw_activo = payload.get("activo")
            if isinstance(raw_activo, bool):
                data["activo"] = raw_activo
            else:
                raise ApiError(
                    "El campo 'activo' debe ser booleano (true/false).",
                    400,
                )

    # tiene_seguro (boolean opcional)
    for field in BOOL_OPTIONAL:
        if partial and field not in payload:
            continue
        if field not in payload:
            data[field] = False
        else:
            raw = payload.get(field)
            if isinstance(raw, bool):
                data[field] = raw
            else:
                raise ApiError(
                    f"El campo '{field}' debe ser booleano (true/false).",
                    400,
                )

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

    # Campos numéricos existentes
    # - sueldo/viaticos/viaje/kms son 2dp
    # - por_km son 4dp
    for field in NUMERIC_FIELDS:
        if partial and field not in payload:
            continue
        raw = payload.get(field)
        dec = _parse_decimal(raw, field)

        if field in ("viaticos_por_km", "sueldo_por_km"):
            data[field] = _quantize_4dp(dec)
        else:
            data[field] = _quantize_2dp(dec)

    # Tarifas catálogo (2dp)
    for field in CATALOG_RATE_FIELDS_2DP:
        if partial and field not in payload:
            continue
        raw = payload.get(field)
        data[field] = _quantize_2dp(_parse_decimal(raw, field))

    # NUEVO: Maniobras (2dp)
    for field in MANIOBRA_FIELDS_2DP:
        if partial and field not in payload:
            continue
        raw = payload.get(field)
        data[field] = _quantize_2dp(_parse_decimal(raw, field))

    # Ayuda escolar (2dp)
    for field in CATALOG_MONEY_FIELDS_2DP:
        if partial and field not in payload:
            continue
        raw = payload.get(field)
        data[field] = _quantize_2dp(_parse_decimal(raw, field))

    # Campos de texto reales
    for field in TEXT_FIELDS:
        if partial and field not in payload:
            continue
        raw = payload.get(field)
        if raw is None:
            data[field] = ""
        else:
            data[field] = str(raw).strip()

    return data


# -----------------------------------------------------------------------------
# Serializers
# -----------------------------------------------------------------------------

def serialize_operator_brief(op: Operator) -> Dict[str, Any]:
    """
    Representación breve para el catálogo de operadores.
    """
    return {
        "id": op.id,
        "client_id": op.client_id,
        "codigo": op.codigo,
        "nombre": op.nombre,
        "fecha_ingreso": op.fecha_ingreso.isoformat() if op.fecha_ingreso else None,
        "activo": op.activo,

        "domicilio": op.domicilio,

        "kms_acumulados": _decimal_to_float_2dp(op.kms_acumulados),

        "sueldo_op_1": _decimal_to_float_2dp(op.sueldo_op_1),
        "viaticos_op_1": _decimal_to_float_2dp(op.viaticos_op_1),
        "sueldo_op_2": _decimal_to_float_2dp(op.sueldo_op_2),
        "viaticos_op_2": _decimal_to_float_2dp(op.viaticos_op_2),
        "viaje_especial": _decimal_to_float_2dp(op.viaje_especial),

        # Tarifas catálogo (2dp)
        "mexico": _decimal_to_float_2dp(getattr(op, "mexico", None)),
        "exp_ver": _decimal_to_float_2dp(getattr(op, "exp_ver", None)),
        "exp_lc": _decimal_to_float_2dp(getattr(op, "exp_lc", None)),
        "exp_tux": _decimal_to_float_2dp(getattr(op, "exp_tux", None)),
        "importado": _decimal_to_float_2dp(getattr(op, "importado", None)),
        "local": _decimal_to_float_2dp(getattr(op, "local", None)),
        "patios": _decimal_to_float_2dp(getattr(op, "patios", None)),
        "slp_altamira": _decimal_to_float_2dp(getattr(op, "slp_altamira", None)),
        "ramos_altamira": _decimal_to_float_2dp(getattr(op, "ramos_altamira", None)),
        "slp_lc": _decimal_to_float_2dp(getattr(op, "slp_lc", None)),
        "sal_lzc": _decimal_to_float_2dp(getattr(op, "sal_lzc", None)),
        "sal_ver": _decimal_to_float_2dp(getattr(op, "sal_ver", None)),
        "sal_altamira": _decimal_to_float_2dp(getattr(op, "sal_altamira", None)),
        "resguardo": _decimal_to_float_2dp(getattr(op, "resguardo", None)),

        # NUEVO: Maniobras (2dp)
        "man_nac": _decimal_to_float_2dp(getattr(op, "man_nac", None)),
        "man_esp": _decimal_to_float_2dp(getattr(op, "man_esp", None)),
        "man_df": _decimal_to_float_2dp(getattr(op, "man_df", None)),
        "man_ver": _decimal_to_float_2dp(getattr(op, "man_ver", None)),
        "man_slp_altamira": _decimal_to_float_2dp(getattr(op, "man_slp_altamira", None)),
        "man_ramos_altamira": _decimal_to_float_2dp(getattr(op, "man_ramos_altamira", None)),
        "man_slp_lzc": _decimal_to_float_2dp(getattr(op, "man_slp_lzc", None)),
        "man_salamanca_lzc": _decimal_to_float_2dp(getattr(op, "man_salamanca_lzc", None)),
        "man_salamanca_ver": _decimal_to_float_2dp(getattr(op, "man_salamanca_ver", None)),
        "man_salamanca_altamira": _decimal_to_float_2dp(
            getattr(op, "man_salamanca_altamira", None)
        ),

        "ayuda_escolar": _decimal_to_float_2dp(getattr(op, "ayuda_escolar", None)),
        "tipo_carro": op.tipo_carro,

        "correo_electronico": op.correo_electronico,
        "gafete_aduana": op.gafete_aduana,
        "apto_medico_licencia": op.apto_medico_licencia.isoformat()
        if getattr(op, "apto_medico_licencia", None)
        else None,
        "tiene_seguro": bool(getattr(op, "tiene_seguro", False)),
    }


def serialize_operator_detail(op: Operator) -> Dict[str, Any]:
    """
    Representación completa para el formulario de alta / edición.
    """
    data = serialize_operator_brief(op)
    data.update(
        {
            "telefono": op.telefono,
            "no_imss": op.no_imss,
            "rfc": op.rfc,
            "no_licencia": op.no_licencia,

            "fecha_venc_licencia": op.fecha_venc_licencia.isoformat()
            if op.fecha_venc_licencia
            else None,

            # por_km en 4dp
            "viaticos_por_km": _decimal_to_float_4dp(op.viaticos_por_km),
            "sueldo_por_km": _decimal_to_float_4dp(op.sueldo_por_km),

            "observaciones": op.observaciones,
            "status_display": op.status_display,

            "correo_electronico": op.correo_electronico,
            "gafete_aduana": op.gafete_aduana,
            "apto_medico_licencia": op.apto_medico_licencia.isoformat()
            if getattr(op, "apto_medico_licencia", None)
            else None,
            "tiene_seguro": bool(getattr(op, "tiene_seguro", False)),
        }
    )
    return data