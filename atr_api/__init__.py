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

    # Extensiones
    db.init_app(app)
    migrate.init_app(app, db)

    cors_origins = app.config.get("CORS_ORIGINS") or [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    CORS(
        app,
        resources={r"/api/*": {"origins": cors_origins}},
        methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS", "PUT"],
        allow_headers=["Content-Type", "Authorization"],
    )
    # ---------------------------------

    # Blueprints
    register_blueprints(app)

    # Manejadores de errores (ApiError, 404, 500)
    register_error_handlers(app)

    return app
