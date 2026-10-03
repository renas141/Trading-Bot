"""Restartable public-quote PF_XBTUSD PAPER observer; never sends orders."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

from app.derivatives.forward_paper import (
    MAX_HOLDING_BARS,
    _file_sha,
    _json_value,
    _new_state,
    _position,
    _restore_broker,
    _risk,
    _save_runtime,
    _settings,
    verify_paper_gate,
)
from app.derivatives.observed_costs import load_observed_cost_scenario
from app.derivatives.risk import LeveragedRiskManager
from app.derivatives.settings import DerivativeSettings
from app.domain import Direction
from app.errors import MarketDataError
from app.market_data.datasets import sha256
from app.market_data.kraken_perpetual_analytics import (
    AnalyticsSnapshot,
    KrakenPerpetualAnalyticsAdapter,
)
from app.market_data.quote_monitor import exclusive_file, publish_summary
from app.strategies.funding_aware_regime_momentum import (
    FundingAwareRegimeMomentumParameters,
    FundingAwareRegimeMomentumStrategy,
)
from app.strategies.models import Signal
from backtesting.derivatives import calculate_derivative_performance
from backtesting.perpetual_forward_research import (
    FEE_RATE,
    FEE_SOURCE,
    FORWARD_START,
    TOTAL_BLOCKS,
    _bundle_inventory,
    load_forward_series,
)


VERSION = 1
DEFAULT_MAX_QUOTE_AGE_SECONDS = 180
DEFAULT_MAX_REQUEST_SECONDS = 30
DEFAULT_MAX_SIGNAL_AGE_SECONDS = 900


@dataclass(frozen=True)
class CandidateObservation:
    signal: Signal | None
    candle_end: datetime | None
    funding_rate: Decimal = Decimal("0")
    bundle: str | None = None
    bundle_manifest_sha256: str | None = None
    skipped_candles: int = 0
    note: str | None = None


def _hold(at: datetime) -> Signal:
    return Signal(
        "BTC/USD", at, Direction.HOLD, Decimal("0"),
        ("Realtime observer has no approved strategy.",),
        "no_trade_realtime_perpetual", "1", requested_leverage=Decimal("1"),
    )


def _runtime_settings(candidate: Path, summary: Path) -> tuple[DerivativeSettings, dict]:
    observed = load_observed_cost_scenario(
        candidate, summary, fee_rate=FEE_RATE, fee_source=FEE_SOURCE,
    )
    # The public bid/ask already contains the observed spread. Retain only the
    # separately calibrated adverse depth/slippage assumption.
    settings = replace(observed.settings, spread_bps=Decimal("0"))
    proof = {
        "cost_candidate_sha256": _file_sha(candidate),
        "cost_summary_sha256": _file_sha(summary),
        "source_summary_sha256": observed.source_summary_sha256,
        "spread_model": "observed public bid/ask",
        "additional_slippage_bps": str(settings.slippage_bps),
        "fee_rate": str(settings.fee_rate),
    }
    return settings, proof


def _new_realtime_state(settings: DerivativeSettings, activated_at: datetime) -> dict:
    state = _new_state(settings, _hold(activated_at))
    state.update({
        "quote_events": 0,
        "last_quote_event_at": None,
        "last_quote_received_at": None,
        "last_signal_candle": None,
        "last_funding_candle": None,
        "position_bars_held": 0,
        "last_actions": [],
    })
    return state


def _event_id(snapshot: AnalyticsSnapshot) -> str:
    evidence = {
        "event_at": snapshot.event_at.isoformat(),
        "raw": {kind: sha256(raw) for kind, raw in snapshot.raw.items()},
    }
    return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()


def _validate_snapshot(snapshot: AnalyticsSnapshot, now: datetime, *, max_quote_age: int,
                       max_request_seconds: int) -> None:
    if (snapshot.symbol != "PF_XBTUSD" or snapshot.bid <= 0 or snapshot.ask <= snapshot.bid
            or snapshot.requested_at.tzinfo is None or snapshot.received_at.tzinfo is None
            or snapshot.event_at.tzinfo is None):
        raise MarketDataError("Invalid PF_XBTUSD public quote snapshot")
    event_age = (now - snapshot.event_at).total_seconds()
    request_time = (snapshot.received_at - snapshot.requested_at).total_seconds()
    receipt_age = (now - snapshot.received_at).total_seconds()
    if (not 0 <= event_age <= max_quote_age or not 0 <= request_time <= max_request_seconds
            or not 0 <= receipt_age <= max_quote_age):
        raise MarketDataError("Public quote is stale, slow, or from the future")
    if set(snapshot.raw) != {"spreads", "slippage", "funding"}:
        raise MarketDataError("Public quote evidence inventory differs")


def _tier(notional: Decimal) -> str | None:
    for limit, name in ((Decimal("1000"), "1k"), (Decimal("10000"), "10k"),
                        (Decimal("100000"), "100k"), (Decimal("1000000"), "1m")):
        if notional <= limit:
            return name
    return None


def _entry_decision(manager: LeveragedRiskManager, signal: Signal, broker, risk,
                    settings: DerivativeSettings, snapshot: AnalyticsSnapshot):
    reference = snapshot.ask if signal.direction == Direction.LONG else snapshot.bid
    account = broker.snapshot((snapshot.bid + snapshot.ask) / 2)
    context = risk.observe(settings, reference, snapshot.received_at, account.equity)
    decision = manager.evaluate(signal, account, context)
    if not decision.allowed:
        return decision, None
    for _ in range(2):
        tier = _tier(decision.quantity * decision.entry_price)
        execution = (snapshot.execution_prices.get(
            f"{'buy' if signal.direction == Direction.LONG else 'sell'}_{tier}"
        ) if tier else None)
        if execution is None:
            return replace(decision, allowed=False,
                           reasons=("Observed execution depth is unavailable for this size.",)), tier
        fraction = settings.slippage_bps / Decimal("10000")
        if signal.direction == Direction.LONG:
            reference = max(snapshot.ask, execution / (1 + fraction))
        else:
            reference = min(snapshot.bid, execution / (1 - fraction))
        account = broker.snapshot((snapshot.bid + snapshot.ask) / 2)
        context = risk.observe(settings, reference, snapshot.received_at, account.equity)
        decision = manager.evaluate(signal, account, context)
        if not decision.allowed:
            return decision, tier
    return decision, tier


def _exit_reference(snapshot: AnalyticsSnapshot, position, settings: DerivativeSettings) -> tuple[Decimal, str]:
    tier = _tier(position.quantity * ((snapshot.bid + snapshot.ask) / 2)) or "1m"
    fraction = settings.slippage_bps / Decimal("10000")
    if position.direction == Direction.LONG:
        observed = snapshot.execution_prices.get(f"sell_{tier}")
        reference = min(snapshot.bid, observed / (1 - fraction)) if observed is not None else snapshot.bid
    else:
        observed = snapshot.execution_prices.get(f"buy_{tier}")
        reference = max(snapshot.ask, observed / (1 + fraction)) if observed is not None else snapshot.ask
    return reference, tier


def candidate_observation(forward_root: Path, state: dict, now: datetime) -> CandidateObservation:
    inventory = _bundle_inventory(forward_root)
    post_cutoff = [(path, manifest) for path, manifest in inventory
                   if datetime.fromisoformat(manifest["start"]) >= FORWARD_START]
    if len(post_cutoff) < TOTAL_BLOCKS:
        raise ValueError("Candidate PAPER requires complete verified holdout coverage")
    series = load_forward_series(forward_root, len(post_cutoff))
    latest, path = series.trade[-1], series.paths[-1]
    activated = datetime.fromisoformat(state["activated_at"])
    previous = (datetime.fromisoformat(state["last_signal_candle"])
                if state["last_signal_candle"] else activated)
    if latest.closed_at <= previous:
        return CandidateObservation(None, None, note="No new completed candidate candle.")
    fresh_indices = [index for index, candle in enumerate(series.trade)
                     if previous < candle.closed_at <= now]
    if not fresh_indices:
        return CandidateObservation(None, None, note="Latest verified candle is not yet usable.")
    index = fresh_indices[-1]
    latest, path = series.trade[index], series.paths[index]
    if latest.closed_at <= activated:
        return CandidateObservation(
            None, latest.closed_at, bundle=path.name,
            bundle_manifest_sha256=_file_sha(path / "bundle.json"),
            skipped_candles=max(0, len(fresh_indices) - 1),
            note="Warm-up evidence predates realtime activation.",
        )
    parameters = FundingAwareRegimeMomentumParameters()
    begin = index - parameters.required_history + 1
    if begin < 0:
        raise ValueError("Candidate PAPER has insufficient verified warm-up")
    funding_by_candle = dict(zip((c.timestamp for c in series.trade), series.funding))
    strategy = FundingAwareRegimeMomentumStrategy(series.aligned, funding_by_candle)
    signal = strategy.analyze(series.trade[begin:index + 1])
    funding = sum((series.funding[item] for item in fresh_indices), Decimal("0"))
    return CandidateObservation(
        signal, latest.closed_at, funding, path.name,
        _file_sha(path / "bundle.json"), max(0, len(fresh_indices) - 1),
        "Missed completed candles were not backfilled as entries." if len(fresh_indices) > 1 else None,
    )


def process_snapshot(state: dict, settings: DerivativeSettings, snapshot: AnalyticsSnapshot,
                     observation: CandidateObservation | None, *, manual_halt: bool,
                     max_signal_age_seconds: int = DEFAULT_MAX_SIGNAL_AGE_SECONDS) -> list[str]:
    broker, risk = _restore_broker(settings, state), _risk(state)
    manager, actions = LeveragedRiskManager(settings), []
    midpoint = (snapshot.bid + snapshot.ask) / 2
    account = broker.mark(midpoint)
    risk.observe(settings, midpoint, snapshot.received_at, account.equity)
    position = account.position
    if (position is not None and observation is not None
            and observation.candle_end is not None and observation.funding_rate):
        payment = broker.apply_funding(observation.funding_rate, midpoint)
        actions.append(f"FUNDING_{payment}")
        position = broker.snapshot(midpoint).position
    if position is not None:
        liquidated = ((position.direction == Direction.LONG and midpoint <= position.liquidation_price)
                      or (position.direction == Direction.SHORT and midpoint >= position.liquidation_price))
        stopped = ((position.direction == Direction.LONG and snapshot.bid <= position.stop_price)
                   or (position.direction == Direction.SHORT and snapshot.ask >= position.stop_price))
        if liquidated or stopped:
            reference, tier = _exit_reference(snapshot, position, settings)
            reason = "PAPER_REALTIME_LIQUIDATION" if liquidated else "PAPER_REALTIME_STOP"
            broker.close_position(reference, snapshot.received_at, reason, liquidation=liquidated)
            state["position_bars_held"] = 0
            actions.append(f"{reason}_{tier}")

    if observation is not None and observation.candle_end is not None:
        position = broker.snapshot(midpoint).position
        state["last_signal_candle"] = observation.candle_end.isoformat()
        state["last_funding_candle"] = observation.candle_end.isoformat()
        if position is not None:
            state["position_bars_held"] += 1 + observation.skipped_candles
            if state["position_bars_held"] >= MAX_HOLDING_BARS:
                reference, tier = _exit_reference(snapshot, position, settings)
                broker.close_position(reference, snapshot.received_at, "PAPER_REALTIME_TIME_EXIT")
                state["position_bars_held"] = 0
                actions.append(f"PAPER_REALTIME_TIME_EXIT_{tier}")
        if observation.note:
            actions.append(observation.note)

        signal = observation.signal
        if signal is not None:
            if (signal.timestamp != observation.candle_end
                    or signal.timestamp > snapshot.received_at):
                raise ValueError("Candidate signal does not match the fresh completed candle")
            state["pending_signal"] = _json_value(asdict(signal))
            if signal.direction == Direction.HOLD:
                actions.append("NO_ENTRY_HOLD")
            elif manual_halt:
                actions.append("ENTRY_REJECTED: Manual kill switch is active.")
            elif (snapshot.received_at - signal.timestamp).total_seconds() > max_signal_age_seconds:
                actions.append("ENTRY_REJECTED: Closed-candle signal is stale.")
            elif broker.snapshot(midpoint).position is not None:
                actions.append("ENTRY_REJECTED: A derivative position is already open.")
            else:
                decision, tier = _entry_decision(manager, signal, broker, risk, settings, snapshot)
                if decision.allowed:
                    opened = broker.open_position(signal, decision, snapshot.received_at)
                    state["position_bars_held"] = 0
                    actions.append(f"OPEN_{opened.direction.value}_{opened.leverage}X_{tier}")
                else:
                    actions.append("ENTRY_REJECTED: " + decision.reasons[0])

    account = broker.mark(midpoint)
    risk.observe(settings, midpoint, snapshot.received_at, account.equity)
    state["equity_curve"].append(str(account.equity))
    state["quote_events"] += 1
    state["last_quote_event_at"] = snapshot.event_at.isoformat()
    state["last_quote_received_at"] = snapshot.received_at.isoformat()
    state["last_actions"] = actions
    _save_runtime(state, broker, risk)
    return actions


def _load_events(output: Path, initial: dict,
                 forward_root: Path | None = None) -> tuple[dict, set[str]]:
    state, prior, ids = initial, None, set()
    event_dir = output / "events"
    files = sorted(event_dir.glob("*.json")) if event_dir.exists() else []
    for sequence, path in enumerate(files, 1):
        event = json.loads(path.read_text(encoding="utf-8"))
        if (path.name != f"{sequence:08}.json" or event.get("sequence") != sequence
                or event.get("previous_event_sha256") != prior
                or event.get("event_id") in ids):
            raise ValueError("Realtime PAPER event chain is incomplete, reordered or duplicated")
        for kind in ("spreads", "slippage", "funding"):
            raw = event.get("quote_raw", {}).get(kind)
            expected = event.get("quote_sha256", {}).get(kind)
            if not isinstance(raw, str) or sha256(raw.encode()) != expected:
                raise ValueError("Realtime PAPER quote evidence checksum mismatch")
        candidate = event.get("candidate_observation")
        if candidate and candidate.get("bundle"):
            if forward_root is None:
                raise ValueError("Candidate event has no configured forward evidence root")
            root = forward_root.resolve()
            manifest = (root / candidate["bundle"] / "bundle.json").resolve()
            if (not manifest.is_relative_to(root) or not manifest.is_file()
                    or _file_sha(manifest) != candidate.get("bundle_manifest_sha256")):
                raise ValueError("Realtime PAPER candidate bundle checksum mismatch")
        state = event["state_after"]
        if state.get("last_event_sha256") != prior:
            raise ValueError("Realtime PAPER state anchor differs")
        ids.add(event["event_id"])
        prior = _file_sha(path)
    state["last_event_sha256"] = prior
    cache = output / "state.json"
    if cache.is_file() and json.loads(cache.read_text(encoding="utf-8")) != state:
        publish_summary(cache, state)
    return state, ids


def _append_event(output: Path, state: dict, snapshot: AnalyticsSnapshot,
                  actions: list[str], observation: CandidateObservation | None) -> None:
    sequence = state["quote_events"]
    event = {
        "version": VERSION, "sequence": sequence, "event_id": _event_id(snapshot),
        "previous_event_sha256": state["last_event_sha256"],
        "quote_event_at": snapshot.event_at.isoformat(),
        "quote_received_at": snapshot.received_at.isoformat(),
        "bid": str(snapshot.bid), "ask": str(snapshot.ask),
        "spread_bps": str(snapshot.spread_bps),
        "funding_relative_rate": str(snapshot.funding_relative_rate),
        "execution_prices": _json_value(snapshot.execution_prices),
        "quote_urls": snapshot.urls,
        "quote_raw": {kind: raw.decode("utf-8") for kind, raw in snapshot.raw.items()},
        "quote_sha256": {kind: sha256(raw) for kind, raw in snapshot.raw.items()},
        "candidate_observation": _json_value(asdict(observation)) if observation else None,
        "actions": actions, "state_after": state,
        "limitations": [
            "Analytics quotes are minute buckets and do not guarantee fills.",
            "Liquidation uses public bid/ask midpoint because a tick mark price is unavailable here.",
            "Observed depth plus calibrated adverse slippage is a conservative PAPER model.",
        ],
    }
    directory = output / "events"
    directory.mkdir(exist_ok=True)
    target = directory / f"{sequence:08}.json"
    if target.exists():
        raise ValueError("Realtime PAPER event already exists")
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(_json_value(event), indent=2, ensure_ascii=False) + "\n")
    temporary.replace(target)
    state["last_event_sha256"] = _file_sha(target)
    publish_summary(output / "state.json", state)


def _status(settings: DerivativeSettings, state: dict, strategy_status: str,
            manual_halt: bool, status: str, *, last_error: str | None = None) -> dict:
    broker = _restore_broker(settings, state)
    snapshot = broker.snapshot()
    performance = calculate_derivative_performance(
        settings.initial_capital, broker._balance, broker.trades,
        [Decimal(value) for value in state["equity_curve"]],
    )
    return {
        "schema_version": 1, "status": status, "mode": "PAPER",
        "provider": "Kraken Futures public analytics", "market": "PF_XBTUSD",
        "strategy_status": strategy_status, "live_enabled": False,
        "manual_kill_switch": manual_halt, "quote_events": state["quote_events"],
        "last_quote_event_at": state["last_quote_event_at"],
        "last_quote_received_at": state["last_quote_received_at"],
        "last_signal_candle": state["last_signal_candle"],
        "balance": str(snapshot.balance), "equity": str(snapshot.equity),
        "open_position": _position(snapshot.position), "closed_trades": len(broker.trades),
        "performance": performance.as_dict(), "last_actions": state["last_actions"],
        "daily_halted": state["risk"]["daily_halted"],
        "drawdown_halted": state["risk"]["drawdown_halted"],
        "maximum_leverage_allowed": 10, "last_error": last_error,
        "last_event_sha256": state["last_event_sha256"],
        "model_limit": (
            "Liquidationen werden mit dem öffentlichen Bid-/Ask-Mittelpunkt geprüft; "
            "ein Tick-Markpreis ist in diesem Abruf nicht enthalten."
        ),
    }


def observe(output: Path, cost_candidate: Path, cost_summary: Path, *, count: int = 1,
            interval: int = 60, until: datetime | None = None, activate_candidate: bool = False,
            protocol: Path | None = None, forward_root: Path | None = None,
            adapter=None, clock: Callable[[], datetime] | None = None,
            pause: Callable[[float], None] = time.sleep) -> dict:
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    until = until or now + timedelta(seconds=max(60, count * interval + 30))
    if (type(count) is not int or not 1 <= count <= 10000 or type(interval) is not int
            or not 60 <= interval <= 3600 or until.tzinfo is None or until <= now):
        raise ValueError("Invalid bounded realtime PAPER schedule")
    settings, cost_proof = _runtime_settings(cost_candidate, cost_summary)
    activation_proof = None
    if activate_candidate:
        if protocol is None or forward_root is None:
            raise ValueError("Candidate activation requires protocol and forward root")
        gated_settings, activation_proof = verify_paper_gate(
            protocol, cost_candidate, cost_summary,
        )
        settings = replace(gated_settings, spread_bps=Decimal("0"))
    strategy_status = ("funding_aware_candidate_active" if activate_candidate
                       else "no_trade_waiting_for_validation")
    config = {
        "version": VERSION, "mode": "PAPER", "live_enabled": False,
        "provider": "Kraken Futures public analytics", "market": "PF_XBTUSD",
        "strategy_status": strategy_status, "settings": _settings(settings),
        "cost_proof": cost_proof, "activation_proof": activation_proof,
        "runner_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "strategy_source_sha256": (hashlib.sha256(
            inspect.getsource(FundingAwareRegimeMomentumStrategy).encode()).hexdigest()
            if activate_candidate else None),
        "freshness": {"quote_seconds": DEFAULT_MAX_QUOTE_AGE_SECONDS,
                      "request_seconds": DEFAULT_MAX_REQUEST_SECONDS,
                      "signal_seconds": DEFAULT_MAX_SIGNAL_AGE_SECONDS},
    }
    output.mkdir(parents=True, exist_ok=True)
    adapter = adapter or KrakenPerpetualAnalyticsAdapter()
    with exclusive_file(output / "runner.lock"):
        session_path = output / "session.json"
        if session_path.is_file():
            saved = json.loads(session_path.read_text(encoding="utf-8"))
            expected = dict(saved)
            activated_raw = expected.pop("activated_at", None)
            if expected != config or not isinstance(activated_raw, str):
                raise ValueError("Realtime PAPER session configuration changed")
            activated_at = datetime.fromisoformat(activated_raw)
        else:
            if {path.name for path in output.iterdir()} - {"runner.lock"}:
                raise ValueError("New realtime PAPER session requires an empty output directory")
            activated_at = now
            config["activated_at"] = activated_at.isoformat()
            publish_summary(session_path, config)
        initial = _new_realtime_state(settings, activated_at)
        initial["activated_at"] = activated_at.isoformat()
        state, event_ids = _load_events(
            output, initial, forward_root if activate_candidate else None,
        )
        manual_halt = (output / "HALT.json").is_file()
        errors = 0
        result = _status(settings, state, strategy_status, manual_halt, "paused")
        result["attempts_this_process"] = 0
        for attempt in range(count):
            if clock() >= until:
                break
            try:
                snapshot = adapter.snapshot()
                current = clock()
                _validate_snapshot(
                    snapshot, current, max_quote_age=DEFAULT_MAX_QUOTE_AGE_SECONDS,
                    max_request_seconds=DEFAULT_MAX_REQUEST_SECONDS,
                )
                identity = _event_id(snapshot)
                if identity in event_ids:
                    actions = ["DUPLICATE_QUOTE_IGNORED"]
                else:
                    observation = (candidate_observation(forward_root, state, current)
                                   if activate_candidate else None)
                    actions = process_snapshot(
                        state, settings, snapshot, observation, manual_halt=manual_halt,
                    )
                    _append_event(output, state, snapshot, actions, observation)
                    event_ids.add(identity)
                errors = 0
                result = _status(settings, state, strategy_status, manual_halt, "observing")
            except (MarketDataError, ValueError, OSError) as exc:
                errors += 1
                result = _status(
                    settings, state, strategy_status, manual_halt, "degraded",
                    last_error=f"{type(exc).__name__}: {exc}",
                )
                with (output / "poll-errors.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"at": clock().isoformat(),
                                             "error": result["last_error"]}) + "\n")
            result["attempts_this_process"] = attempt + 1
            result["consecutive_errors"] = errors
            publish_summary(output / "status.json", result)
            if errors >= 5:
                break
            if attempt + 1 < count and clock() < until:
                pause(min(interval, max(0, (until - clock()).total_seconds())))
        final = _status(settings, state, strategy_status, manual_halt,
                        "paused" if errors < 5 else "degraded",
                        last_error=result.get("last_error"))
        final["attempts_this_process"] = result.get("attempts_this_process", 0)
        final["consecutive_errors"] = errors
        publish_summary(output / "status.json", final)
        return final


def set_halt(output: Path, active: bool) -> dict:
    if not (output / "session.json").is_file():
        raise ValueError("Realtime PAPER session does not exist")
    with exclusive_file(output / "runner.lock"):
        target = output / "HALT.json"
        if active:
            publish_summary(target, {
                "active": True, "set_at": datetime.now(timezone.utc).isoformat(),
                "effect": "New entries blocked; protective virtual exits remain active.",
            })
        elif target.exists():
            target.unlink()
        status_path = output / "status.json"
        status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
        status["manual_kill_switch"] = active
        status["control_updated_at"] = datetime.now(timezone.utc).isoformat()
        publish_summary(status_path, status)
        return {"manual_kill_switch": active, "output": str(output)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Bounded, restartable PF_XBTUSD realtime PAPER observer; never orders"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("observe", "activate-candidate"):
        run = sub.add_parser(name)
        run.add_argument("--output", type=Path, required=True)
        run.add_argument("--cost-candidate", type=Path, required=True)
        run.add_argument("--cost-summary", type=Path, required=True)
        run.add_argument("--count", type=int, default=1)
        run.add_argument("--interval", type=int, default=60)
        run.add_argument("--until", type=datetime.fromisoformat)
        if name == "activate-candidate":
            run.add_argument("--protocol", type=Path, required=True)
            run.add_argument("--forward-root", type=Path, required=True)
    for name in ("halt", "resume"):
        control = sub.add_parser(name)
        control.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"halt", "resume"}:
            result = set_halt(args.output, args.command == "halt")
        else:
            active = args.command == "activate-candidate"
            result = observe(
                args.output, args.cost_candidate, args.cost_summary,
                count=args.count, interval=args.interval, until=args.until,
                activate_candidate=active,
                protocol=getattr(args, "protocol", None),
                forward_root=getattr(args, "forward_root", None),
            )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, MarketDataError, json.JSONDecodeError) as exc:
        print(f"Realtime PAPER failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
