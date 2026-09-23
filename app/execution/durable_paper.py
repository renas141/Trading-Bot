"""Crash-consistent PAPER broker checkpoints; no network or real orders.

A checkpoint is committed with its ledger changes. Each writer compares a revision
so an old process cannot continue spending a portfolio resumed by another process.
This restores execution/risk state only: strategy history belongs to its runner.
"""

import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from functools import wraps

from app.config.settings import Settings
from app.database.repository import Repository, _json
from app.domain import Direction, TradingMode, aware_timestamp, positive_decimal
from app.errors import SimulationError
from app.execution.costs import ExecutionCosts
from app.execution.paper_broker import PaperBroker
from app.portfolio.models import Position, Trade
from app.risk.state import RiskState
from app.risk.stop_risk import StopRiskManager


def settings_digest(settings: Settings) -> str:
    values = asdict(settings)
    for field in ("database_path", "log_directory", "log_level"):
        values.pop(field)
    return hashlib.sha256(_json(values).encode()).hexdigest()


def checkpointed(operation):
    @wraps(operation)
    def wrapped(self, *args, **kwargs):
        with self.atomic():
            result = operation(self, *args, **kwargs)
            self._persist()
            return result
    return wrapped


def _position(payload: dict) -> Position:
    values = dict(payload)
    for field in ("quantity", "entry_price", "entry_fee", "leverage", "stop_price", "take_profit_price"):
        values[field] = Decimal(values[field]) if values[field] is not None else None
    values["direction"] = Direction(values["direction"])
    values["opened_at"] = datetime.fromisoformat(values["opened_at"])
    result = Position(**values)
    if result.direction != Direction.LONG or result.leverage != 1:
        raise ValueError("Recovery supports cash-funded LONG only")
    return result


def _trade(payload: dict) -> Trade:
    values = dict(payload)
    values["position"] = _position(values["position"])
    values["closed_at"] = datetime.fromisoformat(values["closed_at"])
    values["exit_price"], values["exit_fee"] = Decimal(values["exit_price"]), Decimal(values["exit_fee"])
    return Trade(**values)


