# atr_api/models/guide_convenio.py
from __future__ import annotations

from atr_api.extensions import db


class GuideConvenio(db.Model):
    """
    Tabla de convenio (CONVENIO.xls) por cliente.

    Clave lógica:
      (client_id, destination_codigo) -> (kms, td, ...)

    Donde:
      - destination_codigo: coincide con Destination.codigo (normalizado, ej. "0001")
      - kms: entero (sin decimales)
      - td: tipo destino (E/I/IV/IM/EL/ET/etc.)
    """

    __tablename__ = "guide_convenios"

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client = db.relationship("Client")  # opcional: back_populates si lo quieres

    destination_codigo = db.Column(db.String(20), nullable=False)  # ej: "0001"
    td = db.Column(db.String(10), nullable=False)  # ej: "E", "IV", "EL", etc.
    kms = db.Column(db.Integer, nullable=False)  # entero, sin decimales

    # Campos opcionales solo para referencia (no se usan para cálculo)
    destinatario_nombre = db.Column(db.String(180), nullable=True)
    ciudad = db.Column(db.String(80), nullable=True)

    activo = db.Column(db.Boolean, nullable=False, server_default="true")

    __table_args__ = (
        db.UniqueConstraint(
            "client_id",
            "destination_codigo",
            name="uq_guide_convenios_client_destination_codigo",
        ),
        db.Index(
            "ix_guide_convenios_lookup",
            "client_id",
            "destination_codigo",
        ),
        db.CheckConstraint("kms >= 0", name="ck_guide_convenios_kms_nonneg"),
    )

    def __repr__(self) -> str:
        return (
            f"<GuideConvenio id={self.id} client_id={self.client_id} "
            f"destination_codigo={self.destination_codigo!r} td={self.td!r} kms={self.kms}>"
        )