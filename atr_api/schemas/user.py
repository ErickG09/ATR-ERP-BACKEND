from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from atr_api.errors import ApiError
from atr_api.models import User

# Áreas permitidas. Por ahora solo usamos "contabilidad" para este módulo,
# pero dejamos otras para futuro.
ALLOWED_AREAS = {
    "contabilidad",
    "trafico",
    "operaciones",
    "direccion",
    "sistemas",
}


def _clean_str(value: Any, field: str, *, required: bool = True, max_len: int = 120) -> str:
    if value is None:
        if required:
            raise ApiError(f"El campo '{field}' es obligatorio.", status_code=400)
        return ""
    s = str(value).strip()
    if required and not s:
        raise ApiError(f"El campo '{field}' es obligatorio.", status_code=400)
    if len(s) > max_len:
        raise ApiError(
            f"El campo '{field}' es demasiado largo (máx {max_len} caracteres).",
            status_code=400,
        )
    return s


def _parse_date(value: Any, field: str) -> Optional[datetime.date]:
    if value in (None, "", "null"):
        return None
    s = str(value).strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(
            f"El campo '{field}' debe tener formato 'YYYY-MM-DD'.",
            status_code=400,
        )


def sanitize_user_create_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Payload para alta de usuario desde tu panel de administración.
    """
    username = _clean_str(payload.get("username"), "username", max_len=64)
    password = _clean_str(payload.get("password"), "password", max_len=255)
    first_name = _clean_str(payload.get("first_name"), "first_name", max_len=80)
    last_name = _clean_str(payload.get("last_name"), "last_name", max_len=80)

    email_raw = payload.get("email")
    email = _clean_str(email_raw, "email", required=False, max_len=120)
    phone = _clean_str(payload.get("phone"), "phone", required=False, max_len=30)

    area_raw = payload.get("area") or "contabilidad"
    area = str(area_raw).strip().lower()
    if area not in ALLOWED_AREAS:
        raise ApiError(
            f"Área inválida '{area}'. Debe ser una de: {', '.join(sorted(ALLOWED_AREAS))}.",
            status_code=400,
        )

    # 👇 aquí aceptamos birth_date o date_of_birth
    raw_dob = payload.get("date_of_birth") or payload.get("birth_date")
    date_of_birth = _parse_date(raw_dob, "date_of_birth")

    age_val = payload.get("age")
    age: Optional[int]
    if age_val in (None, "", "null"):
        age = None
    else:
        try:
            age = int(age_val)
        except (TypeError, ValueError):
            raise ApiError("El campo 'age' debe ser numérico.", status_code=400)
        if age < 0 or age > 120:
            raise ApiError("El campo 'age' debe estar entre 0 y 120.", status_code=400)

    # is_active opcional desde el front (si no, True)
    is_active_val = payload.get("is_active", True)
    is_active = bool(is_active_val)

    return {
        "username": username,
        "password": password,
        "first_name": first_name,
        "last_name": last_name,
        "email": email or None,
        "phone": phone or None,
        "area": area,
        "date_of_birth": date_of_birth,
        "age": age,
        "is_active": is_active,
    }



def sanitize_login_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    username = _clean_str(payload.get("username"), "username", max_len=64)
    password = _clean_str(payload.get("password"), "password", max_len=255)
    return {"username": username, "password": password}


def serialize_user(user: User) -> Dict[str, Any]:
    """
    Lo que va a ver el front (sin password).
    """
    # asegurar que age esté consistente si tenemos fecha de nacimiento
    if user.date_of_birth and user.age is None:
        user.update_age_from_birthdate()

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": user.full_name,
        "date_of_birth": user.date_of_birth.isoformat() if user.date_of_birth else None,
        "age": user.age,
        "area": user.area,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }
