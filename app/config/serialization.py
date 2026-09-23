"""Strict JSON representation of public simulation settings, without environment reads."""

from dataclasses import asdict, fields
from decimal import Decimal
from pathlib import Path

from app.config.settings import RiskLimits, Settings
from app.domain import TradingMode


def encode_settings(settings: Settings) -> dict:
    def encode(value):
        if isinstance(value, (Decimal, Path, TradingMode)):
            return str(value)
        if isinstance(value, dict):
            return {k: encode(v) for k, v in value.items()}
        return value
    return encode(asdict(settings))


def decode_settings(value: dict) -> Settings:
    def decode(data, default):
        if not isinstance(data, dict) or set(data) != {field.name for field in fields(default)}:
            raise ValueError("Settings snapshot fields differ")
        converted = {}
        for name, item in data.items():
            template = getattr(default, name)
            if isinstance(template, Decimal):
                if not isinstance(item, str):
                    raise ValueError("Money settings must be decimal strings")
                converted[name] = Decimal(item)
            elif isinstance(template, Path):
                converted[name] = Path(item)
            else:
                converted[name] = item
        return converted
    values = decode(value, Settings())
    values["mode"] = TradingMode(values["mode"])
    values["risk"] = RiskLimits(**decode(values["risk"], RiskLimits()))
    return Settings(**values)
