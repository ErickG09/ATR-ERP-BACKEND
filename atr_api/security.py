from __future__ import annotations

import datetime as dt
from functools import wraps
from typing import Any, Dict, Optional

import jwt
from flask import current_app, g, request
from werkzeug.security import check_password_hash, generate_password_hash

from atr_api.errors import ApiError
from atr_api.models import User


# ---------------------------------------------------------
# Password hashing
# ---------------------------------------------------------

def hash_password(password: str) -> str:
    """
    Hashea la contraseña usando PBKDF2+SHA256 con salt aleatorio.
    """
    if not password or len(password) < 6:
        raise ApiError("La contraseña debe tener al menos 6 caracteres.", status_code=400)
    return generate_password_hash(password, method="pbkdf2:sha256", salt_length=16)


def verify_password(pwhash: str, password: str) -> bool:
    if not pwhash or not password:
        return False
    return check_password_hash(pwhash, password)


# ---------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------

def _jwt_secret() -> str:
    secret = current_app.config.get("SECRET_KEY")
    if not secret or not isinstance(secret, str):
        raise ApiError("SECRET_KEY no está configurado en la app.", status_code=500)
    return secret


def _jwt_algo() -> str:
    algo = current_app.config.get("JWT_ALGORITHM", "HS256")
    return algo


def _jwt_expires_seconds() -> int:
    try:
        return int(current_app.config.get("JWT_EXPIRES_SECONDS", 3600))
    except Exception:
        return 3600


def create_access_token(user: User, *, expires_in: Optional[int] = None) -> str:
    """
    Crea un token de acceso (JWT) con vencimiento.
    Nota clave:
      - sub debe ser STRING para compatibilidad con validaciones de PyJWT.
    """
    now = dt.datetime.now(dt.timezone.utc)
    ttl = int(expires_in if expires_in is not None else _jwt_expires_seconds())

    payload: Dict[str, Any] = {
        "sub": str(user.id),  # <- CLAVE: string, no int
        "username": user.username,
        "area": user.area,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(seconds=ttl)).timestamp()),
    }

    token = jwt.encode(payload, _jwt_secret(), algorithm=_jwt_algo())
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def decode_token(token: str) -> Dict[str, Any]:
    try:
        data = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[_jwt_algo()],
            options={"require": ["exp", "sub"]},
        )
        if not isinstance(data, dict):
            raise ApiError("Token inválido.", status_code=401)
        return data
    except jwt.ExpiredSignatureError:
        raise ApiError("El token ha expirado. Inicia sesión de nuevo.", status_code=401)
    except jwt.InvalidTokenError:
        raise ApiError("Token inválido.", status_code=401)


def _extract_bearer_token() -> str:
    """
    Espera: Authorization: Bearer <token>
    """
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header:
        raise ApiError("Falta encabezado Authorization.", status_code=401)

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ApiError("Authorization inválido. Usa: Bearer <token>", status_code=401)

    token = parts[1].strip()
    if not token:
        raise ApiError("Token vacío.", status_code=401)

    return token


def get_current_user() -> User:
    """
    Lee el header Authorization: Bearer <token> y regresa el usuario.
    """
    token = _extract_bearer_token()
    data = decode_token(token)

    user_id_raw = data.get("sub")
    if not user_id_raw:
        raise ApiError("Token inválido (sin usuario).", status_code=401)

    try:
        user_id = int(user_id_raw)  # sub viene string, aquí lo convertimos
    except (TypeError, ValueError):
        raise ApiError("Token inválido (usuario inválido).", status_code=401)

    user: Optional[User] = User.query.get(user_id)
    if not user:
        raise ApiError("Usuario no encontrado.", status_code=401)
    if not user.is_active:
        raise ApiError("Usuario no encontrado o inactivo.", status_code=401)

    g.current_user = user
    return user


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        get_current_user()
        return fn(*args, **kwargs)

    return wrapper
