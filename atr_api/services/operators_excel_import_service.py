from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List

from werkzeug.datastructures import FileStorage
from sqlalchemy.exc import IntegrityError

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models import Operator
from atr_api.schemas.operator import sanitize_operator_payload
from atr_api.schemas.operators_excel_import import (
    parse_excel_operators,
    normalize_full_name,
    make_operator_code_generator,
    normalize_codigo_from_excel,
)


@dataclass
class RowError:
    row_number: int
    message: str
    data: Dict[str, Any]


def _norm_rfc(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip().upper()
    # quita espacios y guiones (y cualquier cosa rara)
    s = re.sub(r"[^A-Z0-9Ñ&]+", "", s)
    return s


def _norm_imss(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    # solo dígitos
    s = re.sub(r"\D+", "", s)
    return s


def import_operators_from_excel(
    *,
    client_id: int,
    file_storage: FileStorage,
    dry_run: bool = False,
    upsert_by_name: bool = False,
) -> Dict[str, Any]:
    """
    Lee un Excel y crea/actualiza operadores.

    Cambios clave:
    - Si el Excel trae CODIGO, se respeta tal cual y se hace UPSERT por (client_id, codigo).
      Esto evita duplicados al re-subir el mismo archivo.
    - Si NO trae código, se genera llenando huecos por prefijo (A001..A005, saltar A006, etc.)
    - Soporta importar tipo_carro desde Excel.
    """
    try:
        rows = parse_excel_operators(file_storage)
    except ApiError:
        raise
    except Exception as e:
        raise ApiError(f"No se pudo leer el Excel: {e}", status_code=400)

    if not rows:
        raise ApiError("El Excel no tiene filas de datos.", status_code=400)

    code_gen = make_operator_code_generator(client_id=client_id)

    created = 0
    updated = 0
    skipped = 0
    errors: List[RowError] = []
    preview: List[Dict[str, Any]] = []

    try:
        for item in rows:
            row_number = item["_row_number"]
            raw_payload = dict(item["payload"])

            # Nombre obligatorio
            nombre = normalize_full_name(raw_payload.get("nombre", ""))
            if not nombre:
                errors.append(RowError(row_number=row_number, message="El campo 'Nombre' es obligatorio.", data=raw_payload))
                continue
            raw_payload["nombre"] = nombre

            # Si no viene fecha_ingreso, asignamos hoy
            if not raw_payload.get("fecha_ingreso"):
                raw_payload["fecha_ingreso"] = date.today().isoformat()

            # Normalizaciones útiles para que no truene por formato del Excel
            raw_payload["rfc"] = _norm_rfc(raw_payload.get("rfc"))
            raw_payload["no_imss"] = _norm_imss(raw_payload.get("no_imss"))

            # CODIGO:
            # - si viene en Excel, lo respetamos y normalizamos a formato A006
            # - si NO viene, lo dejamos vacío para generarlo después
            try:
                excel_codigo = normalize_codigo_from_excel(
                    codigo=raw_payload.get("codigo"),
                    nombre=raw_payload.get("nombre"),
                )
            except ApiError as e:
                errors.append(RowError(row_number=row_number, message=str(e), data=raw_payload))
                continue

            raw_payload["codigo"] = excel_codigo  # puede ser "" si no venía

            # Sanitiza/valida
            try:
                data = sanitize_operator_payload(raw_payload, partial=False)
            except ApiError as e:
                errors.append(RowError(row_number=row_number, message=str(e), data=raw_payload))
                continue

            data["client_id"] = client_id

            # Si no venía código en Excel, lo generamos (llenando huecos)
            if not data.get("codigo"):
                data["codigo"] = code_gen(full_name=data["nombre"])

            if dry_run:
                preview.append(
                    {
                        "row": row_number,
                        "codigo_sugerido": data["codigo"],
                        "nombre": data["nombre"],
                    }
                )
                continue

            # UPSERT POR CODIGO (principal):
            existing_by_code = (
                Operator.query.filter_by(client_id=client_id, codigo=data["codigo"])
                .limit(1)
                .first()
            )
            if existing_by_code:
                # Actualiza todo excepto id/client_id/codigo
                for k, v in data.items():
                    if k in ("id", "client_id", "codigo"):
                        continue
                    setattr(existing_by_code, k, v)
                updated += 1
                continue

            # Fallback opcional: UPSERT por nombre (solo si el usuario lo pidió)
            if upsert_by_name:
                existing_by_name = (
                    Operator.query.filter_by(client_id=client_id, nombre=data["nombre"])
                    .limit(1)
                    .first()
                )
                if existing_by_name:
                    for k, v in data.items():
                        if k in ("id", "client_id", "codigo"):
                            continue
                        setattr(existing_by_name, k, v)
                    updated += 1
                    continue

            # Crear nuevo
            op = Operator(**data)
            db.session.add(op)
            created += 1

        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()

    except IntegrityError:
        db.session.rollback()
        raise ApiError(
            "Error de integridad al importar (posible código duplicado u otro constraint). "
            "Revisa el archivo y vuelve a intentar.",
            status_code=409,
        )
    except ApiError:
        db.session.rollback()
        raise
    except Exception as e:
        db.session.rollback()
        raise ApiError(f"Error inesperado importando Excel: {e}", status_code=500)

    return {
        "dry_run": dry_run,
        "upsert_by_name": upsert_by_name,
        "total_rows": len(rows),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors_count": len(errors),
        "errors": [{"row": er.row_number, "message": er.message, "data": er.data} for er in errors],
        "preview": preview if dry_run else [],
    }
