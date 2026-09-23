"""Source-bound amendment of the 4h experiment, before any performance is seen."""

import argparse
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

from app.database.repository import Repository
from app.market_data.candles import load_candles
from app.market_data.datasets import write_json
from app.market_data.reconciliation import reconcile
from backtesting.benchmarks import benchmarks
from backtesting.net_reward_research import code_hashes, json_value, run_case, sha
from backtesting.observed_history import VerifiedEmptyInterval, validate_observed_history
from backtesting.slow_research import definition as original_definition, settings_by_cost as original_costs, render_report

VERSION = "slow-observed-gated-v2"


def settings_by_cost():
    costs = original_costs()
    costs["kraken_current"] = replace(costs["base"], paper_fee_rate=Decimal("0.008"))
    costs["kraken_stress"] = replace(costs["double_costs"], paper_fee_rate=Decimal("0.016"))
    return costs


def definition():
    spec = original_definition()
    spec["settings"] = json_value({k: asdict(v) for k, v in settings_by_cost().items()})
    spec["rules"][1] = "Only source-verified empty intervals may be skipped. No fabricated prices, marks or executions. Expire pending entries; retain positions/account/risk state; execute protective gaps at the first published trade time and price. Restart indicator warm-up after each interval."
    spec["rules"] += [
        "Base/double_costs preserve the original 0.26%/0.52% fee model as controls, not current Kraken prices.",
        "Add constant current Kraken entry-tier taker cost 0.80% and stress 1.60% per side; all four scenarios must pass before 2025 is opened.",
        "Current-tier costs on historical prices are a present-cost counterfactual, not reconstruction of fees charged in 2023/2024. No tier discounts inferred from turnover.",
        "Trade-time decimals are rounded UP to the next representable microsecond, never before the first published post-gap trade."]
    spec["fee_source"] = {"checked_at": "2026-09-23", "url": "https://www.kraken.com/features/fee-schedule",
                          "support_url": "https://support.kraken.com/articles/cross-platform-fee-tier-changes",
                          "tier": "Tier 1 spot taker: 0.80% per side; local account eligibility not authenticated"}
    return spec


def assess(runs):
    expected = {(v, c) for v in definition()["variants"] for c in settings_by_cost()}
    indexed = {(r["variant"], r["cost_scenario"]): r["performance"] for r in runs}
    if len(runs) != len(expected) or set(indexed) != expected:
        raise ValueError("All eight cases are required")
    checks = {}
    for cost in settings_by_cost():
        p = indexed["net_reward", cost]
        checks[cost] = {"positive_net": Decimal(p["net_profit"]) > 0,
                        "at_least_20_trades": type(p["trades"]) is int and p["trades"] >= 20,
                        "drawdown_below_10_percent": Decimal(p["max_drawdown"]) < Decimal("0.10")}
    return {"checks": checks, "screen_passed": all(all(c.values()) for c in checks.values())}


