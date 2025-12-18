# atr_api/utils/seed_clients.py

from __future__ import annotations

from atr_api.wsgi import create_app        # ⬅ usa tu factory de Flask
from atr_api.extensions import db
from atr_api.models.client import Client


# Los clientes base que quieres tener SIEMPRE en la BD
CLIENTS = [
    {"id": 1, "code": "VW",    "name": "Volkswagen"},
    {"id": 2, "code": "AUDI",  "name": "Audi México"},
    {"id": 3, "code": "CUPRA", "name": "CUPRA"},
    {"id": 4, "code": "GM",    "name": "General Motors"},
    {"id": 5, "code": "MAZDA", "name": "Mazda"},
]


def seed_clients() -> None:
    """
    Inserta o actualiza los clientes base en la tabla `clients`.

    - Si el id ya existe, solo actualiza code/name (por si cambian).
    - Si no existe, lo crea.
    """
    app = create_app()

    with app.app_context():
        for data in CLIENTS:
            client = Client.query.filter_by(id=data["id"]).first()

            if client:
                # Actualizamos por si el nombre/código cambian
                client.code = data["code"]
                client.name = data["name"]
            else:
                client = Client(**data)
                db.session.add(client)

        db.session.commit()
        print("✅ Clientes base sembrados/actualizados correctamente.")


if __name__ == "__main__":
    seed_clients()
