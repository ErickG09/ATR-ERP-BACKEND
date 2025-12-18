# app/models/client_counter.py

# Ajusta este import a tu proyecto
from atr_api.extensions import db


class ClientCounter(db.Model):
    __tablename__ = "client_counters"

    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), primary_key=True)

    # secuencia para liquidaciones
    liquidacion_folio_seq = db.Column(db.Integer, nullable=False, default=0)
