# atr_api/models/operator_deduccion_extra.py
from __future__ import annotations

from datetime import datetime
from atr_api.extensions import db


class OperatorDeduccionExtra(db.Model):
    """
    Deducción extra tipo "deuda" por operador:
    - saldo_original: monto inicial
    - saldo_restante: se va reduciendo conforme el contador aplica descuentos en liquidaciones
    En cuanto llega a 0 -> se puede marcar activo = False.
    """
    __tablename__ = "operator_deducciones_extras"

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

    label = db.Column(db.String(140), nullable=False)

    saldo_original = db.Column(db.Numeric(14, 2), nullable=False, server_default="0")
    saldo_restante = db.Column(db.Numeric(14, 2), nullable=False, server_default="0")

    activo = db.Column(db.Boolean, nullable=False, server_default="true")

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index("ix_op_extra_client_operator", "client_id", "operator_id"),
        db.Index("ix_op_extra_active", "client_id", "activo"),
    )

    def __repr__(self) -> str:
        return f"<OperatorDeduccionExtra id={self.id} operator_id={self.operator_id} saldo_restante={self.saldo_restante}>"
