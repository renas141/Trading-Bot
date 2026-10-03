"""Preregistered funding-aware PF_XBTUSD forward screen and holdout."""

import argparse
import json
import shutil
import sys
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.derivatives.observed_costs import ObservedCostScenario, load_observed_cost_scenario
from app.market_data.kraken_funding import align_hourly_funding_to_4h
from app.market_data.kraken_funding_archive import load_dataset as load_funding_dataset
from app.market_data.kraken_futures import load_futures_dataset
from app.market_data.kraken_perpetual_forward import STEP, load_bundle
from app.market_data.kraken_perpetual_regime_history import load_dataset as load_regime_dataset
from app.market_data.perpetual_regime_alignment import align_futures_regime
from app.market_data.datasets import write_json
from app.strategies.funding_aware_regime_momentum import (
    FundingAwareRegimeMomentumParameters,
    FundingAwareRegimeMomentumStrategy,
)
from backtesting.derivative_research import json_value, sha
from backtesting.derivatives import CloseExitPolicy, DerivativeBacktester


VERSION = "pf-xbtusd-funding-aware-forward-v2"
FORWARD_START = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
SCREEN_BLOCKS = 180
TOTAL_BLOCKS = 540
FEE_RATE = Decimal("0.0005")
FEE_SOURCE = "Kraken Derivatives published base taker fee, verified 2026-09-23"
EXIT = CloseExitPolicy(max_holding_bars=42)
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
    "app/derivatives/models.py", "app/derivatives/settings.py",
    "app/derivatives/risk.py", "app/derivatives/broker.py",
    "app/derivatives/observed_costs.py", "backtesting/derivatives.py",
    "backtesting/derivative_research.py", "backtesting/perpetual_forward_research.py",
)


@dataclass(frozen=True)
class ForwardSeries:
    paths: tuple[Path, ...]
    trade: tuple
    mark: tuple
    aligned: tuple
    funding: tuple[Decimal, ...]


def code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    return {name: sha(root / name) for name in CODE_FILES}


def cost_cases(observed: ObservedCostScenario):
    base = observed.settings
    return {
        "observed_p95_actual_funding": base,
        "double_cost_and_funding_stress": replace(
            base, fee_rate=base.fee_rate * 2,
            spread_bps=base.spread_bps * 2,
            slippage_bps=base.slippage_bps * 2,
        ),
    }


def definition(observed: ObservedCostScenario) -> dict:
    parameters = FundingAwareRegimeMomentumParameters()
    return {
        "market": "PF_XBTUSD", "symbol": "BTC/USD", "timeframe": "4h",
        "forward_start": FORWARD_START.isoformat(),
        "hypothesis": (
            "A 2-day/7-day price trend confirmed by rising seven-day open interest and "
            "directional aggressor/CVD flow has a more robust net return when entry is vetoed "
            "while completed funding pressure in the intended direction is increasing."
        ),
        "motivation": (
            "The earlier 7/28-day regime strategy was economically flat in 2025 and failed "
            "double-cost stress. Funding is a signed transfer and an observable crowding cost; "
            "this rule tests its change without fitting a numeric threshold."
        ),
        "strategy": {
            "name": FundingAwareRegimeMomentumStrategy.name,
            "version": FundingAwareRegimeMomentumStrategy.version,
            "parameters": json_value(asdict(parameters)),
            "entry_checks": [
                "2-day and 7-day close returns have the same non-zero sign",
                "7-day open-interest change is positive",
                "latest delayed aggressor differential agrees with direction",
                "7-day delayed CVD change agrees with direction",
                "directional current 4h funding is no worse than the preceding 24h mean",
            ],
            "excluded": [
                "numeric funding threshold", "parameter search", "fallback candidate",
                "long-short-ratio filter", "liquidation-volume threshold",
            ],
        },
        "timing": {
            "regime": "completed 4h bucket plus one full 4h safety lag",
            "funding": "four completed hourly values known at signal close",
            "execution": "next 4h trade candle open",
        },
        "exit": {"maximum_holding_bars": 42, "protective_stop": "ATR(42) x 3",
                 "fixed_target": None},
        "costs": {
            "fee_rate": str(FEE_RATE), "fee_source": observed.fee_source,
            "source_summary_sha256": observed.source_summary_sha256,
            "primary": "observed p95 spread/slippage plus actual signed hourly funding",
            "stress": "double fee, spread, slippage and every signed funding value",
        },
        "stages": {
            "screen": {
                "blocks": SCREEN_BLOCKS, "warmup_blocks": parameters.required_history,
                "minimum_trades_each_cost": 4, "profit_factor_minimum": "1.10",
                "maximum_drawdown": "0.08",
                "purpose": "operability screen only; cannot activate PAPER",
            },
            "holdout": {
                "starts_after_block": SCREEN_BLOCKS, "total_blocks_required": TOTAL_BLOCKS,
                "blocks": TOTAL_BLOCKS - SCREEN_BLOCKS,
                "warmup_blocks": parameters.required_history,
                "minimum_trades_each_cost": 8, "profit_factor_minimum": "1.20",
                "maximum_drawdown": "0.10",
            },
        },
        "gate": {
            "every_cost_case": "net_profit > 0, required profit factor/trades, drawdown below cap, no liquidation",
            "maximum_leverage": 10,
            "activation": "holdout pass creates a PAPER candidate only; LIVE remains disabled",
        },
        "rules": [
            "All bundles ending at or before the cutoff are excluded from performance evaluation.",
            "The screen must pass unchanged before the later holdout may be opened.",
            "Failure ends this hypothesis; no parameter adjustment can rescue either stage.",
            "Fresh 1000 USD account and both cost cases are used in each stage.",
            "PAPER and LIVE remain disabled by this protocol and its results.",
        ],
    }


