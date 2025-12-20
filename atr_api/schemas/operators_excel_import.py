from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, List, Tuple, Callable

from werkzeug.datastructures import FileStorage

from atr_api.errors import ApiError
from atr_api.models import Operator
from atr_api.extensions import db

# Requiere openpyxl
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel


# -----------------------------
# Encabezados soportados
# -----------------------------
# Mapeo: "Encabezado en Excel" -> "campo backend"
HEADER_ALIASES: Dict[str, str] = {
    # obligatorios / base
    "nombre": "nombre",
    "fecha ingreso": "fecha_ingreso",

    # sueldos/viaticos
    "sueldo op1": "sueldo_op_1",
    "viaticos op1": "viaticos_op_1",
    "sueldo op2": "sueldo_op_2",
    "viaticos op2": "viaticos_op_2",

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
    "rfc": "rfc",
    "email": "correo_electronico",
    "correo": "correo_electronico",
    "correo electronico": "correo_electronico",

    "gafete aduana": "gafete_aduana",
    "gafete": "gafete_aduana",

    "apto medico": "apto_medico_licencia",
    "apto médico": "apto_medico_licencia",

    "seguro": "tiene_seguro",
}

# Los que vamos a producir como payload para sanitize_operator_payload
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
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "si", "sí", "s"):
        return True
    if s in ("0", "false", "f", "no", "n", ""):
        return False
    # Si meten algo raro, mejor error
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

    # Excel serial number
    if isinstance(value, (int, float)):
        try:
            d = from_excel(value)
            if isinstance(d, datetime):
                return d.date().isoformat()
            if isinstance(d, date):
                return d.isoformat()
        except Exception:
            # cae a parse de string
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
    """
    Dejamos que sanitize_operator_payload convierta a Decimal.
    Aquí solo normalizamos vacíos.
    """
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
    # openpyxl necesita bytes -> FileStorage stream
    try:
        wb = load_workbook(file_storage, data_only=True)
    except Exception as e:
        raise ApiError(f"Excel inválido o corrupto: {e}", 400)

    ws = wb.active

    # Encabezados = fila 1
    headers = []
    for cell in ws[1]:
        headers.append(_norm_header(cell.value))

    if not any(headers):
        raise ApiError("No se detectaron encabezados en la fila 1.", 400)

    # Mapear columnas a campos backend
    col_to_field: Dict[int, str] = {}
    for idx, h in enumerate(headers):
        if not h:
            continue
        if h in HEADER_ALIASES:
            col_to_field[idx] = HEADER_ALIASES[h]

    if "nombre" not in col_to_field.values():
        raise ApiError("El Excel debe incluir la columna 'Nombre'.", 400)

    rows_out: List[Dict[str, Any]] = []

    # Datos desde fila 2
    for row_idx in range(2, ws.max_row + 1):
        row = ws[row_idx]
        payload: Dict[str, Any] = {}

        # Construir payload desde columnas reconocidas
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

        # Saltar filas totalmente vacías (sin nombre)
        if not normalize_full_name(payload.get("nombre", "")):
            continue

        # Importante: codigo NO viene del Excel (lo forzamos vacío)
        payload["codigo"] = ""

        rows_out.append(
            {
                "_row_number": row_idx,
                "payload": payload,
            }
        )

    return rows_out


# -----------------------------
# Generación de código (R001…)
# -----------------------------
def _extract_first_surname(full_name: str) -> str:
    parts = normalize_full_name(full_name).split(" ")
    return parts[0] if parts else ""


def _clean_initial(letter: str) -> str:
    letter = (letter or "").strip().upper()
    # Si no hay letra, usamos 'X'
    return letter[0] if letter else "X"


def make_operator_code_generator(*, client_id: int) -> Callable[[str], str]:
    """
    Regresa una función que genera códigos únicos por cliente:
      inicial + 3 dígitos (R001, R002...)
    Se apoya en DB para conocer el máximo existente por inicial
    y mantiene contador en memoria para múltiples filas del mismo Excel.
    """
    cache_next_number: Dict[str, int] = {}

    def get_next_number_for_prefix(prefix: str) -> int:
        if prefix in cache_next_number:
            n = cache_next_number[prefix]
            cache_next_number[prefix] = n + 1
            return n

        # Buscar máximo existente en DB para ese prefijo
        # Formato esperado: "R001"
        like = f"{prefix}%"
        existing_codes = (
            db.session.query(Operator.codigo)
            .filter(Operator.client_id == client_id)
            .filter(Operator.codigo.ilike(like))
            .all()
        )

        max_n = 0
        for (code,) in existing_codes:
            if not code:
                continue
            m = re.match(r"^[A-Z](\d+)$", str(code).strip().upper())
            if not m:
                continue
            try:
                num = int(m.group(1))
                max_n = max(max_n, num)
            except Exception:
                continue

        next_n = max_n + 1
        cache_next_number[prefix] = next_n + 1  # guardamos el siguiente después de usarlo
        return next_n

    def generator(*, full_name: str) -> str:
        surname = _extract_first_surname(full_name)
        prefix = _clean_initial(surname[:1])
        n = get_next_number_for_prefix(prefix)
        return f"{prefix}{n:03d}"

    return generator
