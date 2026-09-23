"""Fixed 4h hypothesis with a gated, chronologically later historical holdout."""

import argparse
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.database.repository import Repository
from app.market_data.datasets import load_dataset, write_json
from app.market_data.full_archive import PARTS
from app.strategies.registry import strategy_metadata
from backtesting.benchmarks import benchmarks
from backtesting.net_reward_research import code_hashes, json_value, run_case, scenarios, sha

VERSION = "slow-timeframe-gated-v1"


def settings_by_cost():
    return {name: replace(settings, timeframe="4h") for name, settings in scenarios().items()}


def definition():
    return json_value({
        "hypothesis": "On 4h bars, the unchanged trend-breakout rules plus net reward/risk >= 1 may retain sufficient price movement after costs. Original unfiltered policy is a descriptive control, never a fallback winner.",
        "strategy": strategy_metadata("trend_breakout"), "symbol": "BTC/EUR", "timeframe": "4h",
        "source_parts": PARTS, "start": "2023-01-01T00:00:00+00:00", "end": "2026-01-01T00:00:00+00:00",
        "screen_years": [2023, 2024], "holdout_years": [2025], "variants": ["original", "net_reward"],
        "primary_variant": "net_reward", "minimum_net_reward_risk": "1",
        "settings": {name: asdict(s) for name, s in settings_by_cost().items()},
        "screen": {"minimum_trades_each_primary_run": 20, "net_profit_exclusive": "0", "max_drawdown_exclusive": "0.10"},
        "rules": [
            "No optimization; all original bar-count parameters unchanged. Four hours is chosen before downloading this history.",
            "Require complete coverage; any gap blocks evaluation, no synthetic bars or discretionary segmentation.",
            "Each year and variant starts with a fresh 1000 EUR account; first 50 bars are warm-up without earlier-year data.",
            "Both cost scenarios and both variants are reported for every evaluated year; never combine annual returns into a continuous portfolio.",
            "Primary variant must have positive net profit, at least 20 trades and observed drawdown below 10% in EACH year and cost scenario.",
            "20 trades is a minimum research screen, not statistical significance. Passing does not establish an edge or authorize trading.",
            "2025 may be evaluated only if every 2023/2024 primary run passes. No fallback to the unfiltered control.",
            "2025 then receives exactly the same rules and criteria; no parameter adjustment between phases.",
            "Cash and buy-and-hold cover the full year including warm-up; same costs, but buy-and-hold has no strategy risk limits.",
            "Older, locally unused history is retrospective evidence motivated by later 2026 observations, not a prospective test.",
            "Raw source may contain reserved prices. Only coverage/integrity inspection is permitted before the holdout gate opens.",
            "No new hypothesis on these periods may label them untouched after evaluation; no automatic PAPER or LIVE activation."]})


