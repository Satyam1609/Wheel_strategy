"""Backtest a monthly synthetic wheel on cash-settled NIFTY derivatives."""

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from itertools import groupby
from pathlib import Path

from main.backtest import costs
from main.backtest.run_real_backtest import CAPITAL, metrics, write_csv


BASE = Path(__file__).resolve().parents[2]
DEFAULT_CASH_RATE = 0.0


def load_prices(path, end):
    with path.open(newline="") as handle:
        return {row["date"]: float(row["NIFTY"]) for row in csv.DictReader(handle)
                if row["date"] <= end and row["NIFTY"]}


def load_tri(path, end):
    with path.open(newline="") as handle:
        return {row["date"]: float(row["total_return_index"])
                for row in csv.DictReader(handle) if row["date"] <= end}


def derivative_days(path, end):
    with path.open(newline="") as handle:
        for day, grouped in groupby(csv.DictReader(handle), key=lambda row: row["date"]):
            if day > end:
                break
            rows = []
            for row in grouped:
                rows.append({
                    "instrument": row["instrument"], "expiry": row["expiry"],
                    "strike": float(row["strike"]), "close": float(row["close"]),
                    "settlement": float(row["settlement"]),
                    "volume": int(float(row["volume"])),
                    "oi": int(float(row["open_interest"])),
                    "lot": int(row["lot_size"]),
                })
            yield day, rows


def choose_future(rows, day, end):
    candidates = [row for row in rows if row["instrument"] == "future" and
                  day < row["expiry"] <= end and row["volume"] > 0 and row["oi"] > 0]
    return min(candidates, key=lambda row: row["expiry"]) if candidates else None


def choose_option(rows, kind, expiry, reference, floor=0.0, otm=0.05, lot=None):
    target = reference * (1 - otm if kind == "put" else 1 + otm)
    candidates = [row for row in rows if row["instrument"] == kind and
                  row["expiry"] == expiry and row["volume"] > 0 and row["oi"] > 0 and
                  row["close"] > 0 and (lot is None or row["lot"] == lot) and
                  (row["strike"] < reference if kind == "put" else row["strike"] >= max(target, floor))]
    return min(candidates, key=lambda row: (abs(row["strike"] - target), -row["volume"])) if candidates else None


def option_intrinsic(kind, strike, spot):
    """Cash settlement using the available expiry-day NIFTY close proxy."""
    return max(strike - spot, 0.0) if kind == "put" else max(spot - strike, 0.0)


def margin_required(state):
    option = state["option"]
    future = state["future"]
    if option and option["type"] == "put":
        return option["strike"] * option["qty"]
    future_margin = 0.15 * future["last"] * future["qty"] if future else 0.0
    call_margin = 0.20 * option["strike"] * option["qty"] if option else 0.0
    return max(future_margin, call_margin)


