# atr_api/schemas/liquidaciones_excel_import.py

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from werkzeug.datastructures import FileStorage

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

from atr_api.errors import ApiError


# -----------------------------------------------------------------------------
# Encabezados soportados (aliases)
# -----------------------------------------------------------------------------
# Mapeo: "Encabezado en Excel" -> "campo interno"
#
# Nota: los nombres pueden variar; aquí soportamos variantes comunes.
# En el service haremos la validación de negocio (series, consecutivos, etc).
HEADER_ALIASES: Dict[str, str] = {
    # Talón / viaje
    "talon": "talon_interno",
    "talón": "talon_interno",
    "talon interno": "talon_interno",
    "talón interno": "talon_interno",
    "talon/viaje": "talon_interno",
    "talón/viaje": "talon_interno",
    "viaje": "talon_interno",
    "no viaje": "talon_interno",
    "n° viaje": "talon_interno",
    "num viaje": "talon_interno",

    # Factura / Carta Porte
    "factura": "factura_cp",
    "c.p.": "factura_cp",
    "cp": "factura_cp",
    "carta porte": "factura_cp",
    "factura/c.p.": "factura_cp",
    "factura/c.p": "factura_cp",
    "factura/carta porte": "factura_cp",

    # Fecha
    "fecha": "fecha",

    # Carro / unidad (camión) / placas (si llegara)
    "carro": "carro",
    "unidad": "carro",
    "camion": "carro",
    "camión": "carro",
    "tracto": "carro",
    "placas": "carro",

    # Dealer / destino
    "dealer": "dealer",
    "agencia": "dealer",
    "destino": "dealer",
    "destinatario": "dealer",

    # Unidades (cantidad de vehículos transportados)
    "unidades": "unidades",
    "uds": "unidades",
    "cantidad": "unidades",
    "cantidad unidades": "unidades",

    # Kms
    "kms": "kms",
    "km": "kms",
    "kilometros": "kms",
    "kilómetros": "kms",

    # Flete / subtotal (comercial)
    "flete": "flete",
    "subtotal": "flete",

    # IVA / retención / total
    "iva": "iva",
    "retencion": "retencion",
    "retención": "retencion",
    "total": "total",

    # Operadores
    "1er operador": "operador_1",
    "1 operador": "operador_1",
    "operador 1": "operador_1",
    "primer operador": "operador_1",

    "2º operador": "operador_2",
    "2do operador": "operador_2",
    "2 operador": "operador_2",
    "operador 2": "operador_2",
    "segundo operador": "operador_2",

    # Anticipos / recibos por operador
    "anticipo de gastos 1º": "anticipo_1",
    "anticipo gastos 1": "anticipo_1",
    "anticipo 1": "anticipo_1",
    "anticipo operador 1": "anticipo_1",

    "folio recibo 1º": "recibo_1",
    "folio recibo 1": "recibo_1",
    "recibo 1": "recibo_1",
    "folio 1": "recibo_1",

    "anticipo de gastos 2º": "anticipo_2",
    "anticipo gastos 2": "anticipo_2",
    "anticipo 2": "anticipo_2",
    "anticipo operador 2": "anticipo_2",

    "folio recibo 2º": "recibo_2",
    "folio recibo 2": "recibo_2",
    "recibo 2": "recibo_2",
    "folio 2": "recibo_2",
}

SUPPORTED_FIELDS = set(HEADER_ALIASES.values())


# -----------------------------------------------------------------------------
# Normalización y parseos básicos
# -----------------------------------------------------------------------------
def _norm_header(s: Any) -> str:
    """
    Normaliza encabezados para hacer matching robusto:
      - lower
      - espacios colapsados
      - quita saltos de línea
      - quita puntos finales redundantes (pero conserva 'c.p.' si viene tal cual por alias)
    """
    if s is None:
        return ""
    raw = str(s).strip().lower()
    raw = raw.replace("\n", " ").replace("\r", " ")
    raw = re.sub(r"\s+", " ", raw)
    raw = raw.strip()
    return raw


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _parse_date_flexible(value: Any) -> Optional[str]:
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

    s = _clean_string(value)
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


