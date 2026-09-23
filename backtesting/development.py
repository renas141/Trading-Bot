"""Reusable frozen runner for fixed strategy/exit comparisons on Bitvavo development data."""

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.database.repository import Repository
from app.market_data.datasets import write_json
from backtesting.benchmarks import benchmarks
from backtesting.net_reward_research import code_hashes, json_value, run_case, sha
from backtesting.venue_research import inputs, cases


def freeze(output, dataset, snapshot, *, version, definition):
    _, _, market = inputs(dataset, snapshot)
    protocol = {"protocol_version": version, "created_at": datetime.now(timezone.utc).isoformat(),
                "python_version": sys.version.split()[0], "definition": definition(market),
                "input_manifest_sha256": sha(dataset / "manifest.json"),
                "instrument_snapshot_sha256": sha(snapshot / "snapshot.json"), "code_sha256": code_hashes()}
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


def verify(path, dataset, snapshot, *, version, definition):
    protocol = json.loads(path.read_text())
    candles, manifest, market = inputs(dataset, snapshot)
    if (protocol["protocol_version"] != version or protocol["definition"] != definition(market)
            or protocol["python_version"] != sys.version.split()[0] or protocol["code_sha256"] != code_hashes()
            or protocol["input_manifest_sha256"] != sha(dataset / "manifest.json")
            or protocol["instrument_snapshot_sha256"] != sha(snapshot / "snapshot.json")
            or any(sha(path.parent / "source" / p) != digest for p, digest in protocol["code_sha256"].items())):
        raise ValueError("Frozen sources differ")
    return protocol, candles, manifest, market


def evaluate(path, dataset, snapshot, *, version, definition, variants, assess, title):
    protocol, candles, manifest, market = verify(path, dataset, snapshot, version=version, definition=definition)
    protocol_digest = sha(path)
    output = path.parent / "evaluation"
    output.mkdir(exist_ok=False)
    write_json(output / "input.json", {"manifest": manifest, "instrument": json.loads((snapshot / "snapshot.json").read_text())})
    segments = []
    with Repository(output / "research.sqlite3") as repo:
        for year in (2023, 2024):
            selected = tuple(c for c in candles if c.timestamp.year == year)
            runs, references = [], {}
            for cost, settings in cases(market).items():
                references[cost] = benchmarks(selected, settings)
                for name, (strategy, policy, execution) in variants().items():
                    assumptions = {"protocol_sha256": protocol_digest, "input_sha256": manifest["sha256"]["candles.csv"],
                                   "provider": "Bitvavo", "cost_scenario": cost, "year": year, "phase": "development",
                                   "variant": name, "settings": json_value(asdict(settings)),
                                   "rule": protocol["definition"]["variants"][name]}
                    run = run_case(selected, settings, policy, repo, assumptions, strategy=strategy, execution_factory=execution)
                    run["variant"] = name
                    runs.append(run)
                    write_json(output / f"{year}_{name}_{cost}.json", run)
                    print(f"{year}/{name}/{cost}: {run['performance']['trades']} trades, {run['performance']['net_profit']} EUR", flush=True)
            segments.append({"name": str(year), "start": selected[0].timestamp.isoformat(), "end": selected[-1].closed_at.isoformat(),
                             "runs": runs, "benchmarks": references})
    verify(path, dataset, snapshot, version=version, definition=definition)
    if protocol_digest != sha(path):
        raise ValueError("Protocol changed")
    assessment = assess(segments)
    result = json_value({"protocol_sha256": protocol_digest, "input_sha256": manifest["sha256"]["candles.csv"],
                         "phase": "development", "segments": segments, "assessment": assessment,
                         "screen_passed": assessment["screen_passed"],
                         "holdout_note": "Vorab festgelegter Entwicklungsversuch auf bekannten Jahren. 2025 bleibt in diesem Versuch reserviert; keine automatische Handelsfreigabe."})
    write_json(output / "results.json", result)
    lines = [f"# {title}", "", result["holdout_note"], "", "Sichtung bestanden: " + str(assessment["screen_passed"]), "",
             "Eigene Bitvavo-Kurse, aktuelle Takerkosten 0,25 % / Stress 0,50 % je Seite; konservative feste Spread-/Slippage-Annahmen.",
             "Je Jahr/Kostenfall ein eigenes 1.000-EUR-Konto. Kein Addieren jährlicher Konten.", "",
             "| Jahr | Variante | Kosten | Trades | Netto EUR | Drawdown % |", "| --- | --- | --- | ---: | ---: | ---: |"]
    for segment in segments:
        for run in segment["runs"]:
            p = run["performance"]
            lines.append(f"| {segment['name']} | {run['variant']} | {run['cost_scenario']} | {p['trades']} | {Decimal(p['net_profit']):.2f} | {Decimal(p['max_drawdown'])*100:.2f} |")
    lines += ["", "## Vorab festgelegte Regeln", ""] + ["- " + text for text in protocol["definition"]["rules"]]
    lines += ["", "## Prüfungen", "", "```json", json.dumps(assessment, indent=2), "```", "",
              "Kleine Stichprobe und bereits gesehene Entwicklungsjahre; auch eine bestandene Sichtung ist kein unabhängiger Profitabilitätsnachweis."]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    write_json(output / "completion.json", {"results_sha256": sha(output / "results.json"), "completed_at": datetime.now(timezone.utc).isoformat()})
    return result
