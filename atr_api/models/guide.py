# atr_api/models/guide.py
from __future__ import annotations

from atr_api.extensions import db


class Guide(db.Model):
    __tablename__ = "guides"

    id = db.Column(db.Integer, primary_key=True)

    # Segmentación por cliente
    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client = db.relationship("Client", back_populates="guides")

    # Relaciones principales
    operator_id = db.Column(
        db.Integer,
        db.ForeignKey("operators.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    operator = db.relationship("Operator", back_populates="guides")

    car_id = db.Column(
        db.Integer,
        db.ForeignKey("cars.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    car = db.relationship("Car")  # no necesitas back_populates si no lo usarás

    destination_id = db.Column(
        db.Integer,
        db.ForeignKey("destinations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    destination = db.relationship("Destination")

    # Datos de la guía
    folio = db.Column(db.String(30), nullable=False)  # folio / no. guía
    fecha = db.Column(db.Date, nullable=False, index=True)

    # Tipo de carro usado para tarifas (ej: "CA", "FU", etc.)
    car_type = db.Column(db.String(10), nullable=False, server_default="")

    # Datos numéricos típicos para liquidación (ajusta a tu lógica)
    kms = db.Column(db.Numeric(12, 2), nullable=False, server_default="0")
    tarifa = db.Column(db.Numeric(12, 2), nullable=False, server_default="0")
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, server_default="0")

    aplica_iva = db.Column(db.Boolean, nullable=False, server_default="false")
    iva_pct = db.Column(db.Numeric(6, 2), nullable=False, server_default="0")
    iva_monto = db.Column(db.Numeric(12, 2), nullable=False, server_default="0")

    aplica_retencion = db.Column(db.Boolean, nullable=False, server_default="false")
    retencion_pct = db.Column(db.Numeric(6, 2), nullable=False, server_default="0")
    retencion_monto = db.Column(db.Numeric(12, 2), nullable=False, server_default="0")

    total = db.Column(db.Numeric(12, 2), nullable=False, server_default="0")

    # Estatus: draft | posted | liquidated | cancelled
    status = db.Column(db.String(20), nullable=False, server_default="draft", index=True)

    observaciones = db.Column(db.Text, nullable=True)

    # Control simple (tu estilo actual no usa created_at en otros modelos, así que lo omito)
    activo = db.Column(db.Boolean, nullable=False, server_default="true")

    __table_args__ = (
        db.UniqueConstraint("client_id", "folio", name="uq_guide_client_folio"),
        db.Index("ix_guides_client_operator_date", "client_id", "operator_id", "fecha"),
    )

    def __repr__(self) -> str:
        return f"<Guide id={self.id} folio={self.folio!r} client_id={self.client_id}>"
