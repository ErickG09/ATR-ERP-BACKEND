from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Tuple

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
)


@dataclass
class RowError:
    row_number: int
    message: str
    data: Dict[str, Any]


def import_operators_from_excel(
    *,
    client_id: int,
    file_storage: FileStorage,
    dry_run: bool = False,
    upsert_by_name: bool = False,
) -> Dict[str, Any]:
    """
    Lee un Excel y crea/actualiza operadores.

    - codigo NO se toma del Excel; se genera por apellido inicial + consecutivo (R001…)
    - fecha_ingreso: si no viene, se asigna hoy
    - numéricos vacíos => 0
    - textos vacíos => ""
    - fechas soportan date/datetime, serial de Excel, YYYY-MM-DD, DD/MM/YYYY, etc.
    """
    try:
        rows = parse_excel_operators(file_storage)
    except ApiError:
        raise
    except Exception as e:
        raise ApiError(f"No se pudo leer el Excel: {e}", status_code=400)

    if not rows:
        raise ApiError("El Excel no tiene filas de datos.", status_code=400)

    # Generador de códigos robusto (consulta DB y mantiene contador por inicial)
    code_gen = make_operator_code_generator(client_id=client_id)

    created = 0
    updated = 0
    skipped = 0
    errors: List[RowError] = []

    # Para preview cuando dry_run=1
    preview: List[Dict[str, Any]] = []

    # Transacción
    try:
        for item in rows:
            row_number = item["_row_number"]
            raw_payload = dict(item["payload"])

            # Nombre obligatorio (lo validará sanitize_operator_payload, pero damos error más claro)
            nombre = normalize_full_name(raw_payload.get("nombre", ""))
            if not nombre:
                errors.append(
                    RowError(
                        row_number=row_number,
                        message="El campo 'Nombre' es obligatorio.",
                        data=raw_payload,
                    )
                )
                continue
            raw_payload["nombre"] = nombre

            # fecha_ingreso no venía en tu lista, pero tu modelo la requiere.
            # Solución: si no viene en Excel, asignamos hoy (sin tocar tus schemas actuales).
            if not raw_payload.get("fecha_ingreso"):
                raw_payload["fecha_ingreso"] = date.today().isoformat()

            # Forzamos: codigo siempre vacío => se genera
            raw_payload["codigo"] = ""

            # Normaliza/valida usando TU sanitizer actual
            try:
                data = sanitize_operator_payload(raw_payload, partial=False)
            except ApiError as e:
                errors.append(RowError(row_number=row_number, message=str(e), data=raw_payload))
                continue

            # Asignar client_id
            data["client_id"] = client_id

            # Generar código según primer apellido
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

            if upsert_by_name:
                existing = (
                    Operator.query.filter_by(client_id=client_id, nombre=data["nombre"])
                    .limit(1)
                    .first()
                )
                if existing:
                    # No tocamos codigo existente en upsert
                    for k, v in data.items():
                        if k in ("id", "client_id", "codigo"):
                            continue
                        setattr(existing, k, v)
                    updated += 1
                    continue

            op = Operator(**data)
            db.session.add(op)
            created += 1

        if dry_run:
            # No escribimos en DB
            db.session.rollback()
        else:
            db.session.commit()

    except IntegrityError as e:
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
        "errors": [
            {"row": er.row_number, "message": er.message, "data": er.data} for er in errors
        ],
        "preview": preview if dry_run else [],
    }
