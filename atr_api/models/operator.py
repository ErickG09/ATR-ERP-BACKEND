from __future__ import annotations

from datetime import date

from atr_api.extensions import db


class Operator(db.Model):
    __tablename__ = "operators"

    id = db.Column(db.Integer, primary_key=True)

    # Relación con cliente (segmentación por cliente)
    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
    )
    client = db.relationship("Client", back_populates="operators")

    # Identificación básica
    codigo = db.Column(db.String(10), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)

    fecha_ingreso = db.Column(db.Date, nullable=False)
    # Campo booleano real para activo/inactivo
    activo = db.Column(db.Boolean, nullable=False, server_default="true")

    # --- Datos de contacto / personales (opcionales, texto) ---
    domicilio = db.Column(db.String(255), nullable=False, server_default="")
    telefono = db.Column(db.String(50), nullable=False, server_default="")
    no_imss = db.Column(db.String(50), nullable=False, server_default="")
    rfc = db.Column(db.String(50), nullable=False, server_default="")
    no_licencia = db.Column(db.String(50), nullable=False, server_default="")

    # --- NUEVOS (opcionales) ---
    correo_electronico = db.Column(db.String(120), nullable=False, server_default="")
    gafete_aduana = db.Column(db.String(80), nullable=False, server_default="")
    apto_medico_licencia = db.Column(db.Date, nullable=True)
    tiene_seguro = db.Column(db.Boolean, nullable=False, server_default="false")


    fecha_venc_licencia = db.Column(db.Date, nullable=True)

    # --- Campos numéricos (sueldos / viáticos / kms) ---
    sueldo_op_1 = db.Column(
        db.Numeric(10, 2), nullable=False, server_default="0"
    )
    viaticos_op_1 = db.Column(
        db.Numeric(10, 2), nullable=False, server_default="0"
    )
    sueldo_op_2 = db.Column(
        db.Numeric(10, 2), nullable=False, server_default="0"
    )
    viaticos_op_2 = db.Column(
        db.Numeric(10, 2), nullable=False, server_default="0"
    )
    viaje_especial = db.Column(
        db.Numeric(10, 2), nullable=False, server_default="0"
    )

    kms_acumulados = db.Column(
        db.Numeric(12, 2), nullable=False, server_default="0"
    )
    viaticos_por_km = db.Column(
        db.Numeric(10, 4), nullable=False, server_default="0"
    )
    sueldo_por_km = db.Column(
        db.Numeric(10, 4), nullable=False, server_default="0"
    )

    # --- Campos de catálogo (texto, no booleanos) ---
    mexico = db.Column(db.String(20), nullable=False, server_default="")
    exp_ver = db.Column(db.String(20), nullable=False, server_default="")
    exp_lc = db.Column(db.String(20), nullable=False, server_default="")
    exp_tux = db.Column(db.String(20), nullable=False, server_default="")
    importado = db.Column(db.String(20), nullable=False, server_default="")
    local = db.Column(db.String(20), nullable=False, server_default="")
    patios = db.Column(db.String(20), nullable=False, server_default="")
    slp_altamira = db.Column(db.String(20), nullable=False, server_default="")
    ramos_altamira = db.Column(db.String(20), nullable=False, server_default="")
    slp_lc = db.Column(db.String(20), nullable=False, server_default="")
    sal_lzc = db.Column(db.String(20), nullable=False, server_default="")
    sal_ver = db.Column(db.String(20), nullable=False, server_default="")
    sal_altamira = db.Column(db.String(20), nullable=False, server_default="")
    resguardo = db.Column(db.String(20), nullable=False, server_default="")
    ayuda_escolar = db.Column(db.String(20), nullable=False, server_default="")
    tipo_carro = db.Column(db.String(50), nullable=False, server_default="")

    observaciones = db.Column(db.Text, nullable=True)

    # Único por cliente: no se puede repetir el código dentro del mismo cliente
    __table_args__ = (
        db.UniqueConstraint("client_id", "codigo", name="uq_operator_client_codigo"),
    )

    guides = db.relationship(
        "Guide",
        back_populates="operator",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


    def __repr__(self) -> str:
        return f"<Operator id={self.id} codigo={self.codigo!r} client_id={self.client_id}>"

    @property
    def status_display(self) -> str:
        """Compatibilidad con T/F si algún día quieres exportar a Excel."""
        return "T" if self.activo else "F"

    @status_display.setter
    def status_display(self, value: str) -> None:
        self.activo = (str(value).upper() == "T")
