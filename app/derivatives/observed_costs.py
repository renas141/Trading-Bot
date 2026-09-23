"""Load a gated observed-cost candidate into BACKTEST settings only."""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.derivatives.settings import DerivativeSettings
from app.market_data.datasets import sha256
from app.market_data.perpetual_cost_calibration import calibrate


@dataclass(frozen=True)
class ObservedCostScenario:
    settings: DerivativeSettings
    funding_rate_per_4h: Decimal
    source_summary_sha256: str
    fee_source: str


def _nonnegative_decimal(value, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        raise ValueError(f"Invalid {name}") from None
    if not result.is_finite() or result < 0:
        raise ValueError(f"Invalid {name}")
    return result


def load_observed_cost_scenario(candidate_path: Path, summary_path: Path, *,
                                fee_rate: Decimal, fee_source: str) -> ObservedCostScenario:
    """Recompute the gate before mapping measured costs into replay settings."""
    if not isinstance(fee_rate, Decimal) or not fee_rate.is_finite() or not 0 <= fee_rate < 1:
        raise ValueError("A finite separate fee rate below one is required")
    if not isinstance(fee_source, str) or not fee_source.strip():
        raise ValueError("A fee source is required")
    try:
        summary_raw = summary_path.read_bytes()
        candidate = json.loads(candidate_path.read_bytes())
        recomputed = calibrate(summary_raw)
        if candidate != recomputed:
            raise ValueError("Cost candidate does not match the gated source summary")
        if (candidate["status"] != "cost_candidate_only"
                or candidate["source_summary_sha256"] != sha256(summary_raw)
                or candidate["evidence"]["target_notional_usd"] != "10000"
                or candidate["candidate"]["fee_rate"] is not None
                or candidate["activation"] != {
                    "backtest_changed": False, "paper_enabled": False, "live_enabled": False,
                }):
            raise ValueError("Cost candidate has unsupported provenance or activation state")
        spread = _nonnegative_decimal(candidate["candidate"]["spread_bps_p95"], "spread")
        slippage = _nonnegative_decimal(
            candidate["candidate"]["adverse_slippage_bps_p95"], "slippage",
        )
        funding = _nonnegative_decimal(
            candidate["candidate"]["adverse_funding_sensitivity_per_4h"], "funding",
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, ArithmeticError):
        raise ValueError("Invalid or unverified observed-cost candidate") from None
    settings = DerivativeSettings(
        fee_rate=fee_rate,
        spread_bps=spread,
        slippage_bps=slippage,
    )
    return ObservedCostScenario(settings, funding, sha256(summary_raw), fee_source.strip())