def run(prices, tri, derivative_path, otm=0.05, option_slippage_bps=25,
        futures_slippage_bps=2, end="2026-06-30", cash_rate=DEFAULT_CASH_RATE):
    state = {
        "cash": CAPITAL, "option": None, "future": None, "pending_future": None,
        "recovery_basis": 0.0, "premium": 0.0, "option_settlement": 0.0,
        "futures_mtm": 0.0, "interest": 0.0, "costs": 0.0,
        "put_entries": 0, "put_assignments": 0, "call_entries": 0,
        "calls_away": 0, "futures_entries": 0, "futures_rolls": 0,
        "futures_days": 0, "skipped": 0, "stale_option_marks": 0,
        "stale_future_marks": 0, "roll_basis_points": 0.0,
    }
    trades, equity, positions = [], [], []
    previous_spot = None
    tri0 = None
    for day, rows in derivative_days(derivative_path, end):
        if day not in prices or day not in tri:
            continue
        spot = prices[day]
        if tri0 is None:
            tri0 = tri[day]
        transitioned = False

        future = state["future"]
        if future:
            marks = [row for row in rows if row["instrument"] == "future" and
                     row["expiry"] == future["expiry"] and row["lot"] == future["lot"]]
            if marks:
                mark = marks[0]["settlement"]
                mtm = (mark - future["last"]) * future["qty"]
                state["cash"] += mtm
                state["futures_mtm"] += mtm
                future["last"] = mark
            else:
                state["stale_future_marks"] += 1
            state["futures_days"] += 1

        option = state["option"]
        if option:
            marks = [row for row in rows if row["instrument"] == option["type"] and
                     row["expiry"] == option["expiry"] and row["strike"] == option["strike"] and
                     row["lot"] == option["lot"]]
            if marks:
                option["mark"] = marks[0]["settlement"]
            else:
                state["stale_option_marks"] += 1

        expired = bool(option and day >= option["expiry"])
        if expired:
            intrinsic = option_intrinsic(option["type"], option["strike"], spot)
            # Legacy expiry rows place the underlying final-settlement value in
            # SETTLE_PR rather than the option's intrinsic value. Cash-settled
            # index options debit intrinsic against the official expiry index;
            # the EOD NIFTY close is the available final-settlement proxy here.
            settlement = intrinsic
            debit = settlement * option["qty"]
            state["cash"] -= debit
            state["option_settlement"] += debit
            action = "PUT_EXPIRED" if option["type"] == "put" else "CALL_EXPIRED"
            if option["type"] == "put" and intrinsic > 0:
                state["put_assignments"] += 1
                state["pending_future"] = {
                    "qty": option["qty"], "put_intrinsic": settlement,
                    "put_premium": option["entry_premium"], "signal_day": day,
                }
                action = "SYNTHETIC_ASSIGNMENT"
            elif option["type"] == "call" and intrinsic > 0:
                state["calls_away"] += 1
                future = state["future"]
                notional = future["last"] * future["qty"]
                fee = costs.futures_leg_cost(notional, date.fromisoformat(day), "sell", futures_slippage_bps)
                state["cash"] -= fee
                state["costs"] += fee
                trades.append({"date": day, "action": "CLOSE_FUTURE", "expiry": future["expiry"],
                               "strike": 0, "price": future["last"], "premium": 0,
                               "contracts": future["contracts"], "qty": future["qty"],
                               "cost": fee, "cash": state["cash"]})
                state["future"] = None
                state["recovery_basis"] = 0.0
                action = "SYNTHETIC_CALLED_AWAY"
            trades.append({"date": day, "action": action, "expiry": option["expiry"],
                           "strike": option["strike"], "price": spot,
                           "premium": option["entry_premium"], "contracts": option["contracts"],
                           "qty": option["qty"], "cost": 0, "cash": state["cash"]})
            state["option"] = None
            transitioned = True

        future = state["future"]
        if future and day >= future["expiry"]:
            next_future = choose_future(rows, day, end)
            if next_future:
                old_price, old_qty = future["last"], future["qty"]
                close_cost = costs.futures_leg_cost(old_price * old_qty, date.fromisoformat(day),
                                                    "sell", futures_slippage_bps)
                # Exchange lot revisions must not multiply economic exposure.
                # Preserve as many index units as the new lot permits.
                new_contracts = int(old_qty // next_future["lot"])
                new_qty = new_contracts * next_future["lot"]
                if new_contracts <= 0:
                    raise ValueError(f"Cannot roll {old_qty} units into lot {next_future['lot']}")
                open_cost = costs.futures_leg_cost(next_future["close"] * new_qty,
                                                   date.fromisoformat(day), "buy", futures_slippage_bps)
                fee = close_cost + open_cost
                state["cash"] -= fee
                state["costs"] += fee
                state["roll_basis_points"] += next_future["close"] - old_price
                state["future"] = {"expiry": next_future["expiry"], "lot": next_future["lot"],
                                   "contracts": new_contracts, "qty": new_qty,
                                   "last": next_future["close"], "entry": next_future["close"]}
                state["futures_rolls"] += 1
                trades.append({"date": day, "action": "ROLL_FUTURE", "expiry": next_future["expiry"],
                               "strike": 0, "price": next_future["close"], "premium": 0,
                               "contracts": new_contracts, "qty": new_qty,
                               "cost": fee, "cash": state["cash"]})
            else:
                # The last available contract cannot be rolled beyond the
                # requested sample. It has already been marked to settlement,
                # so closing here adds only the execution costs and leaves no
                # phantom expired future in the ending portfolio.
                fee = costs.futures_leg_cost(future["last"] * future["qty"],
                                             date.fromisoformat(day), "sell",
                                             futures_slippage_bps)
                state["cash"] -= fee
                state["costs"] += fee
                trades.append({"date": day, "action": "CLOSE_FUTURE_END",
                               "expiry": future["expiry"], "strike": 0,
                               "price": future["last"], "premium": 0,
                               "contracts": future["contracts"], "qty": future["qty"],
                               "cost": fee, "cash": state["cash"]})
                state["future"] = None
                state["recovery_basis"] = 0.0
            transitioned = True

        pending = state["pending_future"]
        if pending and day > pending["signal_day"] and not state["future"]:
            choice = choose_future(rows, day, end)
            if choice:
                contracts = int(pending["qty"] // choice["lot"])
                qty = contracts * choice["lot"]
                if contracts <= 0:
                    state["skipped"] += 1
                    state["pending_future"] = None
                    transitioned = True
                    continue
                fee = costs.futures_leg_cost(choice["close"] * qty, date.fromisoformat(day),
                                             "buy", futures_slippage_bps)
                required = 0.15 * choice["close"] * qty
                if state["cash"] - fee >= required:
                    state["cash"] -= fee
                    state["costs"] += fee
                    state["future"] = {"expiry": choice["expiry"], "lot": choice["lot"],
                                       "contracts": contracts, "qty": qty,
                                       "last": choice["close"], "entry": choice["close"]}
                    state["recovery_basis"] = (choice["close"] + pending["put_intrinsic"] -
                                               pending["put_premium"])
                    state["futures_entries"] += 1
                    trades.append({"date": day, "action": "BUY_FUTURE", "expiry": choice["expiry"],
                                   "strike": 0, "price": choice["close"], "premium": 0,
                                   "contracts": contracts, "qty": qty,
                                   "cost": fee, "cash": state["cash"]})
                    state["pending_future"] = None
                else:
                    state["skipped"] += 1
            else:
                state["skipped"] += 1
            transitioned = True

        if previous_spot is not None and not state["option"] and not transitioned:
            future = state["future"]
            if future:
                choice = choose_option(rows, "call", future["expiry"], previous_spot,
                                       state["recovery_basis"], otm, future["lot"])
                contracts = future["contracts"]
                kind = "call"
            else:
                near_future = choose_future(rows, day, end)
                choice = (choose_option(rows, "put", near_future["expiry"], previous_spot,
                                        0.0, otm, near_future["lot"]) if near_future else None)
                kind = "put"
                contracts = 0
                if choice:
                    contracts = int(state["cash"] // (choice["strike"] * choice["lot"]))
            if choice and contracts > 0:
                qty = contracts * choice["lot"]
                premium = choice["close"] * qty
                fee = costs.option_leg_cost(premium, date.fromisoformat(day),
                                            "sell_to_open", option_slippage_bps)
                candidate = {"type": kind, "strike": choice["strike"], "qty": qty}
                old_option = state["option"]
                state["option"] = candidate
                required = margin_required(state)
                state["option"] = old_option
                if state["cash"] + premium - fee >= required:
                    state["cash"] += premium - fee
                    state["premium"] += premium
                    state["costs"] += fee
                    state["put_entries" if kind == "put" else "call_entries"] += 1
                    state["option"] = {"type": kind, "strike": choice["strike"],
                                       "expiry": choice["expiry"], "lot": choice["lot"],
                                       "contracts": contracts, "qty": qty,
                                       "entry_premium": choice["close"],
                                       "mark": choice["settlement"]}
                    trades.append({"date": day, "action": "SELL_PUT" if kind == "put" else "SELL_CALL",
                                   "expiry": choice["expiry"], "strike": choice["strike"],
                                   "price": spot, "premium": choice["close"],
                                   "contracts": contracts, "qty": qty,
                                   "cost": fee, "cash": state["cash"]})
                else:
                    state["skipped"] += 1
            else:
                state["skipped"] += 1

        # Cash posted as option security or futures margin earns nothing in the
        # base case. A non-zero rate is available only as an explicit scenario.
        accrued = max(state["cash"], 0.0) * cash_rate / 252
        state["cash"] += accrued
        state["interest"] += accrued
        liability = state["option"]["mark"] * state["option"]["qty"] if state["option"] else 0.0
        nav = state["cash"] - liability
        benchmark = CAPITAL * tri[day] / tri0
        required = margin_required(state)
        equity.append({"date": day, "synthetic_nifty_wheel": nav, "nifty_tr": benchmark})
        positions.append({
            "date": day, "cash": state["cash"], "equity": nav, "spot": spot,
            "option_type": state["option"]["type"] if state["option"] else "",
            "option_expiry": state["option"]["expiry"] if state["option"] else "",
            "option_strike": state["option"]["strike"] if state["option"] else "",
            "option_qty": state["option"]["qty"] if state["option"] else 0,
            "option_mark": state["option"]["mark"] if state["option"] else 0,
            "future_expiry": state["future"]["expiry"] if state["future"] else "",
            "future_qty": state["future"]["qty"] if state["future"] else 0,
            "future_mark": state["future"]["last"] if state["future"] else 0,
            "recovery_basis": state["recovery_basis"], "margin_required": required,
            "margin_headroom": state["cash"] - required,
        })
        previous_spot = spot
    return state, trades, equity, positions


def write_chart(rows, output):
    import os
    import tempfile
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "wheel_strategy_matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from datetime import datetime

    dates = [datetime.strptime(row["date"], "%Y-%m-%d") for row in rows]
    fig, ax = plt.subplots(figsize=(12, 5.5), dpi=160)
    ax.plot(dates, [row["synthetic_nifty_wheel"] for row in rows], label="Synthetic NIFTY wheel", color="#6f42c1")
    ax.plot(dates, [row["nifty_tr"] for row in rows], label="NIFTY 50 total return", color="#d97706")
    ax.grid(axis="y", color="#d9dee5", linewidth=.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.yaxis.set_major_formatter(lambda value, _: f"INR {value/1e6:.0f}M")
    ax.set_title("Synthetic NIFTY Wheel: Monthly Options plus Futures", loc="left", fontweight="bold")
    ax.set_ylabel("Portfolio value")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--out", type=Path, default=BASE / "outputs_nifty")
    parser.add_argument("--strike-otm", type=float, default=0.05)
    parser.add_argument("--option-slippage-bps", type=float, default=25)
    parser.add_argument("--futures-slippage-bps", type=float, default=2)
    parser.add_argument("--cash-rate", type=float, default=DEFAULT_CASH_RATE,
                        help="Annual interest rate on positive cash (default: 0)")
    args = parser.parse_args()
    prices = load_prices(BASE / "data/real_prices.csv", args.end)
    tri = load_tri(BASE / "data/nifty50_tr.csv", args.end)
    derivative_path = BASE / "data/nifty_derivatives.csv"
    state, trades, equity, positions = run(
        prices, tri, derivative_path, args.strike_otm, args.option_slippage_bps,
        args.futures_slippage_bps, args.end, args.cash_rate)
    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(args.out / "trade_log.csv", trades)
    write_csv(args.out / "equity_curve.csv", equity)
    write_csv(args.out / "daily_positions.csv", positions)
    dates = [row["date"] for row in equity]
    summary = [dict(series=name, **metrics([row[name] for row in equity], dates))
               for name in ("synthetic_nifty_wheel", "nifty_tr")]
    write_csv(args.out / "summary.csv", summary)
    open_liability = (state["option"]["mark"] * state["option"]["qty"]
                      if state["option"] else 0.0)
    attribution = [{
        "starting_capital": CAPITAL, "premium_received": state["premium"],
        "option_cash_settlement": -state["option_settlement"],
        "futures_mtm": state["futures_mtm"], "cash_interest": state["interest"],
        "costs": -state["costs"], "open_option_liability": -open_liability,
        "ending_equity": equity[-1]["synthetic_nifty_wheel"],
    }]
    explained = sum(value for key, value in attribution[0].items() if key != "ending_equity")
    attribution[0]["reconciliation_error"] = explained - attribution[0]["ending_equity"]
    if abs(attribution[0]["reconciliation_error"]) > 0.01:
        raise AssertionError(f"NIFTY attribution failed: {attribution[0]}")
    write_csv(args.out / "pnl_attribution.csv", attribution)
    diagnostics = [{key: value for key, value in state.items()
                    if key not in ("option", "future", "pending_future")}]
    diagnostics[0]["assignment_rate"] = state["put_assignments"] / state["put_entries"] if state["put_entries"] else 0
    diagnostics[0]["call_away_rate"] = state["calls_away"] / state["call_entries"] if state["call_entries"] else 0
    write_csv(args.out / "diagnostics.csv", diagnostics)
    scenarios = [("base", args.strike_otm, args.option_slippage_bps, args.futures_slippage_bps),
                 ("strike_3pct", .03, args.option_slippage_bps, args.futures_slippage_bps),
                 ("strike_8pct", .08, args.option_slippage_bps, args.futures_slippage_bps),
                 ("option_slippage_10bps", args.strike_otm, 10, args.futures_slippage_bps),
                 ("option_slippage_50bps", args.strike_otm, 50, args.futures_slippage_bps),
                 ("futures_slippage_4bps", args.strike_otm, args.option_slippage_bps, 4)]
    sensitivity = []
    for name, strike, option_slip, future_slip in scenarios:
        scenario_equity = equity if name == "base" else run(
            prices, tri, derivative_path, strike, option_slip, future_slip,
            args.end, args.cash_rate)[2]
        row = {"scenario": name, "strike_otm": strike,
               "option_slippage_bps": option_slip, "futures_slippage_bps": future_slip}
        row.update(metrics([item["synthetic_nifty_wheel"] for item in scenario_equity], dates))
        sensitivity.append(row)
    write_csv(args.out / "sensitivity_summary.csv", sensitivity)
    write_chart(equity, args.out / "equity_curve.png")
    (args.out / "assumptions.json").write_text(json.dumps({
        "construction": "monthly cash-secured NIFTY put; ITM cash settlement triggers a next-session NIFTY futures purchase preserving the option's index units subject to whole-lot rounding; monthly calls cover futures; ITM call cash settlement closes futures",
        "entry": "previous-day NIFTY close selects 5% OTM strike; execution at current NSE option/future close",
        "options": "European cash settlement; monthly expiries identified by listed futures expiry",
        "futures": "daily variation margin at NSE settlement; rolled at expiry after OTM call",
        "margin": "full put strike cash reserve; otherwise max(15% futures notional, 20% short-call notional) as an offset proxy",
        "cash_interest_rate": args.cash_rate,
        "cash_interest_policy": "no interest on cash collateral or margin in the base case",
        "option_slippage_bps": args.option_slippage_bps,
        "futures_slippage_bps": args.futures_slippage_bps,
        "limitations": "EOD closes, no bid/ask or historical SPAN files; transitions execute at next-session close; expiry-day NIFTY close proxies the official option final-settlement index",
    }, indent=2))
    for row in summary:
        print(row)
    print(f"Trades {len(trades)}; puts {state['put_entries']}; assignments {state['put_assignments']}; "
          f"calls {state['call_entries']}; calls away {state['calls_away']}; rolls {state['futures_rolls']}")


if __name__ == "__main__":
    main()
