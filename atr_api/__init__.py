from __future__ import annotations

from flask import Flask
from flask_cors import CORS

from .config import get_config
from .extensions import db, migrate
from .routes import register_blueprints
from .errors import register_error_handlers


def create_app() -> Flask:
    config_class = get_config()

    app = Flask(__name__)
    app.config.from_object(config_class)

    # ---------------------------------------------------------------------
    # Extensiones
    # ---------------------------------------------------------------------
    db.init_app(app)
    migrate.init_app(app, db)

    # ---------------------------------------------------------------------
    # CORS (CLAVE para Authorization header desde Next.js)
    # ---------------------------------------------------------------------
    cors_origins = app.config.get("CORS_ORIGINS") or [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Si NO usas cookies/sesión por cookie y todo es Bearer token,
    # supports_credentials debe ser False (recomendado).
    # Si algún día usas cookies, cámbialo a True y ajusta el front con credentials: "include".
    CORS(
        app,
        resources={r"/api/*": {"origins": cors_origins}},
        methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "Accept",
            "Origin",
            "X-Requested-With",
        ],
        expose_headers=[
            "Authorization",
        ],
        supports_credentials=False,
        max_age=86400,  # cachea el preflight 24h (reduce llamadas OPTIONS)
    )

    # ---------------------------------------------------------------------
    # Blueprints
    # ---------------------------------------------------------------------
    register_blueprints(app)

    # ---------------------------------------------------------------------
    # Manejadores de errores (ApiError, 404, 500)
    # ---------------------------------------------------------------------
    register_error_handlers(app)

    return app