class DurablePaperBroker(PaperBroker):
    """Explicit opt-in durable simulator. BACKTEST sessions keep their existing path."""

    def __init__(self, settings: Settings, repository: Repository, session_id: str) -> None:
        if settings.mode != TradingMode.PAPER:
            raise SimulationError("Durable broker supports PAPER only")
        with repository.transaction():
            if any(repository.records(table, session_id) for table in
                   ("paper_checkpoints", "positions", "orders", "trades", "signals", "equity")):
                raise SimulationError("Existing session requires explicit resume and a valid checkpoint")
            super().__init__(settings, repository, session_id)
            self._revision = 0
            payload = self._payload()
            repository.connection.execute("INSERT INTO paper_checkpoints VALUES (?, ?, ?, ?, ?)",
                                          (session_id, 0, settings_digest(settings), payload,
                                           hashlib.sha256(payload.encode()).hexdigest()))

    def _payload(self) -> str:
        risk = self.risk_state
        return _json({
            "version": 1, "cash": self._cash, "realized_pnl": self._realized_pnl,
            "total_fees": self.total_fees, "position_ids": list(self._positions),
            "trade_ids": [t.id for t in self.trades],
            "risk": {"last_equity": risk.last_equity, "peak": risk.peak, "day_start": risk.day_start,
                     "day": risk.day.isoformat() if risk.day else None,
                     "last_timestamp": risk.last_timestamp.isoformat() if risk.last_timestamp else None,
                     "daily_halted": risk.daily_halted, "drawdown_halted": risk.drawdown_halted,
                     "kill_switch": risk.kill_switch},
        })

    @contextmanager
    def atomic(self):
        """Also usable by a runner to include signals/events in the broker commit.

        On any exception the caller must consider the entire operation rejected;
        both database and this broker's in-memory state are rolled back.
        """
        state = (self._cash, self._positions.copy(), self._realized_pnl, self.trades.copy(),
                 self.total_fees, deepcopy(self.risk_state), self._revision)
        try:
            with self.repository.transaction():
                self._check_current()
                yield
        except BaseException:
            (self._cash, self._positions, self._realized_pnl, self.trades,
             self.total_fees, self.risk_state, self._revision) = state
            raise

    def _check_current(self):
        session = self.repository.records("sessions", self.session_id)
        checkpoints = self.repository.records("paper_checkpoints", self.session_id)
        if (len(session) != 1 or session[0]["status"] != "RUNNING"
                or len(checkpoints) != 1 or checkpoints[0]["revision"] != self._revision
                or checkpoints[0]["settings_sha256"] != settings_digest(self.settings)):
            raise SimulationError("Session is stopped, changed or owned by a newer broker state; resume required")
        if type(self.risk_guard) is not StopRiskManager:
            raise SimulationError("Durable PAPER requires the recorded central stop-risk policy")

    def _persist(self):
        payload = self._payload()
        cursor = self.repository.connection.execute(
            "UPDATE paper_checkpoints SET revision=revision+1, payload=?, payload_sha256=? "
            "WHERE session_id=? AND revision=?",
            (payload, hashlib.sha256(payload.encode()).hexdigest(), self.session_id, self._revision))
        if cursor.rowcount != 1:
            raise SimulationError("Stale paper checkpoint; no changes committed")
        self._revision += 1

    @checkpointed
    def mark(self, price, timestamp):
        return super().mark(price, timestamp)

    @checkpointed
    def open_position(self, signal, decision, price, timestamp=None):
        return super().open_position(signal, decision, price, timestamp)

    @checkpointed
    def close_position(self, position_id, price, timestamp, reason):
        return super().close_position(position_id, price, timestamp, reason)

    @checkpointed
    def trip_kill_switch(self):
        super().trip_kill_switch()

    @classmethod
    def resume(cls, settings: Settings, repository: Repository, session_id: str):
        if settings.mode != TradingMode.PAPER:
            raise SimulationError("Only PAPER sessions can resume")
        try:
            with repository.transaction():
                sessions = repository.records("sessions", session_id)
                checkpoints = repository.records("paper_checkpoints", session_id)
                if (len(sessions) != 1 or len(checkpoints) != 1 or sessions[0]["status"] != "RUNNING"
                        or sessions[0]["mode"] != "PAPER" or sessions[0]["symbol"] != settings.symbol
                        or Decimal(sessions[0]["initial_capital"]) != settings.initial_capital):
                    raise ValueError("A running PAPER session with checkpoint is required")
                checkpoint = checkpoints[0]
                if (checkpoint["settings_sha256"] != settings_digest(settings)
                        or hashlib.sha256(checkpoint["payload"].encode()).hexdigest() != checkpoint["payload_sha256"]):
                    raise ValueError("Checkpoint/settings integrity mismatch")
                payload = json.loads(checkpoint["payload"])
                if payload["version"] != 1:
                    raise ValueError("Unsupported checkpoint")
                broker = cls.__new__(cls)
                broker.settings, broker.repository, broker.session_id = settings, repository, session_id
                broker.costs, broker.risk_guard = ExecutionCosts(settings), StopRiskManager(settings)
                broker._revision = checkpoint["revision"]
                broker._restore_ledger(payload)
                broker._restore_risk(payload["risk"])
                # Acquiring a resume revision invalidates a still-alive previous writer.
                broker._persist()
                return broker
        except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
            raise SimulationError("Paper recovery failed: inconsistent ledger, checkpoint or settings") from exc

    def _restore_ledger(self, payload):
        positions, statuses = {}, {}
        for row in self.repository.records("positions", self.session_id):
            position = _position(json.loads(row["payload"]))
            if (row["id"] != position.id or row["symbol"] != position.symbol
                    or position.symbol != self.settings.symbol or row["status"] not in {"OPEN", "CLOSED"}):
                raise ValueError("Position journal mismatch")
            positions[position.id], statuses[position.id] = position, row["status"]
        trades = []
        closed = set()
        for row in self.repository.records("trades", self.session_id):
            trade = _trade(json.loads(row["payload"]))
            if (trade.position != positions.get(trade.position.id) or statuses[trade.position.id] != "CLOSED"
                    or trade.id != row["id"] or trade.position.id != row["position_id"]
                    or trade.closed_at.isoformat() != row["timestamp"] or trade.net_pnl != Decimal(row["net_pnl"])
                    or trade.position.id in closed):
                raise ValueError("Trade journal mismatch")
            trades.append(trade)
            closed.add(trade.position.id)
        if closed != {key for key, status in statuses.items() if status == "CLOSED"}:
            raise ValueError("Closed position lacks exactly one trade")
        expected = {}
        for position in positions.values():
            expected[(position.id, "BUY")] = (position.quantity, position.entry_price, position.entry_fee, position.opened_at)
        for trade in trades:
            expected[(trade.position.id, "SELL")] = (trade.position.quantity, trade.exit_price, trade.exit_fee, trade.closed_at)
        cash, fees = self.settings.initial_capital, Decimal("0")
        seen = set()
        last_timestamp = None
        for row in self.repository.records("orders", self.session_id):
            order = json.loads(row["payload"])
            key = (order["position_id"], order["side"])
            actual = (Decimal(order["quantity"]), Decimal(order["fill_price"]), Decimal(order["fee"]),
                      datetime.fromisoformat(order["timestamp"]))
            if (key in seen or expected.get(key) != actual or order["id"] != row["id"]
                    or order["position_id"] != row["position_id"] or order["timestamp"] != row["timestamp"]
                    or order["symbol"] != self.settings.symbol or order["status"] != "FILLED"
                    or (last_timestamp is not None and actual[3] < last_timestamp)
                    or (key[1] == "SELL" and (key[0], "BUY") not in seen)):
                raise ValueError("Order journal mismatch")
            notional = actual[0] * actual[1]
            if actual[2] != notional * self.settings.paper_fee_rate:
                raise ValueError("Recorded fee differs from frozen settings")
            cash += -notional - actual[2] if key[1] == "BUY" else notional - actual[2]
            if cash < 0:
                raise ValueError("Ledger overdraft")
            fees += actual[2]
            last_timestamp = actual[3]
            seen.add(key)
        if set(expected) != seen:
            raise ValueError("Missing orders")
        self._positions = {key: value for key, value in positions.items() if statuses[key] == "OPEN"}
        self.trades = trades
        self._cash, self.total_fees = cash, fees
        self._realized_pnl = sum((trade.net_pnl for trade in trades), Decimal("0"))
        if (payload["position_ids"] != list(self._positions) or payload["trade_ids"] != [t.id for t in trades]
                or Decimal(payload["cash"]) != cash or Decimal(payload["total_fees"]) != fees
                or Decimal(payload["realized_pnl"]) != self._realized_pnl):
            raise ValueError("Checkpoint disagrees with ledger")
        self._last_order_timestamp = last_timestamp

    def _restore_risk(self, values):
        risk = RiskState(self.settings.initial_capital, self.settings.risk)
        for field in ("last_equity", "peak", "day_start"):
            value = Decimal(values[field])
            positive_decimal(value, field, allow_zero=True)
            setattr(risk, field, value)
        risk.day = date.fromisoformat(values["day"]) if values["day"] is not None else None
        risk.last_timestamp = datetime.fromisoformat(values["last_timestamp"]) if values["last_timestamp"] is not None else None
        if risk.last_timestamp is not None:
            aware_timestamp(risk.last_timestamp)
            from datetime import timezone
            if risk.day != risk.last_timestamp.astimezone(timezone.utc).date():
                raise ValueError("Risk day mismatch")
        elif risk.day is not None or self._last_order_timestamp is not None:
            raise ValueError("Missing risk timestamp")
        if (risk.peak < max(self.settings.initial_capital, risk.last_equity, risk.day_start)
                or (self._last_order_timestamp is not None and risk.last_timestamp < self._last_order_timestamp)):
            raise ValueError("Invalid risk high water mark or chronology")
        for field in ("daily_halted", "drawdown_halted", "kill_switch"):
            if type(values[field]) is not bool:
                raise ValueError("Invalid risk latch")
            setattr(risk, field, values[field])
        if (self.settings.risk.kill_switch and not risk.kill_switch
                or (risk.last_equity <= risk.peak * (1 - risk.limits.max_drawdown) and not risk.drawdown_halted)
                or (risk.last_equity <= risk.day_start * (1 - risk.limits.max_daily_loss) and not risk.daily_halted)):
            raise ValueError("Risk stop was cleared")
        self.risk_state = risk
