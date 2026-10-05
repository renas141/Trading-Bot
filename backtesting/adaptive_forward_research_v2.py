"""Evaluate corrected adaptive candidate v2 without opening holdout early."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.derivatives.observed_costs import load_observed_cost_scenario
from app.derivatives.safety import StressRiskPolicy
from app.market_data.kraken_funding import align_hourly_funding_to_4h
from app.market_data.kraken_funding_archive import load_dataset as load_funding_dataset
from app.market_data.kraken_futures import load_futures_dataset
from app.market_data.kraken_perpetual_forward import STEP, load_bundle
from app.market_data.kraken_perpetual_regime_history import load_dataset as load_regime_dataset
from app.market_data.perpetual_regime_alignment import align_futures_regime
from app.strategies.funding_aware_regime_momentum import FundingAwareRegimeMomentumParameters
from app.strategies.funding_aware_regime_momentum_v2 import AdaptiveFundingAwareMomentumStrategy
from backtesting.adaptive_forward_protocol_v2 import (
    FORWARD_START, SCREEN_BLOCKS, TOTAL_BLOCKS, read_protocol,
)
from backtesting.perpetual_forward_research import FEE_RATE, FEE_SOURCE, cost_cases
from backtesting.safe_derivatives_v2 import SafeDerivativeBacktester


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(root: Path) -> list[tuple[Path, dict]]:
    rows = []
    for path in sorted(candidate for candidate in root.glob("pf_xbtusd_*")
                       if candidate.is_dir()):
        rows.append((path, load_bundle(path)))
    for previous, current in zip(rows, rows[1:]):
        if previous[1]["end"] != current[1]["start"]:
            raise ValueError("Adaptive forward evidence has a gap")
    return rows


def load_stage_series(root: Path, blocks: int):
    warmup = FundingAwareRegimeMomentumParameters().required_history
    start = FORWARD_START - STEP * warmup
    end = FORWARD_START + STEP * blocks
    selected = [
        (path, manifest) for path, manifest in _inventory(root)
        if datetime.fromisoformat(manifest["start"]) >= start
        and datetime.fromisoformat(manifest["end"]) <= end
    ]
    if len(selected) != warmup + blocks:
        raise ValueError("Adaptive stage lacks exact warm-up or forward coverage")
    if (datetime.fromisoformat(selected[0][1]["start"]) != start
            or datetime.fromisoformat(selected[-1][1]["end"]) != end):
        raise ValueError("Adaptive stage boundaries differ")
    trade, mark, regime, funding_points = [], [], [], []
    for path, _ in selected:
        one_trade, one_mark, _ = load_futures_dataset(path / "prices")
        one_regime, _ = load_regime_dataset(path / "regime")
        one_funding, _ = load_funding_dataset(path / "funding")
        if (len(one_trade), len(one_mark), len(one_regime), len(one_funding)) != (1, 1, 1, 4):
            raise ValueError("Adaptive bundle component cardinality differs")
        trade.extend(one_trade); mark.extend(one_mark)
        regime.extend(one_regime); funding_points.extend(one_funding)
    funding = align_hourly_funding_to_4h(
        tuple(funding_points), tuple(candle.timestamp for candle in trade)
    )
    aligned = align_futures_regime(tuple(trade), tuple(mark), tuple(regime))
    return tuple(path for path, _ in selected), tuple(trade), tuple(mark), aligned, funding


def assess(runs: list[dict], stage: str) -> dict:
    if stage not in {"screen", "holdout"}:
        raise ValueError("Unknown adaptive stage")
    minimum = 6 if stage == "screen" else 12
    factor_minimum = Decimal("1.10") if stage == "screen" else Decimal("1.20")
    drawdown_maximum = Decimal("0.08") if stage == "screen" else Decimal("0.10")
    expected = {"observed_p95_actual_funding", "double_cost_and_funding_stress"}
    indexed = {run["scenario"]: run for run in runs}
    if set(indexed) != expected:
        raise ValueError("Adaptive result scenarios differ")
    checks = {}
    for scenario in sorted(expected):
        performance = indexed[scenario]["performance"]
        factor = performance["profit_factor"]
        checks[scenario] = {
            "positive_net": Decimal(performance["net_profit"]) > 0,
            "profit_factor": factor is not None and Decimal(factor) >= factor_minimum,
            "enough_trades": performance["trades"] >= minimum,
            "drawdown_below_cap": Decimal(performance["max_drawdown"]) < drawdown_maximum,
            "no_liquidation": performance["liquidations"] == 0,
            "leverage_within_cap": performance["maximum_leverage_used"] <= 10,
        }
    passed = all(all(case.values()) for case in checks.values())
    return {"stage": stage, "checks": checks, "passed": passed,
            "paper_candidate": stage == "holdout" and passed}


def _stage_bounds(stage: str, warmup_count: int, total_blocks: int) -> tuple[int, int]:
    if stage == "screen" and total_blocks == SCREEN_BLOCKS:
        return warmup_count, warmup_count + SCREEN_BLOCKS
    if stage == "holdout" and total_blocks == TOTAL_BLOCKS:
        return warmup_count + SCREEN_BLOCKS, warmup_count + TOTAL_BLOCKS
    raise ValueError("Adaptive stage bounds differ")


def _run(root: Path, blocks: int, observed, stage: str) -> tuple[list[Path], list[dict]]:
    paths, trade, mark, aligned, funding = load_stage_series(root, blocks)
    warmup_count = FundingAwareRegimeMomentumParameters().required_history
    begin, end = _stage_bounds(stage, warmup_count, blocks)
    funding_map = {candle.timestamp: rate for candle, rate in zip(trade, funding)}
    runs = []
    for scenario, settings in cost_cases(observed).items():
        multiplier = Decimal("2") if scenario == "double_cost_and_funding_stress" else Decimal("1")
        replay = SafeDerivativeBacktester(
            AdaptiveFundingAwareMomentumStrategy(aligned, funding_map),
            settings, StressRiskPolicy(),
        ).run(
            trade[begin:end], mark[begin:end],
            warmup=trade[begin - warmup_count:begin],
            funding_rates=tuple(rate * multiplier for rate in funding[begin:end]),
        )
        runs.append({
            "scenario": scenario, "warmup_candles": warmup_count,
            "candles": replay.candles_processed, "signals": replay.signals,
            "entries": replay.entries, "rejected_entries": replay.rejected_entries,
            "funding_liquidations": replay.funding_liquidations,
            "performance": replay.performance.as_dict(),
        })
    return list(paths[warmup_count:]), runs


def evaluate(protocol_path: Path, root: Path,
             candidate: Path, summary: Path, stage: str) -> dict:
    protocol = read_protocol(protocol_path, candidate, summary)
    observed = load_observed_cost_scenario(
        candidate, summary, fee_rate=FEE_RATE, fee_source=FEE_SOURCE,
    )
    output = protocol_path.parent / stage
    if output.exists():
        raise ValueError("Adaptive stage output already exists")
    if stage == "screen":
        blocks = SCREEN_BLOCKS
    elif stage == "holdout":
        prior_path = protocol_path.parent / "screen" / "results.json"
        receipt_path = protocol_path.parent / "screen" / "completion.json"
        if not prior_path.is_file() or not receipt_path.is_file():
            raise ValueError("Passing adaptive screen receipt is required")
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (prior.get("assessment", {}).get("passed") is not True
                or prior.get("protocol_sha256") != _sha(protocol_path)
                or receipt.get("results_sha256") != _sha(prior_path)):
            raise ValueError("Adaptive screen receipt did not pass integrity checks")
        blocks = TOTAL_BLOCKS
    else:
        raise ValueError("Unknown adaptive stage")
    paths, runs = _run(root, blocks, observed, stage)
    result = {
        "protocol_sha256": _sha(protocol_path),
        "evaluator_sha256": _sha(Path(__file__)),
        "stage": stage,
        "coverage": {"start": FORWARD_START.isoformat(),
                     "end": (FORWARD_START + STEP * blocks).isoformat(),
                     "bundles": blocks},
        "bundle_manifests": [{"name": path.name, "sha256": _sha(path / "bundle.json")}
                             for path in paths],
        "runs": runs, "assessment": assess(runs, stage),
        "activation": {"paper_enabled": False, "live_enabled": False},
    }
    output.mkdir()
    target = output / "results.json"
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    (output / "completion.json").write_text(json.dumps({
        "results_sha256": _sha(target), "live_enabled": False,
    }, indent=2) + "\n")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate one adaptive forward stage")
    parser.add_argument("stage", choices=("screen", "holdout"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--forward-root", type=Path, required=True)
    parser.add_argument("--cost-candidate", type=Path, required=True)
    parser.add_argument("--cost-summary", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = evaluate(args.protocol, args.forward_root,
                          args.cost_candidate, args.cost_summary, args.stage)
        print(json.dumps(result["assessment"], indent=2))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Adaptive evaluation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
