from __future__ import annotations

from atr_api.extensions import db


class CarTypeConfig(db.Model):
    """
    Tarifas por tipo de carro (CA, FU, NO, UR, HI...) por cliente.
    """

    __tablename__ = "car_type_configs"

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
    )
    client = db.relationship("Client", back_populates="car_type_configs")

    # Ej: "CA", "FU", "NO", "UR", "HI"
    car_type = db.Column(db.String(10), nullable=False)

    # Sueldos / viáticos
    sueldo_por_km = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    viaticos_por_km = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    sueldo_ayudante = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    viaticos_ayudante = db.Column(
        db.Numeric(10, 4), nullable=False, server_default="0"
    )
    viaje_especial = db.Column(db.Numeric(10, 2), nullable=False, server_default="0")

    # Tarifas (4 decimales)
    mexico = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    exp_ver = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    exp_lc = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    exp_tux = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    importado = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    local = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    patios = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")

    slp_altamira = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    ramos_altamira = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    slp_lc = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")

    sal_lzc = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    sal_ver = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")
    sal_altamira = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")

    resguardo = db.Column(db.Numeric(10, 4), nullable=False, server_default="0")

    __table_args__ = (
        db.UniqueConstraint(
            "client_id",
            "car_type",
            name="uq_car_type_config_client_type",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CarTypeConfig id={self.id} client_id={self.client_id} "
            f"car_type={self.car_type!r}>"
        )
