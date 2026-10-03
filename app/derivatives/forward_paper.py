"""Durable, activation-gated PF_XBTUSD PAPER execution from verified bundles.

This module deliberately has no private exchange API and cannot submit orders.  It
advances one immutable four-hour bundle at a time, persists the complete simulated
account after every bundle, and refuses to start unless the preregistered screen and
holdout both produced valid passing receipts.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.derivatives.broker import DerivativePaperBroker
from app.derivatives.models import DerivativePosition, DerivativeTrade
from app.derivatives.risk import DerivativeRiskContext, LeveragedRiskManager
from app.derivatives.settings import DerivativeSettings
from app.domain import Direction
from app.market_data.datasets import sha256
from app.market_data.kraken_perpetual_forward import STEP
from app.market_data.quote_monitor import exclusive_file, publish_summary
from app.strategies.funding_aware_regime_momentum import (
    FundingAwareRegimeMomentumParameters,
    FundingAwareRegimeMomentumStrategy,
)
from app.strategies.models import Signal
from backtesting.derivatives import calculate_derivative_performance
from backtesting.perpetual_forward_research import (
    FORWARD_START,
    SCREEN_BLOCKS,
    TOTAL_BLOCKS,
    _bundle_inventory,
    load_forward_series,
    read_protocol,
    sha,
)


VERSION = 1
MAX_HOLDING_BARS = 42
PAPER_START = FORWARD_START + TOTAL_BLOCKS * STEP


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Direction):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _file_sha(path: Path) -> str:
    return sha256(path.read_bytes())


def _stage_receipt(protocol_path: Path, stage: str, blocks: int) -> dict[str, Any]:
    directory = protocol_path.parent / stage
    results_path, completion_path = directory / "results.json", directory / "completion.json"
    if not results_path.is_file() or not completion_path.is_file():
        raise ValueError(f"Completed {stage} receipt is missing")
    results = json.loads(results_path.read_text(encoding="utf-8"))
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    assessment = results.get("assessment", {})
    if (completion.get("results_sha256") != _file_sha(results_path)
            or results.get("protocol_sha256") != _file_sha(protocol_path)
            or results.get("stage") != stage
            or results.get("coverage", {}).get("bundles") != blocks
            or results.get("activation") != {"paper_enabled": False, "live_enabled": False}
            or assessment.get("passed") is not True
            or (stage == "holdout" and assessment.get("paper_candidate") is not True)):
        raise ValueError(f"Passing {stage} receipt failed integrity or activation checks")
    return {
        "results_sha256": _file_sha(results_path),
        "completion_sha256": _file_sha(completion_path),
        "coverage": results["coverage"],
    }


def verify_paper_gate(protocol_path: Path, cost_candidate: Path,
                      cost_summary: Path) -> tuple[DerivativeSettings, dict[str, Any]]:
    """Return frozen primary settings only after both forward stages pass."""
    protocol, observed = read_protocol(protocol_path, cost_candidate, cost_summary)
    screen = _stage_receipt(protocol_path, "screen", SCREEN_BLOCKS)
    holdout = _stage_receipt(protocol_path, "holdout", TOTAL_BLOCKS)
    if (datetime.fromisoformat(holdout["coverage"]["end"]) != PAPER_START
            or protocol["definition"]["gate"]["maximum_leverage"] != 10
            or observed.settings.max_leverage > 10):
        raise ValueError("Holdout coverage or leverage gate differs from the frozen protocol")
    proof = {
        "protocol_sha256": _file_sha(protocol_path),
        "cost_candidate_sha256": _file_sha(cost_candidate),
        "cost_summary_sha256": _file_sha(cost_summary),
        "screen": screen,
        "holdout": holdout,
    }
    return observed.settings, proof


def readiness(protocol_path: Path) -> dict[str, Any]:
    """Describe the non-mutating activation state without opening holdout data early."""
    screen = protocol_path.parent / "screen" / "completion.json"
    holdout = protocol_path.parent / "holdout" / "completion.json"
    if not screen.is_file():
        status, reason = "awaiting_screen", "The preregistered 30-day screen is incomplete."
    elif not holdout.is_file():
        status, reason = "awaiting_holdout", "The independent 60-day holdout is incomplete."
    else:
        status, reason = "receipts_available", "Receipts exist; run verifies every hash and gate."
    return {"status": status, "reason": reason, "paper_start": PAPER_START.isoformat(),
            "live_enabled": False}


def _signal(signal: Signal) -> dict[str, Any]:
    return _json_value(asdict(signal))


def _load_signal(value: dict[str, Any]) -> Signal:
    return Signal(
        value["symbol"], datetime.fromisoformat(value["timestamp"]),
        Direction(value["direction"]), Decimal(value["confidence"]),
        tuple(value["reasons"]), value["strategy"], value["strategy_version"],
        Decimal(value["stop_price"]) if value["stop_price"] is not None else None,
        Decimal(value["take_profit_price"]) if value["take_profit_price"] is not None else None,
        Decimal(value["requested_leverage"]),
    )


def _position(position: DerivativePosition | None) -> dict[str, Any] | None:
    if position is None:
        return None
    value = asdict(position)
    value.pop("contract")
    return _json_value(value)


def _load_position(value: dict[str, Any] | None,
                   settings: DerivativeSettings) -> DerivativePosition | None:
    if value is None:
        return None
    return DerivativePosition(
        value["id"], settings.contract, Direction(value["direction"]),
        Decimal(value["quantity"]), Decimal(value["entry_price"]), int(value["leverage"]),
        datetime.fromisoformat(value["opened_at"]), Decimal(value["entry_fee"]),
        Decimal(value["initial_margin"]), Decimal(value["liquidation_price"]),
        Decimal(value["stop_price"]),
        Decimal(value["take_profit_price"]) if value["take_profit_price"] is not None else None,
    )


def _trade(trade: DerivativeTrade) -> dict[str, Any]:
    return {
        "id": trade.id, "position": _position(trade.position),
        "exit_price": str(trade.exit_price), "closed_at": trade.closed_at.isoformat(),
        "exit_fee": str(trade.exit_fee), "funding_paid": str(trade.funding_paid),
        "liquidation_fee": str(trade.liquidation_fee), "exit_reason": trade.exit_reason,
    }


def _load_trade(value: dict[str, Any], settings: DerivativeSettings) -> DerivativeTrade:
    position = _load_position(value["position"], settings)
    if position is None:
        raise ValueError("Stored trade has no position")
    return DerivativeTrade(
        value["id"], position, Decimal(value["exit_price"]),
        datetime.fromisoformat(value["closed_at"]), Decimal(value["exit_fee"]),
        Decimal(value["funding_paid"]), Decimal(value["liquidation_fee"]),
        value["exit_reason"],
    )


def _settings(settings: DerivativeSettings) -> dict[str, Any]:
    return _json_value(asdict(settings))


@dataclass
class _RiskState:
    peak: Decimal
    day_start: Decimal
    last_equity: Decimal
    day: date | None = None
    daily_halted: bool = False
    drawdown_halted: bool = False

    def observe(self, settings: DerivativeSettings, price: Decimal, timestamp: datetime,
                equity: Decimal) -> DerivativeRiskContext:
        current_day = timestamp.astimezone(timezone.utc).date()
        if current_day != self.day:
            self.day_start = self.last_equity
            self.daily_halted = False
            self.day = current_day
        self.peak = max(self.peak, equity)
        self.daily_halted |= equity <= self.day_start * (1 - settings.max_daily_loss)
        self.drawdown_halted |= equity <= self.peak * (1 - settings.max_drawdown)
        self.last_equity = equity
        return DerivativeRiskContext(
            price, timestamp, max(equity, Decimal("0")), self.day_start, self.peak,
            self.daily_halted, self.drawdown_halted, equity <= 0,
        )


def _new_state(settings: DerivativeSettings, pending: Signal) -> dict[str, Any]:
    capital = str(settings.initial_capital)
    return {
        "processed_blocks": 0, "balance": capital, "funding_paid": "0",
        "last_mark": None, "position": None, "trades": [],
        "pending_signal": _signal(pending), "pending_management_exit": None,
        "position_bars_held": 0,
        "risk": {"peak": capital, "day_start": capital, "last_equity": capital,
                 "day": None, "daily_halted": False, "drawdown_halted": False},
        "equity_curve": [capital], "last_event_sha256": None,
    }


def _restore_broker(settings: DerivativeSettings, state: dict[str, Any]) -> DerivativePaperBroker:
    broker = DerivativePaperBroker(settings)
    broker._balance = Decimal(state["balance"])
    broker._funding_paid = Decimal(state["funding_paid"])
    broker._last_mark = Decimal(state["last_mark"]) if state["last_mark"] is not None else None
    broker._position = _load_position(state["position"], settings)
    broker.trades = [_load_trade(value, settings) for value in state["trades"]]
    return broker


def _risk(state: dict[str, Any]) -> _RiskState:
    value = state["risk"]
    return _RiskState(
        Decimal(value["peak"]), Decimal(value["day_start"]), Decimal(value["last_equity"]),
        date.fromisoformat(value["day"]) if value["day"] else None,
        bool(value["daily_halted"]), bool(value["drawdown_halted"]),
    )


def _save_runtime(state: dict[str, Any], broker: DerivativePaperBroker,
                  risk: _RiskState) -> None:
    state.update({
        "balance": str(broker._balance), "funding_paid": str(broker._funding_paid),
        "last_mark": str(broker._last_mark) if broker._last_mark is not None else None,
        "position": _position(broker._position),
        "trades": [_trade(trade) for trade in broker.trades],
        "risk": {"peak": str(risk.peak), "day_start": str(risk.day_start),
                 "last_equity": str(risk.last_equity),
                 "day": risk.day.isoformat() if risk.day else None,
                 "daily_halted": risk.daily_halted,
                 "drawdown_halted": risk.drawdown_halted},
    })


def _process_bar(state: dict[str, Any], settings: DerivativeSettings, trade, mark,
                 funding: Decimal, next_signal: Signal) -> list[str]:
    broker, risk = _restore_broker(settings, state), _risk(state)
    manager, actions = LeveragedRiskManager(settings), []
    at_open = trade.timestamp

    account = broker.mark(mark.open)
    risk.observe(settings, trade.open, at_open, account.equity)
    position = account.position
    if position is not None:
        liquidated = ((position.direction == Direction.LONG and mark.open <= position.liquidation_price)
                      or (position.direction == Direction.SHORT and mark.open >= position.liquidation_price))
        stop_gap = ((position.direction == Direction.LONG and trade.open <= position.stop_price)
                    or (position.direction == Direction.SHORT and trade.open >= position.stop_price))
        if liquidated:
            broker.close_position(mark.open, at_open, "LIQUIDATION_GAP", liquidation=True)
            state["position_bars_held"] = 0
            actions.append("LIQUIDATION_GAP")
        elif stop_gap:
            broker.close_position(trade.open, at_open, "STOP_GAP")
            state["position_bars_held"] = 0
            actions.append("STOP_GAP")

    position = broker.snapshot(mark.open).position
    pending_exit = state["pending_management_exit"]
    if position is not None and pending_exit == position.id:
        broker.close_position(trade.open, at_open, "TIME_EXIT")
        state["position_bars_held"] = 0
        actions.append("TIME_EXIT")
    state["pending_management_exit"] = None

    pending = _load_signal(state["pending_signal"])
    if pending.direction in (Direction.LONG, Direction.SHORT):
        account = broker.snapshot(mark.open)
        context = risk.observe(settings, trade.open, at_open, account.equity)
        decision = manager.evaluate(pending, account, context)
        if decision.allowed:
            broker.open_position(pending, decision, at_open)
            state["position_bars_held"] = 0
            actions.append(f"OPEN_{pending.direction.value}_{decision.leverage}X")
        else:
            actions.append("ENTRY_REJECTED: " + decision.reasons[0])

    position = broker.snapshot(mark.open).position
    if position is not None:
        stop_hit = ((position.direction == Direction.LONG and trade.low <= position.stop_price)
                    or (position.direction == Direction.SHORT and trade.high >= position.stop_price))
        liquidated = ((position.direction == Direction.LONG and mark.low <= position.liquidation_price)
                      or (position.direction == Direction.SHORT and mark.high >= position.liquidation_price))
        end_at = trade.closed_at - timedelta(microseconds=1)
        if stop_hit:
            broker.close_position(position.stop_price, end_at, "STOP_LOSS")
            state["position_bars_held"] = 0
            actions.append("STOP_LOSS")
        elif liquidated:
            broker.close_position(position.liquidation_price, end_at, "LIQUIDATION", liquidation=True)
            state["position_bars_held"] = 0
            actions.append("LIQUIDATION")

    position = broker.snapshot(mark.close).position
    if position is not None and funding:
        paid = broker.apply_funding(funding, mark.close)
        actions.append(f"FUNDING_{paid}")
    position = broker.snapshot(mark.close).position
    if position is not None:
        state["position_bars_held"] += 1
        if state["position_bars_held"] >= MAX_HOLDING_BARS:
            state["pending_management_exit"] = position.id

    account = broker.mark(mark.close)
    end_at = trade.closed_at - timedelta(microseconds=1)
    risk.observe(settings, trade.close, end_at, account.equity)
    state["equity_curve"].append(str(account.equity))
    state["pending_signal"] = _signal(next_signal)
    _save_runtime(state, broker, risk)
    return actions


def _load_events(output: Path, initial: dict[str, Any]) -> dict[str, Any]:
    state, previous = initial, None
    event_dir = output / "events"
    files = sorted(event_dir.glob("*.json")) if event_dir.exists() else []
    for sequence, path in enumerate(files, 1):
        event = json.loads(path.read_text(encoding="utf-8"))
        prior = previous
        if (path.name != f"{sequence:08}.json" or event.get("sequence") != sequence
                or event.get("previous_event_sha256") != prior):
            raise ValueError("PAPER event chain is incomplete or reordered")
        state = event["state_after"]
        if state.get("last_event_sha256") != prior:
            # The stored state anchors the preceding event because an event cannot hash itself.
            raise ValueError("PAPER event state anchor differs")
        previous = _file_sha(path)
    state["last_event_sha256"] = previous
    cache = output / "state.json"
    if cache.is_file():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached != state:
            publish_summary(cache, state)
    return state


def _verify_event_evidence(output: Path, series, processed: int) -> None:
    files = sorted((output / "events").glob("*.json")) if (output / "events").exists() else []
    if len(files) != processed:
        raise ValueError("PAPER state and event count differ")
    for sequence, event_path in enumerate(files, 1):
        absolute = TOTAL_BLOCKS + sequence - 1
        source = series.paths[absolute]
        event = json.loads(event_path.read_text(encoding="utf-8"))
        if (event.get("bundle") != source.name
                or event.get("bundle_manifest_sha256") != sha(source / "bundle.json")
                or event.get("start") != series.trade[absolute].timestamp.isoformat()
                or event.get("end") != series.trade[absolute].closed_at.isoformat()):
            raise ValueError("Stored PAPER event no longer matches verified forward evidence")


def _summary(settings: DerivativeSettings, state: dict[str, Any], status: str) -> dict[str, Any]:
    broker = _restore_broker(settings, state)
    snapshot = broker.snapshot()
    performance = calculate_derivative_performance(
        settings.initial_capital, broker._balance, broker.trades,
        [Decimal(value) for value in state["equity_curve"]],
    )
    maximum = max(
        [trade.position.leverage for trade in broker.trades]
        + ([snapshot.position.leverage] if snapshot.position else [0])
    )
    return {
        "status": status, "mode": "PAPER", "provider": "Kraken Futures public evidence",
        "market": settings.contract.market_id, "processed_blocks": state["processed_blocks"],
        "balance": str(snapshot.balance), "equity": str(snapshot.equity),
        "open_position": _position(snapshot.position), "closed_trades": len(broker.trades),
        "performance": performance.as_dict(), "maximum_leverage_used": maximum,
        "maximum_leverage_allowed": 10, "live_enabled": False,
        "last_event_sha256": state["last_event_sha256"],
    }


def run(output: Path, forward_root: Path, protocol_path: Path, cost_candidate: Path,
        cost_summary: Path, *, max_blocks: int = 42) -> dict[str, Any]:
    if type(max_blocks) is not int or not 1 <= max_blocks <= 42:
        raise ValueError("max_blocks must be an integer from 1 to 42")
    settings, proof = verify_paper_gate(protocol_path, cost_candidate, cost_summary)
    if settings.max_leverage > 10:
        raise ValueError("PAPER leverage exceeds the 10x hard cap")
    inventory = _bundle_inventory(forward_root)
    post_cutoff = [(path, manifest) for path, manifest in inventory
                   if datetime.fromisoformat(manifest["start"]) >= FORWARD_START]
    if len(post_cutoff) < TOTAL_BLOCKS:
        raise ValueError("Verified holdout bundles are incomplete")
    paper_available = len(post_cutoff) - TOTAL_BLOCKS
    total = TOTAL_BLOCKS + paper_available
    series = load_forward_series(forward_root, total)
    funding_by_candle = dict(zip((c.timestamp for c in series.trade), series.funding))
    strategy = FundingAwareRegimeMomentumStrategy(series.aligned, funding_by_candle)
    warmup = FundingAwareRegimeMomentumParameters().required_history
    initial_pending = strategy.analyze(series.trade[TOTAL_BLOCKS - warmup:TOTAL_BLOCKS])
    initial = _new_state(settings, initial_pending)
    config = {
        "version": VERSION, "mode": "PAPER", "live_enabled": False,
        "provider": "Kraken Futures public verified forward bundles",
        "market": settings.contract.market_id, "paper_start": PAPER_START.isoformat(),
        "strategy": FundingAwareRegimeMomentumStrategy.name,
        "strategy_version": FundingAwareRegimeMomentumStrategy.version,
        "strategy_source_sha256": hashlib.sha256(
            inspect.getsource(FundingAwareRegimeMomentumStrategy).encode()).hexdigest(),
        "runner_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "settings": _settings(settings), "activation_proof": proof,
        "execution": "next 4h open; intrabar stop/liquidation; signed completed funding",
    }
    output.mkdir(parents=True, exist_ok=True)
    with exclusive_file(output / "runner.lock"):
        session_path = output / "session.json"
        if session_path.is_file():
            if json.loads(session_path.read_text(encoding="utf-8")) != config:
                raise ValueError("PAPER session configuration or activation proof changed")
        else:
            if any(output.iterdir()):
                allowed = {"runner.lock"}
                if {path.name for path in output.iterdir()} - allowed:
                    raise ValueError("New PAPER session requires an empty output directory")
            publish_summary(session_path, config)
        state = _load_events(output, initial)
        if state["processed_blocks"] > paper_available:
            raise ValueError("Persisted PAPER state is ahead of verified evidence")
        _verify_event_evidence(output, series, state["processed_blocks"])
        event_dir = output / "events"
        event_dir.mkdir(exist_ok=True)
        stop = min(paper_available, state["processed_blocks"] + max_blocks)
        for paper_index in range(state["processed_blocks"], stop):
            absolute = TOTAL_BLOCKS + paper_index
            history = series.trade[absolute - warmup + 1:absolute + 1]
            next_signal = strategy.analyze(history)
            actions = _process_bar(
                state, settings, series.trade[absolute], series.mark[absolute],
                series.funding[absolute], next_signal,
            )
            sequence = paper_index + 1
            state["processed_blocks"] = sequence
            path = series.paths[absolute]
            event = {
                "version": VERSION, "sequence": sequence,
                "previous_event_sha256": state["last_event_sha256"],
                "bundle": path.name, "bundle_manifest_sha256": sha(path / "bundle.json"),
                "start": series.trade[absolute].timestamp.isoformat(),
                "end": series.trade[absolute].closed_at.isoformat(),
                "actions": actions, "state_after": state,
            }
            target = event_dir / f"{sequence:08}.json"
            if target.exists():
                raise ValueError("PAPER event already exists")
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(json.dumps(_json_value(event), indent=2,
                                             ensure_ascii=False, allow_nan=False).encode() + b"\n")
            temporary.replace(target)
            state["last_event_sha256"] = _file_sha(target)
            publish_summary(output / "state.json", state)
        status = "observing" if state["processed_blocks"] < paper_available else "caught_up"
        summary = _summary(settings, state, status)
        summary["available_blocks"] = paper_available
        summary["activation_proof"] = proof
        publish_summary(output / "status.json", summary)
        return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Activation-gated durable PF_XBTUSD PAPER runner; never submits orders"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--protocol", type=Path, required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--output", type=Path, required=True)
    execute.add_argument("--forward-root", type=Path, required=True)
    execute.add_argument("--protocol", type=Path, required=True)
    execute.add_argument("--cost-candidate", type=Path, required=True)
    execute.add_argument("--cost-summary", type=Path, required=True)
    execute.add_argument("--max-blocks", type=int, default=42)
    args = parser.parse_args(argv)
    try:
        result = (readiness(args.protocol) if args.command == "status" else
                  run(args.output, args.forward_root, args.protocol,
                      args.cost_candidate, args.cost_summary, max_blocks=args.max_blocks))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Perpetual PAPER failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
