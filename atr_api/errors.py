from flask import jsonify


class ApiError(Exception):
    """Excepción genérica para errores de negocio/controlados."""

    def __init__(self, message: str, status_code: int = 400, extra: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.extra = extra or {}


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        payload = {"error": error.message}
        payload.update(error.extra)
        return jsonify(payload), error.status_code

    @app.errorhandler(404)
    def handle_404(_):
        return jsonify({"error": "Recurso no encontrado"}), 404

    @app.errorhandler(500)
    def handle_500(_):
        return jsonify({"error": "Error interno del servidor"}), 500
