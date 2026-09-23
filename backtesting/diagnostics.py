"""Read-only accounting diagnosis of frozen cash-long-next-bar-v1 research."""

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

from app.market_data.datasets import load_dataset

D = Decimal
ZERO = D("0")
MIN_SIZE = "Allowed size is below the simulation minimum after rounding."


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exit_reference(trade: dict, candle) -> Decimal:
    reason = trade["exit_reason"]
    if reason in ("STOP_LOSS", "STOP_FIRST_AMBIGUOUS_BAR"):
        return D(trade["position"]["stop_price"])
    if reason in ("TAKE_PROFIT", "TAKE_PROFIT_GAP"):
        return D(trade["position"]["take_profit_price"])
    if reason == "STOP_GAP":
        return candle.open
    if reason == "END_OF_DATA":
        return candle.close
    raise ValueError("Unknown exit reason")


def decompose(trade: dict, entry_reference: Decimal, exit_reference: Decimal,
              assumptions: dict) -> dict:
    """Same recorded quantity and fills; this is not a zero-cost backtest."""
    require(assumptions["execution_model"] == "cash-long-next-bar-v1", "Unsupported execution model")
    position = trade["position"]
    require(position["direction"] == "LONG" and D(position["leverage"]) == 1, "Only cash LONG supported")
    costs = assumptions["costs"]
    fee, slip, half_spread = D(costs["fee_rate"]), D(costs["slippage_bps"]) / 10000, D(costs["spread_bps"]) / 20000
    tick = D(assumptions["price_tick"])
    quantity, entry, exit_ = D(position["quantity"]), D(position["entry_price"]), D(trade["exit_price"])

    def sell(reference):
        return (reference * (1 - slip - half_spread) / tick).to_integral_value(rounding=ROUND_FLOOR) * tick

    raw_entry = entry_reference * (1 + slip + half_spread)
    raw_exit = exit_reference * (1 - slip - half_spread)
    require(entry == (raw_entry / tick).to_integral_value(rounding=ROUND_CEILING) * tick
            and exit_ == sell(exit_reference), "Recorded fills disagree with frozen cost assumptions")
    require(D(position["entry_fee"]) == quantity * entry * fee
            and D(trade["exit_fee"]) == quantity * exit_ * fee, "Recorded fees disagree with assumptions")
    fees = D(position["entry_fee"]) + D(trade["exit_fee"])
    gross = (exit_reference - entry_reference) * quantity
    spread = (entry_reference + exit_reference) * quantity * half_spread
    slippage = (entry_reference + exit_reference) * quantity * slip
    rounding = ((entry - raw_entry) + (raw_exit - exit_)) * quantity
    net = (exit_ - entry) * quantity - fees
    require(abs(gross - spread - slippage - rounding - fees - net) <= D("1e-18"), "Accounting does not reconcile")
    target = position["take_profit_price"]
    target_net = None if target is None else quantity * (sell(D(target)) * (1 - fee) - entry * (1 + fee))
    stop_net = quantity * (sell(D(position["stop_price"])) * (1 - fee) - entry * (1 + fee))
    opened, closed = datetime.fromisoformat(position["opened_at"]), datetime.fromisoformat(trade["closed_at"])
    duration = closed - opened
    require(duration.total_seconds() >= 0, "Trade closed before entry")
    minutes = (D(duration.days * 86400 + duration.seconds) + D(duration.microseconds) / 1000000) / 60
    return {"trade_id": trade["id"], "opened_at": opened.isoformat(), "closed_at": closed.isoformat(),
            "exit_reason": trade["exit_reason"], "quantity": quantity, "entry_reference": entry_reference,
            "exit_reference": exit_reference, "entry_fill": entry, "exit_fill": exit_,
            "reference_gross_eur": gross, "spread_eur": spread, "slippage_eur": slippage,
            "rounding_eur": rounding, "fees_eur": fees, "net_eur": net,
            "target_net_at_entry_eur": target_net,
            "net_reward_risk_at_entry": None if target_net is None or stop_net >= 0 else target_net / -stop_net,
            "holding_minutes": minutes}


