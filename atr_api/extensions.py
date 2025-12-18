# atr_api/extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS

db = SQLAlchemy()
migrate = Migrate()
cors = CORS()


def init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)

    origins = app.config.get("CORS_ORIGINS", [])
    if isinstance(origins, str):
        origins = [o.strip() for o in origins.split(",") if o.strip()]

    cors.init_app(
        app,
        resources={r"/*": {"origins": origins or "*"}},
        supports_credentials=False,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )
