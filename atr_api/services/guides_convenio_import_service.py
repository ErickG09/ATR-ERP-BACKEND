# atr_api/services/guides_convenio_import_service.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from werkzeug.datastructures import FileStorage
from sqlalchemy.exc import IntegrityError

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models.guide_convenio import GuideConvenio
from atr_api.schemas.guides_convenio_excel_import import parse_excel_guide_convenio


@dataclass
class RowError:
    row_number: int
    message: str
    data: Dict[str, Any]


def _validate_rows_unique(rows: List[Dict[str, Any]]) -> Tuple[List[RowError], Dict[str, int]]:
    """
    Valida duplicados dentro del archivo por destination_codigo.
    """
    errors: List[RowError] = []
    seen: Dict[str, int] = {}

    for r in rows:
        code = str(r["destination_codigo"]).strip().upper()
        seen[code] = seen.get(code, 0) + 1

    for code, count in seen.items():
        if count > 1:
            errors.append(
                RowError(
                    row_number=0,
                    message=f"Duplicado dentro del archivo para destination_codigo={code}.",
                    data={"destination_codigo": code, "count": count},
                )
            )
    return errors, seen


def _delete_all_for_client(client_id: int) -> int:
    return GuideConvenio.query.filter_by(client_id=client_id).delete(synchronize_session=False)


def import_guide_convenio_excel(
    *,
    client_id: int,
    file: FileStorage,
    mode: str = "dry_run",
    replace: bool = False,
    codigo_pad_left: int = 4,
) -> Dict[str, Any]:
    """
    Importa CONVENIO desde Excel.

    Params:
      - mode: "dry_run" | "import"
      - replace:
          False -> UPSERT por (client_id, destination_codigo)
          True  -> borra todo lo del cliente y carga de nuevo
      - codigo_pad_left: padding para claves numéricas (1 -> "0001" si pad=4)

    Return (siempre):
      {
        "ok": bool,
        "mode": str,
        "replace": bool,
        "sheet": str,
        "counts": {...},
        "errors": [...],
        "stats": {...},
        "settings": {...}
      }
    """
    mode = (mode or "").strip().lower()
    if mode not in ("dry_run", "import"):
        raise ApiError("mode inválido. Usa: dry_run | import.", status_code=400)

    parsed = parse_excel_guide_convenio(file, codigo_pad_left=int(codigo_pad_left))
    rows: List[Dict[str, Any]] = list(parsed.get("rows") or [])
    errors: List[Dict[str, Any]] = list(parsed.get("errors") or [])

    # Duplicados dentro del archivo
    dupe_errors, _ = _validate_rows_unique(rows)
    for e in dupe_errors:
        errors.append({"row_number": e.row_number, "message": e.message, "data": e.data})

    if errors:
        return {
            "ok": False,
            "mode": mode,
            "replace": bool(replace),
            "sheet": parsed.get("sheet"),
            "counts": parsed.get("counts"),
            "errors": errors,
            "stats": {"inserted": 0, "updated": 0, "deleted": 0},
            "settings": parsed.get("settings") or {"codigo_pad_left": int(codigo_pad_left)},
        }

    if mode == "dry_run":
        return {
            "ok": True,
            "mode": mode,
            "replace": bool(replace),
            "sheet": parsed.get("sheet"),
            "counts": parsed.get("counts"),
            "errors": [],
            "stats": {"inserted": 0, "updated": 0, "deleted": 0},
            "settings": parsed.get("settings") or {"codigo_pad_left": int(codigo_pad_left)},
        }

    inserted = 0
    updated = 0
    deleted = 0

    try:
        if replace:
            deleted = _delete_all_for_client(client_id)

        codes = {str(r["destination_codigo"]).strip().upper() for r in rows}
        if codes and not replace:
            existing = (
                GuideConvenio.query.filter(GuideConvenio.client_id == client_id)
                .filter(GuideConvenio.destination_codigo.in_(list(codes)))
                .all()
            )
        else:
            existing = []

        existing_map: Dict[str, GuideConvenio] = {
            str(e.destination_codigo).strip().upper(): e for e in existing
        }

        for r in rows:
            code = str(r["destination_codigo"]).strip().upper()
            td = str(r["td"]).strip().upper()
            kms = int(r["kms"])

            destinatario_nombre = r.get("destinatario_nombre")
            ciudad = r.get("ciudad")

            obj = existing_map.get(code)
            if obj is None:
                obj = GuideConvenio(
                    client_id=client_id,
                    destination_codigo=code,
                    td=td,
                    kms=kms,
                    destinatario_nombre=(str(destinatario_nombre).strip() if destinatario_nombre else None),
                    ciudad=(str(ciudad).strip() if ciudad else None),
                    activo=True,
                )
                db.session.add(obj)
                inserted += 1
            else:
                changed = False
                if str(obj.td or "").strip().upper() != td:
                    obj.td = td
                    changed = True
                if int(obj.kms or 0) != kms:
                    obj.kms = kms
                    changed = True

                # opcionales (solo si vienen en el excel)
                if "destinatario_nombre" in r:
                    new_name = str(destinatario_nombre).strip() if destinatario_nombre else None
                    if (obj.destinatario_nombre or None) != new_name:
                        obj.destinatario_nombre = new_name
                        changed = True
                if "ciudad" in r:
                    new_city = str(ciudad).strip() if ciudad else None
                    if (obj.ciudad or None) != new_city:
                        obj.ciudad = new_city
                        changed = True

                if not bool(obj.activo):
                    obj.activo = True
                    changed = True

                if changed:
                    updated += 1

        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        raise ApiError(
            "No se pudo importar CONVENIO por conflicto de datos (duplicados o constraint). "
            "Ejecuta dry_run y corrige el Excel.",
            status_code=409,
        )
    except ApiError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        raise ApiError("Error inesperado al importar CONVENIO.", status_code=500)

    return {
        "ok": True,
        "mode": mode,
        "replace": bool(replace),
        "sheet": parsed.get("sheet"),
        "counts": parsed.get("counts"),
        "errors": [],
        "stats": {"inserted": inserted, "updated": updated, "deleted": deleted},
        "settings": parsed.get("settings") or {"codigo_pad_left": int(codigo_pad_left)},
    }