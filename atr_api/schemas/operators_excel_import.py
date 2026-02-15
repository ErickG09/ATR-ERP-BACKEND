from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, List, Callable

from werkzeug.datastructures import FileStorage

from atr_api.errors import ApiError
from atr_api.models import Operator
from atr_api.extensions import db

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel


# -----------------------------
# Encabezados soportados
# -----------------------------
# Mapeo: "Encabezado en Excel" -> "campo backend"
HEADER_ALIASES: Dict[str, str] = {
    # identificadores
    "codigo": "codigo",
    "código": "codigo",

    # base
    "nombre": "nombre",
    "fecha ingreso": "fecha_ingreso",

    # sueldos/viaticos
    "sueldo op1": "sueldo_op_1",
    "viaticos op1": "viaticos_op_1",
    "viáticos op1": "viaticos_op_1",
    "sueldo op2": "sueldo_op_2",
    "viaticos op2": "viaticos_op_2",
    "viáticos op2": "viaticos_op_2",

    # contacto / ids
    "domicilio": "domicilio",
    "imss": "no_imss",
    "no imss": "no_imss",
    "nss": "no_imss",

    "licencia": "no_licencia",
    "no licencia": "no_licencia",

    "vence licencia": "fecha_venc_licencia",
    "vencimiento licencia": "fecha_venc_licencia",

    "telefono": "telefono",
    "teléfono": "telefono",

    "rfc": "rfc",

    "email": "correo_electronico",
    "correo": "correo_electronico",
    "correo electronico": "correo_electronico",
    "correo electrónico": "correo_electronico",

    "gafete aduana": "gafete_aduana",
    "gafete": "gafete_aduana",
    "gafete aduána": "gafete_aduana",

    "apto medico": "apto_medico_licencia",
    "apto médico": "apto_medico_licencia",

    "seguro": "tiene_seguro",

    # NUEVO: Tipo carro
    "tipo carro": "tipo_carro",
    "tipo de carro": "tipo_carro",
    "tipo unidad": "tipo_carro",
}

SUPPORTED_FIELDS = set(HEADER_ALIASES.values())


def _norm_header(s: Any) -> str:
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_full_name(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _parse_bool_si_no(value: Any) -> bool:
    """
    Vacio => False (esto es importante porque en muchos Excels viene en blanco).
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "si", "sí", "s"):
        return True
    if s in ("0", "false", "f", "no", "n", ""):
        return False
    raise ApiError("El campo 'Seguro' debe ser SI/NO (o true/false, 1/0).", 400)


def _parse_date_flexible(value: Any) -> str | None:
    """
    Devuelve ISO 'YYYY-MM-DD' o None.
    Soporta:
      - date/datetime
      - número serial Excel
      - string YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, (int, float)):
        try:
            d = from_excel(value)
            if isinstance(d, datetime):
                return d.date().isoformat()
            if isinstance(d, date):
                return d.isoformat()
        except Exception:
            pass

    s = str(value).strip()
    if not s:
        return None

    # YYYY-MM-DD
    try:
        return date.fromisoformat(s).isoformat()
    except Exception:
        pass

    # DD/MM/YYYY o DD-MM-YYYY
    m = re.match(r"^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$", s)
    if m:
        dd = int(m.group(1))
        mm = int(m.group(2))
        yyyy = int(m.group(3))
        try:
            return date(yyyy, mm, dd).isoformat()
        except Exception:
            raise ApiError("Fecha inválida en Excel. Usa YYYY-MM-DD o una fecha válida.", 400)

    raise ApiError("Fecha inválida. Usa YYYY-MM-DD o una fecha válida de Excel.", 400)


def _parse_numeric_or_blank(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str) and not value.strip():
        return ""
    return value


