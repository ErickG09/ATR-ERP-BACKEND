# atr_api/models/destination.py
from __future__ import annotations

from atr_api.extensions import db


class Destination(db.Model):
    __tablename__ = "destinations"

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 👇 ESTO ES LO QUE TE FALTA (para que exista Destination.client)
    client = db.relationship("Client", back_populates="destinations")

    codigo = db.Column(db.String(20), nullable=False)
    nombre = db.Column(db.String(180), nullable=False)

    plaza = db.Column(db.String(80), nullable=True)
    ciudad = db.Column(db.String(80), nullable=True)
    estado = db.Column(db.String(80), nullable=True)

    aplica_iva = db.Column(db.Boolean, nullable=False, server_default="true")
    iva_pct = db.Column(db.Numeric(6, 2), nullable=False, server_default="16")

    aplica_retencion = db.Column(db.Boolean, nullable=False, server_default="false")
    retencion_pct = db.Column(db.Numeric(6, 2), nullable=False, server_default="0")

    activo = db.Column(db.Boolean, nullable=False, server_default="true")

    __table_args__ = (
        db.UniqueConstraint("client_id", "codigo", name="uq_destination_client_codigo"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "client_id": self.client_id,
            "codigo": self.codigo,
            "nombre": self.nombre,
            "plaza": self.plaza,
            "ciudad": self.ciudad,
            "estado": self.estado,
            "aplica_iva": bool(self.aplica_iva),
            "iva_pct": float(self.iva_pct or 0),
            "aplica_retencion": bool(self.aplica_retencion),
            "retencion_pct": float(self.retencion_pct or 0),
            "activo": bool(self.activo),
        }
