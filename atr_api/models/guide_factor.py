# atr_api/models/guide_factor.py
from __future__ import annotations

from atr_api.extensions import db


class GuideFactor(db.Model):
    """
    Tabla de tarifas (FACTORES.xls) por cliente.

    Clave lógica:
      (client_id, carro, td, kms) -> importe

    Donde:
      - carro: tipo de unidad (CA/UR/HI/NO/...)
      - td: tipo destino (P/E/I/IV/M/L/PA/RE/EL/ET/IM/...)
      - kms: entero (según FACTORES)
      - importe: numeric(12,2) (lo que en tu UI llamas tarifa)
    """

    __tablename__ = "guide_factors"

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client = db.relationship("Client")  # opcional: back_populates si lo quieres

    carro = db.Column(db.String(10), nullable=False)  # ej: "CA"
    td = db.Column(db.String(10), nullable=False)  # ej: "E", "IV", "EL", etc.
    kms = db.Column(db.Integer, nullable=False)  # entero, sin decimales
    importe = db.Column(db.Numeric(12, 2), nullable=False)  # tarifa/importe

    activo = db.Column(db.Boolean, nullable=False, server_default="true")

    __table_args__ = (
        db.UniqueConstraint(
            "client_id", "carro", "td", "kms", name="uq_guide_factors_client_carro_td_kms"
        ),
        db.Index("ix_guide_factors_lookup", "client_id", "carro", "td", "kms"),
        db.CheckConstraint("kms >= 0", name="ck_guide_factors_kms_nonneg"),
        db.CheckConstraint("importe >= 0", name="ck_guide_factors_importe_nonneg"),
    )

    def __repr__(self) -> str:
        return (
            f"<GuideFactor id={self.id} client_id={self.client_id} "
            f"carro={self.carro!r} td={self.td!r} kms={self.kms} importe={self.importe}>"
        )