"""Descriptive completed-trade metrics; no annualized Sharpe assumption."""

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Sequence

from app.portfolio.models import Trade
from app.domain import Direction


@dataclass(frozen=True)
class Performance:
    net_profit: Decimal
    return_fraction: Decimal
    trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    profit_factor: Decimal | None
    expectancy: Decimal | None
    max_drawdown: Decimal
    fees: Decimal
    long_trades: int
    short_trades: int = 0

    def as_dict(self) -> dict[str, object]:
        return {name: str(value) if isinstance(value, Decimal) else value for name, value in asdict(self).items()}


def calculate_performance(capital: Decimal, final_cash: Decimal, trades: Sequence[Trade],
                          equity_curve: Sequence[Decimal], fees: Decimal) -> Performance:
    pnl = [trade.net_pnl for trade in trades]
    winners, losers = [v for v in pnl if v > 0], [v for v in pnl if v < 0]
    profit, loss = sum(winners, Decimal("0")), -sum(losers, Decimal("0"))
    peak, drawdown = capital, Decimal("0")
    for equity in equity_curve:
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
    count = len(trades)
    return Performance(final_cash - capital, (final_cash - capital) / capital,
                       count, len(winners), len(losers), sum(v == 0 for v in pnl),
                       Decimal(len(winners)) / count if count else None,
                       profit / len(winners) if winners else None,
                       -loss / len(losers) if losers else None,
                       profit / loss if loss else None,
                       sum(pnl, Decimal("0")) / count if count else None,
                       drawdown, fees,
                       sum(trade.position.direction == Direction.LONG for trade in trades),
                       sum(trade.position.direction == Direction.SHORT for trade in trades))
