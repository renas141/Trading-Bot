"""Causal replay for the second-generation funding-aware safety model."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import Sequence

from app.derivatives.models import DerivativeTrade
from app.derivatives.risk import DerivativeRiskContext
from app.derivatives.safety import (
    FundingAwarePaperBroker,
    StressAwareRiskManager,
    StressRiskPolicy,
)
from app.derivatives.settings import DerivativeSettings
from app.domain import Direction
from app.market_data.models import Candle
from app.market_data.quality import require_complete
from app.strategies.base import Strategy
from backtesting.derivatives import DerivativePerformance, calculate_derivative_performance


@dataclass(frozen=True)
class SafeDerivativeReplayResult:
    candles_processed: int
    signals: int
    entries: int
    rejected_entries: int
    funding_liquidations: int
    performance: DerivativePerformance
    trades: tuple[DerivativeTrade, ...]
    equity_curve: tuple[Decimal, ...]


class _RiskState:
    def __init__(self, settings: DerivativeSettings) -> None:
        self.settings = settings
        self.peak = self.day_start = self.last_equity = settings.initial_capital
        self.day = None
        self.daily_halted = self.drawdown_halted = False

    def observe(self, price: Decimal, timestamp, equity: Decimal) -> DerivativeRiskContext:
        current_day = timestamp.date()
        if current_day != self.day:
            self.day_start = self.last_equity
            self.daily_halted = False
            self.day = current_day
        self.peak = max(self.peak, equity)
        self.daily_halted |= equity <= self.day_start * (1 - self.settings.max_daily_loss)
        self.drawdown_halted |= equity <= self.peak * (1 - self.settings.max_drawdown)
        self.last_equity = equity
        return DerivativeRiskContext(
            price, timestamp, max(equity, Decimal("0")), self.day_start, self.peak,
            self.daily_halted, self.drawdown_halted, equity <= 0,
        )


class SafeDerivativeBacktester:
    """Replay with next-open entries and dynamic funding-adjusted margin health."""

    def __init__(self, strategy: Strategy, settings: DerivativeSettings,
                 policy: StressRiskPolicy | None = None,
                 maximum_holding_bars: int = 42) -> None:
        if type(maximum_holding_bars) is not int or maximum_holding_bars < 2:
            raise ValueError("maximum_holding_bars must be an integer of at least two")
        self.strategy = strategy
        self.settings = settings
        self.policy = policy or StressRiskPolicy(maximum_holding_bars=maximum_holding_bars)
        if self.policy.maximum_holding_bars != maximum_holding_bars:
            raise ValueError("Risk and exit holding horizons must match")
        self.maximum_holding_bars = maximum_holding_bars

    def run(self, trade_candles: Sequence[Candle], mark_candles: Sequence[Candle], *,
            funding_rates: Sequence[Decimal], warmup: Sequence[Candle] = ()) -> SafeDerivativeReplayResult:
        require_complete(trade_candles)
        require_complete(mark_candles)
        if tuple(c.timestamp for c in trade_candles) != tuple(c.timestamp for c in mark_candles):
            raise ValueError("Trade and mark candles must be aligned")
        if len(funding_rates) != len(trade_candles) or any(
                not isinstance(rate, Decimal) or not rate.is_finite() for rate in funding_rates):
            raise ValueError("Signed funding must align with every evaluation candle")
        if warmup:
            require_complete(warmup)
            if warmup[-1].closed_at != trade_candles[0].timestamp:
                raise ValueError("Warm-up must directly precede the evaluation")

        broker = FundingAwarePaperBroker(self.settings)
        manager = StressAwareRiskManager(self.settings, self.policy)
        risk = _RiskState(self.settings)
        observed = tuple(warmup) + tuple(trade_candles)
        pending = None
        opened_index = None
        signals = entries = rejected = funding_liquidations = 0
        equity_curve = [self.settings.initial_capital]

        for index, (trade, mark, funding) in enumerate(
                zip(trade_candles, mark_candles, funding_rates)):
            at_open = trade.timestamp
            account = broker.mark(mark.open)
            risk.observe(trade.open, at_open, account.equity)
            position = account.position
            if position is not None:
                health = broker.margin_health(mark.open)
                stop_gap = (
                    trade.open <= position.stop_price if position.direction == Direction.LONG
                    else trade.open >= position.stop_price
                )
                if health is not None and health.liquidatable:
                    broker.close_position(mark.open, at_open, "DYNAMIC_LIQUIDATION_GAP",
                                          liquidation=True)
                    opened_index = None
                elif stop_gap:
                    broker.close_position(trade.open, at_open, "STOP_GAP")
                    opened_index = None

            position = broker.snapshot(mark.open).position
            if (position is not None and opened_index is not None
                    and index - opened_index >= self.maximum_holding_bars):
                broker.close_position(trade.open, at_open, "TIME_EXIT")
                opened_index = None

            if pending is not None and pending.direction in (Direction.LONG, Direction.SHORT):
                signals += 1
                account = broker.snapshot(mark.open)
                context = risk.observe(trade.open, at_open, account.equity)
                decision = manager.evaluate(pending, account, context)
                if decision.allowed:
                    broker.open_position(pending, decision, at_open)
                    opened_index = index
                    entries += 1
                else:
                    rejected += 1

            position = broker.snapshot(mark.open).position
            if position is not None:
                health = broker.margin_health(mark.open)
                assert health is not None
                liquidation_hit = (
                    mark.low <= health.dynamic_liquidation_price
                    if position.direction == Direction.LONG
                    else mark.high >= health.dynamic_liquidation_price
                )
                stop_hit = (
                    trade.low <= position.stop_price
                    if position.direction == Direction.LONG
                    else trade.high >= position.stop_price
                )
                end_at = trade.closed_at - timedelta(microseconds=1)
                # Without tick ordering, assume liquidation before a stop whenever both
                # thresholds appear inside the same four-hour bar.
                if liquidation_hit:
                    broker.close_position(
                        health.dynamic_liquidation_price, end_at,
                        "DYNAMIC_LIQUIDATION", liquidation=True,
                    )
                    opened_index = None
                elif stop_hit:
                    broker.close_position(position.stop_price, end_at, "STOP_LOSS")
                    opened_index = None

            position = broker.snapshot(mark.close).position
            if position is not None and funding:
                broker.apply_funding(funding, mark.close)
                if broker.liquidation_required(mark.close):
                    broker.close_position(
                        mark.close, trade.closed_at - timedelta(microseconds=1),
                        "FUNDING_LIQUIDATION", liquidation=True,
                    )
                    funding_liquidations += 1
                    opened_index = None

            account = broker.mark(mark.close)
            risk.observe(trade.close, trade.closed_at - timedelta(microseconds=1),
                         account.equity)
            equity_curve.append(account.equity)
            history = observed[:len(warmup) + index + 1]
            pending = self.strategy.analyze(history)
            if pending.symbol != trade.symbol or pending.timestamp != trade.closed_at:
                raise ValueError("Strategy signal must match the completed trade candle")

        if broker.snapshot(mark_candles[-1].close).position is not None:
            broker.close_position(
                trade_candles[-1].close,
                trade_candles[-1].closed_at - timedelta(microseconds=1),
                "END_OF_DATA",
            )
        final = broker.snapshot().balance
        performance = calculate_derivative_performance(
            self.settings.initial_capital, final, broker.trades, equity_curve
        )
        performance = replace(
            performance,
            liquidations=sum("LIQUIDATION" in trade.exit_reason for trade in broker.trades),
        )
        return SafeDerivativeReplayResult(
            len(trade_candles), signals, entries, rejected, funding_liquidations,
            performance, tuple(broker.trades), tuple(equity_curve),
        )
