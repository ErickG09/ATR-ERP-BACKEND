from flask import Flask


def register_blueprints(app: Flask) -> None:
    """Registra todos los blueprints de la API."""

    from .clients import bp as clients_bp
    from .operators import bp as operators_bp
    from .cars import bp as cars_bp
    from .car_types import bp as car_types_bp
    from .auth import bp as auth_bp
    from .destinations import bp as destinations_bp
    from .guides import bp as guides_bp
    from .liquidaciones import liquidaciones_bp

    # Clientes “catálogo”
    app.register_blueprint(clients_bp, url_prefix="/api/clients")

    # Operadores, carros y tipos de carro
    app.register_blueprint(operators_bp, url_prefix="/api")
    app.register_blueprint(cars_bp, url_prefix="/api")
    app.register_blueprint(car_types_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api")
    app.register_blueprint(destinations_bp, url_prefix="/api")
    app.register_blueprint(guides_bp, url_prefix="/api")
    app.register_blueprint(liquidaciones_bp)