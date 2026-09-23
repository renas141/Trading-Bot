"""Two preregistered slow candidates; seen-data development and one gated holdout."""

import argparse
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.database.repository import Repository
from app.market_data.datasets import write_json
from app.strategies.trend_breakout import TrendBreakoutParameters, TrendBreakoutStrategy
from app.strategies.trend_pullback import PullbackParameters, TrendPullbackStrategy
from backtesting.benchmarks import benchmarks
from backtesting.gap_research import read_input
from backtesting.net_reward_research import code_hashes, json_value, run_case, sha
from backtesting.slow_research import settings_by_cost as original_costs

VERSION = "slow-candidates-development-v1"
CANDIDATES = ("slow_breakout", "trend_pullback")


def make_candidate(name):
    if name == "slow_breakout":
        return TrendBreakoutStrategy(TrendBreakoutParameters(trend_period=300, breakout_period=120,
                    volume_period=30, momentum_period=30, atr_period=42, volume_multiplier=Decimal(1),
                    stop_atr_multiple=Decimal(3), reward_risk_multiple=Decimal(3)))
    if name == "trend_pullback":
        return TrendPullbackStrategy()
    raise ValueError("Unknown fixed candidate")


def settings_by_cost():
    base, stress = original_costs()["base"], original_costs()["double_costs"]
    return {"kraken_current": replace(base, paper_fee_rate=Decimal("0.008")),
            "kraken_stress": replace(stress, paper_fee_rate=Decimal("0.016")),
            "low_cost_sensitivity": replace(base, paper_fee_rate=Decimal("0.0025")),
            "low_cost_stress": replace(stress, paper_fee_rate=Decimal("0.005"))}


def definition():
    return json_value({"hypothesis": "Two fixed slower trend entries, wider ATR stops and targets, tested as development hypotheses after the earlier 4h failure.",
        "symbol": "BTC/EUR", "timeframe": "4h", "start": "2023-01-01T00:00:00+00:00", "end": "2026-01-01T00:00:00+00:00",
        "development_years": [2023, 2024], "holdout_years": [2025],
        "candidates": {name: {"strategy": make_candidate(name).name, "version": make_candidate(name).version,
                               "parameters": asdict(make_candidate(name).parameters)} for name in CANDIDATES},
        "settings": {k: asdict(v) for k, v in settings_by_cost().items()},
        "selection": "Eligible candidates must have positive net, drawdown <10%, at least 5 current-fee trades and 3 stress trades in EACH development year. Pick the highest worst-year Kraken-stress net; alphabetical tie-break. No low-cost-only winner.",
        "holdout_criteria": "One selected candidate only, positive net, drawdown <10%, at least 5 current-fee and 3 stress trades. Both Kraken cost cases must pass; report sensitivity too.",
        "rules": ["2023/2024 were already seen. This is development selection, not new out-of-sample evidence.",
                  "Exactly two parameter sets; no optimizer and no post-result parameter adjustments within this protocol.",
                  "Slow strategies intentionally have fewer trades; count thresholds are feasibility screens, not significance or proof of an edge.",
                  "Fixed net reward/risk >=1, ordinary account risk limits, LONG 1x, next observed open, stop first on ambiguous bars.",
                  "Keep accounts through verified empty intervals, expire entries, reset indicator warm-up, no synthetic candles.",
                  "Fresh 1000 EUR account per year and cost case; no combining annual returns into one portfolio.",
                  "0.25% fees on Kraken candles are a Bitvavo-like sensitivity only, not actual Bitvavo performance. No maker fills assumed.",
                  "Current costs on old prices are counterfactual. No retrospective fee tiers or automatic real trading.",
                  "2025 is inspected for performance once, only after selection is locked by development. If no candidate qualifies, do not open it."]})


