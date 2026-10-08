"""Fail-closed, non-mutating readiness report for the trading-bot project."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.derivatives.qualification import source_hashes as qualification_source_hashes
from app.exchange.kraken_futures_instrument import load_snapshot
from app.exchange.kraken_futures_readonly import configuration_status
from app.market_data.kraken_perpetual_forward import STEP, load_bundle
from backtesting.perpetual_forward_research import (
    FORWARD_START,
    SCREEN_BLOCKS,
    TOTAL_BLOCKS,
    read_protocol,
)
from backtesting.adaptive_forward_protocol_v2 import (
    FORWARD_START as ADAPTIVE_FORWARD_START,
    SCREEN_BLOCKS as ADAPTIVE_SCREEN_BLOCKS,
    read_protocol as read_adaptive_protocol,
)


@dataclass(frozen=True)
class ReadinessPaths:
    forward_root: Path
    protocol: Path
    cost_candidate: Path
    cost_summary: Path
    instrument_snapshot: Path
    paper_root: Path
    account_summary: Path
    adaptive_protocol: Path
    adaptive_amendment: Path
    technical_qualification: Path


DEFAULT_PATHS = ReadinessPaths(
    Path("data/forward/pf_xbtusd"),
    Path("data/research/perpetual_funding_aware_forward_20261003_v2/protocol.json"),
    Path("data/evidence/perpetual-costs-20260923-evening/cost-candidate.json"),
    Path("data/evidence/perpetual-costs-20260923-evening/summary.json"),
    Path("data/evidence/kraken_derivatives_20261006_live"),
    Path("data/paper"),
    Path("data/evidence/kraken-readonly/account-summary.json"),
    Path("data/research/perpetual_adaptive_forward_20261005_v2/protocol.json"),
    Path("data/research/perpetual_adaptive_forward_20261005_v2/protocol.json"),
    Path("data/readiness/technical-qualification.json"),
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verified_forward_rows(root: Path) -> list[tuple[Path, datetime, datetime]]:
    rows = []
    for path in sorted(candidate for candidate in root.glob("pf_xbtusd_*") if candidate.is_dir()):
        manifest = load_bundle(path)
        rows.append((path, datetime.fromisoformat(manifest["start"]),
                     datetime.fromisoformat(manifest["end"])))
    if not rows:
        raise ValueError("No verified PF_XBTUSD forward bundles are available")
    for previous, current in zip(rows, rows[1:]):
        if previous[2] != current[1]:
            raise ValueError("PF_XBTUSD forward evidence has a gap or overlap")
    return rows


def _forward_progress(rows: list[tuple[Path, datetime, datetime]]) -> dict:
    post = [row for row in rows if row[1] >= FORWARD_START]
    if post and post[0][1] != FORWARD_START:
        raise ValueError("PF_XBTUSD post-cutoff evidence starts late")
    screen = min(len(post), SCREEN_BLOCKS)
    holdout = min(max(len(post) - SCREEN_BLOCKS, 0), TOTAL_BLOCKS - SCREEN_BLOCKS)
    return {
        "verified_bundles": len(rows),
        "excluded_before_or_at_cutoff": len(rows) - len(post),
        "post_cutoff_bundles": len(post),
        "first_start": rows[0][1].isoformat(),
        "last_end": rows[-1][2].isoformat(),
        "screen": {
            "collected": screen, "required": SCREEN_BLOCKS,
            "progress_percent": round(screen / SCREEN_BLOCKS * 100, 2),
            "expected_end": (FORWARD_START + STEP * SCREEN_BLOCKS).isoformat(),
        },
        "holdout": {
            "collected": holdout, "required": TOTAL_BLOCKS - SCREEN_BLOCKS,
            "progress_percent": round(holdout / (TOTAL_BLOCKS - SCREEN_BLOCKS) * 100, 2),
            "expected_end": (FORWARD_START + STEP * TOTAL_BLOCKS).isoformat(),
        },
    }


def _stage(protocol: Path, name: str) -> dict:
    results_path = protocol.parent / name / "results.json"
    completion_path = protocol.parent / name / "completion.json"
    if not results_path.exists() and not completion_path.exists():
        return {"status": "not_evaluated", "passed": False}
    if not results_path.is_file() or not completion_path.is_file():
        raise ValueError(f"{name} result and completion receipt differ")
    results = json.loads(results_path.read_text(encoding="utf-8"))
    receipt = json.loads(completion_path.read_text(encoding="utf-8"))
    if (receipt.get("results_sha256") != _sha(results_path)
            or results.get("protocol_sha256") != _sha(protocol)
            or results.get("stage") != name
            or results.get("activation") != {"paper_enabled": False, "live_enabled": False}
            or type(results.get("assessment", {}).get("passed")) is not bool):
        raise ValueError(f"{name} result receipt is invalid")
    passed = results["assessment"]["passed"]
    return {"status": "passed" if passed else "failed", "passed": passed}


def _paper_status(root: Path) -> dict:
    candidates = sorted(root.glob("pf_xbtusd_*/status.json"),
                        key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("mode") != "PAPER"
                or value.get("market") != "PF_XBTUSD"
                or value.get("live_enabled") is not False):
            raise ValueError("PAPER status is invalid")
        healthy = value.get("status") not in {"degraded", "failed"}
        observed = int(value.get("quote_events", value.get("processed_blocks", 0)))
        return {
            "status": value.get("status"), "healthy": healthy,
            "observations": observed, "closed_trades": int(value.get("closed_trades", 0)),
            "source": path.parent.name, "live_enabled": False,
        }
    return {"status": "not_started", "healthy": False, "observations": 0,
            "closed_trades": 0, "live_enabled": False}


def _private_account(path: Path, configured: dict) -> dict:
    result = {
        "configured": configured["configured"],
        "required_permissions": configured["required_permissions"],
        "verified": False,
        "verified_at": None,
        "pf_xbtusd_accessible": False,
        "pf_xbtusd_eligible": False,
        "minimum_trade_size": None,
    }
    if not path.is_file():
        return result
    if path.stat().st_size > 100_000:
        raise ValueError("Kraken read-only verification summary is too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    market = value.get("pf_xbtusd")
    if (value.get("schema_version") != 1 or value.get("mode") != "read_only"
            or value.get("permissions") != configured["required_permissions"]
            or value.get("order_capability") is not False
            or value.get("transfer_capability") is not False
            or not isinstance(value.get("verified_at"), str)
            or not isinstance(market, dict)):
        raise ValueError("Kraken read-only verification summary is invalid")
    result.update({
        "verified": market.get("accessible") is True and market.get("eligible") is True,
        "verified_at": value["verified_at"],
        "pf_xbtusd_accessible": market.get("accessible") is True,
        "pf_xbtusd_eligible": market.get("eligible") is True,
        "minimum_trade_size": market.get("minimum_trade_size"),
    })
    return result


def _adaptive_candidate(
    paths: ReadinessPaths,
    verified_rows: list[tuple[Path, datetime, datetime]],
) -> dict:
    if not paths.adaptive_protocol.is_file():
        return {
            "status": "not_frozen", "verified": False, "collected": 0,
            "required": ADAPTIVE_SCREEN_BLOCKS, "live_enabled": False,
        }
    protocol = read_adaptive_protocol(
        paths.adaptive_protocol, paths.cost_candidate, paths.cost_summary
    )
    rows = [(start, end) for _, start, end in verified_rows
            if start >= ADAPTIVE_FORWARD_START]
    if rows:
        if rows[0][0] != ADAPTIVE_FORWARD_START:
            raise ValueError("Adaptive forward evidence starts late")
        for previous, current in zip(rows, rows[1:]):
            if previous[1] != current[0]:
                raise ValueError("Adaptive forward evidence has a gap")
    collected = min(len(rows), ADAPTIVE_SCREEN_BLOCKS)
    return {
        "status": "collecting_forward_screen",
        "verified": protocol["protocol_version"]
        == "pf-xbtusd-adaptive-funding-forward-v2",
        "forward_start": ADAPTIVE_FORWARD_START.isoformat(),
        "collected": collected, "required": ADAPTIVE_SCREEN_BLOCKS,
        "progress_percent": round(collected / ADAPTIVE_SCREEN_BLOCKS * 100, 2),
        "risk_tiers": {"three_confirmations": "0.5%", "four_confirmations": "1.25%"},
        "maximum_leverage": 10,
        "paper_enabled": False, "live_enabled": False,
    }


def _technical_qualification(path: Path) -> dict:
    if not path.is_file():
        return {"status": "not_generated", "verified": False, "live_enabled": False}
    if path.stat().st_size > 1_000_000:
        raise ValueError("Technical qualification report is too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    checks = value.get("checks")
    expected = {
        "long_short_leverage_lifecycles",
        "funding_adjusted_liquidation",
        "tail_gap_deleveraging",
        "unavailable_depth_rejection",
        "event_chain_recovery",
        "live_lock",
    }
    if (value.get("schema_version") != 1 or value.get("market") != "PF_XBTUSD"
            or value.get("mode") != "PAPER" or value.get("passed") is not True
            or value.get("live_enabled") is not False or not isinstance(checks, dict)
            or set(checks) != expected
            or not all(isinstance(check, dict) and check.get("passed") is True
                       for check in checks.values())
            or value.get("source_sha256") != qualification_source_hashes()):
        raise ValueError("Technical qualification report is invalid or stale")
    return {
        "status": "passed", "verified": True,
        "generated_at": value.get("generated_at"),
        "checks": {name: True for name in sorted(expected)},
        "live_enabled": False,
    }


def build_readiness(paths: ReadinessPaths = DEFAULT_PATHS,
                    environ: dict[str, str] | None = None) -> dict:
    protocol, _ = read_protocol(paths.protocol, paths.cost_candidate, paths.cost_summary)
    verified_rows = _verified_forward_rows(paths.forward_root)
    forward = _forward_progress(verified_rows)
    instrument = load_snapshot(paths.instrument_snapshot)
    if instrument.get("ready_for_research") is not True or instrument.get("live_enabled") is not False:
        raise ValueError("Current PF_XBTUSD instrument evidence is not research-ready")
    screen, holdout = _stage(paths.protocol, "screen"), _stage(paths.protocol, "holdout")
    if holdout["status"] != "not_evaluated" and not screen["passed"]:
        raise ValueError("Holdout exists without a passing screen")
    paper = _paper_status(paths.paper_root)
    configured_account = configuration_status(os.environ if environ is None else environ)
    account = _private_account(paths.account_summary, configured_account)
    adaptive = _adaptive_candidate(paths, verified_rows)
    technical = _technical_qualification(paths.technical_qualification)

    screen_data_complete = forward["screen"]["collected"] == SCREEN_BLOCKS
    holdout_data_complete = forward["holdout"]["collected"] == TOTAL_BLOCKS - SCREEN_BLOCKS
    if screen["status"] == "failed":
        overall = "hypothesis_failed"
    elif not screen_data_complete:
        overall = "collecting_forward_screen"
    elif screen["status"] == "not_evaluated":
        overall = "screen_ready_for_evaluation"
    elif not screen["passed"]:
        overall = "hypothesis_failed"
    elif not holdout_data_complete:
        overall = "collecting_holdout"
    elif holdout["status"] == "not_evaluated":
        overall = "holdout_ready_for_evaluation"
    elif holdout["passed"] and technical["verified"]:
        overall = "paper_candidate"
    elif holdout["passed"]:
        overall = "technical_qualification_required"
    else:
        overall = "hypothesis_failed"

    blockers = []
    if not screen_data_complete:
        blockers.append(f"Forward-Screen: {forward['screen']['collected']} von {SCREEN_BLOCKS} Blöcken")
    elif screen["status"] == "not_evaluated":
        blockers.append("Forward-Screen ist vollständig, aber noch nicht ausgewertet")
    elif not screen["passed"]:
        blockers.append("Die vorab festgelegte Hypothese hat den Forward-Screen nicht bestanden")
    if screen["passed"] and not holdout_data_complete:
        blockers.append(
            f"Unabhängiger Holdout: {forward['holdout']['collected']} von "
            f"{TOTAL_BLOCKS - SCREEN_BLOCKS} Blöcken"
        )
    elif screen["passed"] and holdout_data_complete and holdout["status"] == "not_evaluated":
        blockers.append("Holdout ist vollständig, aber noch nicht ausgewertet")
    elif holdout["status"] == "failed":
        blockers.append("Die Hypothese hat den unabhängigen Holdout nicht bestanden")
    if not technical["verified"]:
        blockers.append("Technische Derivatequalifikation ist nicht aktuell bestätigt")
    if not account["verified"]:
        blockers.append("Persönlicher Kraken-Lesezugang und Produktberechtigung sind nicht bestätigt")
    blockers.append("Kraken stellt am früheren Host keine nutzbare Demo-Umgebung mehr bereit")

    profitable = holdout["passed"]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market": "PF_XBTUSD",
        "overall_status": overall,
        "profitability_proven": profitable,
        "paper_candidate": profitable and technical["verified"],
        "live_enabled": False,
        "gates": {
            "frozen_protocol": {"verified": protocol.get("protocol_version") is not None},
            "public_contract": {
                "verified": True,
                "server_time": instrument["server_time"],
                "maximum_leverage": instrument["public_contract"]["maximum_leverage_from_first_tier"],
            },
            "forward": forward,
            "screen": screen,
            "holdout": holdout,
            "paper_observer": paper,
            "private_account": account,
            "demo_environment": {"available": False, "status": "legacy_host_decommissioned"},
            "adaptive_candidate": adaptive,
            "technical_qualification": technical,
        },
        "blockers": blockers,
        "user_actions": ([
            "Kraken-EWR-Derivatezugang im persönlichen Konto bestätigen.",
            "Einen separaten API-Schlüssel mit General READ_ONLY und Transfer NO_ACCESS anlegen.",
            "Schlüssel nur lokal als Prozessvariablen bereitstellen; nicht im Chat oder in Git senden.",
        ] if not account["configured"] else ([
            "Die lokale Nur-Lese-Prüfung ausführen und den entschärften Nachweis speichern."
        ] if not account["verified"] else [])),
    }


def validate_report(value: dict) -> dict:
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or value.get("market") != "PF_XBTUSD"
            or value.get("live_enabled") is not False
            or not isinstance(value.get("gates"), dict)
            or not isinstance(value.get("blockers"), list)
            or type(value.get("profitability_proven")) is not bool):
        raise ValueError("Readiness report is invalid")
    return value


def write_report(output: Path, report: dict) -> None:
    validate_report(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build a fail-closed trading-bot readiness report")
    parser.add_argument("--output", type=Path, default=Path("data/readiness/status.json"))
    parser.add_argument("--forward-root", type=Path, default=DEFAULT_PATHS.forward_root)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PATHS.protocol)
    parser.add_argument("--cost-candidate", type=Path, default=DEFAULT_PATHS.cost_candidate)
    parser.add_argument("--cost-summary", type=Path, default=DEFAULT_PATHS.cost_summary)
    parser.add_argument("--instrument-snapshot", type=Path,
                        default=DEFAULT_PATHS.instrument_snapshot)
    parser.add_argument("--paper-root", type=Path, default=DEFAULT_PATHS.paper_root)
    parser.add_argument("--account-summary", type=Path, default=DEFAULT_PATHS.account_summary)
    parser.add_argument("--adaptive-protocol", type=Path, default=DEFAULT_PATHS.adaptive_protocol)
    parser.add_argument("--adaptive-amendment", type=Path,
                        default=DEFAULT_PATHS.adaptive_amendment)
    parser.add_argument("--technical-qualification", type=Path,
                        default=DEFAULT_PATHS.technical_qualification)
    args = parser.parse_args(argv)
    paths = ReadinessPaths(args.forward_root, args.protocol, args.cost_candidate,
                           args.cost_summary, args.instrument_snapshot, args.paper_root,
                           args.account_summary, args.adaptive_protocol,
                           args.adaptive_amendment, args.technical_qualification)
    try:
        report = build_readiness(paths)
        write_report(args.output, report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Readiness report failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
