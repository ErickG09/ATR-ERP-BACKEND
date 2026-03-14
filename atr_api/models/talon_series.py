# atr_api/models/talon_series.py

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from atr_api.extensions import db


class TalonSeries(db.Model):
    """
    Catálogo de series/prefijos de talón interno por cliente del sistema.
    Ej:
      client_id = 1 (VWM)
      folio = "VWP"
      cliente_nombre = "VOLKS WAGEN PUEBLA"
      padding = 5  -> VWP00001

     Ajuste: padding permitido hasta 12 (si decides generar con ceros),
    pero esto NO obliga a mostrar 12 ceros: solo amplía el límite permitido.
    """

    __tablename__ = "talon_series"

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Prefijo/clave del talón (VWP, ESP, etc.)
    folio = db.Column(db.String(8), nullable=False)

    # Nombre descriptivo (opcional): "VOLKS WAGEN PUEBLA"
    cliente_nombre = db.Column(db.String(120), nullable=True)

    # Cantidad de dígitos del consecutivo (default 5 => 00001)
    # (si tu flujo actual deja de ser automático, quizá no lo uses por ahora)
    padding = db.Column(db.Integer, nullable=False, default=5)

    activo = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("client_id", "folio", name="uq_talon_series_client_folio"),
        #  permitir hasta 12 (antes 10)
        CheckConstraint("padding >= 1 AND padding <= 12", name="ck_talon_series_padding"),
        Index("ix_talon_series_client_activo", "client_id", "activo"),
        Index("ix_talon_series_client_folio", "client_id", "folio"),
    )

    def __repr__(self) -> str:
        return f"<TalonSeries id={self.id} client_id={self.client_id} folio={self.folio}>"