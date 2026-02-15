# atr_api/models/liquidacion.py
from datetime import datetime, date

from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from atr_api.extensions import db

LIQ_STATUS_CHOICES = ("draft", "posted", "liquidated", "cancelled")


class Liquidacion(db.Model):
    __tablename__ = "liquidaciones"

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)

    folio_num = db.Column(db.Integer, nullable=False)
    folio = db.Column(db.String(32), nullable=False)

    # -------------------------
    # Talón interno (nuevo flujo)
    # -------------------------
    # Display final (ej. ESP00036)
    talon_interno = db.Column(db.String(64), nullable=True)

    # Prefijo/folio del talón (ej. "ESP") para consultas y orden
    talon_folio = db.Column(db.String(8), nullable=True)

    # Consecutivo numérico del talón (ej. 36)
    talon_seq = db.Column(db.Integer, nullable=True)

    fecha = db.Column(db.Date, nullable=False, default=date.today)

    # Operadores
    operator_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=False)
    operator2_id = db.Column(db.Integer, db.ForeignKey("operators.id"), nullable=True)

    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=True)
    destination_id = db.Column(db.Integer, db.ForeignKey("destinations.id"), nullable=True)

    car_type = db.Column(db.String(8), nullable=True)

    # Captura base (la conservamos)
    kms = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    tarifa = db.Column(db.Numeric(14, 4), nullable=False, default=0)

    # Cálculos “fiscales/comerciales” (conservados)
    subtotal = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    aplica_iva = db.Column(db.Boolean, nullable=False, default=False)
    iva_pct = db.Column(db.Numeric(6, 2), nullable=False, default=0)
    iva_monto = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    aplica_retencion = db.Column(db.Boolean, nullable=False, default=False)
    retencion_pct = db.Column(db.Numeric(6, 2), nullable=False, default=0)
    retencion_monto = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    total = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    # -------------------------
    # snapshots para cálculo por viaje
    # -------------------------
    sueldo_base_op1 = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    viaticos_base_op1 = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    sueldo_base_op2 = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    viaticos_base_op2 = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    # “maniobra y todo eso” (por operador, editable por liquidación)
    maniobra_op1 = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    maniobra_op2 = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    otros_ingresos_op1 = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    otros_ingresos_op2 = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    # -------------------------
    # GASTOS capturados (base SIN IVA - Opción A)
    # -------------------------
    gasto_autopistas = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_rep_menores = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_otros_c_comp = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_ayudas = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_maniobras_1ro = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_maniobras_2do = db.Column(db.Numeric(14, 2), nullable=True, default=0)

    # Gastos de viaje (catálogo)
    gasto_dias_taller = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_estancias = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_gasolina = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_infracciones = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_pension = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_permisos = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_sanitizacion = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_talachas = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_taxis = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_transitos = db.Column(db.Numeric(14, 2), nullable=True, default=0)

    # ---- Con IVA (según tu catálogo)
    gasto_aceites = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_diesel = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_estacionamiento = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_hotel = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_refacciones = db.Column(db.Numeric(14, 2), nullable=True, default=0)
    gasto_urea = db.Column(db.Numeric(14, 2), nullable=True, default=0)

    # -------------------------
    # IVA % por concepto con IVA (Opción A)
    # -------------------------
    gasto_aceites_iva_pct = db.Column(db.Numeric(6, 2), nullable=False, default=16)
    gasto_diesel_iva_pct = db.Column(db.Numeric(6, 2), nullable=False, default=16)
    gasto_estacionamiento_iva_pct = db.Column(db.Numeric(6, 2), nullable=False, default=16)
    gasto_hotel_iva_pct = db.Column(db.Numeric(6, 2), nullable=False, default=16)
    gasto_refacciones_iva_pct = db.Column(db.Numeric(6, 2), nullable=False, default=16)
    gasto_urea_iva_pct = db.Column(db.Numeric(6, 2), nullable=False, default=16)

    # -------------------------
    # Totales por operador
    # -------------------------
    impuestos_op1 = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    impuestos_op2 = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    deducciones_total_op1 = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    deducciones_total_op2 = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    neto_op1 = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    neto_op2 = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    anticipos_total_op1 = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    anticipos_total_op2 = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    pago_final_op1 = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    pago_final_op2 = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    # Compatibilidad (totales agregados)
    deducciones_total = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    neto_operador = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    pago_final_total = db.Column(db.Numeric(14, 2), nullable=False, default=0)

    status = db.Column(db.String(16), nullable=False, default="draft")
    observaciones = db.Column(db.Text, nullable=True)
    activo = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    pagado = db.Column(db.Boolean, nullable=False, default=False)
    pagado_at = db.Column(db.DateTime, nullable=True)

    # Relaciones
    deducciones = db.relationship(
        "LiquidacionDeduccion",
        backref="liquidacion",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LiquidacionDeduccion.id",
    )

    anticipos = db.relationship(
        "LiquidacionAnticipo",
        backref="liquidacion",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LiquidacionAnticipo.id",
    )

    __table_args__ = (
        UniqueConstraint("client_id", "folio_num", name="uq_liq_client_folio_num"),
        UniqueConstraint("client_id", "folio", name="uq_liq_client_folio"),

        # NUEVO: evitar talones duplicados dentro del mismo cliente (si talon_interno no es NULL)
        UniqueConstraint("client_id", "talon_interno", name="uq_liq_client_talon_interno"),

        # NUEVO: unicidad por serie+seq (solo aplica cuando ambos no son NULL)
        UniqueConstraint("client_id", "talon_folio", "talon_seq", name="uq_liq_client_talon_folio_seq"),

        CheckConstraint(f"status IN {LIQ_STATUS_CHOICES}", name="ck_liq_status_valid"),

        # Validaciones mínimas de talón (permitimos NULL para legacy)
        CheckConstraint("talon_seq IS NULL OR talon_seq >= 1", name="ck_liq_talon_seq_valid"),
        CheckConstraint(
            "talon_folio IS NULL OR length(talon_folio) BETWEEN 2 AND 8",
            name="ck_liq_talon_folio_len",
        ),

        Index("ix_liq_client_fecha", "client_id", "fecha"),
        Index("ix_liq_client_status", "client_id", "status"),
        Index("ix_liq_client_activo", "client_id", "activo"),

        # mantenemos índice por compatibilidad y búsquedas
        Index("ix_liq_client_talon", "client_id", "talon_interno"),

        # NUEVO: índices para sugerencias/orden rápidas por serie
        Index("ix_liq_client_talon_folio_seq", "client_id", "talon_folio", "talon_seq"),
        Index("ix_liq_client_talon_folio", "client_id", "talon_folio"),
    )

    # -------------------------
    # Helpers IVA gastos (Opción A)
    # -------------------------
    IVA_GASTOS_KEYS = (
        "gasto_aceites",
        "gasto_diesel",
        "gasto_estacionamiento",
        "gasto_hotel",
        "gasto_refacciones",
        "gasto_urea",
    )

    def calc_gastos_iva(self) -> dict:
        """
        Calcula (sin persistir) el iva_monto y total_con_iva por cada gasto con IVA.
        Regresa:
          {
            "items": { "gasto_aceites": {"base":x,"iva_pct":p,"iva_monto":y,"total":t}, ... },
            "iva_total": ...,
            "total_con_iva": ...,
          }
        """
        items = {}
        iva_total = 0.0
        total_con_iva = 0.0

        for key in self.IVA_GASTOS_KEYS:
            base = float(getattr(self, key, 0) or 0)
            pct = float(getattr(self, f"{key}_iva_pct", 0) or 0)
            pct = max(0.0, min(100.0, pct))
            iva = round(base * (pct / 100.0), 2) if base > 0 and pct > 0 else 0.0
            tot = round(base + iva, 2)

            items[key] = {
                "base": round(base, 2),
                "iva_pct": round(pct, 2),
                "iva_monto": iva,
                "total": tot,
            }

            iva_total += iva
            total_con_iva += tot

        return {
            "items": items,
            "iva_total": round(iva_total, 2),
            "total_con_iva": round(total_con_iva, 2),
        }

    def recalc_totals(self):
        # 1) totales “fiscales/comerciales” existentes (conservamos)
        kms = float(self.kms or 0)
        tarifa = float(self.tarifa or 0)
        subtotal = kms * tarifa

        iva_pct = float(self.iva_pct or 0)
        ret_pct = float(self.retencion_pct or 0)

        iva_monto = subtotal * (iva_pct / 100.0) if self.aplica_iva else 0.0
        ret_monto = subtotal * (ret_pct / 100.0) if self.aplica_retencion else 0.0

        total = subtotal + iva_monto - ret_monto

        self.subtotal = round(subtotal, 2)
        self.iva_monto = round(iva_monto, 2)
        self.retencion_monto = round(ret_monto, 2)
        self.total = round(total, 2)

        # 2) cálculo por operador: base + impuestos(6%) + deducciones + anticipos
        def _gross(slot: int) -> float:
            if slot == 1:
                return (
                    float(self.sueldo_base_op1 or 0)
                    + float(self.viaticos_base_op1 or 0)
                    + float(self.maniobra_op1 or 0)
                    + float(self.otros_ingresos_op1 or 0)
                )
            return (
                float(self.sueldo_base_op2 or 0)
                + float(self.viaticos_base_op2 or 0)
                + float(self.maniobra_op2 or 0)
                + float(self.otros_ingresos_op2 or 0)
            )

        gross1 = _gross(1)
        gross2 = _gross(2) if self.operator2_id else 0.0

        imp1 = round(gross1 * 0.06, 2)
        imp2 = round(gross2 * 0.06, 2) if self.operator2_id else 0.0

        self.impuestos_op1 = imp1
        self.impuestos_op2 = imp2

        # 2a) “upsert” deducción impuestos por slot
        def _ensure_tax_ded(slot: int, amount: float):
            if slot == 2 and not self.operator2_id:
                self.deducciones = [
                    d
                    for d in (self.deducciones or [])
                    if not (d.key == "impuestos" and int(getattr(d, "operator_slot", 1)) == 2)
                ]
                return

            found = None
            for d in (self.deducciones or []):
                if d.key == "impuestos" and int(getattr(d, "operator_slot", 1)) == slot:
                    found = d
                    break
            if found is None:
                from atr_api.models.liquidacion_deduccion import LiquidacionDeduccion

                self.deducciones.append(
                    LiquidacionDeduccion(
                        operator_slot=slot,
                        key="impuestos",
                        label="Impuestos",
                        monto=amount,
                    )
                )
            else:
                found.label = "Impuestos"
                found.monto = amount

        _ensure_tax_ded(1, imp1)
        _ensure_tax_ded(2, imp2)

        # 2b) sumar deducciones por slot
        ded1 = 0.0
        ded2 = 0.0
        for d in (self.deducciones or []):
            slot = int(getattr(d, "operator_slot", 1) or 1)
            m = float(getattr(d, "monto", 0) or 0)
            if slot == 1:
                ded1 += m
            elif slot == 2:
                ded2 += m

        # 2c) sumar anticipos por slot
        ant1 = 0.0
        ant2 = 0.0
        for a in (self.anticipos or []):
            slot = int(getattr(a, "operator_slot", 1) or 1)
            m = float(getattr(a, "importe", 0) or 0)
            if slot == 1:
                ant1 += m
            elif slot == 2:
                ant2 += m

        net1 = round(gross1 - ded1, 2)
        net2 = round(gross2 - ded2, 2)

        pay1 = round(net1 - ant1, 2)
        pay2 = round(net2 - ant2, 2)

        self.deducciones_total_op1 = round(ded1, 2)
        self.deducciones_total_op2 = round(ded2, 2)

        self.anticipos_total_op1 = round(ant1, 2)
        self.anticipos_total_op2 = round(ant2, 2)

        self.neto_op1 = net1
        self.neto_op2 = net2

        self.pago_final_op1 = pay1
        self.pago_final_op2 = pay2

        # agregados (compatibilidad)
        self.deducciones_total = round(ded1 + ded2, 2)
        self.neto_operador = round(net1 + net2, 2)
        self.pago_final_total = round(pay1 + pay2, 2)

    @staticmethod
    def format_folio(folio_num: int) -> str:
        return f"L{int(folio_num):05d}"
