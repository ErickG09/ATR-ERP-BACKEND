from __future__ import annotations

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
    activo = db.Column(db.Boolean, nullable=False, server_default="true")

    # Datos opcionales
    domicilio = db.Column(db.String(255), nullable=False, server_default="")
    telefono = db.Column(db.String(50), nullable=False, server_default="")
    no_imss = db.Column(db.String(50), nullable=False, server_default="")
    rfc = db.Column(db.String(50), nullable=False, server_default="")
    no_licencia = db.Column(db.String(50), nullable=False, server_default="")

    correo_electronico = db.Column(db.String(120), nullable=False, server_default="")
    gafete_aduana = db.Column(db.String(80), nullable=False, server_default="")
    apto_medico_licencia = db.Column(db.Date, nullable=True)
    tiene_seguro = db.Column(db.Boolean, nullable=False, server_default="false")

    fecha_venc_licencia = db.Column(db.Date, nullable=True)

    # Sueldos / viáticos / kms
    sueldo_op_1 = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    viaticos_op_1 = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    sueldo_op_2 = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    viaticos_op_2 = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    viaje_especial = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")

    kms_acumulados = db.Column(db.Numeric(12, 2), nullable=False, server_default="0")

    viaticos_por_km = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    sueldo_por_km = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")

    # Tarifas existentes
    mexico = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    exp_ver = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    exp_lc = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    exp_tux = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    importado = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    local = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    patios = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    slp_altamira = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    ramos_altamira = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    slp_lc = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    sal_lzc = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    sal_ver = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    sal_altamira = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    resguardo = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")

    # NUEVAS MANIOBRAS
    man_nac = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    man_esp = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    man_df = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    man_ver = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    man_slp_altamira = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    man_ramos_altamira = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    man_slp_lzc = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    man_salamanca_lzc = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    man_salamanca_ver = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")
    man_salamanca_altamira = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")

    ayuda_escolar = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")

    tipo_carro = db.Column(db.String(50), nullable=False, server_default="")
    observaciones = db.Column(db.Text, nullable=True)

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
        return "T" if self.activo else "F"

    @status_display.setter
    def status_display(self, value: str) -> None:
        self.activo = str(value).strip().upper() == "T"