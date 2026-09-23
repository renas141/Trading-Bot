"""Small SQLite repository; money is encoded as decimal strings, never floats."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.domain import TradingMode
from app.execution.models import Order
from app.portfolio.models import Position, Trade
from app.risk.risk_manager import RiskDecision
from app.strategies.models import Signal

SCHEMA_VERSION = 3
TABLES = frozenset({"sessions", "signals", "orders", "positions", "trades", "equity", "backtest_results", "paper_checkpoints"})


def _encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _json(value: Any) -> str:
    return json.dumps(value, default=_encode, ensure_ascii=False, allow_nan=False)


class Repository:
    """One connection per application session; not a concurrent trading database."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self._savepoint_number = 0
        try:
            self.connection.execute("PRAGMA foreign_keys = ON")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, SCHEMA_VERSION):
                raise ValueError("Unsupported database schema version")
            self.connection.executescript("""
                BEGIN;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, mode TEXT NOT NULL,
                    started_at TEXT NOT NULL, ended_at TEXT,
                    status TEXT NOT NULL, initial_capital TEXT NOT NULL,
                    symbol TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    timestamp TEXT NOT NULL, symbol TEXT NOT NULL,
                    payload TEXT NOT NULL, risk_decision TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS positions (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    symbol TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    position_id TEXT NOT NULL REFERENCES positions(id),
                    timestamp TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    position_id TEXT NOT NULL UNIQUE REFERENCES positions(id),
                    timestamp TEXT NOT NULL, net_pnl TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS equity (
                    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    timestamp TEXT NOT NULL, value TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS signals_session ON signals(session_id, timestamp);
                CREATE INDEX IF NOT EXISTS orders_session ON orders(session_id, timestamp);
                CREATE TABLE IF NOT EXISTS backtest_results (
                    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
                    payload TEXT NOT NULL, assumptions TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_checkpoints (
                    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
                    revision INTEGER NOT NULL, settings_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL
                );
                PRAGMA user_version = 3;
                COMMIT;
            """)
        except Exception:
            self.connection.close()
            raise

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *exc: object) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self):
        """Nestable savepoints: an outer unit of work owns the final commit."""
        self._savepoint_number += 1
        name = f"unit_{self._savepoint_number}"
        self.connection.execute(f"SAVEPOINT {name}")
        try:
            yield
            self.connection.execute(f"RELEASE SAVEPOINT {name}")
        except BaseException:
            self.connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
            self.connection.execute(f"RELEASE SAVEPOINT {name}")
            raise

    def start_session(self, mode: TradingMode, capital: Decimal, symbol: str) -> str:
        if mode not in (TradingMode.PAPER, TradingMode.BACKTEST):
            raise ValueError("Only simulation sessions are supported")
        session_id = str(uuid4())
        with self.transaction():
            self.connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, NULL, 'RUNNING', ?, ?)",
                (session_id, mode.value, datetime.now(timezone.utc).isoformat(), str(capital), symbol),
            )
        return session_id

    def finish_session(self, session_id: str, *, failed: bool = False) -> None:
        with self.transaction():
            self.connection.execute(
                "UPDATE sessions SET ended_at=?, status=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), "FAILED" if failed else "STOPPED", session_id),
            )

    def record_signal(self, session_id: str, signal: Signal, decision: RiskDecision) -> None:
        with self.transaction():
            self.connection.execute("INSERT INTO signals VALUES (?, ?, ?, ?, ?, ?)",
                                    (str(uuid4()), session_id, signal.timestamp.isoformat(),
                                     signal.symbol, _json(signal), _json(decision)))

    def record_open(self, session_id: str, position: Position, order: Order) -> None:
        """Position and entry order either both persist or neither does."""
        with self.transaction():
            self.connection.execute("INSERT INTO positions VALUES (?, ?, ?, 'OPEN', ?)",
                                    (position.id, session_id, position.symbol, _json(position)))
            self._insert_order(session_id, order)

    def record_close(self, session_id: str, trade: Trade, order: Order) -> None:
        """Exit order, trade and position status share one transaction."""
        with self.transaction():
            cursor = self.connection.execute(
                "UPDATE positions SET status='CLOSED' WHERE id=? AND session_id=? AND status='OPEN'",
                (trade.position.id, session_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Position is not open in this session")
            self._insert_order(session_id, order)
            self.connection.execute("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?)",
                                    (trade.id, session_id, trade.position.id,
                                     trade.closed_at.isoformat(), str(trade.net_pnl), _json(trade)))

    def _insert_order(self, session_id: str, order: Order) -> None:
        self.connection.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?)",
                                (order.id, session_id, order.position_id,
                                 order.timestamp.isoformat(), _json(order)))

    def record_equity(self, session_id: str, timestamp: datetime, value: Decimal) -> None:
        with self.transaction():
            self.connection.execute("INSERT INTO equity (session_id, timestamp, value) VALUES (?, ?, ?)",
                                    (session_id, timestamp.isoformat(), str(value)))

    def records(self, table: str, session_id: str) -> list[dict[str, Any]]:
        """Read facade for tests and a future local dashboard."""
        if table not in TABLES:
            raise ValueError("Unknown table")
        column = "id" if table == "sessions" else "session_id"
        rows = self.connection.execute(f"SELECT * FROM {table} WHERE {column}=? ORDER BY rowid", (session_id,))
        return [dict(row) for row in rows]

    def record_backtest_result(self, session_id: str, result: Any, assumptions: dict[str, Any]) -> None:
        with self.transaction():
            self.connection.execute("INSERT INTO backtest_results VALUES (?, ?, ?)",
                                    (session_id, _json(result), _json(assumptions)))
