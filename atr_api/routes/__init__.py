from flask import Flask

def register_blueprints(app: Flask) -> None:
    from .clients import bp as clients_bp
    from .operators import bp as operators_bp
    from .cars import bp as cars_bp
    from .car_types import bp as car_types_bp
    from .auth import bp as auth_bp
    from .destinations import bp as destinations_bp
    from .guides import bp as guides_bp
    from .liquidaciones import liquidaciones_bp
    from .operators_import import bp as operators_import_bp
    from .cars_import import bp as cars_import_bp
    from .destinations_import import bp as destinations_import_bp
    from .deducciones import bp as deducciones_bp

    app.register_blueprint(clients_bp, url_prefix="/api/clients")

    app.register_blueprint(operators_bp, url_prefix="/api")
    app.register_blueprint(cars_bp, url_prefix="/api")
    app.register_blueprint(car_types_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api")
    app.register_blueprint(destinations_bp, url_prefix="/api")
    app.register_blueprint(guides_bp, url_prefix="/api")

    app.register_blueprint(liquidaciones_bp)   # ✅ ya trae /api/clients/... en su blueprint
    app.register_blueprint(deducciones_bp)     # ✅ ya trae /api/clients/... en su blueprint

    app.register_blueprint(operators_import_bp, url_prefix="/api")
    app.register_blueprint(cars_import_bp, url_prefix="/api")
    app.register_blueprint(destinations_import_bp, url_prefix="/api")
