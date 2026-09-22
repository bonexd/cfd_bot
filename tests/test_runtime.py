import copy
import time
import unittest
from datetime import datetime, timezone

import app  # noqa: F401 - keeps legacy top-level imports available

from broker.capital import CapitalBroker
from broker.base import AccountState
from instruments import MARKETS
from risk import RiskManager
from streamers import classify_text
from research.walk import pick_winner
from main import capital_map, effective_trade_cfg, enabled_markets, resolved_markets, terminal_scan_due


class RuntimeRegressionTests(unittest.TestCase):
    def test_market_resolution_skips_unavailable_symbol(self):
        markets = [copy.deepcopy(MARKETS["gold"]), copy.deepcopy(MARKETS["us500"])]
        markets[1].epic = ""

        class Broker:
            def resolve_epic(self, term):
                raise RuntimeError("not offered")

        live_map = capital_map(markets, Broker())
        self.assertEqual(live_map["gold"], "GOLD")
        self.assertNotIn("us500", live_map)
        self.assertEqual([m.key for m in resolved_markets(markets, live_map)], ["gold"])

    def test_shared_risk_is_point_seven_percent(self):
        cfg = {"account": {"leverage": 20}, "risk": {"risk_per_trade_pct": 0.7}}
        rm = RiskManager(cfg)
        self.assertEqual(rm.snapshot()["per_trade"], 0.7)

    def test_bootstrap_profile_activates_between_50_and_200(self):
        cfg = {
            "account": {"leverage": 20},
            "risk": {
                "risk_per_trade_pct": 0.7,
                "max_portfolio_allocation_pct": 30.0,
                "max_open_positions": 12,
                "max_positions_per_market": 4,
                "max_index_positions": 8,
                "daily_loss_enabled": False,
                "bootstrap": {
                    "enabled": True,
                    "min_equity": 50.0,
                    "target_equity": 200.0,
                    "risk_per_trade_pct": 1.0,
                    "max_min_lot_risk_pct": 2.0,
                    "max_portfolio_allocation_pct": 60.0,
                    "max_open_positions": 2,
                    "max_positions_per_market": 1,
                    "max_index_positions": 1,
                },
            },
        }
        rm = RiskManager(cfg)

        below = rm.snapshot(49.99)
        bootstrap = rm.snapshot(50.0)
        standard = rm.snapshot(200.0)

        self.assertEqual(below["profile"], "below_minimum")
        self.assertEqual(bootstrap["profile"], "bootstrap")
        self.assertEqual(bootstrap["per_trade"], 1.0)
        self.assertEqual(bootstrap["max_portfolio_allocation_pct"], 60.0)
        self.assertEqual(bootstrap["max_open"], 2)
        self.assertEqual(standard["profile"], "standard")
        self.assertEqual(standard["per_trade"], 0.7)
        self.assertEqual(standard["max_portfolio_allocation_pct"], 30.0)
        self.assertEqual(standard["max_open"], 12)

    def test_bootstrap_blocks_new_entries_below_50(self):
        cfg = {
            "account": {"leverage": 20},
            "risk": {
                "risk_per_trade_pct": 0.7,
                "max_portfolio_allocation_pct": 30.0,
                "max_open_positions": 12,
                "max_positions_per_market": 4,
                "max_index_positions": 8,
                "daily_loss_enabled": False,
                "bootstrap": {
                    "enabled": True,
                    "min_equity": 50.0,
                    "target_equity": 200.0,
                    "risk_per_trade_pct": 1.0,
                    "max_min_lot_risk_pct": 2.0,
                    "max_portfolio_allocation_pct": 60.0,
                    "max_open_positions": 2,
                    "max_positions_per_market": 1,
                    "max_index_positions": 1,
                },
            },
        }
        rm = RiskManager(cfg)
        decision = rm.check_account(49.99, 0)
        self.assertFalse(decision.allowed)
        self.assertIn("below bootstrap minimum", decision.reason)

    def test_bootstrap_can_use_minimum_lot_inside_two_percent_cap(self):
        market = copy.deepcopy(MARKETS["gold"])
        market.contract_size = 1.0
        market.point_value = 1.0
        market.min_lot = 0.01
        market.lot_step = 0.01
        market.max_lot = 2.0
        market.margin_factor = None
        cfg = {
            "account": {"leverage": 20},
            "risk": {
                "risk_per_trade_pct": 0.7,
                "max_portfolio_allocation_pct": 30.0,
                "max_open_positions": 12,
                "max_positions_per_market": 4,
                "max_index_positions": 8,
                "daily_loss_enabled": False,
                "bootstrap": {
                    "enabled": True,
                    "min_equity": 50.0,
                    "target_equity": 200.0,
                    "risk_per_trade_pct": 1.0,
                    "max_min_lot_risk_pct": 2.0,
                    "max_portfolio_allocation_pct": 60.0,
                    "max_open_positions": 2,
                    "max_positions_per_market": 1,
                    "max_index_positions": 1,
                },
            },
        }
        rm = RiskManager(cfg)
        # CHF 50 * 1% = 0.50 target risk. A 60-point stop risks 0.60
        # at the 0.01 minimum lot, which is allowed by the 2% (=1.00) hard cap.
        sized = rm.size_lots(50.0, 60.0, market, price=100.0)
        self.assertTrue(sized.allowed)
        self.assertEqual(sized.reason, "bootstrap minimum lot")
        self.assertAlmostEqual(sized.lots, 0.01)

    def test_terminal_bar_scheduler_skips_redundant_scans(self):
        state = {
            "bar_state": {
                "gold": {
                    "bar": "2026-09-22T14:00:00+00:00",
                    "terminal": True,
                }
            }
        }
        self.assertFalse(
            terminal_scan_due(
                state,
                "gold",
                "1m",
                datetime(2026, 9, 22, 14, 1, 30, tzinfo=timezone.utc),
            )
        )
        self.assertTrue(
            terminal_scan_due(
                state,
                "gold",
                "1m",
                datetime(2026, 9, 22, 14, 2, 2, tzinfo=timezone.utc),
            )
        )

    def test_account_cache_reuses_recent_snapshot(self):
        broker = CapitalBroker.__new__(CapitalBroker)
        cached = AccountState(1000.0, 1000.0, "EUR", [])
        broker._last_account_state = cached
        broker._last_account_at = time.monotonic()
        broker.account = lambda: (_ for _ in ()).throw(AssertionError("network fetch"))
        self.assertIs(broker.account_cached(6.0), cached)

    def test_unconfirmed_order_is_not_reported_as_success(self):
        broker = CapitalBroker.__new__(CapitalBroker)

        def fake_request(method, path, payload=None, query=None):
            if method == "POST" and path == "/api/v1/positions":
                return {"dealReference": "o_test"}
            raise RuntimeError("confirmation temporarily unavailable")

        broker._request = fake_request
        fill = broker.market_order("GOLD", "buy", 1.0, 100.0, 110.0, "test")
        self.assertFalse(fill.ok)
        self.assertIn("UNCONFIRMED", fill.message)

    def test_confirmed_order_can_succeed(self):
        broker = CapitalBroker.__new__(CapitalBroker)

        def fake_request(method, path, payload=None, query=None):
            if method == "POST":
                return {"dealReference": "o_test"}
            if path == "/api/v1/confirms/o_test":
                return {
                    "dealStatus": "ACCEPTED",
                    "dealId": "deal-1",
                    "level": 105.0,
                }
            raise AssertionError(path)

        broker._request = fake_request
        fill = broker.market_order("GOLD", "buy", 1.0, 100.0, 110.0, "test")
        self.assertTrue(fill.ok)
        self.assertEqual(fill.price, 105.0)

    def test_contract_size_is_used_in_risk_sizing(self):
        market = copy.deepcopy(MARKETS["gold"])
        market.contract_size = 50.0
        market.min_lot = 0.01
        market.lot_step = 0.01
        market.max_lot = 10.0
        cfg = {
            "account": {"leverage": 20},
            "risk": {
                "risk_per_trade_pct": 0.4,
                "max_portfolio_allocation_pct": 100.0,
                "daily_loss_enabled": False,
                "max_open_positions": 12,
                "max_positions_per_market": 4,
                "max_index_positions": 8,
            },
        }
        rm = RiskManager(cfg)
        sized = rm.size_lots(10_000.0, 1.0, market, price=100.0)
        self.assertTrue(sized.allowed)
        self.assertAlmostEqual(sized.lots, 0.8)

    def test_streamer_negation_is_not_a_directional_vote(self):
        self.assertEqual(classify_text("Gold not bullish - do not buy"), "neutral")
        self.assertEqual(classify_text("Nasdaq bearish short setup"), "sell")
        self.assertEqual(classify_text("Gold bullish buy setup"), "buy")

    def test_demo_frequency_overrides_do_not_change_live(self):
        cfg = {
            "mode": "demo",
            "execution": {
                "demo_market_scope": "all",
                "demo_frequency": {
                    "quality": {"min_reward_risk": 1.0},
                    "news": {"min_confidence": 0.68},
                },
            },
            "quality": {"min_reward_risk": 1.05},
            "news": {"min_confidence": 0.62},
            "markets": {
                "gold": {"enabled": True, "live_enabled": True},
                "us500": {"enabled": True, "live_enabled": False},
            },
        }
        demo = effective_trade_cfg(cfg, "demo")
        live = effective_trade_cfg(cfg, "live")
        self.assertEqual(demo["quality"]["min_reward_risk"], 1.0)
        self.assertEqual(demo["news"]["min_confidence"], 0.68)
        self.assertEqual(live["quality"]["min_reward_risk"], 1.05)
        self.assertEqual(live["news"]["min_confidence"], 0.62)

    def test_no_profitable_strategy_returns_no_winner(self):
        rows = [
            {
                "name": "a",
                "error": None,
                "trades": 10,
                "pnl": -5.0,
                "expectancy": -0.5,
                "pf": 0.8,
                "score": -1.0,
                "win_rate": 40.0,
            }
        ]
        self.assertIsNone(pick_winner(rows))


if __name__ == "__main__":
    unittest.main()
