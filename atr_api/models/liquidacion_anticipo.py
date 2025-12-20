# atr_api/models/liquidacion_anticipo.py

from datetime import datetime
from sqlalchemy import CheckConstraint, Index
from atr_api.extensions import db


class LiquidacionAnticipo(db.Model):
    __tablename__ = "liquidacion_anticipos"

    id = db.Column(db.Integer, primary_key=True)

    liquidacion_id = db.Column(
        db.Integer,
        db.ForeignKey("liquidaciones.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 1 = operador principal, 2 = operador segundo
    operator_slot = db.Column(db.Integer, nullable=False, default=1)

    # Guardamos también operator_id “snapshot” para auditoría/histórico
    operator_id = db.Column(
        db.Integer,
        db.ForeignKey("operators.id"),
        nullable=True,
        index=True,
    )

    importe = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    recibo = db.Column(db.String(64), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("operator_slot IN (1,2)", name="ck_liq_ant_slot_valid"),
        CheckConstraint("importe >= 0", name="ck_liq_ant_importe_nonneg"),
        Index("ix_liq_ant_liq_slot", "liquidacion_id", "operator_slot"),
    )
