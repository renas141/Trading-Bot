"""Preregister the future-only adaptive PF_XBTUSD candidate before its first bar."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.derivatives.observed_costs import load_observed_cost_scenario
from app.derivatives.safety import StressRiskPolicy
from app.market_data.kraken_perpetual_forward import STEP, load_bundle
from app.strategies.funding_aware_regime_momentum import (
    FundingAwareRegimeMomentumParameters,
)
from app.strategies.funding_aware_regime_momentum_v2 import (
    AdaptiveFundingAwareMomentumStrategy,
)
from backtesting.perpetual_forward_research import FEE_RATE, FEE_SOURCE


VERSION = "pf-xbtusd-adaptive-funding-forward-v1"
FORWARD_START = datetime(2026, 10, 5, 16, tzinfo=timezone.utc)
SCREEN_BLOCKS = 180
TOTAL_BLOCKS = 540
CODE_FILES = (
    "app/domain.py", "app/market_data/models.py", "app/market_data/quality.py",
    "app/market_data/candles.py", "app/market_data/kraken_futures.py",
    "app/market_data/kraken_funding.py", "app/market_data/kraken_funding_archive.py",
    "app/market_data/kraken_perpetual_regime.py",
    "app/market_data/kraken_perpetual_regime_history.py",
    "app/market_data/perpetual_regime_alignment.py",
    "app/market_data/kraken_perpetual_forward.py", "app/indicators/core.py",
    "app/strategies/base.py", "app/strategies/models.py",
    "app/strategies/funding_aware_regime_momentum.py",
    "app/strategies/funding_aware_regime_momentum_v2.py",
    "app/derivatives/models.py", "app/derivatives/settings.py",
    "app/derivatives/risk.py", "app/derivatives/broker.py",
    "app/derivatives/observed_costs.py", "app/derivatives/safety.py",
    "backtesting/derivatives.py", "backtesting/safe_derivatives.py",
    "backtesting/adaptive_forward_protocol.py",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    return {name: _sha(root / name) for name in CODE_FILES}


def definition() -> dict:
    strategy = FundingAwareRegimeMomentumParameters()
    risk = StressRiskPolicy()
    return {
        "market": "PF_XBTUSD", "symbol": "BTC/USD", "timeframe": "4h",
        "forward_start": FORWARD_START.isoformat(),
        "hypothesis": (
            "An agreed 2-day/7-day price trend with at least three of four delayed "
            "open-interest, aggressor-flow, CVD and funding confirmations produces more "
            "robust opportunities when three confirmations risk 0.5% and four risk 1.25%, "
            "subject to a 3% tail-loss cap and funding-adjusted liquidation checks."
        ),
        "motivation": (
            "Earlier strict filters were sparse and 2025 results were fragile. Public regime "
            "fields are noisy, so one failed confirmation is accepted only at smaller risk. "
            "Full agreement may take greater risk, while gap and funding stress can still "
            "reduce quantity or leverage."
        ),
        "strategy": {
            "name": AdaptiveFundingAwareMomentumStrategy.name,
            "version": AdaptiveFundingAwareMomentumStrategy.version,
            "parameters": _json_value(asdict(strategy)),
            "price_gate": "2-day and 7-day close returns agree in a non-zero direction",
            "confirmations": [
                "7-day open interest rises",
                "latest delayed aggressor differential agrees with direction",
                "7-day delayed CVD change agrees with direction",
                "directional current 4h funding is no worse than the prior 24h mean",
            ],
            "minimum_confirmations": 3,
            "excluded": [
                "numeric signal optimization", "best-of-candidate selection",
                "direction removal", "fallback parameter set",
            ],
        },
        "risk": {
            **_json_value(asdict(risk)),
            "maximum_leverage": 10,
            "three_confirmations": "0.5% normal stop-risk budget",
            "four_confirmations": "1.25% normal stop-risk budget",
            "tail_stress": (
                "2% gap beyond stop plus round-trip fees and 0.002% adverse funding "
                "per 4h bar for 42 bars; combined loss at most 3% equity"
            ),
            "margin": (
                "retain at least 5% free collateral and require the stressed exit to remain "
                "before the funding-adjusted liquidation threshold"
            ),
            "selection": "smallest safe integer leverage; automatically reduce size or leverage",
        },
        "timing": {
            "regime": "completed 4h bucket plus one full 4h safety lag",
            "funding": "four completed hourly values known at signal close",
            "execution": "next 4h trade candle open",
            "maximum_holding_bars": 42,
        },
        "costs": {
            "fee_rate": str(FEE_RATE), "fee_source": FEE_SOURCE,
            "primary": "observed p95 spread/slippage plus actual signed hourly funding",
            "stress": "double fee, spread, slippage and every signed funding value",
        },
        "stages": {
            "screen": {
                "blocks": SCREEN_BLOCKS, "minimum_trades_each_cost": 6,
                "profit_factor_minimum": "1.10", "maximum_drawdown": "0.08",
                "maximum_liquidations": 0,
            },
            "holdout": {
                "starts_after_block": SCREEN_BLOCKS,
                "blocks": TOTAL_BLOCKS - SCREEN_BLOCKS,
                "total_blocks_required": TOTAL_BLOCKS,
                "minimum_trades_each_cost": 12,
                "profit_factor_minimum": "1.20", "maximum_drawdown": "0.10",
                "maximum_liquidations": 0,
            },
        },
        "multiple_hypothesis_rule": (
            "This secondary candidate is judged independently and cannot replace, rescue or "
            "be selected against the 2026-10-03 strict candidate."
        ),
        "activation": (
            "A holdout pass creates a separate long-running PAPER candidate only; LIVE remains off."
        ),
        "rules": [
            "Every bundle whose start precedes the cutoff is warm-up only.",
            "The screen must pass unchanged before the holdout may be read.",
            "Failure ends this candidate; no parameter adjustment can rescue a stage.",
            "Both cost cases use a fresh 1000 USD account and the safe replay engine.",
            "No result from this protocol can enable real orders.",
        ],
    }


def inventory(root: Path) -> dict:
    rows = []
    for path in sorted(candidate for candidate in root.glob("pf_xbtusd_*")
                       if candidate.is_dir()):
        manifest = load_bundle(path)
        start = datetime.fromisoformat(manifest["start"])
        if start >= FORWARD_START:
            continue
        rows.append({
            "name": path.name, "start": manifest["start"], "end": manifest["end"],
            "bundle_sha256": _sha(path / "bundle.json"),
        })
    if not rows:
        raise ValueError("Adaptive protocol needs verified warm-up evidence")
    for previous, current in zip(rows, rows[1:]):
        if previous["end"] != current["start"]:
            raise ValueError("Adaptive warm-up evidence has a gap")
    return {
        "bundles_present_at_freeze": len(rows),
        "start": rows[0]["start"], "end": rows[-1]["end"],
        "uncollected_warmup_until": FORWARD_START.isoformat(),
        "bundle_manifests": rows,
    }


def freeze(output: Path, forward_root: Path, cost_candidate: Path, cost_summary: Path,
           *, clock=lambda: datetime.now(timezone.utc)) -> dict:
    created = clock().astimezone(timezone.utc)
    if created >= FORWARD_START:
        raise ValueError("Adaptive protocol must be frozen before its forward cutoff")
    if output.exists():
        raise ValueError("Adaptive protocol output already exists")
    observed = load_observed_cost_scenario(
        cost_candidate, cost_summary, fee_rate=FEE_RATE, fee_source=FEE_SOURCE,
    )
    value = {
        "protocol_version": VERSION,
        "created_at": created.isoformat(),
        "definition": definition(),
        "code_sha256": code_hashes(),
        "cost_evidence": {
            "candidate_sha256": _sha(cost_candidate),
            "summary_sha256": _sha(cost_summary),
            "source_summary_sha256": observed.source_summary_sha256,
        },
        "pre_registration_inventory": inventory(forward_root),
        "activation": {"paper_enabled": False, "live_enabled": False},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return value


def read_protocol(path: Path, cost_candidate: Path, cost_summary: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    observed = load_observed_cost_scenario(
        cost_candidate, cost_summary, fee_rate=FEE_RATE, fee_source=FEE_SOURCE,
    )
    if (value.get("protocol_version") != VERSION
            or datetime.fromisoformat(value.get("created_at", "")) >= FORWARD_START
            or value.get("definition") != definition()
            or value.get("code_sha256") != code_hashes()
            or value.get("activation") != {"paper_enabled": False, "live_enabled": False}
            or value.get("cost_evidence", {}).get("candidate_sha256") != _sha(cost_candidate)
            or value.get("cost_evidence", {}).get("summary_sha256") != _sha(cost_summary)
            or value.get("cost_evidence", {}).get("source_summary_sha256")
            != observed.source_summary_sha256):
        raise ValueError("Adaptive forward protocol integrity check failed")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Freeze the adaptive future-only protocol")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--forward-root", type=Path, required=True)
    parser.add_argument("--cost-candidate", type=Path, required=True)
    parser.add_argument("--cost-summary", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = freeze(
            args.output, args.forward_root, args.cost_candidate, args.cost_summary
        )
        print(json.dumps({
            "protocol_version": value["protocol_version"],
            "created_at": value["created_at"],
            "forward_start": value["definition"]["forward_start"],
            "protocol_sha256": _sha(args.output),
            "paper_enabled": False, "live_enabled": False,
        }, indent=2))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Adaptive protocol freeze failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
