# atr_api/models/talon_series_counter.py

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, event

from atr_api.extensions import db


class TalonSeriesCounter(db.Model):
    """
    Contador por (client_id, folio) para asignación segura de consecutivo en concurrencia.
    seq guarda el último consecutivo utilizado (ej. 35 => próximo sugerido 36).
    """

    __tablename__ = "talon_series_counters"

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Normalizado en mayúsculas (ver listener abajo)
    folio = db.Column(db.String(8), nullable=False)

    # Último número utilizado (no el siguiente)
    seq = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("client_id", "folio", name="uq_talon_counter_client_folio"),
        CheckConstraint("seq >= 0", name="ck_talon_counter_seq_nonneg"),
        Index("ix_talon_counter_client_folio", "client_id", "folio"),
    )

    def __repr__(self) -> str:
        return (
            f"<TalonSeriesCounter "
            f"id={self.id} client_id={self.client_id} "
            f"folio={self.folio} seq={self.seq}>"
        )


# -------------------------------------------------------------------------
# Normalización y timestamps automáticos
# -------------------------------------------------------------------------


@event.listens_for(TalonSeriesCounter, "before_insert")
def _before_insert(mapper, connection, target: TalonSeriesCounter):
    if target.folio:
        target.folio = str(target.folio).strip().upper()
    if target.seq is None or int(target.seq) < 0:
        target.seq = 0
    target.updated_at = datetime.utcnow()


@event.listens_for(TalonSeriesCounter, "before_update")
def _before_update(mapper, connection, target: TalonSeriesCounter):
    if target.folio:
        target.folio = str(target.folio).strip().upper()
    if target.seq is None or int(target.seq) < 0:
        target.seq = 0
    target.updated_at = datetime.utcnow()