def read_input(dataset, protocol):
    manifest = json.loads((dataset / "manifest.json").read_text())
    if sha(dataset / "manifest.json") != protocol["input_manifest_sha256"]:
        raise ValueError("Archive manifest changed")
    spec = protocol["definition"]
    if any(manifest[k] != spec[k] for k in ("symbol", "timeframe", "start", "end")):
        raise ValueError("Wrong input range or market")
    for name, expected in manifest["sha256"].items():
        if name not in ("source.raw", "candles.csv", "quality.json") or sha(dataset / name) != expected:
            raise ValueError("Archive content changed")
    gaps = []
    for evidence in protocol["gap_evidence"]:
        folder = Path(evidence["directory"])
        result = json_value(reconcile(dataset, folder, datetime.fromisoformat(evidence["audit"]["gap_start"])))
        if result != evidence["audit"] or result["classification"] != "empty_in_public_trade_history":
            raise ValueError("Gap evidence changed or does not verify an empty interval")
        stamp = Decimal(result["first_trade_after"]["timestamp"])
        micros = int((stamp * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
        first_trade = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=micros)
        gaps.append(VerifiedEmptyInterval(datetime.fromisoformat(result["gap_start"]),
                    datetime.fromisoformat(result["gap_end"]), first_trade, result["evidence_manifest_sha256"]))
    candles = load_candles(dataset / "candles.csv", "BTC/EUR", "4h")
    if candles[0].timestamp.isoformat() != spec["start"] or candles[-1].closed_at.isoformat() != spec["end"]:
        raise ValueError("Dataset does not cover the full frozen interval")
    validate_observed_history(candles, gaps)
    return candles, manifest, tuple(gaps)


def freeze(output, parent_path, dataset, audits):
    parent = json.loads(parent_path.read_text())
    if (parent["protocol_version"] != "slow-timeframe-gated-v1" or parent["definition"] != original_definition()
            or (parent_path.parent / "evaluation").exists()):
        raise ValueError("Amendment requires the unevaluated original hypothesis")
    evidence = [{"directory": json.loads(p.read_text())["evidence_directory"], "audit": json.loads(p.read_text())} for p in audits]
    protocol = {"protocol_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                "python_version": sys.version.split()[0], "definition": definition(), "code_sha256": code_hashes(),
                "input_manifest_sha256": sha(dataset / "manifest.json"), "gap_evidence": evidence,
                "amendment": {"parent_protocol_sha256": sha(parent_path),
                              "reason": "Public trade evidence confirms empty intervals, not recoverable omitted candles. Introduce explicit observed-only replay and current-fee stress before any performance evaluation; strategy and risk parameters unchanged."}}
    read_input(dataset, protocol)
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    for relative, expected in protocol["code_sha256"].items():
        source = root / relative
        if sha(source) != expected:
            raise ValueError("Source changed while freezing")
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    write_json(output / "protocol.json", protocol)
    return protocol


def read_protocol(path):
    protocol = json.loads(path.read_text())
    if (protocol["protocol_version"] != VERSION or protocol["definition"] != definition()
            or protocol["code_sha256"] != code_hashes() or protocol["python_version"] != sys.version.split()[0]):
        raise ValueError("Frozen code or definition changed")
    for relative, expected in protocol["code_sha256"].items():
        if sha(path.parent / "source" / relative) != expected:
            raise ValueError("Frozen source snapshot changed")
    return protocol


def check_gate(path, manifest):
    folder = path.parent / "evaluation"
    result = json.loads((folder / "results.json").read_text())
    receipt = json.loads((folder / "completion.json").read_text())
    if (sha(folder / "results.json") != receipt["results_sha256"] or result["protocol_sha256"] != sha(path)
            or result["input_sha256"] != manifest["sha256"]["candles.csv"] or result["phase"] != "screen"
            or [s["name"] for s in result["segments"]] != ["2023", "2024"]
            or not all(assess(s["runs"])["screen_passed"] for s in result["segments"])):
        raise ValueError("Holdout remains reserved: full screen has not passed")


def evaluate(path, dataset, phase):
    if phase not in ("screen", "holdout"):
        raise ValueError("Unknown phase")
    protocol = read_protocol(path)
    candles, manifest, gaps = read_input(dataset, protocol)
    if phase == "holdout":
        check_gate(path, manifest)
    output = path.parent / ("evaluation" if phase == "screen" else "holdout")
    output.mkdir(exist_ok=False)
    protocol_hash = sha(path)
    write_json(output / "input.json", {"protocol_sha256": protocol_hash, "dataset": str(dataset.resolve()), "manifest": manifest})
    segments = []
    with Repository(output / "research.sqlite3") as repo:
        for year in protocol["definition"][f"{phase}_years"]:
            selected = tuple(c for c in candles if c.timestamp.year == year)
            year_gaps = tuple(g for g in gaps if g.start.year == year)
            runs, references = [], {}
            for cost, settings in settings_by_cost().items():
                references[cost] = benchmarks(selected, settings, verified_empty_intervals=year_gaps)
                for variant in protocol["definition"]["variants"]:
                    assumptions = {"protocol_sha256": protocol_hash, "input_sha256": manifest["sha256"]["candles.csv"],
                                   "execution_model": "observed-only-expire-reset-v1", "year": year, "phase": phase,
                                   "variant": variant, "cost_scenario": cost, "settings": json_value(asdict(settings)),
                                   "gaps": json_value([asdict(g) for g in year_gaps])}
                    run = run_case(selected, settings, variant, repo, assumptions, verified_empty_intervals=year_gaps)
                    runs.append(run)
                    write_json(output / f"{year}_{variant}_{cost}.json", run)
                    print(f"{year}/{variant}/{cost}: {run['performance']['trades']} trades, {run['performance']['net_profit']} EUR", flush=True)
            segments.append({"name": str(year), "start": selected[0].timestamp.isoformat(), "end": selected[-1].closed_at.isoformat(),
                             "rows": len(selected), "gaps": json_value([asdict(g) for g in year_gaps]),
                             "runs": runs, "benchmarks": references, "assessment": assess(runs)})
    if read_protocol(path) != protocol or sha(path) != protocol_hash or read_input(dataset, protocol)[1] != manifest:
        raise ValueError("Research sources changed during evaluation")
    passed = all(s["assessment"]["screen_passed"] for s in segments)
    note = ("2025 wurde jetzt ausgewertet und gilt als gesehen." if phase == "holdout" else
            "2025 bleibt noch ungesehen; alle Kostenfälle bestanden, Holdout-Prüfung zulässig." if passed else
            "2025 bleibt hinsichtlich Strategieergebnissen zurückgehalten; die festgelegte Prüfung wurde nicht bestanden.")
    result = json_value({"protocol_sha256": protocol_hash, "input_sha256": manifest["sha256"]["candles.csv"],
                         "phase": phase, "segments": segments, "screen_passed": passed, "holdout_note": note})
    write_json(output / "results.json", result)
    report = render_report(result).replace("Kosten sind Modellannahmen, keine verifizierten aktuellen Kraken-Tarife.",
        "base/double_costs sind alte Modellkosten (0,26/0,52 % je Seite); kraken_current/stress verwenden 0,80/1,60 % je Seite. Aktuelle Gebühren auf historischen Kursen sind keine damaligen Gebühren.")
    report += "\nGeprüfte leere Intervalle: keine Kurse ergänzt, keine Ausführungen oder Bewertungen während der Pause. Wartende Einstiege verfallen; offene Positionen und Risikozustand bleiben bestehen. Schutzorders reagieren erst am ersten belegten Folge-Trade, Indikatoren wärmen neu auf. Alle vier Kostenfälle müssen bestehen.\n"
    report += "\nGebührenquelle: https://www.kraken.com/features/fee-schedule (abgerufen 23.09.2026).\n"
    (output / "report.md").write_text(report)
    write_json(output / "completion.json", {"results_sha256": sha(output / "results.json"), "completed_at": datetime.now(timezone.utc).isoformat()})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Amended 4h research with verified empty intervals")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    prepare.add_argument("--parent", type=Path, required=True)
    prepare.add_argument("--dataset", type=Path, required=True)
    prepare.add_argument("--audit", type=Path, action="append", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--dataset", type=Path, required=True)
    run.add_argument("--phase", choices=("screen", "holdout"), default="screen")
    args = parser.parse_args(argv)
    if args.command == "freeze":
        freeze(args.output, args.parent, args.dataset, args.audit)
    else:
        evaluate(args.protocol, args.dataset, args.phase)


if __name__ == "__main__":
    main()