def assess(segments, candidates=CANDIDATES):
    decisions = {}
    for name in candidates:
        checks, stressed = {}, []
        for segment in segments:
            indexed = {(r["variant"], r["cost_scenario"]): r for r in segment["runs"]}
            if len(indexed) != len(segment["runs"]) or any((name, c) not in indexed for c in settings_by_cost()):
                raise ValueError("Missing or duplicate candidate cases")
            for cost, minimum in (("kraken_current", 5), ("kraken_stress", 3)):
                p = indexed[name, cost]["performance"]
                checks[f"{segment['name']}/{cost}"] = {"positive_net": Decimal(p["net_profit"]) > 0,
                       "enough_trades": type(p["trades"]) is int and p["trades"] >= minimum,
                       "drawdown_below_limit": Decimal(p["max_drawdown"]) < Decimal("0.10")}
                if cost == "kraken_stress":
                    stressed.append(Decimal(p["net_profit"]))
        if not checks:
            raise ValueError("No candidate periods")
        decisions[name] = {"checks": checks, "eligible": all(all(c.values()) for c in checks.values()),
                           "worst_stress_net": str(min(stressed))}
    eligible = [name for name in candidates if decisions[name]["eligible"]]
    selected = sorted(eligible, key=lambda n: (-Decimal(decisions[n]["worst_stress_net"]), n))[0] if eligible else None
    return {"candidates": decisions, "selected": selected, "screen_passed": selected is not None}


def freeze(output, source_protocol, dataset):
    parent = json.loads(source_protocol.read_text())
    if parent["protocol_version"] != "slow-observed-gated-v2" or not (source_protocol.parent / "evaluation/completion.json").is_file():
        raise ValueError("Requires the completed previous 4h research")
    if (source_protocol.parent / "holdout").exists():
        raise ValueError("2025 was already opened by parent experiment")
    protocol = {"protocol_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                "python_version": sys.version.split()[0], "definition": definition(), "code_sha256": code_hashes(),
                "input_manifest_sha256": sha(dataset / "manifest.json"), "gap_evidence": parent["gap_evidence"],
                "parent_protocol_sha256": sha(source_protocol),
                "previous_development_results_sha256": sha(source_protocol.parent / "evaluation/results.json")}
    read_input(dataset, protocol)
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    for relative, expected in protocol["code_sha256"].items():
        source = root / relative
        if sha(source) != expected:
            raise ValueError("Code changed during freeze")
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    write_json(output / "protocol.json", protocol)


def read_protocol(path):
    protocol = json.loads(path.read_text())
    if (protocol["protocol_version"] != VERSION or protocol["definition"] != definition()
            or protocol["code_sha256"] != code_hashes() or protocol["python_version"] != sys.version.split()[0]):
        raise ValueError("Frozen definition or code differs")
    for relative, expected in protocol["code_sha256"].items():
        if sha(path.parent / "source" / relative) != expected:
            raise ValueError("Source snapshot differs")
    return protocol


def selected_candidate(path, manifest):
    folder = path.parent / "evaluation"
    result = json.loads((folder / "results.json").read_text())
    receipt = json.loads((folder / "completion.json").read_text())
    if (receipt["results_sha256"] != sha(folder / "results.json") or result["protocol_sha256"] != sha(path)
            or result["input_sha256"] != manifest["sha256"]["candles.csv"] or result["phase"] != "development"
            or [s["name"] for s in result["segments"]] != ["2023", "2024"]):
        raise ValueError("Invalid development selection evidence")
    selection = assess(result["segments"])
    if selection != result["selection"] or selection["selected"] is None:
        raise ValueError("No eligible candidate: 2025 remains reserved")
    return selection["selected"]


def render_report(result):
    lines = ["# Zwei langsamere Strategiehypothesen", "", f"Phase: {result['phase']}. Auswahl: {result['selection']['selected'] or 'kein geeigneter Kandidat'}.",
             "2023/2024 sind bereits bekannte Entwicklungsdaten. Keine neue unabhängige Bestätigung durch diese Jahre.", "",
             "| Jahr | Kandidat | Kosten | Trades | Netto EUR | Max. Drawdown % | Gebühren EUR |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: |"]
    for segment in result["segments"]:
        for run in segment["runs"]:
            p = run["performance"]
            lines.append(f"| {segment['name']} | {run['variant']} | {run['cost_scenario']} | {p['trades']} | {Decimal(p['net_profit']):.2f} | {Decimal(p['max_drawdown'])*100:.2f} | {Decimal(p['fees']):.2f} |")
    lines += ["", result["holdout_note"], "",
              "Kraken normal/stress: 0,80/1,60 % je Seite. Niedrige Kosten: 0,25/0,50 % auf denselben Kraken-Kursen; nur Sensitivität, kein Bitvavo-Backtest.",
              "Je Jahr erforderlich: positiver Nettoertrag in beiden Kraken-Fällen, mindestens 5 normale bzw. 3 Stress-Trades, beobachteter Drawdown <10 %.",
              "Diese Mindestzahlen sind keine statistische Signifikanz. Unter geeigneten Kandidaten entscheidet der schlechteste Stress-Jahresertrag, dann der Name.",
              "Jahreskonten sind getrennt. Benchmarkrisiken unterscheiden sich. Keine automatisierte Handelsfreigabe; LIVE bleibt gesperrt."]
    return "\n".join(lines) + "\n"


