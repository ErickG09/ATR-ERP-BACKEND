# atr_api/models/liquidacion_deduccion.py

from datetime import datetime
from sqlalchemy import CheckConstraint, Index
from atr_api.extensions import db


class LiquidacionDeduccion(db.Model):
    __tablename__ = "liquidacion_deducciones"

    id = db.Column(db.Integer, primary_key=True)

    liquidacion_id = db.Column(
        db.Integer,
        db.ForeignKey("liquidaciones.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 1 = operador principal, 2 = operador segundo
    operator_slot = db.Column(db.Integer, nullable=False, default=1)

    key = db.Column(db.String(64), nullable=True)
    label = db.Column(db.String(120), nullable=False)
    monto = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("operator_slot IN (1,2)", name="ck_liq_ded_slot_valid"),
        CheckConstraint("monto >= 0", name="ck_liq_ded_monto_nonneg"),
        Index("ix_liq_ded_liq_created", "liquidacion_id", "created_at"),
        Index("ix_liq_ded_liq_slot", "liquidacion_id", "operator_slot"),
    )
