# atr_api/services/guides_factors_import_service.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Tuple

from werkzeug.datastructures import FileStorage
from sqlalchemy.exc import IntegrityError

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models.guide_factor import GuideFactor
from atr_api.schemas.guides_factors_excel_import import parse_excel_guide_factors


@dataclass
class RowError:
    row_number: int
    message: str
    data: Dict[str, Any]


def _as_decimal_money(v: Any) -> Decimal:
    """
    Convierte el string del parser (ej. "20641.60") a Decimal.
    """
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise ApiError("Importe inválido.", status_code=400)


def _validate_rows_unique(rows: List[Dict[str, Any]]) -> Tuple[List[RowError], Dict[Tuple[str, str, int], int]]:
    """
    Valida duplicados dentro del archivo por (carro, td, kms).
    Regresa:
      - errors: lista de RowError
      - seen: dict key->count
    """
    errors: List[RowError] = []
    seen: Dict[Tuple[str, str, int], int] = {}

    # Ojo: el parser ya calculó row_number en errors, pero en rows ya no lo trae.
    # Aquí solo detectamos duplicados lógicos para que no explote el UNIQUE al importar.
    for i, r in enumerate(rows, start=1):
        key = (str(r["carro"]), str(r["td"]), int(r["kms"]))
        seen[key] = seen.get(key, 0) + 1

    for key, count in seen.items():
        if count > 1:
            errors.append(
                RowError(
                    row_number=0,
                    message=f"Duplicado dentro del archivo para (CARRO={key[0]}, TD={key[1]}, KMS={key[2]}).",
                    data={"carro": key[0], "td": key[1], "kms": key[2], "count": count},
                )
            )

    return errors, seen


def _delete_all_for_client(client_id: int) -> int:
    """
    Borra todos los factores del cliente (modo replace).
    Retorna #rows borradas (aprox, depende del driver).
    """
    return GuideFactor.query.filter_by(client_id=client_id).delete(synchronize_session=False)


def import_guide_factors_excel(
    *,
    client_id: int,
    file: FileStorage,
    mode: str = "dry_run",
    replace: bool = False,
) -> Dict[str, Any]:
    """
    Importa FACTORES (tarifas) desde Excel.

    Params:
      - mode: "dry_run" | "import"
      - replace:
          False -> UPSERT por (client_id, carro, td, kms)
          True  -> borra todo lo del cliente y carga de nuevo

    Return (siempre):
      {
        "ok": bool,
        "mode": str,
        "replace": bool,
        "sheet": str,
        "counts": {...},
        "errors": [...],
        "stats": {...}
      }
    """
    mode = (mode or "").strip().lower()
    if mode not in ("dry_run", "import"):
        raise ApiError("mode inválido. Usa: dry_run | import.", status_code=400)

    parsed = parse_excel_guide_factors(file)
    rows: List[Dict[str, Any]] = list(parsed.get("rows") or [])
    errors: List[Dict[str, Any]] = list(parsed.get("errors") or [])

    # Duplicados dentro del archivo por llave lógica
    dupe_errors, _ = _validate_rows_unique(rows)
    for e in dupe_errors:
        errors.append({"row_number": e.row_number, "message": e.message, "data": e.data})

    # Si hay errores de parseo o duplicados, no importamos
    if errors:
        return {
            "ok": False,
            "mode": mode,
            "replace": bool(replace),
            "sheet": parsed.get("sheet"),
            "counts": parsed.get("counts"),
            "errors": errors,
            "stats": {"inserted": 0, "updated": 0, "deleted": 0},
        }

    if mode == "dry_run":
        # Solo preview (sin tocar BD)
        return {
            "ok": True,
            "mode": mode,
            "replace": bool(replace),
            "sheet": parsed.get("sheet"),
            "counts": parsed.get("counts"),
            "errors": [],
            "stats": {"inserted": 0, "updated": 0, "deleted": 0},
        }

    # -------------------------
    # IMPORT real (BD)
    # -------------------------
    inserted = 0
    updated = 0
    deleted = 0

    try:
        if replace:
            deleted = _delete_all_for_client(client_id)

        # Para hacer upsert eficiente, traemos existentes por llaves presentes
        keys = {(r["carro"], r["td"], int(r["kms"])) for r in rows}
        if keys and not replace:
            # cargar existentes para esas llaves
            existing = (
                GuideFactor.query.filter(GuideFactor.client_id == client_id)
                .filter(
                    db.tuple_(GuideFactor.carro, GuideFactor.td, GuideFactor.kms).in_(list(keys))
                )
                .all()
            )
        else:
            existing = []

        existing_map: Dict[Tuple[str, str, int], GuideFactor] = {
            (e.carro, e.td, int(e.kms)): e for e in existing
        }

        for r in rows:
            carro = str(r["carro"]).strip().upper()
            td = str(r["td"]).strip().upper()
            kms = int(r["kms"])
            importe = _as_decimal_money(r["importe"]).quantize(Decimal("0.01"))

            k = (carro, td, kms)
            obj = existing_map.get(k)

            if obj is None:
                obj = GuideFactor(
                    client_id=client_id,
                    carro=carro,
                    td=td,
                    kms=kms,
                    importe=importe,
                    activo=True,
                )
                db.session.add(obj)
                inserted += 1
            else:
                # update si cambió
                changed = False
                if Decimal(obj.importe or 0) != importe:
                    obj.importe = importe
                    changed = True
                if not bool(obj.activo):
                    obj.activo = True
                    changed = True
                if changed:
                    updated += 1

        db.session.commit()

    except IntegrityError:
        db.session.rollback()
        # Si esto ocurre, normalmente es un UNIQUE por duplicados, o data inconsistente
        raise ApiError(
            "No se pudo importar FACTORES por conflicto de datos (duplicados o constraint). "
            "Ejecuta dry_run y corrige el Excel.",
            status_code=409,
        )
    except ApiError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        raise ApiError("Error inesperado al importar FACTORES.", status_code=500)

    return {
        "ok": True,
        "mode": mode,
        "replace": bool(replace),
        "sheet": parsed.get("sheet"),
        "counts": parsed.get("counts"),
        "errors": [],
        "stats": {"inserted": inserted, "updated": updated, "deleted": deleted},
    }