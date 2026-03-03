# atr_api/models/__init__.py

from atr_api.extensions import db

from .client import Client
from .operator import Operator
from .car import Car
from .car_type_config import CarTypeConfig
from .user import User
from .destination import Destination
from .guide import Guide

from .client_counter import ClientCounter
from .liquidacion import Liquidacion

from .deducciones_config import ClientDeduccionesConfig
from .operator_deduccion_extra import OperatorDeduccionExtra

from .talon_series_counter import TalonSeriesCounter
from .talon_series import TalonSeries
from .operator_imss import OperatorIMSS
from .liquidacion_detalle import LiquidacionDetalle

__all__ = [
    "db",
    "Client",
    "Operator",
    "CarTypeConfig",
    "User",
    "Car",
    "Destination",
    "Guide",
    "ClientCounter",
    "Liquidacion",
    "ClientDeduccionesConfig",
    "OperatorDeduccionExtra",
    "TalonSeriesCounter",   
    "TalonSeries",
    "OperatorIMSS",
    "LiquidacionDetalle",
]
