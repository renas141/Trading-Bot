"""Idempotent PAPER events: closed-candle decisions, subsequent public quote fills.

No historical bar-open fills are synthesized. The CLI uses NoTradeStrategy; the
execution paths are exercised with test-only signals until research qualifies.
"""

import hashlib
import json
import inspect
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.database.repository import _json
from app.domain import Direction, aware_timestamp, positive_decimal
from app.errors import MarketDataError, SimulationError
from app.exchange.bitvavo import BookSnapshot, Instrument
from app.execution.durable_paper import DurablePaperBroker
from app.market_data.models import Candle
from app.market_data.quality import audit_candles
from app.risk.risk_manager import RiskDecision
from app.risk.stop_risk import StopRiskManager
from app.strategies.no_trade import NoTradeStrategy


def digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


class QuotePaperRunner:
    def __init__(self, broker: DurablePaperBroker, strategy=None, *, clock=None,
                 max_quote_age_seconds=10, max_request_seconds=5, max_signal_age_seconds=90):
        if not isinstance(broker, DurablePaperBroker) or broker.settings.paper_spread_bps != 0:
            raise ValueError("Quote PAPER requires durable broker and zero synthetic spread; actual bid/ask are used")
        for value in (max_quote_age_seconds, max_request_seconds, max_signal_age_seconds):
            if type(value) is not int or not 1 <= value <= 300:
                raise ValueError("Invalid observation freshness limit")
        self.broker, self.strategy = broker, strategy or NoTradeStrategy()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_quote_age = max_quote_age_seconds
        self.max_request_age = max_request_seconds
        self.max_signal_age = max_signal_age_seconds
        self.spec = self._spec()
        repo = broker.repository
        with broker.atomic():
            repo.connection.execute("CREATE TABLE IF NOT EXISTS paper_runner (session_id TEXT PRIMARY KEY REFERENCES sessions(id), config TEXT NOT NULL, state TEXT NOT NULL)")
            repo.connection.execute("CREATE TABLE IF NOT EXISTS paper_events (session_id TEXT NOT NULL REFERENCES sessions(id), event_id TEXT NOT NULL, timestamp TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(session_id,event_id))")
            row = repo.connection.execute("SELECT config FROM paper_runner WHERE session_id=?", (broker.session_id,)).fetchone()
            if row:
                if json.loads(row[0]) != self.spec:
                    raise SimulationError("Runner configuration changed; use a new PAPER session")
            else:
                # An existing portfolio cannot be silently assigned a new runner history.
                if broker.snapshot().positions or broker.trades or repo.records("signals", broker.session_id):
                    raise SimulationError("Runner initialization requires a fresh portfolio")
                now = self.clock()
                aware_timestamp(now)
                state = {"activated_at": now.isoformat(), "last_quote_at": None,
                         "last_candle_at": None, "last_candle_sha256": None}
                repo.connection.execute("INSERT INTO paper_runner VALUES (?,?,?)", (broker.session_id, _json(self.spec), _json(state)))

    def _spec(self):
        parameters = getattr(self.strategy, "parameters", None)
        return json.loads(_json({"version": 1, "provider": "Bitvavo", "symbol": self.broker.settings.symbol,
              "timeframe": self.broker.settings.timeframe,
              "strategy": type(self.strategy).__module__ + "." + type(self.strategy).__qualname__,
              "strategy_version": getattr(self.strategy, "version", "unversioned"),
              "strategy_source_sha256": hashlib.sha256(inspect.getsource(type(self.strategy)).encode()).hexdigest(),
              "parameters": asdict(parameters) if is_dataclass(parameters) else None,
              "max_quote_age_seconds": self.max_quote_age, "max_request_seconds": self.max_request_age,
              "max_signal_age_seconds": self.max_signal_age,
              "fills": "observed ask/bid plus adverse slippage; no maker fills; require top size"}))

    def _validate_quote(self, quote, market, now):
        for stamp in (now, quote.requested_at, quote.received_at, market.requested_at):
            aware_timestamp(stamp)
        if (not 0 <= (now - quote.received_at).total_seconds() <= self.max_quote_age
                or not 0 <= (quote.received_at - quote.requested_at).total_seconds() <= self.max_request_age
                or not 0 <= (now - market.requested_at).total_seconds() <= 300):
            raise MarketDataError("Quote or instrument observation is stale, slow, or from the future")
        for value in (quote.bid, quote.ask, quote.bid_size, quote.ask_size):
            positive_decimal(value, "quote")
        if quote.bid >= quote.ask:
            raise MarketDataError("Crossed or locked quote")
        positive_decimal(market.minimum_quantity, "market minimum quantity")
        positive_decimal(market.minimum_notional, "market minimum notional")
        settings = self.broker.settings
        if (market.fee_category != "A" or market.tick_size != settings.price_tick
                or market.quantity_step != settings.quantity_step):
            raise MarketDataError("Instrument limits changed; new session/configuration review required")

    def _history(self, candles, quote, state):
        if not candles or len(candles) > 1440:
            return "No bounded closed-candle history available."
        if any(c.closed_at > quote.requested_at for c in candles):
            return "History contains a candle that was not closed before the quote request."
        try:
            report = audit_candles(candles, self.broker.settings.symbol, self.broker.settings.timeframe,
                                  candles[0].timestamp, candles[-1].closed_at, as_of=quote.requested_at)
        except ValueError:
            return "Invalid candle interval boundaries; entries paused."
        if not report.ready:
            return "Candle history has missing, duplicated or inconsistent intervals."
        if state["last_candle_at"]:
            old = datetime.fromisoformat(state["last_candle_at"])
            match = next((c for c in candles if c.closed_at == old), None)
            if match is None or digest(match) != state["last_candle_sha256"]:
                return "Previously processed candle missing or revised; entries paused."
        return None

    def process(self, quote: BookSnapshot, market: Instrument, candles: tuple[Candle, ...]):
        now = self.clock()
        self._validate_quote(quote, market, now)
        if self._spec() != self.spec:
            raise SimulationError("Strategy or runner parameters changed")
        event_id = digest({"quote_requested_at": quote.requested_at, "raw_sha256": hashlib.sha256(quote.raw).hexdigest()})
        broker, repo = self.broker, self.broker.repository
        with broker.atomic():
            prior = repo.connection.execute("SELECT payload FROM paper_events WHERE session_id=? AND event_id=?", (broker.session_id, event_id)).fetchone()
            if prior:
                return {**json.loads(prior[0]), "duplicate": True}
            state = json.loads(repo.connection.execute("SELECT state FROM paper_runner WHERE session_id=?", (broker.session_id,)).fetchone()[0])
            if ((state["last_quote_at"] and quote.requested_at <= datetime.fromisoformat(state["last_quote_at"]))
                    or quote.requested_at < datetime.fromisoformat(state["activated_at"])):
                raise MarketDataError("Quote is older than activation or last processed observation")
            history_error = self._history(candles, quote, state)
            actions = []
            broker.mark(quote.bid, quote.received_at)
            # Protective exits do not depend on candle availability or strategy signals.
            for position in tuple(broker.snapshot().positions):
                stop = position.stop_price is not None and quote.bid <= position.stop_price
                target = position.take_profit_price is not None and quote.bid >= position.take_profit_price
                if stop or target:
                    if (market.status != "trading" or quote.bid_size < position.quantity
                            or position.quantity < market.minimum_quantity
                            or position.quantity * broker.costs.sell(quote.bid) < market.minimum_notional):
                        actions.append("Protective exit not simulated: market unavailable, below current minimum, or insufficient displayed bid size.")
                    else:
                        price = quote.bid if stop else min(quote.bid, position.take_profit_price)
                        broker.close_position(position.id, price, quote.received_at,
                                              "PAPER_OBSERVED_STOP" if stop else "PAPER_OBSERVED_TARGET")
                        actions.append("Protective exit filled at observed quote model.")
            latest = candles[-1] if candles and not history_error else None
            fresh_bar = latest and (not state["last_candle_at"] or latest.closed_at > datetime.fromisoformat(state["last_candle_at"]))
            if fresh_bar:
                if latest.closed_at <= datetime.fromisoformat(state["activated_at"]):
                    actions.append("Warm-up only: historical signal predates runner activation.")
                else:
                    signal = self.strategy.analyze(candles)
                    if signal.timestamp != latest.closed_at or signal.symbol != broker.settings.symbol:
                        raise ValueError("Strategy signal must describe the latest closed candle and configured market")
                    if signal.direction == Direction.HOLD:
                        decision = RiskDecision(False, ("Strategy recommends no trade.",))
                    elif market.status != "trading":
                        decision = RiskDecision(False, ("Market is not trading.",))
                    elif (quote.received_at - signal.timestamp).total_seconds() > self.max_signal_age:
                        decision = RiskDecision(False, ("Closed-candle signal expired before a usable quote arrived.",))
                    elif broker.snapshot().positions:
                        decision = RiskDecision(False, ("Maximum position count reached.",))
                    else:
                        context = broker.mark(quote.ask, quote.received_at)
                        decision = StopRiskManager(broker.settings).evaluate(signal, broker.snapshot(), context)
                        if decision.allowed and (decision.quantity < market.minimum_quantity
                                or decision.quantity * broker.costs.buy(quote.ask) < market.minimum_notional):
                            decision = RiskDecision(False, ("Proposed quantity is below current market minimums.",))
                        if decision.allowed and decision.quantity > quote.ask_size:
                            decision = RiskDecision(False, ("Displayed ask size is below the proposed quantity; no assumed depth fill.",))
                    repo.record_signal(broker.session_id, signal, decision)
                    if decision.allowed:
                        broker.open_position(signal, decision, quote.ask, quote.received_at)
                        actions.append("Paper entry filled using observed ask plus adverse slippage.")
                    else:
                        actions.extend(decision.reasons)
                state["last_candle_at"] = latest.closed_at.isoformat()
                state["last_candle_sha256"] = digest(latest)
            if history_error:
                actions.append(history_error)
            context = broker.mark(quote.bid, quote.received_at)
            repo.record_equity(broker.session_id, quote.received_at, context.equity)
            state["last_quote_at"] = quote.requested_at.isoformat()
            event = {"event_id": event_id, "timestamp": quote.received_at.isoformat(), "duplicate": False,
                     "actions": actions, "cash": str(broker.snapshot().cash), "equity": str(context.equity),
                     "open_positions": len(broker.snapshot().positions), "history_error": history_error,
                     "market_status": market.status, "book_raw": quote.raw.decode("utf-8"),
                     "book_raw_sha256": hashlib.sha256(quote.raw).hexdigest(), "book_url": quote.request_url,
                     "quote_requested_at": quote.requested_at.isoformat(),
                     "instrument_raw": market.raw.decode("utf-8"), "instrument_requested_at": market.requested_at.isoformat(),
                     "candles": [asdict(c) for c in candles] if fresh_bar else [],
                     "note": "Simulation at public observed quotes; no exchange-event timestamp or guaranteed fill."}
            repo.connection.execute("INSERT INTO paper_events VALUES (?,?,?,?)", (broker.session_id, event_id, quote.received_at.isoformat(), _json(event)))
            repo.connection.execute("UPDATE paper_runner SET state=? WHERE session_id=?", (_json(state), broker.session_id))
            return json.loads(_json(event))
