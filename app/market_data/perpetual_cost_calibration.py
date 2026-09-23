"""Gate a completed public observation before proposing replay cost inputs."""

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.market_data.datasets import sha256
from app.market_data.quote_monitor import publish_summary


MINIMUM_SUCCESSES = 360
MINIMUM_DURATION_SECONDS = 6 * 60 * 60
MAXIMUM_FAILURE_FRACTION = Decimal("0.05")
MAXIMUM_BUCKET_AGE_SECONDS = Decimal("180")
MAXIMUM_REQUEST_SECONDS = Decimal("20")
MAXIMUM_SUCCESS_GAP_SECONDS = Decimal("180")
TARGET_NOTIONAL = "10k"


def _decimal(value, name, *, nonnegative=False):
    try:
        number = Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        raise ValueError(f"Invalid {name}") from None
    if not number.is_finite() or (nonnegative and number < 0):
        raise ValueError(f"Invalid {name}")
    return number


def calibrate(raw: bytes) -> dict:
    """Return a conservative candidate, or reject inadequate observation evidence."""
    try:
        report = json.loads(raw)
        configuration = report["configuration"]
        attempts = report["attempts"]
        successful = report["successful"]
        failed = report["failed"]
        first = datetime.fromisoformat(report["first_request"])
        last = datetime.fromisoformat(report["last_request"])
        if (report["schema_version"] != 1 or report["provider"] != "Kraken Futures"
                or report["market"] != "PF_XBTUSD" or report["status"] != "completed"
                or report["raw_integrity_checked"] is not True
                or report["exchange_analytics_timestamp_available"] is not True
                or type(attempts) is not int or type(successful) is not int or type(failed) is not int
                or attempts != successful + failed or successful < MINIMUM_SUCCESSES
                or first.tzinfo is None or last.tzinfo is None
                or (last - first).total_seconds() < MINIMUM_DURATION_SECONDS
                or configuration["market"] != "PF_XBTUSD"
                or configuration["analytics_interval_seconds"] != 60):
            raise ValueError("Observation has not passed the coverage and integrity gate")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ArithmeticError):
        raise ValueError("Invalid or insufficient perpetual observation summary") from None

    failure_fraction = Decimal(failed) / Decimal(attempts)
    if failure_fraction > MAXIMUM_FAILURE_FRACTION:
        raise ValueError("Perpetual observation failure rate is too high")
    request_seconds = _decimal(report["max_local_request_seconds"], "request duration", nonnegative=True)
    bucket_age = _decimal(report["max_analytics_bucket_age_seconds"], "bucket age", nonnegative=True)
    success_gap = _decimal(report["max_gap_between_successful_receipts_seconds"], "success gap", nonnegative=True)
    if (request_seconds > MAXIMUM_REQUEST_SECONDS or bucket_age > MAXIMUM_BUCKET_AGE_SECONDS
            or success_gap > MAXIMUM_SUCCESS_GAP_SECONDS):
        raise ValueError("Perpetual observation freshness gate failed")

    try:
        spread = _decimal(report["spread_bps"]["p95_nearest_rank"], "spread p95", nonnegative=True)
        buy = report["estimated_adverse_slippage_bps"]["buy"][TARGET_NOTIONAL]
        sell = report["estimated_adverse_slippage_bps"]["sell"][TARGET_NOTIONAL]
        if buy["available_samples"] < MINIMUM_SUCCESSES or sell["available_samples"] < MINIMUM_SUCCESSES:
            raise ValueError("Insufficient 10k slippage samples")
        buy_p95 = _decimal(buy["p95_nearest_rank"], "buy slippage p95", nonnegative=True)
        sell_p95 = _decimal(sell["p95_nearest_rank"], "sell slippage p95", nonnegative=True)
        funding = report["signed_relative_funding_rate"]
        if funding["positive_means_longs_pay"] is not True:
            raise ValueError("Unknown funding sign convention")
        funding_min = _decimal(funding["minimum"], "minimum funding")
        funding_max = _decimal(funding["maximum"], "maximum funding")
    except (KeyError, TypeError, ValueError, ArithmeticError):
        raise ValueError("Perpetual observation lacks usable cost distributions") from None

    adverse_hourly_funding = max(abs(funding_min), abs(funding_max))
    return {
        "schema_version": 1,
        "status": "cost_candidate_only",
        "market": "PF_XBTUSD",
        "source_summary_sha256": sha256(raw),
        "evidence": {
            "attempts": attempts,
            "successful": successful,
            "failed": failed,
            "failure_fraction": str(failure_fraction),
            "first_request": first.isoformat(),
            "last_request": last.isoformat(),
            "target_notional_usd": "10000",
        },
        "candidate": {
            "spread_bps_p95": str(spread),
            "adverse_slippage_bps_p95": str(max(buy_p95, sell_p95)),
            "buy_slippage_bps_p95": str(buy_p95),
            "sell_slippage_bps_p95": str(sell_p95),
            "adverse_funding_sensitivity_per_4h": str(adverse_hourly_funding * Decimal("4")),
            "fee_rate": None,
        },
        "activation": {
            "backtest_changed": False,
            "paper_enabled": False,
            "live_enabled": False,
        },
        "limitations": [
            "The candidate uses a short observed window and is not an execution guarantee.",
            "The 4h funding sensitivity multiplies the most adverse observed hourly snapshot by four.",
            "Trading fees require a separate verified account-tier source and are intentionally absent.",
            "This artifact proposes replay inputs only and cannot activate PAPER or LIVE trading.",
        ],
    }


def create(summary_path: Path, output_path: Path) -> dict:
    if output_path.exists():
        raise ValueError("Cost candidate output already exists")
    raw = summary_path.read_bytes()
    result = calibrate(raw)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    publish_summary(output_path, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gate observed PF_XBTUSD costs for replay research")
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = create(args.summary, args.output)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f"Cost calibration failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
