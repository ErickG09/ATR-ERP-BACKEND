from __future__ import annotations

import datetime as dt
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
    if not secret:
        raise RuntimeError("SECRET_KEY no está configurado en la app.")
    return secret


def create_access_token(user: User, *, expires_in: int = 3600) -> str:
    """
    Crea un token de acceso (JWT) con vencimiento (por defecto 1h).
    """
    now = dt.datetime.utcnow()
    payload: Dict[str, Any] = {
        "sub": user.id,
        "username": user.username,
        "area": user.area,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm="HS256")
    # pyjwt>=2 devuelve str en Python3
    return token


def decode_token(token: str) -> Dict[str, Any]:
    try:
        data = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
        return data
    except jwt.ExpiredSignatureError:
        raise ApiError("El token ha expirado. Inicia sesión de nuevo.", status_code=401)
    except jwt.InvalidTokenError:
        raise ApiError("Token inválido.", status_code=401)


def get_current_user() -> User:
    """
    Lee el header Authorization: Bearer <token> y regresa el usuario.
    """
    auth_header = request.headers.get("Authorization", "").strip()
    if not auth_header.startswith("Bearer "):
        raise ApiError("Falta encabezado Authorization.", status_code=401)

    token = auth_header.split(" ", 1)[1]
    data = decode_token(token)

    user_id = data.get("sub")
    if not user_id:
        raise ApiError("Token inválido (sin usuario).", status_code=401)

    user: Optional[User] = User.query.get(int(user_id))
    if not user or not user.is_active:
        raise ApiError("Usuario no encontrado o inactivo.", status_code=401)

    g.current_user = user
    return user


# Decorador para proteger endpoints más adelante (cuando segmentes módulos)
from functools import wraps  # noqa: E402


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        get_current_user()
        return fn(*args, **kwargs)

    return wrapper
