"""Preregister, bind unseen quarterly data, and compare a single entry filter."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.config.settings import Settings
from app.database.repository import Repository
from app.domain import TradingMode
from app.execution.order_manager import OrderManager
from app.execution.paper_broker import PaperBroker
from app.market_data.archive import ARCHIVES
from app.market_data.candles import load_candles
from app.market_data.datasets import write_json
from app.market_data.quality import audit_candles
from app.risk.net_reward import NetRewardRiskManager, REJECTION
from app.risk.stop_risk import StopRiskManager
from app.strategies.registry import make_strategy, strategy_metadata
from backtesting.benchmarks import benchmarks
from backtesting.engine import Backtester
from backtesting.execution import BacktestExecution


def json_value(value):
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    return {str(path.relative_to(root)): sha(path) for package in ("app", "backtesting")
            for path in sorted((root / package).rglob("*.py"))}


def scenarios() -> dict[str, Settings]:
    base = Settings(mode=TradingMode.BACKTEST, paper_spread_bps=Decimal("10"))
    return {"base": base, "double_costs": replace(base, paper_fee_rate=base.paper_fee_rate * 2,
            paper_slippage_bps=base.paper_slippage_bps * 2, paper_spread_bps=base.paper_spread_bps * 2)}


def definition() -> dict:
    return json_value({
        "hypothesis": "Keeping the original signals, stops and targets, require net target reward >= net stop risk at the next-open entry; compare against the original policy.",
        "strategy": strategy_metadata("trend_breakout"), "minimum_net_reward_risk": "1",
        "variants": ["original", "net_reward"], "quarter": "2026Q1", "source_url": ARCHIVES["2026Q1"],
        "symbol": "BTC/EUR", "timeframe": "15m", "start": "2026-01-01T00:00:00+00:00",
        "end": "2026-04-01T00:00:00+00:00", "expected_rows": 8639,
        "segments": [
            {"name": "before_gap", "start": "2026-01-01T00:00:00+00:00", "end": "2026-02-04T11:30:00+00:00", "rows": 3310},
            {"name": "after_gap", "start": "2026-02-04T11:45:00+00:00", "end": "2026-04-01T00:00:00+00:00", "rows": 5329}],
        "missing_interval": "2026-02-04T11:30:00+00:00",
        "settings": {name: asdict(s) for name, s in scenarios().items()},
        "screen": {"minimum_trades_each_filtered_run": 30, "positive_net_both_costs": True,
                   "strictly_better_net_than_original_both_costs": True, "maximum_drawdown_exclusive": "0.10"},
        "rules": ["Original plan frozen before download; amended only for the verified gap, before any performance calculation.",
                  "No parameter search, no target extension, no synthetic candles.",
                  "Two contiguous segments evaluated separately; first 50 candles of each are warm-up; fresh account per run.",
                  "End each segment flat at its last close. Never bridge the gap or combine results into a continuous quarter.",
                  "Filter after ordinary risk approval; next-open costs include fees, spread, slippage and ticks.",
                  "Independent broker guard repeats the chosen policy; no risk limit is relaxed.",
                  "Cash and full-cash buy-and-hold benchmarks use each full segment, including strategy warm-up.",
                  "Buy-and-hold has no protective stops or drawdown limit; different exposure, not a risk-matched portfolio.",
                  "All eight runs and benchmarks reported; screening must pass in both segments; no automatic PAPER activation.",
                  "Thirty trades is a screening convention, not statistical significance or proof of profitability.",
                  "Q1 was unused locally but precedes Q2: retrospective evaluation, not a forward test or proof of independence.",
                  "After evaluation Q1 becomes seen; no tuning and retesting this quarter as fresh evidence."]})


def freeze(output: Path, amendment_from: Path, dataset: Path) -> dict:
    parent = json.loads(amendment_from.read_text())
    if (parent["protocol_version"] != "net-reward-comparison-v1"
            or parent["definition"]["expected_rows"] != 8640
            or any(parent["definition"][key] != definition()[key] for key in
                   ("strategy", "minimum_net_reward_risk", "settings", "screen", "source_url"))
            or (amendment_from.parent / "evaluation").exists()):
        raise ValueError("Amendment requires the unchanged unevaluated original hypothesis")
    candles, manifest = read_quarter(dataset)
    protocol = {"protocol_version": "net-reward-segmented-v2", "created_at": datetime.now(timezone.utc).isoformat(),
                "python_version": sys.version.split()[0], "definition": definition(), "code_sha256": code_hashes(),
                "amendment": {"parent_protocol_sha256": sha(amendment_from), "parent_protocol": str(amendment_from.resolve()),
                              "original_created_at": parent["created_at"], "reason": "One missing 15m interval, also absent in official 5m data; no performance evaluated before amendment."},
                "input_manifest_sha256": sha(dataset / "manifest.json"), "input_sha256": manifest["sha256"]["candles.csv"]}
    validate_dataset(candles, manifest, protocol)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "protocol.json", protocol)
    return protocol


def read_protocol(path: Path) -> dict:
    protocol = json.loads(path.read_text())
    if (protocol["protocol_version"] != "net-reward-segmented-v2" or protocol["definition"] != definition()
            or protocol["code_sha256"] != code_hashes() or protocol["python_version"] != sys.version.split()[0]):
        raise ValueError("Frozen definition, code or Python version differs; do not silently change the experiment")
    return protocol


def read_quarter(dataset: Path):
    """Accept only the explicitly declared gap; every traded segment remains complete."""
    spec = definition()
    manifest = json.loads((dataset / "manifest.json").read_text())
    if (manifest.get("schema_version") != 1 or manifest.get("market_type") != "spot"
            or set(manifest.get("sha256", {})) != {"candles.csv", "source.raw", "quality.json"}):
        raise ValueError("Unsupported source manifest")
    for name, expected in manifest["sha256"].items():
        if sha(dataset / name) != expected:
            raise ValueError("Source checksum mismatch")
    candles = load_candles(dataset / "candles.csv", spec["symbol"], spec["timeframe"])
    quality = audit_candles(candles, spec["symbol"], spec["timeframe"],
                            datetime.fromisoformat(spec["start"]), datetime.fromisoformat(spec["end"])).as_dict()
    if (quality["errors"] or quality["missing_intervals"] != 1 or len(candles) != spec["expected_rows"]
            or quality["gaps"][0]["start"] != spec["missing_interval"]):
        raise ValueError("Source differs from the single declared gap; do not silently change segment selection")
    return candles, manifest


def validate_dataset(candles, manifest: dict, protocol: dict) -> None:
    spec = protocol["definition"]
    if (any(manifest[key] != spec[key] for key in ("symbol", "timeframe", "start", "end"))
            or len(candles) != spec["expected_rows"] or manifest["source"].get("url") != spec["source_url"]
            or datetime.fromisoformat(manifest["captured_at"]) < datetime.fromisoformat(protocol["amendment"]["original_created_at"])
            or candles[0].timestamp.isoformat() != spec["start"] or candles[-1].closed_at.isoformat() != spec["end"]):
        raise ValueError("Dataset is not the prescribed Q1 source captured after the original preregistration")


def run_case(candles, settings: Settings, variant: str, repository: Repository, assumptions: dict,
             *, verified_empty_intervals=None, strategy=None, execution_factory=BacktestExecution) -> dict:
    if variant not in ("original", "net_reward"):
        raise ValueError("Unknown research variant")
    session = repository.start_session(settings.mode, settings.initial_capital, settings.symbol)
    try:
        policy = NetRewardRiskManager if variant == "net_reward" else StopRiskManager
        broker = PaperBroker(settings, repository, session)
        broker.risk_guard = policy(settings)
        manager = OrderManager(policy(settings), broker, repository, session)
        execution = execution_factory(manager, broker, repository, session)
        strategy = strategy or make_strategy("trend_breakout")
        if verified_empty_intervals is None:
            result = Backtester(strategy, execution).run(candles)
        else:
            from backtesting.observed_history import ObservedHistoryBacktester
            result = ObservedHistoryBacktester(strategy, execution).run(candles, verified_empty_intervals)
        repository.record_backtest_result(session, result, assumptions)
        rejected, approved, longs = Counter(), 0, 0
        for record in repository.records("signals", session):
            signal, decision = json.loads(record["payload"]), json.loads(record["risk_decision"])
            if signal["direction"] == "LONG":
                longs += 1
                approved += int(decision["allowed"])
                if not decision["allowed"]:
                    rejected[decision["reasons"][0]] += 1
        repository.finish_session(session)
        return {"variant": variant, "cost_scenario": assumptions["cost_scenario"], "session_id": session,
                "long_signals": longs, "approved_entries": approved, "rejected_entry_reasons": dict(rejected),
                "net_reward_rejections": rejected[REJECTION], "performance": result.performance.as_dict()}
    except BaseException:
        repository.finish_session(session, failed=True)
        raise


def assess(runs: list[dict]) -> dict:
    by_case = {(r["variant"], r["cost_scenario"]): r["performance"] for r in runs}
    if len(runs) != 4 or set(by_case) != {(v, c) for v in ("original", "net_reward") for c in scenarios()}:
        raise ValueError("Assessment requires all four distinct runs")
    checks = {}
    for cost in scenarios():
        filtered, original = by_case["net_reward", cost], by_case["original", cost]
        checks[cost] = {"positive_net": Decimal(filtered["net_profit"]) > 0,
                        "better_than_original": Decimal(filtered["net_profit"]) > Decimal(original["net_profit"]),
                        "at_least_30_trades": filtered["trades"] >= 30,
                        "drawdown_below_10_percent": Decimal(filtered["max_drawdown"]) < Decimal("0.10")}
    return {"checks": checks, "screen_passed": all(all(case.values()) for case in checks.values()),
            "meaning": "Descriptive preregistered screening only, not a significance test or permission to activate trading."}


def evaluate(protocol_path: Path, dataset: Path) -> dict:
    protocol = read_protocol(protocol_path)
    candles, manifest = read_quarter(dataset)
    validate_dataset(candles, manifest, protocol)
    if (sha(dataset / "manifest.json") != protocol["input_manifest_sha256"]
            or manifest["sha256"]["candles.csv"] != protocol["input_sha256"]):
        raise ValueError("Dataset differs from the frozen amendment")
    protocol_hash = sha(protocol_path)
    output = protocol_path.parent / "evaluation"
    output.mkdir(exist_ok=False)  # A started run cannot silently be overwritten or retried.
    write_json(output / "input.json", {"protocol_sha256": protocol_hash, "manifest_sha256": sha(dataset / "manifest.json"),
                                      "dataset": str(dataset.resolve()), "manifest": manifest})
    segments = []
    with Repository(output / "research.sqlite3") as repository:
        for segment in protocol["definition"]["segments"]:
            selected = tuple(c for c in candles if datetime.fromisoformat(segment["start"]) <= c.timestamp < datetime.fromisoformat(segment["end"]))
            if len(selected) != segment["rows"]:
                raise ValueError("Unexpected segment length")
            runs, references = [], {}
            for cost_name, settings in scenarios().items():
                references[cost_name] = benchmarks(selected, settings)
                for variant in ("original", "net_reward"):
                    assumptions = {"protocol_sha256": protocol_hash, "input_sha256": manifest["sha256"]["candles.csv"],
                                   "execution_model": "cash-long-next-bar-v1", "variant": variant, "segment": segment,
                                   "cost_scenario": cost_name, "settings": json_value(asdict(settings)),
                                   "minimum_net_reward_risk": "1" if variant == "net_reward" else None}
                    run = run_case(selected, settings, variant, repository, assumptions)
                    runs.append(run)
                    write_json(output / f"{segment['name']}_{variant}_{cost_name}.json", run)
                    print(f"Completed {segment['name']}/{variant}/{cost_name}: {run['performance']['trades']} trades, net {run['performance']['net_profit']} EUR", flush=True)
            segments.append({**segment, "runs": runs, "benchmarks": references, "assessment": assess(runs)})
    if sha(protocol_path) != protocol_hash or read_protocol(protocol_path) != protocol:
        raise ValueError("Protocol or code changed during evaluation")
    # Re-verify that the referenced source still has the same data after evaluation.
    _, final_manifest = read_quarter(dataset)
    if final_manifest != manifest:
        raise ValueError("Dataset changed during evaluation")
    result = json_value({"protocol_sha256": protocol_hash, "input_sha256": manifest["sha256"]["candles.csv"],
                         "segments": segments, "screen_passed": all(s["assessment"]["screen_passed"] for s in segments)})
    write_json(output / "results.json", result)
    sections = ["# Zweite Hypothese – getrennte Auswertung wegen Datenlücke", "",
                "Im Archiv fehlen 04.02.2026, 11:30–11:45 UTC, auch in den 5-Minuten-Daten. Keine Kurse wurden ergänzt.",
                "Der ursprüngliche Plan wurde vor jeder Ergebnisberechnung ausschließlich wegen dieser Datenlücke angepasst.",
                "Beide Abschnitte starten mit eigenen Konten. Ergebnisse dürfen nicht zu einem durchgehenden Quartal addiert werden.",
                f"Gesamte vorab festgelegte Prüfung: **{'bestanden' if result['screen_passed'] else 'nicht bestanden'}**.", ""]
    for segment in result["segments"]:
        sections.append(render_report(segment))
    (output / "report.md").write_text("\n".join(sections), encoding="utf-8")
    return result


def render_report(result: dict) -> str:
    lines = [f"## Abschnitt {result['name']}: Nettoziel deckt Stop-Risiko", "",
             f"BTC/EUR, 15 Minuten, {result['start']} bis {result['end']} (Ende exklusiv, UTC), jeweils 1.000 EUR Startkapital.",
             "Ursprüngliches Protokoll vor Datenabruf, Anpassung wegen Datenlücke vor Ergebnisberechnung. Keine Parameteroptimierung.", "",
             "| Variante | Kosten | Trades | Netto EUR | Rendite % | Max. Drawdown % | Gebühren EUR | Filter-Ablehnungen |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for run in result["runs"]:
        p = run["performance"]
        lines.append(f"| {run['variant']} | {run['cost_scenario']} | {p['trades']} | {Decimal(p['net_profit']):.2f} | "
                     f"{Decimal(p['return_fraction']) * 100:.2f} | {Decimal(p['max_drawdown']) * 100:.2f} | "
                     f"{Decimal(p['fees']):.2f} | {run['net_reward_rejections']} |")
    for cost, references in result["benchmarks"].items():
        for name, reference in references.items():
            p = reference["performance"]
            lines.append(f"| {name} | {cost} | {p['trades']} | {Decimal(p['net_profit']):.2f} | "
                         f"{Decimal(p['return_fraction']) * 100:.2f} | {Decimal(p['max_drawdown']) * 100:.2f} | {Decimal(p['fees']):.2f} | – |")
    passed = result["assessment"]["screen_passed"]
    lines += ["", f"Vorab festgelegte Prüfkriterien: **{'erfüllt' if passed else 'nicht erfüllt'}**.",
              "Erforderlich in beiden Kostenfällen: positiver Nettogewinn, besser als die ursprüngliche Variante,",
              "mindestens 30 Trades und beobachteter Drawdown unter 10 %. 30 Trades sind eine Arbeitskonvention, kein Signifikanznachweis.", ""]
    for cost, checks in result["assessment"]["checks"].items():
        lines.append(f"- {cost}: " + "; ".join(f"{name}={'ja' if value else 'nein'}" for name, value in checks.items()))
    lines += ["", "Die Filterregel prüft das unveränderte Kursziel am nächsten Einstiegskurs nach allen modellierten Kosten.",
              "Signalbedingungen, ATR-Stop und Preisziel bleiben gleich. Das Risiko am Stop berücksichtigt keine spätere Kurslücke.",
              "Filter-Ablehnungen zählen nur Signale, die zuvor die normale Risikoprüfung bestanden haben.",
              "Die Varianten haben unterschiedliche Kontoverläufe; die Ergebnisdifferenz ist kein Vergleich identischer Trades.", "",
              "Kaufen-und-Halten investiert am ersten Open einschließlich der Strategie-Aufwärmphase und verkauft am letzten Close.",
              "Kosten und Rundung sind gleich, Schutzstops und Verlustlimits fehlen beim Benchmark. Nicht-Handeln erhält keine Zinsen.",
              "Drawdowns basieren auf beobachteten Simulationsereignissen, nicht auf Tickdaten. Kosten sind Forschungsannahmen.", "",
              "Q1 war in diesem Projekt bislang ungenutzt, liegt aber vor den Q2-Daten, aus deren Diagnose die Regel entstand.",
              "Das ist eine zusätzliche rückblickende Prüfung, kein Vorwärtstest und kein Nachweis statistischer Unabhängigkeit.",
              "Q1 gilt jetzt als gesehen. Keine automatische PAPER-Aktivierung; LIVE bleibt gesperrt.", "",
              "Einzelne Läufe, Ablehnungsgründe und Benchmarks stehen in results.json; Trades und Signale in research.sqlite3."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preregister and evaluate the fixed net-reward research hypothesis")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--amend-from", type=Path, required=True)
    prepare.add_argument("--dataset", type=Path, required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            freeze(args.output, args.amend_from, args.dataset)
            print(f"Frozen protocol: {args.output / 'protocol.json'}")
        else:
            evaluate(args.protocol, args.dataset)
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"Net-reward research failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
