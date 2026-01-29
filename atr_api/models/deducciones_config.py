# atr_api/models/deducciones_config.py
from __future__ import annotations

from datetime import datetime
from atr_api.extensions import db


class ClientDeduccionesConfig(db.Model):
    """
    Config de deducciones por cliente:
    - global: montos base (string/number) para preset keys (excepto "impuestos")
    - per_operator: overrides por operador (enabled + values + extras opcionales de UI)
    - global_extras: extras globales (si los usas en UI como "plantillas")
    NOTA: las deducciones "deuda" con saldo restante van en OperatorDeduccionExtra (tabla aparte).
    """
    __tablename__ = "client_deducciones_config"

    id = db.Column(db.Integer, primary_key=True)

    client_id = db.Column(
        db.Integer,
        db.ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # JSON con forma parecida a tu store del frontend
    global_json = db.Column(db.JSON, nullable=False, default=dict)
    per_operator_json = db.Column(db.JSON, nullable=False, default=dict)
    global_extras_json = db.Column(db.JSON, nullable=False, default=list)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<ClientDeduccionesConfig client_id={self.client_id}>"
