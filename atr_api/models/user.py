from __future__ import annotations

from datetime import datetime, date

from atr_api.extensions import db


class User(db.Model):
    """
    Usuarios del sistema (login de ERP).

    Pensado para crecer por módulos:
    - area: contabilidad / tráfico / operaciones / dirección / etc.
    - luego podrás agregar roles/permisos más finos.
    """

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    # Credenciales
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Datos personales básicos
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    phone = db.Column(db.String(30), nullable=True)

    date_of_birth = db.Column(db.Date, nullable=True)
    age = db.Column(db.Integer, nullable=True)  # redundante pero práctico si contabilidad lo pide

    # Área principal a la que pertenece (para segmentar módulos)
    area = db.Column(db.String(50), nullable=False, default="contabilidad")

    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, index=True
    )
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def update_age_from_birthdate(self) -> None:
        if not self.date_of_birth:
            return
        today = date.today()
        years = today.year - self.date_of_birth.year
        if (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day):
            years -= 1
        self.age = years

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} area={self.area!r}>"
