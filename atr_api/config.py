# atr_api/config.py
from pathlib import Path
import os
from dotenv import load_dotenv

from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _normalize_db_url(url: str) -> str:
    if not url:
        return url

    # SQLAlchemy prefiere "postgresql://" (no "postgres://")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    parsed = urlparse(url)
    qs = dict(parse_qsl(parsed.query))

    # Forzar sslmode si es Postgres y no viene en la URL
    if parsed.scheme.startswith("postgres") and "sslmode" not in qs:
        qs["sslmode"] = os.getenv("DB_SSLMODE", "require")
        parsed = parsed._replace(query=urlencode(qs))
        url = urlunparse(parsed)

    return url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    raw_db_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'atr_api.db'}")
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(raw_db_url)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    #  Evita conexiones muertas (SSL closed unexpectedly)
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "280")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
    }

    _cors_origins_raw = os.getenv("CORS_ORIGINS", "").strip()
    if _cors_origins_raw:
        CORS_ORIGINS = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
    else:
        CORS_ORIGINS = []

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


class DevelopmentConfig(Config):
    DEBUG = True
    ENV = "development"


class ProductionConfig(Config):
    DEBUG = False
    ENV = "production"


def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()
    if env == "production":
        return ProductionConfig
    return DevelopmentConfig