def freeze(output: Path):
    protocol = {"protocol_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                "python_version": sys.version.split()[0], "definition": definition(), "code_sha256": code_hashes()}
    output.mkdir(parents=True, exist_ok=False)
    # Preserve the precise executable sources, not only hashes, for later reproduction.
    root = Path(__file__).resolve().parents[1]
    for relative, expected in protocol["code_sha256"].items():
        source = root / relative
        if sha(source) != expected:
            raise ValueError("Code changed while freezing")
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    write_json(output / "protocol.json", protocol)
    return protocol


def read_protocol(path: Path):
    protocol = json.loads(path.read_text())
    if (protocol["protocol_version"] != VERSION or protocol["definition"] != definition()
            or protocol["python_version"] != sys.version.split()[0] or protocol["code_sha256"] != code_hashes()):
        raise ValueError("Frozen definition, sources or Python changed")
    for relative, expected in protocol["code_sha256"].items():
        if sha(path.parent / "source" / relative) != expected:
            raise ValueError("Frozen source snapshot changed")
    return protocol


def read_input(dataset: Path, protocol: dict):
    candles, manifest = load_dataset(dataset)
    spec = protocol["definition"]
    if (any(manifest[key] != spec[key] for key in ("symbol", "timeframe", "start", "end"))
            or manifest["source"].get("format") != "official-multipart-ohlcvt-zip-member"
            or [p["url"] for p in manifest["source"].get("parts", [])] != spec["source_parts"]
            or datetime.fromisoformat(manifest["captured_at"]) < datetime.fromisoformat(protocol["created_at"])):
        raise ValueError("Wrong data period, market, source or preregistration order")
    return candles, manifest


def assess(runs: list[dict]):
    expected = {(v, c) for v in definition()["variants"] for c in settings_by_cost()}
    indexed = {(r["variant"], r["cost_scenario"]): r["performance"] for r in runs}
    if len(runs) != len(expected) or set(indexed) != expected:
        raise ValueError("Assessment requires all four distinct cases")
    screen = definition()["screen"]
    checks = {}
    for cost in settings_by_cost():
        p = indexed["net_reward", cost]
        checks[cost] = {"positive_net": Decimal(p["net_profit"]) > Decimal(screen["net_profit_exclusive"]),
                        "sufficient_trades": type(p["trades"]) is int and p["trades"] >= screen["minimum_trades_each_primary_run"],
                        "drawdown_below_limit": Decimal(p["max_drawdown"]) < Decimal(screen["max_drawdown_exclusive"])}
    return {"checks": checks, "screen_passed": all(all(c.values()) for c in checks.values())}


def check_holdout_gate(protocol_path: Path, manifest: dict):
    folder = protocol_path.parent / "evaluation"
    result = json.loads((folder / "results.json").read_text())
    receipt = json.loads((folder / "completion.json").read_text())
    if (receipt["results_sha256"] != sha(folder / "results.json")
            or result["protocol_sha256"] != sha(protocol_path)
            or result["input_sha256"] != manifest["sha256"]["candles.csv"]
            or result["phase"] != "screen"
            or [s["name"] for s in result["segments"]] != [str(y) for y in definition()["screen_years"]]
            or not all(assess(s["runs"])["screen_passed"] for s in result["segments"])):
        raise ValueError("2025 remains reserved: 2023/2024 screen did not pass or its artifacts changed")


def render_report(result):
    lines = ["# Dritte Hypothese: längerer Zeitrahmen", "",
             f"Phase: {result['phase']}. BTC/EUR, 4 Stunden. Ergebnis der festgelegten Prüfung: **{'bestanden' if result['screen_passed'] else 'nicht bestanden'}**.",
             "Unveränderte Ausbruchsregeln; primärer Kandidat ist ausschließlich der Nettoziel-Filter. Keine Parametersuche.",
             "Jeder Lauf startet mit 1.000 EUR; Jahresergebnisse sind keine durchgehende Kontokurve.", "",
             "| Jahr | Variante | Kosten | Trades | Netto EUR | Rendite % | Max. Rückgang % | Gebühren EUR |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for segment in result["segments"]:
        rows = list(segment["runs"])
        rows += [{"variant": name, "cost_scenario": cost, "performance": value["performance"]}
                 for cost, references in segment["benchmarks"].items() for name, value in references.items()]
        for row in rows:
            p = row["performance"]
            lines.append(f"| {segment['name']} | {row['variant']} | {row['cost_scenario']} | {p['trades']} | {Decimal(p['net_profit']):.2f} | {Decimal(p['return_fraction'])*100:.2f} | {Decimal(p['max_drawdown'])*100:.2f} | {Decimal(p['fees']):.2f} |")
    lines += ["", "Prüfung je Jahr und Kostenfall: Nettoergebnis > 0, mindestens 20 Trades, beobachteter Drawdown < 10 %.",
              "Die Mindestzahl ist eine Arbeitskonvention und kein statistischer Nachweis. Kosten sind Modellannahmen, keine verifizierten aktuellen Kraken-Tarife."]
    for segment in result["segments"]:
        for cost, checks in segment["assessment"]["checks"].items():
            lines.append(f"- {segment['name']}/{cost}: " + "; ".join(f"{name}={'ja' if passed else 'nein'}" for name, passed in checks.items()))
    lines += ["", result["holdout_note"], "",
              "Alle ausgewerteten Jahre gelten nun als gesehen. Ältere Daten liefern eine rückblickende Prüfung; dies ist kein Vorwärtstest.",
              "Cash erhält keine Zinsen. Kaufen-und-Halten ist voll investiert, ohne Schutzstops und Verlustgrenzen; daher kein risikogleicher Vergleich.",
              "LONG, 1x, nächstes Open, feste ATR-Stops und Kursziele; bei Stop und Ziel in derselben Kerze wird zuerst der Stop angenommen.",
              "Keine Tickdaten; beobachtete Rückgänge können das tatsächliche Risiko unterschätzen. Keine automatische Handelsfreigabe.",
              "Protokoll und ausführbare Quellkopie liegen im übergeordneten Ordner; Einzelergebnisse, Signale und Trades sind vollständig gespeichert."]
    return "\n".join(lines) + "\n"


def evaluate(protocol_path: Path, dataset: Path, phase: str):
    if phase not in ("screen", "holdout"):
        raise ValueError("Unknown phase")
    protocol = read_protocol(protocol_path)
    candles, manifest = read_input(dataset, protocol)
    if phase == "holdout":
        check_holdout_gate(protocol_path, manifest)
    protocol_hash, manifest_hash = sha(protocol_path), sha(dataset / "manifest.json")
    output = protocol_path.parent / ("evaluation" if phase == "screen" else "holdout")
    output.mkdir(exist_ok=False)
    write_json(output / "input.json", {"protocol_sha256": protocol_hash, "manifest_sha256": manifest_hash,
                                      "dataset": str(dataset.resolve()), "manifest": manifest})
    segments = []
    with Repository(output / "research.sqlite3") as repository:
        for year in protocol["definition"][f"{phase}_years"]:
            selected = tuple(c for c in candles if c.timestamp.year == year)
            start, end = datetime(year, 1, 1, tzinfo=timezone.utc), datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            if len(selected) != int((end - start).total_seconds() / 14400):
                raise ValueError("Incomplete year")
            runs, references = [], {}
            for cost, settings in settings_by_cost().items():
                references[cost] = benchmarks(selected, settings)
                for variant in protocol["definition"]["variants"]:
                    assumptions = {"protocol_sha256": protocol_hash, "input_sha256": manifest["sha256"]["candles.csv"],
                                   "execution_model": "cash-long-next-bar-v1", "year": year, "phase": phase,
                                   "variant": variant, "cost_scenario": cost, "settings": json_value(asdict(settings)),
                                   "minimum_net_reward_risk": "1" if variant == "net_reward" else None}
                    run = run_case(selected, settings, variant, repository, assumptions)
                    runs.append(run)
                    write_json(output / f"{year}_{variant}_{cost}.json", run)
                    print(f"{year}/{variant}/{cost}: trades={run['performance']['trades']}, net={run['performance']['net_profit']}", flush=True)
            segments.append({"name": str(year), "start": start.isoformat(), "end": end.isoformat(),
                             "rows": len(selected), "runs": runs, "benchmarks": references, "assessment": assess(runs)})
    if read_protocol(protocol_path) != protocol or sha(protocol_path) != protocol_hash:
        raise ValueError("Protocol or sources changed during evaluation")
    _, final_manifest = read_input(dataset, protocol)
    if final_manifest != manifest or sha(dataset / "manifest.json") != manifest_hash:
        raise ValueError("Source changed during evaluation")
    passed = all(s["assessment"]["screen_passed"] for s in segments)
    note = ("2025 ist nun ausgewertet und gilt als gesehen." if phase == "holdout" else
            "2025 ist noch nicht ausgewertet; die festgelegte Holdout-Prüfung darf jetzt starten." if passed else
            "2025 bleibt zurückgehalten und wurde nicht auf Strategieergebnisse ausgewertet. Die Mindestkriterien wurden verfehlt.")
    result = json_value({"protocol_sha256": protocol_hash, "input_sha256": manifest["sha256"]["candles.csv"],
                         "phase": phase, "segments": segments, "screen_passed": passed, "holdout_note": note})
    write_json(output / "results.json", result)
    (output / "report.md").write_text(render_report(result), encoding="utf-8")
    write_json(output / "completion.json", {"results_sha256": sha(output / "results.json"),
                                           "completed_at": datetime.now(timezone.utc).isoformat()})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fixed 4h hypothesis with gated 2025 holdout")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("freeze")
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("evaluate")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--dataset", type=Path, required=True)
    run.add_argument("--phase", choices=("screen", "holdout"), default="screen")
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            freeze(args.output)
            print(f"Frozen: {args.output / 'protocol.json'}")
        else:
            evaluate(args.protocol, args.dataset, args.phase)
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"4h research failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
