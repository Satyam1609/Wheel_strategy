"""
costs.py
========
Cost and friction assumptions for the historical NSE wheel.

Option-sale STT schedule (the short-option writer pays this on premium):
  < 2023-04-01            : 0.050%
  2023-04-01..2024-09-30  : 0.0625%
  2024-10-01..2026-03-31  : 0.100%
  >= 2026-04-01           : 0.150%

Exercise STT is payable by the option purchaser, not this short-option writer.
Physical share delivery is modeled at the 0.1% delivery-equity STT rate on the
share value. Assignment executes at strike and has no discretionary execution
slippage. Discretionary residual/spin-off sales carry the explicit stock
slippage assumption.

Sources: https://www.nseindia.com/static/products-services/equity-derivatives-securities-transaction-tax
https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies

Other costs (assumptions, held constant given lack of a clean public time
series; flagged as an assumption):
  - Brokerage: flat Rs 20 per executed leg (discount-broker model), capped
    at a token amount for very small premiums (typical of Zerodha/Upstox-style
    pricing throughout the window).
  - Exchange transaction charges: ~0.035% of premium (approx blended NSE F&O
    options charge over the window; real values ranged 0.05%->0.0325%->lower
    per NSE circulars over 2023-2024).
  - GST: 18% on (brokerage + exchange transaction charges).
  - SEBI turnover fee: Rs 10 per crore of premium (negligible, included for
    completeness).
  - Stamp duty: 0.003% of premium on the buy side only (per the buyer-side
    stamp duty convention; wheel is a net seller so this mostly applies to
    the buy-to-close leg of a profit-take).
  - Slippage: an explicit bp assumption on option entries and discretionary
    equity sales (see DEFAULT_SLIPPAGE_BPS); mandatory assignment at strike has
    none. Two alternative assumptions are run in the sensitivity section.
"""

BROKERAGE_PER_LEG = 20.0
EXCH_TXN_RATE = 0.00035     # of premium, options
GST_RATE = 0.18
SEBI_FEE_PER_CR = 10.0
STAMP_DUTY_BUY = 0.00003    # of premium, buy-side only

DEFAULT_SLIPPAGE_BPS = 25    # of premium/notional, applied against the strategy
ALT_SLIPPAGE_BPS = [10, 50]  # for sensitivity


def stt_option_sell(premium_value: float, date) -> float:
    d = str(date.date()) if hasattr(date, "date") else str(date)
    if d < "2023-04-01":
        rate = 0.00050
    elif d < "2024-10-01":
        rate = 0.000625
    elif d < "2026-04-01":
        rate = 0.00100
    else:
        rate = 0.00150
    return premium_value * rate


def option_leg_cost(premium_value: float, date, side: str, slippage_bps: float = DEFAULT_SLIPPAGE_BPS):
    """side: 'sell_to_open', 'buy_to_close' (both premium-settled, no exercise)."""
    brokerage = BROKERAGE_PER_LEG
    exch = premium_value * EXCH_TXN_RATE
    gst = GST_RATE * (brokerage + exch)
    stamp = STAMP_DUTY_BUY * premium_value if side == "buy_to_close" else 0.0
    stt = stt_option_sell(premium_value, date) if side == "sell_to_open" else 0.0
    slippage = premium_value * slippage_bps / 10000.0
    sebi = SEBI_FEE_PER_CR * premium_value / 1e7
    total = brokerage + exch + gst + stamp + stt + slippage + sebi
    return total


def assignment_cost(settlement_value: float, date, slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
                    market_execution: bool = False):
    """One side of share delivery; option exercise STT belongs to the purchaser.

    `market_execution` denotes an actual exchange sale rather than mandatory
    option delivery at strike. `date` is retained for the common cost API.
    """
    brokerage = BROKERAGE_PER_LEG
    exch = settlement_value * 0.0000325  # equity delivery-ish exch charge, approx
    gst = GST_RATE * (brokerage + exch)
    stt = settlement_value * 0.001
    slippage = settlement_value * slippage_bps / 10000.0 if market_execution else 0.0
    sebi = SEBI_FEE_PER_CR * settlement_value / 1e7
    return brokerage + exch + gst + stt + slippage + sebi
