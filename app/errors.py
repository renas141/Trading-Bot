"""Explicit errors at application boundaries."""


class TradingBotError(Exception):
    """Base for expected application errors."""


class ConfigurationError(TradingBotError, ValueError):
    """Configuration is invalid or unsafe."""


class LiveTradingDisabled(TradingBotError):
    """Real trading is deliberately unavailable."""


class SimulationError(TradingBotError):
    """A simulated operation violates the broker's constraints."""


class MarketDataError(TradingBotError):
    """Public market data could not be retrieved or validated."""
