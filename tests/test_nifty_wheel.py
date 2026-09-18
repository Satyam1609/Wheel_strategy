import unittest

from main.backtest import costs
from main.backtest.run_nifty_wheel import (
    DEFAULT_CASH_RATE,
    choose_option,
    margin_required,
    option_intrinsic,
)
from main.data_pipeline.extract_nifty_derivatives import legacy_lot


class NiftyWheelTests(unittest.TestCase):
    def test_base_case_credits_no_cash_interest(self):
        self.assertEqual(DEFAULT_CASH_RATE, 0.0)

    def test_legacy_turnover_inference_recovers_exchange_lot(self):
        future = {
            "CONTRACTS": "10", "VAL_INLAKH": "0.75", "CLOSE": "100",
            "STRIKE_PR": "0", "OPEN_INT": "750",
        }
        option = {
            "CONTRACTS": "10", "VAL_INLAKH": "0.7875", "CLOSE": "5",
            "STRIKE_PR": "100", "OPEN_INT": "750",
        }
        self.assertEqual(legacy_lot(future, "future"), 75)
        self.assertEqual(legacy_lot(option, "put"), 75)

    def test_legacy_lot_uses_oi_divisor_when_turnover_rounds_up(self):
        future = {
            "CONTRACTS": "236005", "VAL_INLAKH": "2447687.43",
            "CLOSE": "13709.1", "STRIKE_PR": "0", "OPEN_INT": "9184875",
        }
        self.assertEqual(legacy_lot(future, "future"), 75)

    def test_covered_call_respects_recovery_floor_and_future_lot(self):
        rows = [
            dict(instrument="call", expiry="2024-01-25", strike=105, close=3,
                 volume=100, oi=1000, lot=50),
            dict(instrument="call", expiry="2024-01-25", strike=115, close=1,
                 volume=100, oi=1000, lot=50),
            dict(instrument="call", expiry="2024-01-25", strike=120, close=.5,
                 volume=100, oi=1000, lot=25),
        ]
        selected = choose_option(rows, "call", "2024-01-25", 100,
                                 floor=112, otm=.05, lot=50)
        self.assertEqual(selected["strike"], 115)

    def test_cash_settlement_is_intrinsic_not_legacy_settlement_field(self):
        self.assertAlmostEqual(option_intrinsic("put", 18000, 17618.15), 381.85)
        self.assertEqual(option_intrinsic("call", 18000, 18100), 100)
        self.assertEqual(option_intrinsic("call", 18000, 17900), 0)

    def test_margin_proxy_changes_with_wheel_state(self):
        put_state = {
            "option": {"type": "put", "strike": 20000, "qty": 50},
            "future": None,
        }
        call_state = {
            "option": {"type": "call", "strike": 22000, "qty": 50},
            "future": {"last": 21000, "qty": 50},
        }
        self.assertEqual(margin_required(put_state), 1_000_000)
        self.assertEqual(margin_required(call_state), 220_000)

    def test_historical_futures_stt_schedule(self):
        notional = 10_000_000
        buy = costs.futures_leg_cost(notional, "2022-01-01", "buy", 0)
        sell_2022 = costs.futures_leg_cost(notional, "2022-01-01", "sell", 0)
        sell_2023 = costs.futures_leg_cost(notional, "2023-06-01", "sell", 0)
        sell_2024 = costs.futures_leg_cost(notional, "2024-10-01", "sell", 0)
        self.assertAlmostEqual(sell_2022 - (buy - notional * .00002), 1000)
        self.assertAlmostEqual(sell_2023 - sell_2022, 250)
        self.assertAlmostEqual(sell_2024 - sell_2023, 750)


if __name__ == "__main__":
    unittest.main()
