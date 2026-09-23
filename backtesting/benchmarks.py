"""Cash and fully funded buy-and-hold references, without strategy risk limits."""

from dataclasses import asdict
from decimal import Decimal
from typing import Sequence

from app.config.settings import Settings
from app.domain import Direction, TradingMode
from app.execution.costs import ExecutionCosts, floor_step
from app.market_data.models import Candle
from app.market_data.quality import require_complete
from app.portfolio.models import Position, Trade
from backtesting.metrics import calculate_performance


def benchmarks(candles: Sequence[Candle], settings: Settings, *, verified_empty_intervals=()) -> dict:
    if verified_empty_intervals:
        from backtesting.observed_history import validate_observed_history
        validate_observed_history(candles, verified_empty_intervals)
    else:
        require_complete(candles)
    if settings.mode != TradingMode.BACKTEST or any(c.symbol != settings.symbol for c in candles):
        raise ValueError("Benchmarks require matching BACKTEST candles")
    capital, zero = settings.initial_capital, Decimal("0")
    costs = ExecutionCosts(settings)
    quantity = floor_step(capital / costs.entry_cost(candles[0].open), settings.quantity_step)
    entry = costs.buy(candles[0].open)
    if quantity <= 0 or quantity < settings.min_order_quantity or quantity * entry < settings.min_order_notional:
        raise ValueError("Buy-and-hold purchase is below minimum notional")
    entry_fee = quantity * entry * settings.paper_fee_rate
    cash = capital - quantity * entry - entry_fee
    position = Position("buy_hold", settings.symbol, Direction.LONG, quantity, entry,
                        candles[0].timestamp, entry_fee)
    exit_price = costs.sell(candles[-1].close)
    exit_fee = quantity * exit_price * settings.paper_fee_rate
    trade = Trade("buy_hold", position, exit_price, candles[-1].closed_at, exit_fee, "BENCHMARK_END")
    equity = [capital]
    for candle in candles:
        equity.extend((cash + quantity * costs.exit_value(candle.open), cash + quantity * costs.exit_value(candle.close)))
    final_cash = cash + quantity * exit_price - exit_fee
    return {
        "cash": {"performance": calculate_performance(capital, capital, (), (capital,), zero).as_dict(),
                 "assumption": "No trades, no interest, no fees."},
        "buy_hold": {"performance": calculate_performance(capital, final_cash, (trade,), equity, trade.fees).as_dict(),
                     "trade": asdict(trade), "uninvested_cash": cash,
                     "assumption": "Buy first open with available cash; sell last close. Same costs and rounding; no stops, daily-loss or drawdown limits. Observed open/close drawdown."},
    }
