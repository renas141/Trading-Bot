"""Reproducible technical qualification for the derivative PAPER core."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.config.settings import Settings
from app.derivatives.models import DerivativeAccountSnapshot
from app.derivatives.risk import DerivativeRiskContext
from app.derivatives.realtime_paper import (
    CandidateObservation,
    _append_event,
    _load_events,
    _new_realtime_state,
    process_snapshot,
)
from app.derivatives.safety import (
    FundingAwarePaperBroker,
    StressAwareRiskManager,
    StressRiskPolicy,
    margin_health,
)
from app.derivatives.settings import DerivativeSettings
from app.domain import Direction, TradingMode
from app.errors import LiveTradingDisabled
from app.market_data.kraken_perpetual_analytics import AnalyticsSnapshot
from app.strategies.models import Signal


VERSION = 1
AT = datetime(2026, 10, 6, 20, tzinfo=timezone.utc)
SOURCE_FILES = (
    "app/config/settings.py",
    "app/derivatives/broker.py",
    "app/derivatives/models.py",
    "app/derivatives/risk.py",
    "app/derivatives/safety.py",
    "app/derivatives/settings.py",
    "app/derivatives/realtime_paper.py",
    "app/market_data/kraken_futures_ticker.py",
    "app/derivatives/qualification.py",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    return {name: _sha(root / name) for name in SOURCE_FILES}


def _signal(direction: Direction, confidence: Decimal = Decimal("1")) -> Signal:
    stop = Decimal("99") if direction == Direction.LONG else Decimal("101")
    return Signal(
        "BTC/USD", AT, direction, confidence,
        ("Deterministic technical qualification",),
        "technical_qualification", "1", stop, None, Decimal("10"),
    )


def _account() -> DerivativeAccountSnapshot:
    return DerivativeAccountSnapshot(
        Decimal("1000"), Decimal("1000"), Decimal("1000"), None, Decimal("0"),
    )


def _context() -> DerivativeRiskContext:
    return DerivativeRiskContext(
        Decimal("100"), AT, Decimal("1000"), Decimal("1000"), Decimal("1000"),
    )


def _leverage_lifecycles() -> dict:
    completed = []
    base = DerivativeSettings(
        fee_rate=Decimal("0"), spread_bps=Decimal("0"), slippage_bps=Decimal("0"),
    )
    for leverage in range(1, 11):
        settings = replace(base, max_leverage=leverage,
                           max_margin_fraction=Decimal("0.01"))
        for direction in (Direction.LONG, Direction.SHORT):
            signal = _signal(direction)
            decision = StressAwareRiskManager(settings).evaluate(
                signal, _account(), _context(),
            )
            if not decision.allowed or decision.leverage != leverage:
                raise ValueError(f"{direction.value} {leverage}x lifecycle was not approved")
            broker = FundingAwarePaperBroker(settings)
            position = broker.open_position(signal, decision, AT)
            if broker.liquidation_required(Decimal("100")):
                raise ValueError("Stress-safe position is immediately liquidatable")
            trade = broker.close_position(Decimal("100"), AT, "QUALIFICATION_CLOSE")
            if (trade.position.id != position.id or broker.snapshot().position is not None
                    or trade.exit_reason != "QUALIFICATION_CLOSE"):
                raise ValueError("Derivative lifecycle did not close consistently")
            completed.append({"direction": direction.value, "leverage": leverage})
    return {"passed": len(completed) == 20, "completed": completed}


def _funding_liquidation() -> dict:
    settings = DerivativeSettings(
        fee_rate=Decimal("0"), spread_bps=Decimal("0"), slippage_bps=Decimal("0"),
        max_margin_fraction=Decimal("0.01"),
    )
    cases = []
    for direction in (Direction.LONG, Direction.SHORT):
        signal = _signal(direction)
        decision = StressAwareRiskManager(settings).evaluate(signal, _account(), _context())
        if not decision.allowed or decision.leverage != 10:
            raise ValueError("Funding qualification requires a stress-safe 10x position")
        broker = FundingAwarePaperBroker(settings)
        position = broker.open_position(signal, decision, AT)
        before = broker.margin_health(Decimal("100"))
        adverse_rate = Decimal("0.01") if direction == Direction.LONG else Decimal("-0.01")
        paid = broker.apply_funding(adverse_rate, Decimal("100"))
        after = broker.margin_health(Decimal("100"))
        if before is None or after is None or paid <= 0:
            raise ValueError("Adverse funding was not charged to the position")
        moved_toward_entry = (
            after.dynamic_liquidation_price > before.dynamic_liquidation_price
            if direction == Direction.LONG
            else after.dynamic_liquidation_price < before.dynamic_liquidation_price
        )
        crossed = (after.dynamic_liquidation_price - Decimal("0.01")
                   if direction == Direction.LONG
                   else after.dynamic_liquidation_price + Decimal("0.01"))
        if not moved_toward_entry or not margin_health(position, crossed, paid).liquidatable:
            raise ValueError("Funding-adjusted liquidation threshold did not react")
        cases.append({
            "direction": direction.value,
            "leverage": decision.leverage,
            "funding_paid": str(paid),
            "threshold_before": str(before.dynamic_liquidation_price),
            "threshold_after": str(after.dynamic_liquidation_price),
        })
    return {"passed": len(cases) == 2, "cases": cases}


def _tail_gap_deleveraging() -> dict:
    settings = DerivativeSettings(
        fee_rate=Decimal("0"), spread_bps=Decimal("0"), slippage_bps=Decimal("0"),
        max_margin_fraction=Decimal("0.01"),
    )
    normal = StressAwareRiskManager(settings).evaluate(
        _signal(Direction.LONG), _account(), _context(),
    )
    stressed = StressAwareRiskManager(
        settings, replace(StressRiskPolicy(), tail_gap_fraction=Decimal("0.10")),
    ).evaluate(_signal(Direction.LONG), _account(), _context())
    passed = (normal.allowed and stressed.allowed
              and stressed.quantity < normal.quantity
              and stressed.leverage < normal.leverage)
    if not passed:
        raise ValueError("Tail-gap stress did not reduce both quantity and leverage")
    return {
        "passed": True,
        "normal": {"quantity": str(normal.quantity), "leverage": normal.leverage},
        "ten_percent_gap": {
            "quantity": str(stressed.quantity), "leverage": stressed.leverage,
        },
    }


def _live_lock() -> dict:
    rejected_mode = rejected_flag = False
    try:
        Settings(mode=TradingMode.LIVE)
    except LiveTradingDisabled:
        rejected_mode = True
    try:
        Settings(enable_live_trading=True)
    except LiveTradingDisabled:
        rejected_flag = True
    if not rejected_mode or not rejected_flag:
        raise ValueError("LIVE configuration lock can be bypassed")
    return {"passed": True, "live_mode_rejected": True, "enable_flag_rejected": True}


def _snapshot(*, execution_available: bool = True) -> AnalyticsSnapshot:
    executions: dict[str, Decimal | None] = {}
    for size in ("1k", "10k", "100k", "1m"):
        executions[f"sell_{size}"] = Decimal("99.99") if execution_available else None
        executions[f"buy_{size}"] = Decimal("100.01") if execution_available else None
    raw = {name: json.dumps({"kind": name}).encode()
           for name in ("spreads", "slippage", "funding", "ticker")}
    return AnalyticsSnapshot(
        "PF_XBTUSD", AT, AT - timedelta(seconds=2), AT,
        Decimal("99.99"), Decimal("100.01"), Decimal("0.00001"),
        executions, raw,
        {name: f"https://futures.kraken.com/{name}" for name in raw},
        Decimal("100"), AT, Decimal("100"), AT - timedelta(seconds=1),
        Decimal("1"), Decimal("1"), AT - timedelta(minutes=1),
    )


def _unavailable_depth_rejection() -> dict:
    settings = DerivativeSettings(
        fee_rate=Decimal("0"), spread_bps=Decimal("0"), slippage_bps=Decimal("0"),
    )
    state = _new_realtime_state(settings, AT - timedelta(hours=1))
    observation = CandidateObservation(
        _signal(Direction.LONG), AT, reference_price=Decimal("100"),
    )
    actions = process_snapshot(
        state, settings, _snapshot(execution_available=False), observation,
        manual_halt=False,
    )
    expected = "ENTRY_REJECTED: Observed execution depth is unavailable for this size."
    if actions != [expected] or state.get("position") is not None:
        raise ValueError("Realtime PAPER accepted an entry without observed depth")
    return {"passed": True, "action": expected, "position_opened": False}


def _event_chain_recovery() -> dict:
    settings = DerivativeSettings(
        fee_rate=Decimal("0"), spread_bps=Decimal("0"), slippage_bps=Decimal("0"),
    )
    snapshot = _snapshot()
    activated = AT - timedelta(hours=1)
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "paper"
        output.mkdir()
        state = _new_realtime_state(settings, activated)
        state["activated_at"] = activated.isoformat()
        actions = process_snapshot(
            state, settings, snapshot, None, manual_halt=False,
        )
        _append_event(output, state, snapshot, actions, None)
        initial = _new_realtime_state(settings, activated)
        initial["activated_at"] = activated.isoformat()
        recovered, identities = _load_events(output, initial)
        if (recovered["quote_events"] != 1 or recovered["balance"] != "1000"
                or len(identities) != 1 or recovered["last_event_sha256"] is None):
            raise ValueError("Realtime PAPER event recovery differs")

        event_path = output / "events" / "00000001.json"
        event = json.loads(event_path.read_text())
        event["quote_raw"]["ticker"] += " "
        event_path.write_text(json.dumps(event))
        tamper_rejected = False
        try:
            _load_events(output, initial)
        except ValueError:
            tamper_rejected = True
        if not tamper_rejected:
            raise ValueError("Realtime PAPER event tampering was accepted")
    return {
        "passed": True,
        "recovered_events": 1,
        "tampered_checksum_rejected": True,
    }


def build_report() -> dict:
    checks = {
        "long_short_leverage_lifecycles": _leverage_lifecycles(),
        "funding_adjusted_liquidation": _funding_liquidation(),
        "tail_gap_deleveraging": _tail_gap_deleveraging(),
        "unavailable_depth_rejection": _unavailable_depth_rejection(),
        "event_chain_recovery": _event_chain_recovery(),
        "live_lock": _live_lock(),
    }
    passed = all(value.get("passed") is True for value in checks.values())
    if not passed:
        raise ValueError("Technical derivative qualification failed")
    return {
        "schema_version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market": "PF_XBTUSD",
        "mode": "PAPER",
        "passed": True,
        "live_enabled": False,
        "checks": checks,
        "source_sha256": source_hashes(),
    }


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Qualify the derivative PAPER safety core")
    parser.add_argument("--output", type=Path,
                        default=Path("data/readiness/technical-qualification.json"))
    args = parser.parse_args(argv)
    try:
        report = build_report()
        write_report(args.output, report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, ArithmeticError) as exc:
        print(f"Technical qualification failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
