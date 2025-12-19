from __future__ import annotations

from datetime import date

from atr_api.extensions import db


class Car(db.Model):
    __tablename__ = "cars"

    id = db.Column(db.Integer, primary_key=True)

    # Relación con cliente
    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
    )
    client = db.relationship("Client", back_populates="cars")

    # Datos principales del carro
    codigo = db.Column(db.String(20), nullable=False)
    # Ej: CA, FU, NO, UR, HI...
    tipo = db.Column(db.String(10), nullable=False)

    capacidad = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    km_acum = db.Column(db.Numeric(12, 2), nullable=False, server_default="0")

    # Fecha última salida
    fec_u_sal = db.Column(db.Date, nullable=True)

    lt_dies_ac = db.Column(db.Numeric(12, 2), nullable=False, server_default="0")
    ingre_acum = db.Column(db.Numeric(12, 2), nullable=False, server_default="0")

    # Nombre del operador asignado (texto, no FK por ahora)
    operador = db.Column(db.String(120), nullable=False, server_default="")

    # Número de serie (opcional)
    serie = db.Column(db.String(80), nullable=False, server_default="")

    # Baja lógica, por si quieres desactivar sin borrar
    activo = db.Column(db.Boolean, nullable=False, server_default="true")

    __table_args__ = (
        db.UniqueConstraint("client_id", "codigo", name="uq_car_client_codigo"),
    )

    def __repr__(self) -> str:
        return f"<Car id={self.id} codigo={self.codigo!r} client_id={self.client_id}>"
