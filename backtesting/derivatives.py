"""Causal next-bar replay for a linear perpetual with separate trade and mark candles."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from app.derivatives.broker import DerivativePaperBroker
from app.derivatives.models import DerivativeTrade
from app.derivatives.risk import DerivativeRiskContext, LeveragedRiskManager, ceil_step, floor_step
from app.derivatives.settings import DerivativeSettings
from app.domain import Direction
from app.indicators.core import average_true_range
from app.market_data.models import Candle
from app.market_data.quality import require_complete
from app.strategies.base import Strategy


@dataclass(frozen=True)
class DerivativePerformance:
    net_profit: Decimal
    return_fraction: Decimal
    trades: int
    wins: int
    losses: int
    win_rate: Decimal | None
    profit_factor: Decimal | None
    expectancy: Decimal | None
    max_drawdown: Decimal
    fees: Decimal
    funding_paid: Decimal
    liquidations: int
    long_trades: int
    short_trades: int
    maximum_leverage_used: int

    def as_dict(self) -> dict[str, object]:
        return {key: str(value) if isinstance(value, Decimal) else value
                for key, value in asdict(self).items()}


@dataclass(frozen=True)
class DerivativeReplayResult:
    candles_processed: int
    signals: int
    entries: int
    rejected_entries: int
    performance: DerivativePerformance
    trades: tuple[DerivativeTrade, ...]
    equity_curve: tuple[Decimal, ...]
    stop_updates: int


@dataclass(frozen=True)
class ProfitProtection:
    """Close-confirmed stop tightening, effective only from the next bar."""

    trigger_r: Decimal
    locked_r: Decimal

    def __post_init__(self) -> None:
        if (not isinstance(self.trigger_r, Decimal) or not isinstance(self.locked_r, Decimal)
                or self.trigger_r <= 0 or self.locked_r < 0 or self.locked_r >= self.trigger_r):
            raise ValueError("Profit protection requires 0 <= locked R < trigger R")


@dataclass(frozen=True)
class CloseExitPolicy:
    """Close-confirmed management exit, submitted for the next candle open."""

    max_holding_bars: int | None = None
    momentum_lookback: int | None = None
    minimum_holding_bars: int = 1

    def __post_init__(self) -> None:
        if self.max_holding_bars is None and self.momentum_lookback is None:
            raise ValueError("An exit policy needs a time or momentum rule")
        for name in ("max_holding_bars", "momentum_lookback"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 2):
                raise ValueError(f"{name} must be an integer of at least two")
        if type(self.minimum_holding_bars) is not int or self.minimum_holding_bars < 1:
            raise ValueError("minimum_holding_bars must be a positive integer")
        if (self.momentum_lookback is not None
                and self.minimum_holding_bars < self.momentum_lookback):
            raise ValueError("Momentum exits need at least one full lookback window")


@dataclass(frozen=True)
class TrailingStopPolicy:
    """Highest/lowest completed close minus/plus a fixed ATR multiple."""

    atr_period: int
    atr_multiple: Decimal

    def __post_init__(self) -> None:
        if type(self.atr_period) is not int or self.atr_period < 2:
            raise ValueError("Trailing ATR period must be an integer of at least two")
        if (not isinstance(self.atr_multiple, Decimal) or not self.atr_multiple.is_finite()
                or self.atr_multiple <= 0):
            raise ValueError("Trailing ATR multiple must be a positive finite Decimal")


class _RiskState:
    def __init__(self, settings: DerivativeSettings) -> None:
        self.settings = settings
        self.peak = self.day_start = self.last_equity = settings.initial_capital
        self.day: date | None = None
        self.daily_halted = self.drawdown_halted = False

    def observe(self, price: Decimal, timestamp: datetime, equity: Decimal) -> DerivativeRiskContext:
        current_day = timestamp.astimezone(timezone.utc).date()
        if current_day != self.day:
            self.day_start = self.last_equity
            self.daily_halted = False
            self.day = current_day
        self.peak = max(self.peak, equity)
        self.daily_halted |= equity <= self.day_start * (1 - self.settings.max_daily_loss)
        self.drawdown_halted |= equity <= self.peak * (1 - self.settings.max_drawdown)
        self.last_equity = equity
        return DerivativeRiskContext(price, timestamp, max(equity, Decimal("0")),
                                     self.day_start, self.peak, self.daily_halted,
                                     self.drawdown_halted, equity <= 0)


def calculate_derivative_performance(capital: Decimal, final_balance: Decimal,
                                     trades: Sequence[DerivativeTrade],
                                     equity_curve: Sequence[Decimal]) -> DerivativePerformance:
    pnl = [trade.net_pnl for trade in trades]
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
    gross_profit, gross_loss = sum(wins, Decimal("0")), -sum(losses, Decimal("0"))
    peak, max_drawdown = capital, Decimal("0")
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    count = len(trades)
    return DerivativePerformance(
        final_balance - capital, (final_balance - capital) / capital,
        count, len(wins), len(losses), Decimal(len(wins)) / count if count else None,
        gross_profit / gross_loss if gross_loss else None,
        sum(pnl, Decimal("0")) / count if count else None,
        max_drawdown,
        sum((trade.fees for trade in trades), Decimal("0")),
        sum((trade.funding_paid for trade in trades), Decimal("0")),
        sum(trade.exit_reason.startswith("LIQUIDATION") for trade in trades),
        sum(trade.position.direction == Direction.LONG for trade in trades),
        sum(trade.position.direction == Direction.SHORT for trade in trades),
        max((trade.position.leverage for trade in trades), default=0),
    )


class DerivativeBacktester:
    """One fixed funding sensitivity is charged per completed 4h bar while open."""

    def __init__(self, strategy: Strategy, settings: DerivativeSettings,
                 funding_rate_per_bar: Decimal,
                 profit_protection: ProfitProtection | None = None,
                 close_exit_policy: CloseExitPolicy | None = None,
                 reentry_cooldown_bars: int = 0,
                 trailing_stop_policy: TrailingStopPolicy | None = None) -> None:
        if not isinstance(funding_rate_per_bar, Decimal) or funding_rate_per_bar < 0:
            raise ValueError("Funding sensitivity must be a non-negative Decimal")
        self.strategy = strategy
        self.settings = settings
        self.funding_rate_per_bar = funding_rate_per_bar
        self.profit_protection = profit_protection
        self.close_exit_policy = close_exit_policy
        self.trailing_stop_policy = trailing_stop_policy
        if type(reentry_cooldown_bars) is not int or reentry_cooldown_bars < 0:
            raise ValueError("Re-entry cooldown must be a non-negative integer")
        self.reentry_cooldown_bars = reentry_cooldown_bars

    def run(self, trade_candles: Sequence[Candle], mark_candles: Sequence[Candle], *,
            warmup: Sequence[Candle] = (),
            funding_rates: Sequence[Decimal] | None = None) -> DerivativeReplayResult:
        require_complete(trade_candles)
        require_complete(mark_candles)
        if tuple(c.timestamp for c in trade_candles) != tuple(c.timestamp for c in mark_candles):
            raise ValueError("Trade and mark candles must be aligned")
        if funding_rates is not None:
            if len(funding_rates) != len(trade_candles):
                raise ValueError("Historical funding rates must align with evaluation candles")
            if any(not isinstance(rate, Decimal) or not rate.is_finite() for rate in funding_rates):
                raise ValueError("Historical funding rates must be finite Decimals")
        if warmup:
            require_complete(warmup)
            if warmup[-1].closed_at != trade_candles[0].timestamp:
                raise ValueError("Warm-up must directly precede the evaluation")
        broker = DerivativePaperBroker(self.settings)
        risk = LeveragedRiskManager(self.settings)
        state = _RiskState(self.settings)
        equity_curve = [self.settings.initial_capital]
        pending = None
        entries = rejected = signals = 0
        stop_updates = 0
        initial_stops: dict[str, Decimal] = {}
        opened_at_index: dict[str, int] = {}
        trailing_anchor: dict[str, Decimal] = {}
        pending_management_exit: tuple[str, str] | None = None
        last_exit_index: int | None = None
        observed = tuple(warmup) + tuple(trade_candles)

        def close(reference: Decimal, at: datetime, reason: str, liquidation: bool = False) -> None:
            nonlocal last_exit_index
            broker.close_position(reference, at, reason, liquidation=liquidation)
            last_exit_index = index

        for index, (trade, mark) in enumerate(zip(trade_candles, mark_candles)):
            at_open = trade.timestamp
            account = broker.mark(mark.open)
            context = state.observe(trade.open, at_open, account.equity)
            position = account.position
            if position is not None:
                liquidated = ((position.direction == Direction.LONG and mark.open <= position.liquidation_price)
                              or (position.direction == Direction.SHORT and mark.open >= position.liquidation_price))
                stop_gap = ((position.direction == Direction.LONG and trade.open <= position.stop_price)
                            or (position.direction == Direction.SHORT and trade.open >= position.stop_price))
                target_gap = (position.take_profit_price is not None and
                              ((position.direction == Direction.LONG and trade.open >= position.take_profit_price)
                               or (position.direction == Direction.SHORT and trade.open <= position.take_profit_price)))
                if liquidated:
                    close(mark.open, at_open, "LIQUIDATION_GAP", True)
                elif stop_gap:
                    close(trade.open, at_open, "STOP_GAP")
                elif target_gap:
                    close(position.take_profit_price, at_open, "TAKE_PROFIT_GAP")

            position = broker.snapshot(mark.open).position
            if (position is not None and pending_management_exit is not None
                    and pending_management_exit[0] == position.id):
                close(trade.open, at_open, pending_management_exit[1])
            pending_management_exit = None

            if pending is not None and pending.direction in (Direction.LONG, Direction.SHORT):
                signals += 1
                cooling_down = (self.reentry_cooldown_bars > 0 and last_exit_index is not None
                                and index - last_exit_index <= self.reentry_cooldown_bars)
                if cooling_down:
                    rejected += 1
                else:
                    account = broker.snapshot(mark.open)
                    context = state.observe(trade.open, at_open, account.equity)
                    decision = risk.evaluate(pending, account, context)
                    if decision.allowed:
                        opened = broker.open_position(pending, decision, at_open)
                        initial_stops[opened.id] = opened.stop_price
                        opened_at_index[opened.id] = index
                        trailing_anchor[opened.id] = opened.entry_price
                        entries += 1
                    else:
                        rejected += 1

            position = broker.snapshot(mark.open).position
            if position is not None:
                stop_hit = ((position.direction == Direction.LONG and trade.low <= position.stop_price)
                            or (position.direction == Direction.SHORT and trade.high >= position.stop_price))
                target_hit = (position.take_profit_price is not None and
                              ((position.direction == Direction.LONG and trade.high >= position.take_profit_price)
                               or (position.direction == Direction.SHORT and trade.low <= position.take_profit_price)))
                liquidation_hit = ((position.direction == Direction.LONG and mark.low <= position.liquidation_price)
                                   or (position.direction == Direction.SHORT and mark.high >= position.liquidation_price))
                end_at = trade.closed_at - timedelta(microseconds=1)
                if stop_hit:
                    close(position.stop_price, end_at,
                          "STOP_FIRST_AMBIGUOUS_BAR" if target_hit else "STOP_LOSS")
                elif liquidation_hit:
                    close(position.liquidation_price, end_at, "LIQUIDATION", True)
                elif target_hit:
                    close(position.take_profit_price, end_at, "TAKE_PROFIT")

            position = broker.snapshot(mark.close).position
            if position is not None:
                if funding_rates is None:
                    rate = (self.funding_rate_per_bar if position.direction == Direction.LONG
                            else -self.funding_rate_per_bar)
                else:
                    rate = funding_rates[index]
                if rate:
                    broker.apply_funding(rate, mark.close)

            position = broker.snapshot(mark.close).position
            if position is not None and self.profit_protection is not None:
                initial_stop = initial_stops[position.id]
                initial_risk = abs(position.entry_price - initial_stop)
                policy = self.profit_protection
                if position.direction == Direction.LONG:
                    triggered = trade.close >= position.entry_price + initial_risk * policy.trigger_r
                    proposed = floor_step(position.entry_price + initial_risk * policy.locked_r,
                                          self.settings.contract.tick_size)
                    tighter = proposed > position.stop_price
                else:
                    triggered = trade.close <= position.entry_price - initial_risk * policy.trigger_r
                    proposed = ceil_step(position.entry_price - initial_risk * policy.locked_r,
                                         self.settings.contract.tick_size)
                    tighter = proposed < position.stop_price
                if triggered and tighter:
                    broker.tighten_stop(proposed)
                    stop_updates += 1

            position = broker.snapshot(mark.close).position
            policy = self.close_exit_policy
            if position is not None and policy is not None:
                bars_held = index - opened_at_index[position.id] + 1
                reason = None
                if policy.max_holding_bars is not None and bars_held >= policy.max_holding_bars:
                    reason = "TIME_EXIT"
                lookback = policy.momentum_lookback
                if reason is None and lookback is not None and bars_held >= policy.minimum_holding_bars:
                    history_end = len(warmup) + index + 1
                    closes = [c.close for c in observed[history_end - lookback:history_end]]
                    average = sum(closes, Decimal("0")) / Decimal(lookback)
                    failed = ((position.direction == Direction.LONG
                               and trade.close < position.entry_price and trade.close < average)
                              or (position.direction == Direction.SHORT
                                  and trade.close > position.entry_price and trade.close > average))
                    if failed:
                        reason = "MOMENTUM_EXIT"
                if reason is not None:
                    pending_management_exit = (position.id, reason)

            position = broker.snapshot(mark.close).position
            trailing = self.trailing_stop_policy
            if position is not None and trailing is not None:
                history_end = len(warmup) + index + 1
                history = observed[:history_end]
                anchor = trailing_anchor[position.id]
                if position.direction == Direction.LONG:
                    anchor = max(anchor, trade.close)
                else:
                    anchor = min(anchor, trade.close)
                trailing_anchor[position.id] = anchor
                if len(history) >= trailing.atr_period + 1:
                    atr = average_true_range(history, trailing.atr_period)
                    if position.direction == Direction.LONG:
                        proposed = floor_step(anchor - atr * trailing.atr_multiple,
                                              self.settings.contract.tick_size)
                        tighter = proposed > position.stop_price
                    else:
                        proposed = ceil_step(anchor + atr * trailing.atr_multiple,
                                             self.settings.contract.tick_size)
                        tighter = proposed < position.stop_price
                    if proposed > 0 and tighter:
                        broker.tighten_stop(proposed)
                        stop_updates += 1
            account = broker.mark(mark.close)
            end_at = trade.closed_at - timedelta(microseconds=1)
            state.observe(trade.close, end_at, account.equity)
            equity_curve.append(account.equity)

            history = observed[:len(warmup) + index + 1]
            signal = self.strategy.analyze(history)
            if signal.symbol != trade.symbol or signal.timestamp != trade.closed_at:
                raise ValueError("Strategy signal must match the completed trade candle")
            pending = signal

        if broker.snapshot(mark_candles[-1].close).position is not None:
            close(trade_candles[-1].close, trade_candles[-1].closed_at - timedelta(microseconds=1),
                  "END_OF_DATA")
        final = broker.snapshot().balance
        equity_curve.append(final)
        performance = calculate_derivative_performance(
            self.settings.initial_capital, final, broker.trades, equity_curve,
        )
        return DerivativeReplayResult(
            len(trade_candles), signals, entries, rejected, performance,
            tuple(broker.trades), tuple(equity_curve),
            stop_updates,
        )