def _bundle_inventory(root: Path, *, before_or_at: datetime | None = None) -> list[tuple[Path, dict]]:
    rows = []
    for path in sorted(candidate for candidate in root.glob("pf_xbtusd_*") if candidate.is_dir()):
        manifest = load_bundle(path)
        start, end = datetime.fromisoformat(manifest["start"]), datetime.fromisoformat(manifest["end"])
        if before_or_at is None or end <= before_or_at:
            rows.append((path, manifest))
    for previous, current in zip(rows, rows[1:]):
        if datetime.fromisoformat(previous[1]["end"]) != datetime.fromisoformat(current[1]["start"]):
            raise ValueError("Forward bundle inventory has a gap")
    return rows


def freeze(output: Path, root: Path, candidate: Path, summary: Path) -> None:
    if output.exists():
        raise ValueError("Use a new research directory")
    observed = load_observed_cost_scenario(
        candidate, summary, fee_rate=FEE_RATE, fee_source=FEE_SOURCE,
    )
    prefix = _bundle_inventory(root, before_or_at=FORWARD_START)
    if not prefix or datetime.fromisoformat(prefix[-1][1]["end"]) != FORWARD_START:
        raise ValueError("Verified pre-registration coverage must end exactly at the cutoff")
    hashes = code_hashes()
    protocol = {
        "protocol_version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "definition": definition(observed),
        "code_sha256": hashes,
        "pre_registration_inventory": {
            "bundles": len(prefix),
            "start": prefix[0][1]["start"], "end": prefix[-1][1]["end"],
            "bundle_manifests": [
                {"name": path.name, "sha256": sha(path / "bundle.json")} for path, _ in prefix
            ],
            "use": "coverage/integrity audit only; excluded from evaluation",
        },
        "cost_candidate_sha256": sha(candidate),
        "cost_summary_sha256": sha(summary),
    }
    output.mkdir(parents=True)
    try:
        project = Path(__file__).resolve().parents[1]
        for relative, expected in hashes.items():
            source = project / relative
            if sha(source) != expected:
                raise ValueError("Source changed during freeze")
            target = output / "source" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        write_json(output / "protocol.json", protocol)
    except BaseException:
        shutil.rmtree(output)
        raise


