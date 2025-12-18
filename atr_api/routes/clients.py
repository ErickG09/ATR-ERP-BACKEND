from flask import Blueprint, jsonify
from atr_api.models import Client

bp = Blueprint("clients", __name__)


@bp.get("/")
def list_clients():
    """
    Lista de clientes disponibles, usando la tabla `clients`.
    Solo clientes activos.
    """
    clients = (
        Client.query
        .filter_by(is_active=True)
        .order_by(Client.id.asc())
        .all()
    )

    items = [
        {
            "id": c.id,
            "code": c.code,
            "name": c.name,
        }
        for c in clients
    ]

    return jsonify(items)
