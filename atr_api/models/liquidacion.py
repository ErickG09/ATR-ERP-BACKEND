# atr_api/models/liquidacion.py
from datetime import datetime, date
from sqlalchemy import CheckConstraint, UniqueConstraint, Index

from atr_api.extensions import db


LIQ_STATUS_CHOICES = ("draft", "posted", "liquidated", "cancelled")


class Liquidacion(db.Model):
    __tablename__ = "liquidaciones"

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)

    # consecutivo real por cliente (único y seguro para concurrencia)
    folio_num = db.Column(db.Integer, nullable=False)

    # folio "humano" (ej: L00001). Lo guardamos para búsqueda/legibilidad.
    folio = db.Column(db.String(32), nullable=False)

    fecha = db.Column(db.Date, nullable=False, default=date.today)

    operator_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=True)
    destination_id = db.Column(db.Integer, db.ForeignKey("destinations.id"), nullable=True)

    # Tipo de carro (CA/FU/NO/UR/HI) - texto para no romper si agregas nuevos
    car_type = db.Column(db.String(8), nullable=True)

    # Captura base
    kms = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    tarifa = db.Column(db.Numeric(14, 4), nullable=False, default=0)

    # Cálculos
    subtotal = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    aplica_iva = db.Column(db.Boolean, nullable=False, default=False)
    iva_pct = db.Column(db.Numeric(6, 2), nullable=False, default=0)
    iva_monto = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    aplica_retencion = db.Column(db.Boolean, nullable=False, default=False)
    retencion_pct = db.Column(db.Numeric(6, 2), nullable=False, default=0)
    retencion_monto = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    # Total "fiscal/comercial" (no lo rompemos)
    total = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    #  NUEVO: total deducciones del operador (suma de liquidacion_deducciones)
    deducciones_total = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    #  NUEVO: neto operador = subtotal - deducciones_total
    neto_operador = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    status = db.Column(db.String(16), nullable=False, default="draft")
    observaciones = db.Column(db.Text, nullable=True)

    activo = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)


    pagado = db.Column(db.Boolean, nullable=False, default=False)
    pagado_at = db.Column(db.DateTime, nullable=True)
    
    #  Relación: deducciones por liquidación (tabla hija)
    deducciones = db.relationship(
        "LiquidacionDeduccion",
        backref="liquidacion",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LiquidacionDeduccion.id",
    )

    __table_args__ = (
        UniqueConstraint("client_id", "folio_num", name="uq_liq_client_folio_num"),
        UniqueConstraint("client_id", "folio", name="uq_liq_client_folio"),
        CheckConstraint(
            f"status IN {LIQ_STATUS_CHOICES}",
            name="ck_liq_status_valid",
        ),
        Index("ix_liq_client_fecha", "client_id", "fecha"),
        Index("ix_liq_client_status", "client_id", "status"),
        Index("ix_liq_client_activo", "client_id", "activo"),
    )

    def recalc_totals(self):
        kms = float(self.kms or 0)
        tarifa = float(self.tarifa or 0)
        subtotal = kms * tarifa

        iva_pct = float(self.iva_pct or 0)
        ret_pct = float(self.retencion_pct or 0)

        iva_monto = subtotal * (iva_pct / 100.0) if self.aplica_iva else 0.0
        ret_monto = subtotal * (ret_pct / 100.0) if self.aplica_retencion else 0.0

        total = subtotal + iva_monto - ret_monto

        

        #  deducciones (operador)
        ded_total = 0.0
        try:
            for d in (self.deducciones or []):
                ded_total += float(getattr(d, "monto", 0) or 0)
        except Exception:
            ded_total = 0.0

        neto_operador = subtotal - ded_total

        self.subtotal = round(subtotal, 2)
        self.iva_monto = round(iva_monto, 2)
        self.retencion_monto = round(ret_monto, 2)
        self.total = round(total, 2)

        self.deducciones_total = round(ded_total, 2)
        self.neto_operador = round(neto_operador, 2)

    @staticmethod
    def format_folio(folio_num: int) -> str:
        return f"L{int(folio_num):05d}"