def evaluate(path, dataset, phase):
    if phase not in ("development", "holdout"):
        raise ValueError("Unknown phase")
    protocol = read_protocol(path)
    candles, manifest, gaps = read_input(dataset, protocol)
    names = (selected_candidate(path, manifest),) if phase == "holdout" else CANDIDATES
    output = path.parent / ("holdout" if phase == "holdout" else "evaluation")
    output.mkdir(exist_ok=False)
    digest = sha(path)
    write_json(output / "input.json", {"protocol_sha256": digest, "manifest": manifest})
    segments = []
    with Repository(output / "research.sqlite3") as repo:
        for year in protocol["definition"][f"{phase}_years"]:
            selected = tuple(c for c in candles if c.timestamp.year == year)
            year_gaps = tuple(g for g in gaps if g.start.year == year)
            runs, references = [], {}
            for cost, settings in settings_by_cost().items():
                references[cost] = benchmarks(selected, settings, verified_empty_intervals=year_gaps)
                for name in names:
                    assumptions = {"protocol_sha256": digest, "input_sha256": manifest["sha256"]["candles.csv"],
                                   "execution_model": "observed-only-expire-reset-v1", "cost_scenario": cost, "year": year,
                                   "phase": phase, "candidate": name, "strategy": protocol["definition"]["candidates"][name],
                                   "settings": json_value(asdict(settings)), "gaps": json_value([asdict(g) for g in year_gaps])}
                    run = run_case(selected, settings, "net_reward", repo, assumptions,
                                   verified_empty_intervals=year_gaps, strategy=make_candidate(name))
                    run["variant"] = name
                    runs.append(run)
                    write_json(output / f"{year}_{name}_{cost}.json", run)
                    print(f"{year}/{name}/{cost}: {run['performance']['trades']} trades, {run['performance']['net_profit']} EUR", flush=True)
            segments.append({"name": str(year), "start": selected[0].timestamp.isoformat(), "end": selected[-1].closed_at.isoformat(),
                             "runs": runs, "benchmarks": references})
    if read_protocol(path) != protocol or sha(path) != digest or read_input(dataset, protocol)[1] != manifest:
        raise ValueError("Sources changed during evaluation")
    selection = assess(segments, names)
    note = ("2025 wurde einmalig ausgewertet und gilt nun als gesehen." if phase == "holdout" else
            "2025 bleibt zurückgehalten. Ein Kandidat wurde anhand der Entwicklung fest ausgewählt; Holdout-Prüfung ist zulässig." if selection["selected"] else
            "Kein Kandidat erfüllt die Auswahlkriterien. 2025 bleibt hinsichtlich Strategieergebnissen ungesehen.")
    result = json_value({"protocol_sha256": digest, "input_sha256": manifest["sha256"]["candles.csv"], "phase": phase,
                         "segments": segments, "selection": selection, "screen_passed": selection["screen_passed"], "holdout_note": note})
    write_json(output / "results.json", result)
    (output / "report.md").write_text(render_report(result))
    write_json(output / "completion.json", {"results_sha256": sha(output / "results.json"), "completed_at": datetime.now(timezone.utc).isoformat()})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fixed two-candidate development and gated holdout")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    prepare.add_argument("--parent", type=Path, required=True)
    prepare.add_argument("--dataset", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--dataset", type=Path, required=True)
    run.add_argument("--phase", choices=("development", "holdout"), default="development")
    args = parser.parse_args(argv)
    if args.command == "freeze":
        freeze(args.output, args.parent, args.dataset)
    else:
        evaluate(args.protocol, args.dataset, args.phase)


if __name__ == "__main__":
    main()