def diagnose(research_dir: Path, dataset: Path, output: Path) -> dict:
    source_paths = [research_dir / name for name in ("protocol.json", "results.json", "research.sqlite3")]
    source_hashes = {path.name: digest(path) for path in source_paths}
    protocol = json.loads(source_paths[0].read_text())
    results = json.loads(source_paths[1].read_text())
    require(results["protocol_sha256"] == source_hashes["protocol.json"], "Protocol hash mismatch")
    require(protocol["protocol_version"] == "fixed-hypothesis-v1" and protocol["timeframe"] == "15m",
            "Unsupported research protocol")
    candles, manifest = load_dataset(dataset)
    require(manifest["sha256"]["candles.csv"] == protocol["input_sha256"], "Dataset differs from original research")
    by_open = {c.timestamp: c for c in candles}
    summaries, ledger = [], []
    # Do not instantiate Repository: its constructor can migrate/write the source.
    with closing(sqlite3.connect(source_paths[2].resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")  # All reads use one SQLite snapshot.
        require(db.execute("PRAGMA user_version").fetchone()[0] in (2, 3), "Unsupported database schema")
        for run in results["runs"]:
            session = run["session_id"]
            saved = db.execute("SELECT * FROM backtest_results WHERE session_id=?", (session,)).fetchone()
            require(saved is not None, "Missing backtest result")
            assumptions = json.loads(saved["assumptions"])
            require(assumptions["protocol_sha256"] == source_hashes["protocol.json"]
                    and assumptions["input_sha256"] == protocol["input_sha256"]
                    and assumptions["period"] == run["period"] and assumptions["cost_scenario"] == run["cost_scenario"]
                    and assumptions["costs"] == protocol["costs"][run["cost_scenario"]], "Run provenance mismatch")
            require(json.loads(saved["payload"])["performance"] == run["performance"], "Stored performance mismatch")
            signals, approved, rejected = [], {}, Counter()
            for record in db.execute("SELECT payload,risk_decision FROM signals WHERE session_id=? ORDER BY rowid", (session,)):
                signal, decision = json.loads(record["payload"]), json.loads(record["risk_decision"])
                if signal["direction"] != "LONG":
                    continue
                signals.append((signal, decision))
                if decision["allowed"]:
                    require(signal["timestamp"] not in approved, "Duplicate approved entry timestamp")
                    approved[signal["timestamp"]] = (signal, decision)
                else:
                    rejected[decision["reasons"][0]] += 1
            require(len(signals) == run["long_signals"] and len(approved) == run["approved_entries"]
                    and dict(rejected) == run["rejected_entry_reasons"], "Signal counts mismatch")
            trades = []
            for record in db.execute("SELECT payload,net_pnl FROM trades WHERE session_id=? ORDER BY timestamp", (session,)):
                trade = json.loads(record["payload"])
                opened, closed = (datetime.fromisoformat(trade["position"]["opened_at"]),
                                  datetime.fromisoformat(trade["closed_at"]))
                entry_bar = by_open[opened]
                exit_bar = by_open[closed.replace(minute=closed.minute // 15 * 15, second=0, microsecond=0)]
                row = decompose(trade, entry_bar.open, exit_reference(trade, exit_bar), assumptions)
                require(row["net_eur"] == D(record["net_pnl"]), "Trade P&L mismatch")
                signal, decision = approved.pop(opened.isoformat())
                require(D(decision["quantity"]) == row["quantity"], "Approved quantity mismatch")
                row.update(period=run["period"], cost_scenario=run["cost_scenario"], session_id=session,
                           entry_reasons=" | ".join(signal["reasons"]))
                trades.append(row)
            require(not approved, "Approved entries are missing closed trades")
            totals = {key: sum((t[key] for t in trades), ZERO) for key in
                      ("reference_gross_eur", "spread_eur", "slippage_eur", "rounding_eur", "fees_eur", "net_eur")}
            performance = run["performance"]
            require(len(trades) == performance["trades"] and totals["net_eur"] == D(performance["net_profit"])
                    and totals["fees_eur"] == D(performance["fees"]), "Trade totals mismatch")
            account = db.execute("SELECT initial_capital FROM sessions WHERE id=?", (session,)).fetchone()
            equity = [D(r[0]) for r in db.execute("SELECT value FROM equity WHERE session_id=? ORDER BY id", (session,))]
            require(bool(equity) and equity[-1] == D(account[0]) + totals["net_eur"], "Final equity mismatch")
            peak = max(D(account[0]), *equity)
            last_close = max((t["closed_at"] for t in trades), default=None)
            after_last = [(s, d) for s, d in signals if last_close and datetime.fromisoformat(s["timestamp"]) > datetime.fromisoformat(last_close)]
            summary = {"period": run["period"], "cost_scenario": run["cost_scenario"], "session_id": session,
                       "start": run["start"], "end": run["end"], "initial_capital": D(account[0]),
                       "trades": len(trades), **totals,
                       "exit_counts": dict(Counter(t["exit_reason"] for t in trades)),
                       "gross_winners_turned_net_losses": sum(t["reference_gross_eur"] > 0 and t["net_eur"] < 0 for t in trades),
                       "target_exits": sum(t["exit_reason"].startswith("TAKE_PROFIT") for t in trades),
                       "target_exits_net_losses": sum(t["exit_reason"].startswith("TAKE_PROFIT") and t["net_eur"] < 0 for t in trades),
                       "entries_with_nonpositive_net_target": sum(t["target_net_at_entry_eur"] is not None and t["target_net_at_entry_eur"] <= 0 for t in trades),
                       "mean_holding_minutes": sum((t["holding_minutes"] for t in trades), ZERO) / len(trades) if trades else None,
                       "rejected_entry_reasons": dict(rejected), "last_close": last_close,
                       "signals_after_last_close": len(after_last),
                       "min_size_rejections_after_last_close": sum(not d["allowed"] and d["reasons"][0] == MIN_SIZE for _, d in after_last),
                       "remaining_drawdown_budget_eur": peak * D(assumptions["risk"]["max_drawdown"]) - (peak - equity[-1])}
            summaries.append(summary)
            ledger.extend(trades)
    require(all(digest(p) == source_hashes[p.name] for p in source_paths), "Source changed during diagnosis")
    report = {"diagnostic_version": "trade-cost-accounting-v1", "source_sha256": source_hashes,
              "input_sha256": protocol["input_sha256"], "runs": summaries,
              "note": "Accounting decomposition of recorded trades, not a zero-cost rerun or an independent validation."}
    output.mkdir(parents=True, exist_ok=False)
    (output / "summary.json").write_text(json.dumps(report, default=str, indent=2) + "\n", encoding="utf-8")
    fields = ["period", "cost_scenario", "session_id", "trade_id", "opened_at", "closed_at", "exit_reason", "quantity",
              "entry_reference", "exit_reference", "entry_fill", "exit_fill", "reference_gross_eur", "spread_eur",
              "slippage_eur", "rounding_eur", "fees_eur", "net_eur", "target_net_at_entry_eur",
              "net_reward_risk_at_entry", "holding_minutes", "entry_reasons"]
    with (output / "trades.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ledger)
    (output / "report.md").write_text(render_report(summaries), encoding="utf-8")
    return report


def render_report(runs: list[dict]) -> str:
    lines = ["# Diagnose der unveränderten Forschungsstrategie", "",
             "Alle Beträge in EUR. Zeiträume und Startkapital stehen unten je Lauf; Zeitgrenzen sind UTC, Ende exklusiv.",
             "Die ursprünglichen Simulationen und Strategieparameter wurden nicht verändert.", "",
             "| Zeitraum / Kosten | Trades | Kursbewegung brutto | Spread | Slippage | Rundung | Gebühren | Netto |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in runs:
        values = " | ".join(f"{r[k]:.4f}" for k in ("reference_gross_eur", "spread_eur", "slippage_eur", "rounding_eur", "fees_eur", "net_eur"))
        lines.append(f"| {r['period']} / {r['cost_scenario']} | {r['trades']} | {values} |")
    lines += ["", "Kursbewegung brutto minus Spread, Slippage, Rundung und Gebühren ergibt Netto. Die Zerlegung hält",
              "ausgeführte Trades und Mengen fest. Sie ist **kein kostenfreier Gegen-Backtest**: Andere Kosten würden",
              "Positionsgrößen, Freigaben und den Zeitpunkt der Risikoerschöpfung verändern.", "",
              "## Kursziele und Verluste", "",
              "| Zeitraum / Kosten | Ziel erreicht | Davon netto negativ | Schon beim Einstieg Ziel netto ≤ 0 | Bruttogewinn → Nettoverlust |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for r in runs:
        lines.append(f"| {r['period']} / {r['cost_scenario']} | {r['target_exits']} | {r['target_exits_net_losses']} | "
                     f"{r['entries_with_nonpositive_net_target']} | {r['gross_winners_turned_net_losses']} |")
    lines += ["", "Das feste Preisziel von zweimal dem ATR-Stop-Abstand ist kein Netto-Chance-Risiko-Verhältnis von 2:1.",
              "Das Nettoziel berücksichtigt hier den tatsächlichen Einstieg, beide Gebühren und den modellierten Verkauf am Ziel.",
              "Im Trade-Journal stehen außerdem das Netto-Chance-Risiko-Verhältnis beim Einstieg und die vollständigen Signalgründe.", "",
              "## Ausstiege und abgelehnte Signale", ""]
    for r in runs:
        lines += [f"### {r['period']} / {r['cost_scenario']}", "",
                  f"- Zeitraum: {r['start']} bis {r['end']}; Startkapital: {r['initial_capital']:.2f} EUR.",
                  f"- Ausstiege: {json.dumps(r['exit_counts'], ensure_ascii=False)}.",
                  f"- Letzter Ausstieg (UTC): {r['last_close'] or 'keine Trades'}.",
                  f"- Verbleibendes Drawdown-Budget am Ende: {r['remaining_drawdown_budget_eur']:.10f} EUR.",
                  f"- Danach {r['signals_after_last_close']} LONG-Signale; davon {r['min_size_rejections_after_last_close']} wegen Mindestgröße abgelehnt."]
        for reason, count in r["rejected_entry_reasons"].items():
            lines.append(f"- Ablehnung insgesamt: {count} × {reason}")
        lines.append("")
    lines += ["Die Mindestgrößen-Ablehnung ist kein ausgelöster Drawdown-Schalter. Mehrere Grenzen bestimmen die Größe;",
              "frühere Ablehnungen werden hier nicht pauschal einer einzelnen Risikogrenze zugeschrieben.", "",
              "## Einordnung", "",
              "Die Kosten belasten diese Trades deutlich. Eine positive Bruttozerlegung allein bestätigt keine handelbare Strategie.",
              "Ein bereits negatives Bruttoergebnis lässt sich nicht allein durch geringere Kosten erklären.",
              "Die vier Läufe sind wegen unterschiedlicher Mengen und Trade-Auswahl keine identischen Vergleichsportfolios.",
              "Intrabar-Zeitstempel sind Modellkonventionen; die Haltedauer ist keine tickgenaue Messung.",
              "Es werden keine einzelnen Indikatoren als Ursache bewiesen und keine Parameter anhand dieser Daten optimiert.",
              "Der Holdout bleibt gesehen. Änderungen brauchen ein neues vorab festgelegtes Protokoll und unabhängige Daten.", "",
              "Dateien: trades.csv (alle Trades), summary.json (exakte Summen und Quellen-Prüfsummen).",
              "Die Quelldatenbank wurde ausschließlich lesend geöffnet; Summen, Fills, Gebühren, Signale und Herkunft wurden abgeglichen."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only diagnosis of frozen research trades and costs")
    parser.add_argument("--research", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = diagnose(args.research, args.dataset, args.output)
        print(f"Diagnosed {sum(r['trades'] for r in report['runs'])} trades; report: {args.output / 'report.md'}")
        return 0
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError, ArithmeticError) as exc:
        print(f"Diagnosis failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
