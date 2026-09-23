"""Read-only presentation of completed research artifacts; never starts a broker."""

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

PAGE_SIZE = 12


def identifier(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compress_equity(rows: list[dict], buckets: int = 180) -> list[dict]:
    """Keep first/last and each bucket's extremes; don't smooth away drawdowns."""
    if len(rows) <= buckets * 2 + 2:
        return rows
    indices = {0, len(rows) - 1}
    step = math.ceil(len(rows) / buckets)
    for start in range(0, len(rows), step):
        group = range(start, min(start + step, len(rows)))
        indices.add(min(group, key=lambda i: Decimal(rows[i]["value"])))
        indices.add(max(group, key=lambda i: Decimal(rows[i]["value"])))
    return [rows[i] for i in sorted(indices)]


class ResearchStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def contained(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("Research path escapes the configured directory")
        return resolved

    def catalog(self) -> tuple[list[dict], dict]:
        studies, sources = [], {}
        paths = sorted(set(self.root.glob("*/results.json")) | set(self.root.glob("*/evaluation/results.json"))
                       | set(self.root.glob("*/holdout/results.json")))
        for candidate in paths:
            try:
                result_path = self.contained(candidate)
                folder = result_path.parent
                protocol_path = self.contained(folder.parent / "protocol.json" if folder.name in ("evaluation", "holdout") else folder / "protocol.json")
                database = self.contained(folder / "research.sqlite3")
                report_path = self.contained(folder / "report.md")
                result, protocol = read_json(result_path), read_json(protocol_path)
                version = protocol["protocol_version"]
                derivative_versions = {
                    "perpetual-regime-development-v1": ("Perpetual: symmetrischer Regime-Ausbruch", "Entwicklung 2023–2024"),
                    "perpetual-long-bias-development-v2": ("Perpetual: Long-only-Filter", "Entwicklung 2023–2024"),
                    "perpetual-long-bias-holdout-v1": ("Perpetual: Long-only-Holdout", "Einmaliger Holdout 2025"),
                    "perpetual-profit-protection-development-v1": ("Perpetual: Gewinnschutz", "Entwicklung 2023–2025"),
                    "perpetual-close-exit-development-v1": ("Perpetual: Zeit- und Momentum-Ausstieg", "Entwicklung 2023–2025"),
                    "perpetual-reentry-development-v1": ("Perpetual: Wiedereinstiegspause", "Entwicklung 2023–2025"),
                    "perpetual-atr-trailing-development-v1": ("Perpetual: ATR-Trailing", "Entwicklung 2023–2025"),
                    "perpetual-donchian-trend-development-v1": ("Perpetual: klassischer Donchian-Trend", "Entwicklung 2023–2025"),
                }
                if version in derivative_versions:
                    receipt = read_json(self.contained(folder / "completion.json"))
                    if (not report_path.is_file()
                            or hashlib.sha256(protocol_path.read_bytes()).hexdigest() != result["protocol_sha256"]
                            or receipt["results_sha256"] != hashlib.sha256(result_path.read_bytes()).hexdigest()):
                        raise ValueError("Incomplete derivative research")
                    title, period = derivative_versions[version]
                    assessment = result["assessment"]
                    passed = assessment.get("holdout_passed", assessment.get("screen_passed"))
                    study_id = identifier(str(candidate.relative_to(self.root)))
                    selected = assessment.get("selected")
                    finding = (f"Auswahl: {selected}." if selected else
                               "Prüfung bestanden." if passed else "Prüfung nicht bestanden; keine Handelsfreigabe.")
                    studies.append({"id": study_id, "title": title,
                                    "subtitle": f"{title} · {period}", "created_at": protocol["created_at"],
                                    "report_only": True, "groups": [], "timeframe_label": "4 Stunden",
                                    "quote_label": "USD",
                                    "finding_note": finding, "screen_passed": passed,
                                    "period_label": period})
                    sources[study_id] = {"report": report_path}
                    continue
                if (not database.is_file() or not report_path.is_file()
                        or hashlib.sha256(protocol_path.read_bytes()).hexdigest() != result["protocol_sha256"]):
                    raise ValueError("Incomplete research or protocol mismatch")
                if version not in ("fixed-hypothesis-v1", "net-reward-segmented-v2", "slow-timeframe-gated-v1", "slow-observed-gated-v2", "slow-candidates-development-v1", "bitvavo-transfer-development-v1", "bitvavo-trailing-development-v1"):
                    continue
                trailing = version == "bitvavo-trailing-development-v1"
                venue = version in ("bitvavo-transfer-development-v1", "bitvavo-trailing-development-v1")
                candidates = version == "slow-candidates-development-v1"
                observed = version == "slow-observed-gated-v2"
                annual = version in ("slow-timeframe-gated-v1", "slow-observed-gated-v2", "slow-candidates-development-v1", "bitvavo-transfer-development-v1", "bitvavo-trailing-development-v1")
                segmented = version != "fixed-hypothesis-v1"
                if annual:
                    receipt = read_json(self.contained(folder / "completion.json"))
                    if receipt["results_sha256"] != hashlib.sha256(result_path.read_bytes()).hexdigest():
                        raise ValueError("Research completion receipt mismatch")
                study_id = identifier(str(candidate.relative_to(self.root)))
                ranges = result["segments"] if segmented else result["runs"]
                first = min(datetime.fromisoformat(r["start"]) for r in ranges)
                last = max(datetime.fromisoformat(r["end"]) for r in ranges) - timedelta(microseconds=1)
                quarter = (first.month - 1) // 3 + 1
                period = f"Q{quarter} {first.year}" if first.year == last.year and quarter == (last.month - 1) // 3 + 1 else f"{first:%m/%Y}–{last:%m/%Y}"
                note = (result["holdout_note"] + " Jedes Jahr startet mit eigenem Konto; Jahresergebnisse nicht addieren." if annual else
                        "Datenlücke am 04.02.: Beide Abschnitte starten mit eigenem Konto. Ergebnisse nicht zu einer Quartalsrendite addieren. Der Zeitraum ist jetzt gesehen." if segmented else
                        "Entwicklung und ehemaliger Holdout starten mit getrennten Konten. Die Daten sind bereits gesehen und stehen nicht mehr für einen unberührten Test zur Verfügung.")
                cost_names = ({"base": "Altes Kostenmodell · 0,26 %", "double_costs": "Altes Modell doppelt · 0,52 %",
                               "kraken_current": "Kraken Einstiegstarif · 0,80 %", "kraken_stress": "Kraken-Stress · 1,60 %"} if observed else
                              {"base": "Normale Kosten", "double_costs": "Doppelte Kosten"})
                if candidates:
                    cost_names = {"kraken_current": "Kraken Einstiegstarif · 0,80 %", "kraken_stress": "Kraken-Stress · 1,60 %",
                                  "low_cost_sensitivity": "Günstigeres Modell · 0,25 %", "low_cost_stress": "Günstigeres Modell doppelt · 0,50 %"}
                    note += " 2023/2024 sind bekannte Entwicklungsdaten. Günstigere Gebühren auf Kraken-Kursen sind kein Bitvavo-Backtest."
                study = {"id": study_id, "title": "Ausbruch auf 4 Stunden" if annual else "Nettoziel-Filter" if segmented else "Trend & Ausbruch",
                         "subtitle": f"{'Dritte' if annual else 'Zweite' if segmented else 'Erste'} Hypothese · {period}" + (" · geprüfte Pausen" if observed else ""),
                         "created_at": protocol["created_at"], "segmented": segmented,
                         "cost_names": cost_names, "default_cost": "kraken_current" if observed or candidates else "base",
                         "timeframe_label": "4 Stunden" if annual else "15 Minuten", "finding_note": note,
                         "screen_passed": result.get("screen_passed"), "groups": []}
                if candidates:
                    study["title"] = "Langsame Strategiekandidaten"
                    study["subtitle"] = f"Langsame Kandidaten · {'Holdout' if result['phase'] == 'holdout' else 'Entwicklung'} · {period}"
                if venue:
                    study["title"] = "Bitvavo: drei feste Varianten"
                    study["subtitle"] = f"Eigene Bitvavo-Kurse · Entwicklung · {period}"
                    study["cost_names"] = {"bitvavo_current": "Bitvavo Taker · 0,25 %", "bitvavo_stress": "Bitvavo-Stress · 0,50 %"}
                    study["default_cost"] = "bitvavo_current"
                    study["finding_title"] = "Broker-Vergleich · noch keine Handelsfreigabe"
                    study["finding_note"] += " Aktuelle Gebühren und Handelsgrenzen auf historischen Kursen; Spread und Slippage sind Modellannahmen."
                if trailing:
                    study["title"] = "Bitvavo: nachgezogener Stop"
                    study["subtitle"] = f"Ausstiegsvergleich · Entwicklung · {period}"
                    study["finding_title"] = "Vorab festgelegte Sichtung bestanden" if result["screen_passed"] else "Vorab festgelegte Sichtung nicht bestanden"
                if segmented:
                    groups = result["segments"]
                else:
                    groups = [{"name": period, "runs": [r for r in result["runs"] if r["period"] == period]}
                              for period in dict.fromkeys(r["period"] for r in result["runs"])]
                for group in groups:
                    start, end = (group["start"], group["end"]) if segmented else (group["runs"][0]["start"], group["runs"][0]["end"])
                    public_group = {"id": group["name"], "start": start, "end": end,
                                    "benchmarks": group.get("benchmarks", {}), "runs": []}
                    for run in group["runs"]:
                        run_id = identifier(study_id + run["session_id"])
                        public = {"id": run_id, "variant": run.get("variant", "original"),
                                  "cost_scenario": run["cost_scenario"], "performance": run["performance"],
                                  "long_signals": run["long_signals"], "approved_entries": run["approved_entries"],
                                  "rejected_entry_reasons": run["rejected_entry_reasons"]}
                        public_group["runs"].append(public)
                        sources[run_id] = {"database": database, "session": run["session_id"], "public": public,
                                           "start": start, "end": end, "study": study_id}
                    study["groups"].append(public_group)
                studies.append(study)
                sources[study_id] = {"report": report_path}
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                # Incomplete or invalid experiments are visible as unavailable, never as zero returns.
                studies.append({"id": identifier(str(candidate)), "unavailable": True,
                                "title": candidate.parent.name, "error": "Auswertung unvollständig oder nicht lesbar.",
                                "created_at": "", "groups": []})
        for candidate in sorted(self.root.glob("*/blocked.json")):
            try:
                blocked_path = self.contained(candidate)
                folder = blocked_path.parent
                protocol_path = self.contained(folder / "protocol.json")
                report_path = self.contained(folder / "report.md")
                blocked, protocol = read_json(blocked_path), read_json(protocol_path)
                if (blocked.get("schema_version") != 1 or blocked.get("status") != "blocked_data_quality"
                        or protocol.get("protocol_version") != "slow-timeframe-gated-v1"
                        or blocked["protocol_sha256"] != hashlib.sha256(protocol_path.read_bytes()).hexdigest()
                        or not report_path.is_file() or (folder / "evaluation").exists()):
                    raise ValueError("Invalid blocked experiment or conflicting evaluation")
                study_id = identifier(str(candidate.relative_to(self.root)))
                review_path = self.contained(folder / "source-review.json")
                if review_path.is_file():
                    review = read_json(review_path)
                    if review["blocked_sha256"] != hashlib.sha256(blocked_path.read_bytes()).hexdigest():
                        raise ValueError("Follow-up does not match original quality report")
                    report_path = self.contained(folder / "source-review.md")
                    if hashlib.sha256(report_path.read_bytes()).hexdigest() != review["report_sha256"]:
                        raise ValueError("Follow-up report changed")
                    blocked["message"] = review["message"]
                studies.append({"id": study_id, "title": blocked["title"], "blocked": True,
                                "subtitle": "Ursprünglicher 4h-Plan · gesperrt", "groups": [],
                                "created_at": protocol["created_at"], "timeframe_label": "4 Stunden",
                                "finding_note": blocked["message"], "screen_passed": None,
                                "period_label": "Geplant: 2023–2024 prüfen · 2025 zurückhalten"})
                sources[study_id] = {"report": report_path}
            except (OSError, ValueError, KeyError, TypeError):
                studies.append({"id": identifier(str(candidate)), "unavailable": True,
                                "title": candidate.parent.name, "created_at": "", "groups": [],
                                "error": "Datenprüfungsbericht unvollständig oder widersprüchlich."})
        studies.sort(key=lambda item: item["created_at"], reverse=True)
        return studies, sources

    @contextmanager
    def connection(self, run_id: str):
        _, sources = self.catalog()
        source = sources.get(run_id)
        if source is None or "database" not in source:
            raise KeyError("Unknown run")
        db = sqlite3.connect(self.contained(source["database"]).as_uri() + "?mode=ro", uri=True)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA user_version").fetchone()[0] not in (2, 3):
                raise ValueError("Unsupported research schema")
            session = db.execute("SELECT * FROM sessions WHERE id=?", (source["session"],)).fetchone()
            stored = db.execute("SELECT payload FROM backtest_results WHERE session_id=?", (source["session"],)).fetchone()
            if (session is None or session["mode"] != "BACKTEST" or session["status"] != "STOPPED"
                    or stored is None or json.loads(stored["payload"])["performance"] != source["public"]["performance"]):
                raise ValueError("Research database and result disagree")
            yield db, source, dict(session)
        finally:
            db.close()

    def run(self, run_id: str) -> dict:
        with self.connection(run_id) as (db, source, session):
            rows = [dict(row) for row in db.execute("SELECT timestamp,value FROM equity WHERE session_id=? ORDER BY id", (source["session"],))]
            if not rows:
                raise ValueError("Missing equity observations")
            expected = Decimal(session["initial_capital"]) + Decimal(source["public"]["performance"]["net_profit"])
            if Decimal(rows[-1]["value"]) != expected:
                raise ValueError("Final equity differs from recorded performance")
            rows.insert(0, {"timestamp": source["start"], "value": session["initial_capital"]})
            counts = {row["direction"]: row["count"] for row in db.execute(
                "SELECT json_extract(payload,'$.direction') AS direction,COUNT(*) AS count FROM signals WHERE session_id=? GROUP BY direction", (source["session"],))}
            return {**source["public"], "start": source["start"], "end": source["end"],
                    "initial_capital": session["initial_capital"], "final_equity": str(expected),
                    "equity": compress_equity(rows), "observation_count": len(rows), "signal_counts": counts,
                    "study_id": source["study"]}

    def trades(self, run_id: str, page: int, outcome: str) -> dict:
        if outcome not in ("all", "win", "loss") or page < 0 or page > 100000:
            raise ValueError("Invalid trade filter")
        with self.connection(run_id) as (db, source, _):
            # Decimal comparisons stay in Python, avoiding SQLite float coercion.
            rows = [dict(r) for r in db.execute("SELECT payload,net_pnl FROM trades WHERE session_id=? ORDER BY timestamp DESC", (source["session"],))]
            selected = [r for r in rows if outcome == "all" or (Decimal(r["net_pnl"]) > 0 if outcome == "win" else Decimal(r["net_pnl"]) < 0)]
            items = []
            for row in selected[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
                trade = json.loads(row["payload"])
                orders = [json.loads(r[0]) for r in db.execute("SELECT payload FROM orders WHERE session_id=? AND position_id=? ORDER BY rowid", (source["session"], trade["position"]["id"]))]
                entry = next((o for o in orders if o["side"] == "BUY"), None)
                updates = []
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='exit_updates'").fetchone():
                    updates = [dict(r) for r in db.execute("SELECT observed_close_at,effective_from,previous_stop,new_stop,reason FROM exit_updates WHERE session_id=? AND position_id=? ORDER BY id", (source["session"], trade["position"]["id"]))]
                items.append({**trade, "stop_updates": updates, "net_pnl": row["net_pnl"], "fees": str(Decimal(trade["position"]["entry_fee"]) + Decimal(trade["exit_fee"])),
                              "entry_reasons": entry["reasons"] if entry else []})
            return {"items": items, "total": len(selected), "page": page, "page_size": PAGE_SIZE}

    def signals(self, run_id: str, page: int, decision: str, direction: str) -> dict:
        if decision not in ("all", "allowed", "denied") or direction not in ("ALL", "LONG", "HOLD") or page < 0 or page > 100000:
            raise ValueError("Invalid signal filter")
        with self.connection(run_id) as (db, source, _):
            where, params = "session_id=?", [source["session"]]
            if direction != "ALL":
                where += " AND json_extract(payload,'$.direction')=?"
                params.append(direction)
            if decision != "all":
                where += " AND json_extract(risk_decision,'$.allowed')=?"
                params.append(int(decision == "allowed"))
            total = db.execute("SELECT COUNT(*) FROM signals WHERE " + where, params).fetchone()[0]
            records = db.execute("SELECT payload,risk_decision FROM signals WHERE " + where + " ORDER BY timestamp DESC,rowid DESC LIMIT ? OFFSET ?", (*params, PAGE_SIZE, page * PAGE_SIZE))
            return {"items": [{"signal": json.loads(r[0]), "decision": json.loads(r[1])} for r in records],
                    "total": total, "page": page, "page_size": PAGE_SIZE}

    def report(self, study_id: str) -> bytes:
        _, sources = self.catalog()
        source = sources.get(study_id)
        if source is None or "report" not in source:
            raise KeyError("Unknown report")
        return self.contained(source["report"]).read_bytes()
