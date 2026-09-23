import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from app.exchange.bitvavo import Instrument
from backtesting.venue_research import cases, definition


class VenueResearchTests(unittest.TestCase):
    def test_fixed_costs_and_all_instrument_limits_are_recorded(self):
        market = Instrument(b"{}", "public", datetime(2026, 9, 23, tzinfo=timezone.utc),
                            "trading", Decimal("1"), Decimal("0.00000001"), Decimal("0.00007"), Decimal("5"), "A")
        settings = cases(market)
        self.assertEqual(settings["bitvavo_current"].paper_fee_rate, Decimal("0.0025"))
        self.assertEqual(settings["bitvavo_stress"].paper_fee_rate, Decimal("0.005"))
        for value in settings.values():
            self.assertEqual(value.price_tick, market.tick_size)
            self.assertEqual(value.min_order_quantity, market.minimum_quantity)
            self.assertEqual(value.min_order_notional, market.minimum_notional)
        frozen = definition(market)
        self.assertEqual(frozen["years"], [2023, 2024])
        self.assertEqual(set(frozen["variants"]), {"net_reward", "slow_breakout", "trend_pullback"})
        self.assertNotEqual(frozen, definition(replace(market, tick_size=Decimal("0.01"))))
