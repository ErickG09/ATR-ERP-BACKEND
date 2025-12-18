from __future__ import annotations

from atr_api.extensions import db


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, server_default="true")

    # Relación con operadores
    operators = db.relationship(
        "Operator",
        back_populates="client",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    # Relación con carros
    cars = db.relationship(
        "Car",
        back_populates="client",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    # Relación con configuración de tipos de carro (tarifas)
    car_type_configs = db.relationship(
        "CarTypeConfig",
        back_populates="client",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    destinations = db.relationship(
        "Destination",
        back_populates="client",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    guides = db.relationship(
        "Guide",
        back_populates="client",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


    def __repr__(self) -> str:  # solo para debug
        return f"<Client id={self.id} code={self.code!r}>"
