# atr_api/models/liquidacion_detalle.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from atr_api.extensions import db


class LiquidacionDetalle(db.Model):
    """
    Renglones/detalles por viaje.

    Objetivo:
      1 Liquidacion (talón) = N LiquidacionDetalle (renglones del Excel)
    """

    __tablename__ = "liquidacion_detalles"

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)

    liquidacion_id = db.Column(
        db.Integer,
        db.ForeignKey("liquidaciones.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Para trazabilidad del import (fila original del Excel)
    row_number = db.Column(db.Integer, nullable=True)

    # Datos del renglón (según tu Excel)
    fecha = db.Column(db.Date, nullable=True)
    factura_cp = db.Column(db.String(64), nullable=True)

    carro = db.Column(db.String(64), nullable=True)
    dealer = db.Column(db.String(160), nullable=True)

    unidades = db.Column(db.Integer, nullable=True)
    kms = db.Column(db.Numeric(12, 2), nullable=True)

    operador_1 = db.Column(db.String(120), nullable=True)
    operador_2 = db.Column(db.String(120), nullable=True)

    flete = db.Column(db.Numeric(14, 2), nullable=True)
    iva = db.Column(db.Numeric(14, 2), nullable=True)
    retencion = db.Column(db.Numeric(14, 2), nullable=True)
    total = db.Column(db.Numeric(14, 2), nullable=True)

    anticipo_1 = db.Column(db.Numeric(14, 2), nullable=True)
    recibo_1 = db.Column(db.String(64), nullable=True)

    anticipo_2 = db.Column(db.Numeric(14, 2), nullable=True)
    recibo_2 = db.Column(db.String(64), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        # Coherencia mínima
        CheckConstraint(
            "unidades IS NULL OR unidades >= 0",
            name="ck_liqdet_unidades_nonneg",
        ),
        CheckConstraint(
            "kms IS NULL OR kms >= 0",
            name="ck_liqdet_kms_nonneg",
        ),
        # Montos no negativos (opcionales pero recomendables)
        CheckConstraint(
            "flete IS NULL OR flete >= 0",
            name="ck_liqdet_flete_nonneg",
        ),
        CheckConstraint(
            "iva IS NULL OR iva >= 0",
            name="ck_liqdet_iva_nonneg",
        ),
        CheckConstraint(
            "retencion IS NULL OR retencion >= 0",
            name="ck_liqdet_retencion_nonneg",
        ),
        CheckConstraint(
            "total IS NULL OR total >= 0",
            name="ck_liqdet_total_nonneg",
        ),
        CheckConstraint(
            "anticipo_1 IS NULL OR anticipo_1 >= 0",
            name="ck_liqdet_anticipo1_nonneg",
        ),
        CheckConstraint(
            "anticipo_2 IS NULL OR anticipo_2 >= 0",
            name="ck_liqdet_anticipo2_nonneg",
        ),
        # Evita duplicar el mismo renglón del Excel dentro de una misma liquidación
        UniqueConstraint(
            "liquidacion_id",
            "row_number",
            name="uq_liqdet_liquidacion_row_number",
        ),
        # Índices para consultas típicas
        Index("ix_liqdet_client_liquidacion", "client_id", "liquidacion_id"),
        Index("ix_liqdet_liquidacion_id", "liquidacion_id"),
        Index("ix_liqdet_client_factura_cp", "client_id", "factura_cp"),
    )