def read_protocol(path: Path, candidate: Path, summary: Path):
    observed = load_observed_cost_scenario(
        candidate, summary, fee_rate=FEE_RATE, fee_source=FEE_SOURCE,
    )
    protocol = json.loads(path.read_text(encoding="utf-8"))
    if (protocol.get("protocol_version") != VERSION
            or protocol.get("python_version") != sys.version.split()[0]
            or protocol.get("definition") != definition(observed)
            or protocol.get("code_sha256") != code_hashes()
            or protocol.get("cost_candidate_sha256") != sha(candidate)
            or protocol.get("cost_summary_sha256") != sha(summary)):
        raise ValueError("Frozen forward protocol, source or costs differ")
    for relative, expected in protocol["code_sha256"].items():
        if sha(path.parent / "source" / relative) != expected:
            raise ValueError("Frozen source snapshot differs")
    return protocol, observed


def load_forward_series(root: Path, blocks: int) -> ForwardSeries:
    if type(blocks) is not int or blocks < 1:
        raise ValueError("Forward block count must be positive")
    inventory = _bundle_inventory(root)
    selected = []
    for path, manifest in inventory:
        start = datetime.fromisoformat(manifest["start"])
        if start >= FORWARD_START:
            selected.append((path, manifest))
        if len(selected) == blocks:
            break
    if len(selected) != blocks:
        raise ValueError(f"Forward stage needs exactly {blocks} available post-cutoff blocks")
    if datetime.fromisoformat(selected[0][1]["start"]) != FORWARD_START:
        raise ValueError("Post-cutoff forward coverage starts late")
    expected_end = FORWARD_START + STEP * blocks
    if datetime.fromisoformat(selected[-1][1]["end"]) != expected_end:
        raise ValueError("Post-cutoff forward coverage is not continuous")

    trade, mark, regime_rows, funding_points = [], [], [], []
    for path, _ in selected:
        one_trade, one_mark, _ = load_futures_dataset(path / "prices")
        one_regime, _ = load_regime_dataset(path / "regime")
        one_funding, _ = load_funding_dataset(path / "funding")
        if len(one_trade) != 1 or len(one_mark) != 1 or len(one_regime) != 1 or len(one_funding) != 4:
            raise ValueError("Forward bundle component cardinality differs")
        trade.extend(one_trade); mark.extend(one_mark)
        regime_rows.extend(one_regime); funding_points.extend(one_funding)
    funding = align_hourly_funding_to_4h(
        tuple(funding_points), tuple(candle.timestamp for candle in trade),
    )
    aligned = align_futures_regime(tuple(trade), tuple(mark), tuple(regime_rows))
    return ForwardSeries(tuple(path for path, _ in selected), tuple(trade), tuple(mark),
                         aligned, funding)


def assess(runs: list[dict], stage: str) -> dict:
    if stage not in {"screen", "holdout"}:
        raise ValueError("Unknown forward stage")
    thresholds = ({"trades": 4, "profit_factor": Decimal("1.10"), "drawdown": Decimal("0.08")}
                  if stage == "screen"
                  else {"trades": 8, "profit_factor": Decimal("1.20"), "drawdown": Decimal("0.10")})
    expected = {"observed_p95_actual_funding", "double_cost_and_funding_stress"}
    indexed = {run["scenario"]: run for run in runs}
    if set(indexed) != expected:
        raise ValueError("Forward result scenarios differ")
    checks = {}
    for scenario in sorted(expected):
        performance = indexed[scenario]["performance"]
        factor = performance["profit_factor"]
        checks[scenario] = {
            "positive_net": Decimal(performance["net_profit"]) > 0,
            "profit_factor": factor is not None and Decimal(factor) >= thresholds["profit_factor"],
            "enough_trades": performance["trades"] >= thresholds["trades"],
            "drawdown_below_cap": Decimal(performance["max_drawdown"]) < thresholds["drawdown"],
            "no_liquidation": performance["liquidations"] == 0,
            "leverage_within_cap": performance["maximum_leverage_used"] <= 10,
        }
    passed = all(all(case.values()) for case in checks.values())
    return {"stage": stage, "checks": checks, "passed": passed,
            "paper_candidate": stage == "holdout" and passed}


