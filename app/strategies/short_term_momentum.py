"""Literature-horizon momentum variant for a separately frozen study."""

from decimal import Decimal

from app.strategies.time_series_momentum import (
    TimeSeriesMomentumParameters,
    TimeSeriesMomentumStrategy,
)


class ShortTermMomentumStrategy(TimeSeriesMomentumStrategy):
    """Agreeing one- and four-week own-price momentum with a one-week risk horizon."""

    name = "short_horizon_tsmom_perpetual"
    version = "0.1.0"

    def __init__(self) -> None:
        super().__init__(TimeSeriesMomentumParameters(
            fast_momentum_bars=42,
            slow_momentum_bars=168,
            atr_period=42,
            stop_atr_multiple=Decimal("3"),
            requested_leverage=Decimal("10"),
        ))
