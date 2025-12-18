from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from atr_api.extensions import db
from atr_api.errors import ApiError
from atr_api.models import User
from atr_api.schemas.user import (
    sanitize_login_payload,
    sanitize_user_create_payload,
    serialize_user,
)
from atr_api.security import (
    create_access_token,
    hash_password,
    verify_password,
    get_current_user,
    login_required,
)

bp = Blueprint("auth", __name__)


# -------------------------------------------------------------------------
# POST /api/auth/register
# Alta de usuario (para tu panel de administración).
# -------------------------------------------------------------------------
@bp.post("/auth/register")
def register_user():
    json_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not json_data:
        raise ApiError("Se requiere un cuerpo JSON.", status_code=400)

    data = sanitize_user_create_payload(json_data)

    # Verificar que username / email no estén tomados
    if User.query.filter_by(username=data["username"]).first():
        raise ApiError("El nombre de usuario ya está en uso.", status_code=400)

    if data.get("email") and User.query.filter_by(email=data["email"]).first():
        raise ApiError("El correo ya está registrado.", status_code=400)

    user = User(
        username=data["username"],
        email=data["email"],
        phone=data["phone"],
        first_name=data["first_name"],
        last_name=data["last_name"],
        area=data["area"],
        date_of_birth=data["date_of_birth"],
        age=data["age"],
        is_active=True,
    )
    user.update_age_from_birthdate()
    user.password_hash = hash_password(data["password"])

    try:
        db.session.add(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError(
            "Error al guardar el usuario. Verifica que el usuario/correo no estén duplicados.",
            status_code=500,
        )

    token = create_access_token(user)
    return jsonify({"user": serialize_user(user), "access_token": token}), 201


# -------------------------------------------------------------------------
# POST /api/auth/login
# Login con usuario + contraseña.
# -------------------------------------------------------------------------

@bp.post("/auth/login")
def login():
    json_data: Dict[str, Any] = request.get_json(silent=True) or {}
    if not json_data:
        raise ApiError("Se requiere un cuerpo JSON.", status_code=400)

    data = sanitize_login_payload(json_data)

    user = User.query.filter_by(username=data["username"]).first()
    if not user or not verify_password(user.password_hash, data["password"]):
        # Respuesta genérica para no revelar si existe o no
        raise ApiError("Usuario o contraseña incorrectos.", status_code=401)

    if not user.is_active:
        raise ApiError("El usuario está inactivo. Contacta al administrador.", status_code=403)

    # 👇 Sólo dejamos pasar área contabilidad
    if user.area != "contabilidad":
        raise ApiError(
            "Área no permitida para este módulo. Solo usuarios de Contabilidad pueden iniciar sesión aquí.",
            status_code=403,
        )

    token = create_access_token(user)
    return jsonify({"user": serialize_user(user), "access_token": token}), 200



# -------------------------------------------------------------------------
# GET /api/auth/me
# Devuelve el usuario actual usando el token Bearer.
# -------------------------------------------------------------------------
@bp.get("/auth/me")
@login_required
def me():
    user = get_current_user()
    return jsonify({"user": serialize_user(user)})
