# atr_api/models/operator_imss.py

from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import relationship

from atr_api.extensions import db


class OperatorIMSS(db.Model):
    """
    Cuota IMSS mensual por operador.

    Un registro por:
        (client_id, operator_id, year, month)

    Esto permite:
    - Mantener histórico por mes/año
    - Reimportar Excel y actualizar el mismo mes sin duplicar
    """

    __tablename__ = "operator_imss"

    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "operator_id",
            "year",
            "month",
            name="uq_operator_imss_client_operator_period",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    operator_id = db.Column(
        db.Integer,
        db.ForeignKey("operators.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=False, index=True)  # 1-12

    monto = db.Column(db.Numeric(12, 2), nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relaciones
    operator = relationship("Operator", backref="imss_cuotas")
    client = relationship("Client")

    def __repr__(self) -> str:
        return (
            f"<OperatorIMSS client={self.client_id} "
            f"operator={self.operator_id} "
            f"{self.year}-{self.month:02d} monto={self.monto}>"
        )