def _run_stage(series: ForwardSeries, observed: ObservedCostScenario, stage: str) -> list[dict]:
    parameters = FundingAwareRegimeMomentumParameters()
    warmup_count = parameters.required_history
    if stage == "screen":
        begin, end = warmup_count, SCREEN_BLOCKS
    elif stage == "holdout":
        begin, end = SCREEN_BLOCKS, TOTAL_BLOCKS
    else:
        raise ValueError("Unknown forward stage")
    warmup = series.trade[begin - warmup_count:begin]
    funding_by_candle = {candle.timestamp: rate
                         for candle, rate in zip(series.trade, series.funding)}
    runs = []
    for scenario, settings in cost_cases(observed).items():
        multiplier = Decimal("2") if scenario == "double_cost_and_funding_stress" else Decimal("1")
        replay = DerivativeBacktester(
            FundingAwareRegimeMomentumStrategy(series.aligned, funding_by_candle),
            settings, Decimal("0"), close_exit_policy=EXIT,
        ).run(
            series.trade[begin:end], series.mark[begin:end], warmup=warmup,
            funding_rates=tuple(rate * multiplier for rate in series.funding[begin:end]),
        )
        runs.append({
            "scenario": scenario, "warmup_candles": len(warmup),
            "candles": replay.candles_processed, "signals": replay.signals,
            "entries": replay.entries, "rejected_entries": replay.rejected_entries,
            "performance": replay.performance.as_dict(),
        })
    return runs


def evaluate(protocol_path: Path, root: Path, candidate: Path, summary: Path,
             stage: str) -> None:
    protocol, observed = read_protocol(protocol_path, candidate, summary)
    output = protocol_path.parent / stage
    if output.exists():
        raise ValueError("Forward stage output already exists")
    if stage == "screen":
        blocks = SCREEN_BLOCKS
    elif stage == "holdout":
        screen_results = protocol_path.parent / "screen" / "results.json"
        screen_completion = protocol_path.parent / "screen" / "completion.json"
        if not screen_results.is_file() or not screen_completion.is_file():
            raise ValueError("A completed passing screen is required before holdout")
        prior = json.loads(screen_results.read_text(encoding="utf-8"))
        receipt = json.loads(screen_completion.read_text(encoding="utf-8"))
        if (prior.get("protocol_sha256") != sha(protocol_path)
                or prior.get("stage") != "screen"
                or prior.get("activation") != {"paper_enabled": False, "live_enabled": False}
                or prior.get("assessment", {}).get("passed") is not True
                or receipt.get("results_sha256") != sha(screen_results)):
            raise ValueError("Forward screen did not pass or its receipt differs")
        blocks = TOTAL_BLOCKS
    else:
        raise ValueError("Unknown forward stage")

    series = load_forward_series(root, blocks)
    output.mkdir()
    try:
        runs = _run_stage(series, observed, stage)
        result = json_value({
            "protocol_sha256": sha(protocol_path), "stage": stage,
            "coverage": {"start": series.trade[0].timestamp.isoformat(),
                         "end": series.trade[-1].closed_at.isoformat(),
                         "bundles": len(series.paths)},
            "bundle_manifests": [{"name": path.name, "sha256": sha(path / "bundle.json")}
                                 for path in series.paths],
            "runs": runs, "assessment": assess(runs, stage),
            "activation": {"paper_enabled": False, "live_enabled": False},
        })
        if read_protocol(protocol_path, candidate, summary)[0] != protocol:
            raise ValueError("Forward protocol changed during evaluation")
        write_json(output / "results.json", result)
        write_json(output / "completion.json", {
            "results_sha256": sha(output / "results.json"),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
    except BaseException:
        shutil.rmtree(output)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Frozen PF_XBTUSD funding-aware forward study")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    prepare.add_argument("--forward-root", type=Path, required=True)
    prepare.add_argument("--cost-candidate", type=Path, required=True)
    prepare.add_argument("--cost-summary", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--forward-root", type=Path, required=True)
    run.add_argument("--cost-candidate", type=Path, required=True)
    run.add_argument("--cost-summary", type=Path, required=True)
    run.add_argument("--stage", choices=("screen", "holdout"), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            freeze(args.output, args.forward_root, args.cost_candidate, args.cost_summary)
        else:
            evaluate(args.protocol, args.forward_root, args.cost_candidate,
                     args.cost_summary, args.stage)
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Forward research failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
