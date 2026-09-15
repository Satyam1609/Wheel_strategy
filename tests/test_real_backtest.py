import unittest

from main.backtest.run_real_backtest import (BASE, TICKERS, adjusted_reference_close, apply_corporate_actions,
                               infer_entry_lot, load_dividends, load_nifty_tr, make_state,
                               margin_collateral, margin_proxy, metrics, revised_expiry, settle)
from main.backtest.select_universe import screen
from main.backtest import costs


class RealBacktestTests(unittest.TestCase):
    def test_original_selection_and_inception_liquidity_are_recorded(self):
        rows = screen(BASE / "data/real_options.csv", "2020-01-01")
        self.assertEqual({r["ticker"] for r in rows}, set(TICKERS))
        self.assertTrue(all(r["passes_inception_liquidity_check"] for r in rows))

    def test_official_tri_covers_every_backtest_price_day(self):
        import csv
        with (BASE / "data/real_prices.csv").open(newline="") as handle:
            dates = [r["date"] for r in csv.DictReader(handle) if r["date"] <= "2026-06-30"]
        values = load_nifty_tr(BASE / "data/nifty50_tr.csv", dates)
        self.assertTrue(all(values[d] > 0 for d in dates))

    def test_writer_does_not_pay_purchaser_exercise_stt(self):
        delivery = 1_000_000
        self.assertLess(costs.assignment_cost(delivery, "2026-06-30"), 1500)
        self.assertGreater(costs.assignment_cost(delivery, "2026-06-30", market_execution=True),
                           costs.assignment_cost(delivery, "2026-06-30"))

    def test_margin_proxy_and_stock_collateral(self):
        option = dict(type="call", strike=100, qty=500, expiry="2020-01-30")
        state = make_state("RELIANCE")
        state["shares"] = 500
        self.assertEqual(margin_proxy(option, 110, "2020-01-27"), 17_500)
        self.assertGreater(margin_collateral(state, 110, option), 17_500)

    def test_per_name_metrics_use_sleeve_initial_capital(self):
        result = metrics([1_000_000, 1_100_000], ["2020-01-01", "2021-01-01"], 1_000_000)
        self.assertEqual(result["start"], 1_000_000)
        self.assertEqual(result["end"], 1_100_000)

    def test_ex_action_reference_is_on_new_share_basis(self):
        self.assertEqual(adjusted_reference_close(9331, [dict(
            action="SPLIT_BONUS", adjustment_factor="10")]), 933.1)
        self.assertEqual(adjusted_reference_close(660.75, [dict(
            action="SPIN_OFF", spin_off_ratio="1", provisional_value="260.75")]), 400)

    def test_nse_dividends_cover_each_name_and_combine_special_payouts(self):
        dividends = load_dividends(BASE / "data/dividends.csv")
        self.assertTrue(set(TICKERS).issubset({ticker for _, ticker in dividends}))
        self.assertEqual(dividends[("2023-01-16", "TCS")], 75)
        self.assertEqual(dividends[("2024-05-31", "INFY")], 28)
        self.assertEqual(dividends[("2026-06-12", "TMCV")], 4)

    def test_split_preserves_equity_and_adjusts_open_call(self):
        state = make_state("BAJFINANCE")
        state.update(shares=250, basis=9000, option=dict(type="call", strike=9500,
                     expiry="2025-06-26", qty=250, entry_premium=100), last_mark=80)
        before = state["cash"] + state["shares"] * 9000 - state["last_mark"] * 250
        actions = {"2025-06-16": [dict(ticker="BAJFINANCE", action="SPLIT_BONUS",
                                      adjustment_factor="10")]}
        apply_corporate_actions(state, "2025-06-16", actions, [])
        after = state["cash"] + state["shares"] * 900 - state["last_mark"] * 2500
        self.assertAlmostEqual(before, after)
        self.assertEqual((state["shares"], state["option"]["qty"], state["option"]["strike"]),
                         (2500, 2500, 950))

    def test_rights_and_demerger_entitlements(self):
        state = make_state("RELIANCE")
        state["shares"] = 500
        state["option"] = dict(type="call", strike=1500, expiry="2020-05-28",
                               qty=500, entry_premium=20)
        apply_corporate_actions(state, "2020-05-13", {"2020-05-13": [dict(
            ticker="RELIANCE", action="RIGHTS", adjustment_factor="0.990610",
            cash_benefit_per_share="13.890625", revised_market_lot="505",
            old_market_lot="500")]}, [])
        self.assertEqual(state["shares"], 500)
        self.assertEqual(state["option"]["qty"], 505)
        self.assertEqual(state["option"]["strike"], 1485.9)
        self.assertAlmostEqual(state["rights_proceeds"], 6945.3125)
        apply_corporate_actions(state, "2023-07-20", {"2023-07-20": [dict(
            ticker="RELIANCE", action="SPIN_OFF", spin_off_symbol="JIOFIN",
            spin_off_ratio="1", provisional_value="261.85")]}, [])
        self.assertEqual(state["spin_offs"]["JIOFIN"], 500)
        self.assertEqual(state["spin_off_marks"]["JIOFIN"], 261.85)

    def test_legacy_reliance_rights_contracts_have_distinct_lots(self):
        self.assertEqual(infer_entry_lot("2020-05-04", "RELIANCE", {
            "expiry": "2020-05-28", "type": "put", "strike": 1360.0,
            "lot": 500, "oi": 1000,
        }), 500)
        self.assertEqual(infer_entry_lot("2020-05-29", "RELIANCE", {
            "expiry": "2020-06-25", "type": "put", "strike": 1386.85,
            "lot": 505, "oi": 1010,
        }), 505)

    def test_put_assignment_and_call_away_update_position(self):
        state = make_state("RELIANCE")
        state["option"] = dict(type="put", strike=100, expiry="2020-01-30",
                               qty=500, entry_premium=5)
        trades = []
        settle(state, "2020-01-30", 90, trades)
        self.assertEqual((state["shares"], state["basis"], state["assignments"]), (500, 95, 1))
        self.assertEqual(trades[-1]["action"], "ASSIGNED")
        state["option"] = dict(type="call", strike=110, expiry="2020-02-27",
                               qty=500, entry_premium=2)
        settle(state, "2020-02-27", 120, trades)
        self.assertEqual((state["shares"], state["calls_away"]), (0, 1))
        self.assertEqual(trades[-1]["action"], "CALLED_AWAY")
        self.assertEqual(state["option_realized_pnl"], -6500)

    def test_exchange_can_move_expiry_forward_one_day(self):
        active = {"expiry": "2023-06-29", "type": "put", "strike": 900.0}
        rows = [{"expiry": "2023-06-28", "type": "put", "strike": 900.0}]
        self.assertEqual(revised_expiry(active, rows, "2023-06-28"), "2023-06-28")

    def test_residual_shares_are_sold_after_call_away(self):
        state = make_state("RELIANCE")
        state["shares"] = 505
        state["basis"] = 100
        state["option"] = dict(type="call",strike=110,expiry="2020-02-27",
                               qty=500,entry_premium=2)
        trades=[]
        settle(state,"2020-02-27",120,trades)
        self.assertEqual(state["shares"],0)
        self.assertEqual(state["basis"],0)
        self.assertEqual(trades[-1]["action"],"SELL_RESIDUAL_SHARES")
        self.assertEqual(int(trades[-1]["qty"]),5)

    def test_metrics_include_drawdown_dates_and_risk_ratios(self):
        result = metrics([20_000_000.0, 24_000_000.0, 18_000_000.0, 26_000_000.0],
                         ["2020-01-01", "2020-01-10", "2020-01-20", "2020-02-01"])
        self.assertEqual(result["MDD_peak"], "2020-01-10")
        self.assertEqual(result["MDD_trough"], "2020-01-20")
        self.assertIn("Sortino", result)
        self.assertIn("Calmar", result)


if __name__ == "__main__":
    unittest.main()