def _parse_int(value: Any, *, allow_blank: bool = True) -> Optional[int]:
    if value is None:
        return None if allow_blank else 0
    if isinstance(value, bool):
        # evita True/False como 1/0
        return None if allow_blank else 0
    if isinstance(value, (int,)):
        return int(value)
    if isinstance(value, float):
        # si viene 10.0 lo aceptamos como 10
        if value.is_integer():
            return int(value)
        return int(round(value))
    s = _clean_string(value)
    if not s:
        return None if allow_blank else 0
    s2 = re.sub(r"[^\d\-]+", "", s)
    if not s2:
        return None if allow_blank else 0
    try:
        return int(s2)
    except Exception:
        raise ApiError(f"Entero inválido: '{s}'", 400)


def _parse_money(value: Any, *, allow_blank: bool = True) -> Optional[float]:
    """
    Parse numérico tolerante:
      - 1,234.56
      - 1234.56
      - 1234,56  (lo convertimos)
      - vacío => None (si allow_blank)
    """
    if value is None:
        return None if allow_blank else 0.0
    if isinstance(value, bool):
        return None if allow_blank else 0.0
    if isinstance(value, (int, float)):
        return float(value)

    s = _clean_string(value)
    if not s:
        return None if allow_blank else 0.0

    # quitar símbolo moneda y espacios
    s = s.replace("$", "").replace(" ", "")

    # Si tiene ambos separadores, asumimos:
    # - coma como miles y punto como decimal (1,234.56)
    # - o punto como miles y coma como decimal (1.234,56)
    if "," in s and "." in s:
        # Si la última coma está después del último punto -> decimal coma
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "")
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        # solo coma -> decimal coma
        if "," in s and "." not in s:
            s = s.replace(",", ".")

    # deja solo dígitos, punto y signo
    s = re.sub(r"[^0-9\.\-]+", "", s)
    if not s or s in ("-", ".", "-."):
        return None if allow_blank else 0.0

    try:
        return float(s)
    except Exception:
        raise ApiError(f"Numérico inválido: '{value}'", 400)


def _normalize_talon(value: Any) -> str:
    """
    Normaliza talón como string sin espacios y en mayúsculas.
    No valida formato aquí (eso se hace en el service para usar el catálogo/padding).
    """
    if value is None:
        return ""
    s = "".join(_clean_string(value).split()).upper()
    return s


# -----------------------------------------------------------------------------
# Parser principal
# -----------------------------------------------------------------------------
def parse_excel_liquidaciones(file_storage: FileStorage) -> List[Dict[str, Any]]:
    """
    Lee el Excel y regresa lista:
      [{ "_row_number": 2, "payload": {...}}, ...]

    Campos internos (payload):
      - talon_interno (str)
      - factura_cp (str)
      - fecha (YYYY-MM-DD o None)
      - carro (str)
      - dealer (str)
      - unidades (int o None)
      - kms (float o None)
      - flete (float o None)
      - iva (float o None)
      - retencion (float o None)
      - total (float o None)
      - operador_1 (str)
      - anticipo_1 (float o None)
      - recibo_1 (str)
      - operador_2 (str)
      - anticipo_2 (float o None)
      - recibo_2 (str)
    """
    try:
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

    # Requeridos mínimos para que el import tenga sentido
    if "talon_interno" not in col_to_field.values():
        raise ApiError("El Excel debe incluir la columna 'TALON' / 'TALON/VIAJE' / 'Talón interno'.", 400)
    if "fecha" not in col_to_field.values():
        raise ApiError("El Excel debe incluir la columna 'FECHA'.", 400)

    rows_out: List[Dict[str, Any]] = []

    for row_idx in range(2, ws.max_row + 1):
        row = ws[row_idx]
        payload: Dict[str, Any] = {}

        for col_idx, field in col_to_field.items():
            value = row[col_idx].value if col_idx < len(row) else None

            if field == "talon_interno":
                payload[field] = _normalize_talon(value)
            elif field == "fecha":
                payload[field] = _parse_date_flexible(value)
            elif field == "unidades":
                payload[field] = _parse_int(value, allow_blank=True)
            elif field in ("kms",):
                payload[field] = _parse_money(value, allow_blank=True)
            elif field in ("flete", "iva", "retencion", "total", "anticipo_1", "anticipo_2"):
                payload[field] = _parse_money(value, allow_blank=True)
            else:
                payload[field] = _clean_string(value)

        # Saltar filas realmente vacías (sin talón)
        talon = _normalize_talon(payload.get("talon_interno", ""))
        if not talon:
            continue
        payload["talon_interno"] = talon

        rows_out.append({"_row_number": row_idx, "payload": payload})

    if not rows_out:
        raise ApiError("El Excel no tiene filas de datos (o todas venían sin talón).", 400)

    return rows_out