def parse_excel_operators(file_storage: FileStorage) -> List[Dict[str, Any]]:
    """
    Lee el Excel y regresa una lista:
      [{ "_row_number": 2, "payload": {...}}, ...]
    """
    try:
        # MUY importante para evitar lecturas parciales en algunos entornos
        file_storage.stream.seek(0)
        wb = load_workbook(file_storage.stream, data_only=True)
    except Exception as e:
        raise ApiError(f"Excel inválido o corrupto: {e}", 400)

    ws = wb.active

    headers: List[str] = [_norm_header(c.value) for c in ws[1]]
    if not any(headers):
        raise ApiError("No se detectaron encabezados en la fila 1.", 400)

    col_to_field: Dict[int, str] = {}
    for idx, h in enumerate(headers):
        if not h:
            continue
        if h in HEADER_ALIASES:
            col_to_field[idx] = HEADER_ALIASES[h]

    if "nombre" not in col_to_field.values():
        raise ApiError("El Excel debe incluir la columna 'Nombre'.", 400)

    rows_out: List[Dict[str, Any]] = []

    for row_idx in range(2, ws.max_row + 1):
        row = ws[row_idx]
        payload: Dict[str, Any] = {}

        for col_idx, field in col_to_field.items():
            value = row[col_idx].value if col_idx < len(row) else None

            if field in ("fecha_ingreso", "fecha_venc_licencia", "apto_medico_licencia"):
                payload[field] = _parse_date_flexible(value)
            elif field == "tiene_seguro":
                payload[field] = _parse_bool_si_no(value)
            elif field in ("sueldo_op_1", "viaticos_op_1", "sueldo_op_2", "viaticos_op_2"):
                payload[field] = _parse_numeric_or_blank(value)
            else:
                payload[field] = "" if value is None else str(value).strip()

        # Saltar filas sin nombre
        if not normalize_full_name(payload.get("nombre", "")):
            continue

        rows_out.append({"_row_number": row_idx, "payload": payload})

    return rows_out


# -----------------------------------------------------------------------------
# Generación de código por cliente, usando HUECOS (A001..A005, saltar A006, etc.)
# -----------------------------------------------------------------------------
_CODE_RE = re.compile(r"^([A-Z])(\d+)$")


def _clean_initial(letter: str) -> str:
    letter = (letter or "").strip().upper()
    return letter[0] if letter else "X"


def _extract_prefix_from_name(full_name: str) -> str:
    # Tu dato viene "APELLIDO NOMBRE" (mayúsculas). Tomamos la inicial del primer token.
    parts = normalize_full_name(full_name).split(" ")
    first = parts[0] if parts else ""
    return _clean_initial(first[:1])


def _normalize_codigo(raw: Any) -> str:
    if raw is None:
        return ""
    s = str(raw).strip().upper()
    s = re.sub(r"\s+", "", s)
    return s


def make_operator_code_generator(*, client_id: int) -> Callable[[str], str]:
    """
    Genera códigos por cliente llenando huecos.
    Ej: si existen A006 y A010, el siguiente para prefijo A será A001, A002... A005, A007...
    Mantiene estado en memoria por prefijo para múltiples inserciones durante el import.
    """
    cache_used: Dict[str, set[int]] = {}
    cache_next_candidate: Dict[str, int] = {}

    def _load_used(prefix: str) -> set[int]:
        if prefix in cache_used:
            return cache_used[prefix]

        like = f"{prefix}%"
        existing = (
            db.session.query(Operator.codigo)
            .filter(Operator.client_id == client_id)
            .filter(Operator.codigo.ilike(like))
            .all()
        )

        used: set[int] = set()
        for (code,) in existing:
            if not code:
                continue
            m = _CODE_RE.match(str(code).strip().upper())
            if not m:
                continue
            try:
                used.add(int(m.group(2)))
            except Exception:
                continue

        cache_used[prefix] = used
        cache_next_candidate[prefix] = 1
        return used

    def _next_available(prefix: str) -> int:
        used = _load_used(prefix)
        n = cache_next_candidate.get(prefix, 1)

        # avanzar hasta encontrar hueco
        while n in used:
            n += 1

        # reservarlo para esta sesión (import / alta manual)
        used.add(n)
        cache_next_candidate[prefix] = n + 1
        return n

    def generator(*, full_name: str) -> str:
        prefix = _extract_prefix_from_name(full_name)
        n = _next_available(prefix)
        return f"{prefix}{n:03d}"

    return generator


def normalize_codigo_from_excel(*, codigo: Any, nombre: Any) -> str:
    """
    Si viene código del Excel, lo respetamos.
    Si NO viene, generaremos a partir del nombre (en el service).
    """
    c = _normalize_codigo(codigo)
    if not c:
        return ""
    # validación suave: letra + dígitos
    m = _CODE_RE.match(c)
    if not m:
        # si viene algo raro, preferimos error claro
        raise ApiError(
            f"Código inválido '{c}'. Debe tener formato como A006 (letra + número).",
            400,
        )
    # normaliza dígitos a 3 (A6 -> A006)
    prefix = m.group(1)
    num = int(m.group(2))
    return f"{prefix}{num:03d}"
