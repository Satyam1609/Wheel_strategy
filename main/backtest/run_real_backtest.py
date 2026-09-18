"""Exploratory stock-wheel backtest using NSE bhavcopy prices and options.

Uses NSE bhavcopy prices and observed option settlements. Corporate actions are
loaded from data/corporate_actions.csv; optional dividends are loaded from
data/dividends.csv. No synthetic prices or IVs are used.
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import date
from itertools import groupby
from pathlib import Path

from main.backtest import costs
from main.data_pipeline.fetch_nse_data import TICKERS


BASE = Path(__file__).resolve().parents[2]
CAPITAL = 20_000_000.0
RISK_FREE_RATE = 0.065
DEFAULT_CASH_RATE = 0.0


def load_prices(path, end, start=None):
    rows = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["date"] > end:
                break
            if start and row["date"] < start:
                continue
            if not all(row[t] for t in ("NIFTY", *TICKERS)):
                raise ValueError(f"Missing underlying price on {row['date']}")
            rows.append((row["date"], {t: float(row[t]) for t in ("NIFTY", *TICKERS)}))
    if not rows:
        raise ValueError("No prices in requested interval")
    return rows


def infer_lots(path, end, reference_path=None):
    """Legacy OPEN_INT is in shares; GCD by ticker/expiry infers contract size.

    The compact reference preserves contract lots previously validated from NSE
    turnover and open-interest divisibility. A GCD fallback supports newly
    downloaded legacy contracts. UDiFF NewBrdLotQty still takes precedence when
    it is present on an option row.
    """
    gcds = defaultdict(int)
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["date"] > end:
                break
            oi = int(float(row["open_interest"] or 0))
            if oi > 0:
                key = (row["ticker"], row["expiry"])
                gcds[key] = math.gcd(gcds[key], oi)
    reference_path = reference_path or BASE / "data/legacy_lot_sizes.csv"
    if reference_path.exists():
        with reference_path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                if row["expiry"] <= end:
                    gcds[(row["ticker"], row["expiry"])] = int(row["lot_size"])
    return gcds


def option_days(path, end, inferred_lots):
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for day, group in groupby(reader, key=lambda row: row["date"]):
            if day > end:
                break
            options = defaultdict(list)
            for row in group:
                lot = int(float(row["lot_size"])) if row["lot_size"] else inferred_lots[(row["ticker"], row["expiry"])]
                if lot <= 0:
                    continue
                options[row["ticker"]].append({
                    "expiry": row["expiry"], "type": row["option_type"],
                    "strike": float(row["strike"]), "close": float(row["close"]),
                    "settlement": float(row["settlement"]),
                    "volume": int(float(row["volume"])),
                    "oi": int(float(row["open_interest"])), "lot": lot,
                    "lot_inferred": not bool(row["lot_size"]),
                })
            yield day, options


def infer_entry_lot(day, ticker, choice):
    """Return the legacy contract lot inferred from consolidated open interest.

    ``option_days`` attaches the ticker/expiry GCD calculated by ``infer_lots``.
    Keeping that derived value in the processed input makes the backtest
    independent of the multi-gigabyte raw archive cache.
    """
    lot = int(choice.get("lot") or 0)
    oi = int(choice.get("oi") or 0)
    return lot if lot > 0 and (oi == 0 or oi % lot == 0) else None


def make_state(ticker):
    return dict(ticker=ticker, cash=CAPITAL/len(TICKERS), shares=0,
                basis=0.0, option=None, last_mark=0.0, cycles=0,
                spin_offs={}, spin_off_marks={}, spin_off_proceeds=0.0, rights_proceeds=0.0,
                assignments=0, calls_away=0, skipped=0, stale_marks=0,
                inferred_entries=0, unresolved_lots=0, premium=0.0, costs=0.0,
                put_entries=0, call_entries=0,
                option_realized_pnl=0.0, closed_premium=0.0,
                delivery_pnl=0.0, dividends=0.0, post_delivery_days=0,
                gross_basis=0.0, stock_cash_flow=0.0, interest=0.0)


def margin_proxy(option, spot, day):
    if not option:
        return 0.0
    notional = option["strike"] * option["qty"]
    remaining = (date.fromisoformat(option["expiry"]) - date.fromisoformat(day)).days
    itm = ((option["type"] == "put" and spot < option["strike"]) or
           (option["type"] == "call" and spot > option["strike"]))
    return max(0.20 * notional, 0.35 * notional if remaining <= 7 and itm else 0.0)


def margin_collateral(state, spot, option):
    return max(0.0, state["cash"]) + (0.8 * state["shares"] * spot if option and option["type"] == "call" else 0.0)


def select_option(rows, state, spot, day, end, strike_otm=0.05):
    kind = "put" if state["shares"] == 0 else "call"
    expiries = sorted({r["expiry"] for r in rows if r["type"] == kind and
                       day < r["expiry"] <= end and
                       (date.fromisoformat(r["expiry"]) - date.fromisoformat(day)).days >= 7})
    if not expiries:
        return None
    expiry = expiries[0]
    target = spot * (1 - strike_otm if kind == "put" else 1 + strike_otm)
    floor = max(target, state["basis"]) if kind == "call" else 0
    candidates = [r for r in rows if r["type"] == kind and r["expiry"] == expiry and
                  r["volume"] > 0 and r["oi"] > 0 and r["close"] > 0 and
                  (r["strike"] >= floor if kind == "call" else r["strike"] < spot)]
    if not candidates:
        return None
    return min(candidates, key=lambda r: (abs(r["strike"] - target), -r["volume"]))


def revised_expiry(active, rows, day):
    """Detect an exchange revision when the same listed strike reappears early."""
    candidates = [r["expiry"] for r in rows if r["type"] == active["type"] and
                  r["strike"] == active["strike"] and
                  day <= r["expiry"] < active["expiry"] and
                  (date.fromisoformat(active["expiry"]) - date.fromisoformat(r["expiry"])).days <= 3]
    return max(candidates) if candidates else None


def adjusted_reference_close(previous_close, actions):
    """Put yesterday's close on today's ex-action share/entitlement basis."""
    reference = previous_close
    for action in actions:
        kind = action["action"]
        if kind in ("BONUS", "SPLIT", "SPLIT_BONUS"):
            reference /= float(action["adjustment_factor"])
        elif kind == "RIGHTS":
            reference -= float(action["cash_benefit_per_share"])
        elif kind == "SPIN_OFF":
            reference -= float(action["spin_off_ratio"]) * float(action["provisional_value"])
    return reference


def settle(state, day, spot, trades, slippage_bps=25):
    opt = state["option"]
    if not opt or day < opt["expiry"]:
        return
    strike, qty = opt["strike"], opt["qty"]
    itm = (spot < strike) if opt["type"] == "put" else (spot > strike)
    intrinsic = max(strike - spot, 0) if opt["type"] == "put" else max(spot - strike, 0)
    state["option_realized_pnl"] += (opt["entry_premium"] - intrinsic) * qty
    state["closed_premium"] += opt["entry_premium"] * qty
    action = "PUT_EXPIRED" if opt["type"] == "put" else "CALL_EXPIRED"
    charge = 0.0
    if itm:
        charge = costs.assignment_cost(strike * qty, date.fromisoformat(day), slippage_bps,
                                       side="buy" if opt["type"] == "put" else "sell")
        state["costs"] += charge
        if opt["type"] == "put":
            state["cash"] -= strike * qty + charge
            state["stock_cash_flow"] -= strike * qty
            state["shares"] += qty
            state["basis"] = strike - opt["entry_premium"]
            state["gross_basis"] = strike
            state["stock_entry_day"] = day
            state["assignments"] += 1
            action = "ASSIGNED"
        else:
            state["cash"] += strike * qty - charge
            state["stock_cash_flow"] += strike * qty
            state["shares"] -= qty
            state["delivery_pnl"] += (strike - state["gross_basis"]) * qty
            if state.get("stock_entry_day"):
                state["post_delivery_days"] += (date.fromisoformat(day) - date.fromisoformat(state["stock_entry_day"])).days
            state["calls_away"] += 1
            action = "CALLED_AWAY"
    state["cycles"] += 1
    trades.append(dict(date=day, ticker=state["ticker"], action=action,
                       expiry=opt["expiry"], strike=strike, qty=qty,
                       premium=opt["entry_premium"], cost=charge,
                       cash=state["cash"], shares=state["shares"]))
    if action == "CALLED_AWAY" and state["shares"] > 0:
        residual = state["shares"]
        sale_value = residual*spot
        state["delivery_pnl"] += (spot - state["gross_basis"]) * residual
        state["stock_cash_flow"] += sale_value
        sale_cost = costs.assignment_cost(sale_value, date.fromisoformat(day), slippage_bps,
                                         market_execution=True)
        state["cash"] += sale_value-sale_cost
        state["costs"] += sale_cost
        state["shares"] = 0
        trades.append(dict(date=day,ticker=state["ticker"],action="SELL_RESIDUAL_SHARES",
                           expiry=opt["expiry"],strike=spot,qty=residual,premium=0,
                           cost=sale_cost,cash=state["cash"],shares=0))
    if action == "CALLED_AWAY":
        state["basis"] = 0.0
        state["gross_basis"] = 0.0
        state.pop("stock_entry_day", None)
    state["option"] = None
    state["last_mark"] = 0.0


def load_corporate_actions(path):
    actions = defaultdict(list)
    if not path.exists():
        return actions
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("effective_date") and row.get("ticker") and row.get("action"):
                actions[row["effective_date"]].append(row)
    return actions


def apply_corporate_actions(state, day, actions, applied, expiry_adjustments=None):
    for action in actions.get(day, []):
        if action.get("ticker") != state["ticker"]:
            continue
        kind = action["action"]
        active = state["option"]
        if kind == "EXPIRY_RESET":
            if active and active["expiry"] > day:
                if expiry_adjustments is not None:
                    expiry_adjustments.append(dict(date=day,ticker=state["ticker"],
                        old_expiry=active["expiry"],new_expiry=day,
                        option_type=active["type"],strike=active["strike"]))
                active["expiry"] = day
        elif kind == "SYMBOL_CHANGE":
            pass
        elif kind in ("BONUS", "SPLIT", "SPLIT_BONUS"):
            factor = float(action["adjustment_factor"])
            state["shares"] *= factor
            if state["basis"]:
                state["basis"] /= factor
            if state["gross_basis"]:
                state["gross_basis"] /= factor
            if active:
                active["strike"] = round(active["strike"] / factor / 0.05) * 0.05
                active["qty"] *= factor
                active["entry_premium"] /= factor
                state["last_mark"] /= factor
        elif kind == "RIGHTS":
            # Rights are sold for their NSE theoretical value on ex-date. A short
            # option is separately converted using the exchange's exact factor.
            benefit = float(action["cash_benefit_per_share"])
            proceeds = state["shares"] * benefit
            state["cash"] += proceeds
            state["rights_proceeds"] += proceeds
            if state["shares"]:
                state["basis"] -= benefit
            if active:
                factor = float(action["adjustment_factor"])
                active["strike"] = round(active["strike"] * factor / 0.05) * 0.05
                old_qty = active["qty"]
                active["qty"] = round(old_qty * float(action["revised_market_lot"]) / float(action["old_market_lot"]))
                state["last_mark"] *= old_qty / active["qty"]
                active["entry_premium"] *= old_qty / active["qty"]
        elif kind == "SPIN_OFF":
            symbol = action["spin_off_symbol"]
            quantity = state["shares"] * float(action["spin_off_ratio"])
            if quantity:
                state["spin_offs"][symbol] = quantity
                state["spin_off_marks"][symbol] = float(action["provisional_value"])
                state["basis"] -= float(action["provisional_value"]) * float(action["spin_off_ratio"])
        else:
            raise ValueError(f"Unsupported corporate action: {kind}")
        applied.append(dict(date=day, ticker=state["ticker"], action=kind,
                            adjustment_factor=action.get("adjustment_factor", ""),
                            shares_after=state["shares"], basis_after=state["basis"],
                            strike_after=(active["strike"] if active else ""),
                            spin_off_symbol=action.get("spin_off_symbol", ""),
                            spin_off_shares=(state["spin_offs"].get(action.get("spin_off_symbol"), 0))))


def run(prices, option_path, inferred_lots, strike_otm=0.05, slippage_bps=25,
        dividends=None, corporate_actions=None, spin_off_prices=None, nifty_tr=None,
        cash_rate=DEFAULT_CASH_RATE):
    states = {t: make_state(t) for t in TICKERS}
    benchmark = {t: dict(shares=CAPITAL / len(TICKERS) / prices[0][1][t],
                         cash=0.0, spin_offs={}, spin_off_marks={}) for t in TICKERS}
    trades, equity_rows, mark_gaps, expiry_adjustments, corporate_action_log, positions = [], [], [], [], [], []
    end = prices[-1][0]
    stream = iter(option_days(option_path, end, inferred_lots))
    next_day = next(stream, None)
    previous_prices = None
    for day, px in prices:
        options = defaultdict(list)
        while next_day and next_day[0] < day:
            next_day = next(stream, None)
        if next_day and next_day[0] == day:
            options = next_day[1]
            next_day = next(stream, None)
        daily = {"date": day}
        for ticker, state in states.items():
            spot = px[ticker]
            holding = benchmark[ticker]
            # The ex-date entitlement belongs to shares held at the previous
            # close, before today's expiry settlement or new option entry.
            dividend = (dividends or {}).get((day, ticker), 0.0)
            if dividend:
                state_credit = dividend * state["shares"]
                state["cash"] += state_credit
                state["dividends"] += state_credit
                holding["cash"] += dividend * holding["shares"]
            for symbol, quantity in state["spin_offs"].items():
                spin_dividend = (dividends or {}).get((day, symbol), 0.0) * quantity
                state["cash"] += spin_dividend
                state["dividends"] += spin_dividend
            for symbol, quantity in holding["spin_offs"].items():
                holding["cash"] += (dividends or {}).get((day, symbol), 0.0) * quantity
            apply_corporate_actions(state, day, corporate_actions or {}, corporate_action_log,
                                    expiry_adjustments)
            for action in (corporate_actions or {}).get(day, []):
                if action["ticker"] != ticker:
                    continue
                kind = action["action"]
                if kind in ("BONUS", "SPLIT", "SPLIT_BONUS"):
                    holding["shares"] *= float(action["adjustment_factor"])
                elif kind == "RIGHTS":
                    holding["cash"] += holding["shares"] * float(action["cash_benefit_per_share"])
                elif kind == "SPIN_OFF":
                    symbol = action["spin_off_symbol"]
                    holding["spin_offs"][symbol] = holding["shares"] * float(action["spin_off_ratio"])
                    holding["spin_off_marks"][symbol] = float(action["provisional_value"])
            for symbol, quote in (spin_off_prices or {}).get(day, {}).items():
                if symbol in holding["spin_offs"]:
                    holding["spin_off_marks"][symbol] = quote
                if symbol in state["spin_offs"]:
                    quantity = state["spin_offs"].pop(symbol)
                    state["spin_off_marks"].pop(symbol)
                    proceeds = quantity * quote
                    fee = costs.assignment_cost(proceeds, date.fromisoformat(day), slippage_bps,
                                                market_execution=True)
                    state["cash"] += proceeds - fee
                    state["spin_off_proceeds"] += proceeds
                    state["costs"] += fee
                    trades.append(dict(date=day,ticker=ticker,action="SELL_SPIN_OFF",
                                       spin_off_symbol=symbol,expiry="",strike=quote,qty=quantity,
                                       premium=0,cost=fee,cash=state["cash"],shares=state["shares"]))
            active = state["option"]
            if active:
                exact = any(r["expiry"] == active["expiry"] and r["type"] == active["type"] and
                            r["strike"] == active["strike"] for r in options[ticker])
                if not exact:
                    revised = revised_expiry(active, options[ticker], day)
                    if revised:
                        expiry_adjustments.append(dict(date=day,ticker=ticker,
                                                       old_expiry=active["expiry"],new_expiry=revised,
                                                       option_type=active["type"],strike=active["strike"]))
                        active["expiry"] = revised
            if active and day < active["expiry"]:
                marks = [r for r in options[ticker] if r["expiry"] == active["expiry"] and
                         r["type"] == active["type"] and r["strike"] == active["strike"]]
                if marks:
                    state["last_mark"] = marks[0]["settlement"]
                else:
                    state["stale_marks"] += 1
                    mark_gaps.append(dict(date=day,ticker=ticker,expiry=active["expiry"],
                                          option_type=active["type"],strike=active["strike"],
                                          last_settlement=state["last_mark"]))
            expired_today = bool(active and day >= active["expiry"])
            if expired_today:
                settle(state, day, spot, trades, slippage_bps)
            if not state["option"] and not expired_today:
                reference = (adjusted_reference_close(previous_prices[ticker],
                    [a for a in (corporate_actions or {}).get(day, []) if a["ticker"] == ticker])
                    if previous_prices is not None else None)
                choice = (select_option(options[ticker], state, reference, day, end, strike_otm)
                          if previous_prices is not None else None)
                if choice is None:
                    state["skipped"] += 1
                else:
                    lot = choice["lot"]
                    if choice["lot_inferred"]:
                        lot = infer_entry_lot(day,ticker,choice)
                        if lot is None:
                            state["unresolved_lots"] += 1
                            state["skipped"] += 1
                            choice = None
                    if choice is None:
                        accrued = state["cash"]*cash_rate/252
                        state["interest"] += accrued
                        daily[ticker] = state["cash"]+accrued+state["shares"]*spot + sum(
                            qty*state["spin_off_marks"][symbol] for symbol,qty in state["spin_offs"].items())
                        state["cash"] += accrued
                        continue
                    lots = (int(state["cash"] // (choice["strike"]*lot)) if state["shares"] == 0
                            else state["shares"] // lot)
                    if lots > 0:
                        candidate = dict(type=choice["type"], strike=choice["strike"],
                                         qty=lots*lot, expiry=choice["expiry"])
                        if margin_proxy(candidate, spot, day) > margin_collateral(state, spot, candidate):
                            lots = 0
                    if lots <= 0:
                        state["skipped"] += 1
                    else:
                        qty = lots*lot
                        premium = choice["close"]*qty
                        fee = costs.option_leg_cost(premium, date.fromisoformat(day), "sell_to_open", slippage_bps)
                        state["cash"] += premium-fee
                        state["premium"] += premium
                        state["put_entries" if choice["type"] == "put" else "call_entries"] += 1
                        state["costs"] += fee
                        state["inferred_entries"] += int(choice["lot_inferred"])
                        state["option"] = dict(type=choice["type"], strike=choice["strike"],
                                               expiry=choice["expiry"], qty=qty,
                                               entry_premium=choice["close"])
                        state["last_mark"] = choice["settlement"]
                        trades.append(dict(date=day, ticker=ticker,
                                           action="SELL_PUT" if choice["type"] == "put" else "SELL_CALL",
                                           expiry=choice["expiry"], strike=choice["strike"], qty=qty,
                                           premium=choice["close"], cost=fee,
                                           cash=state["cash"], shares=state["shares"],
                                           volume=choice["volume"], open_interest=choice["oi"],
                                           lot_size=lot, lot_inferred=choice["lot_inferred"]))
            accrued = state["cash"]*cash_rate/252
            state["cash"] += accrued
            state["interest"] += accrued
            equity = state["cash"] + state["shares"]*spot + sum(
                qty*state["spin_off_marks"][symbol] for symbol,qty in state["spin_offs"].items())
            if state["option"]:
                equity -= state["last_mark"]*state["option"]["qty"]
            daily[ticker] = equity
            active = state["option"]
            # 20% upfront SPAN+exposure proxy, rising to 35% for ITM
            # deliverables in the final seven calendar days. Fully secured
            # cash/share collateral is the binding strategy constraint.
            required_margin = margin_proxy(active, spot, day)
            collateral = margin_collateral(state, spot, active)
            positions.append(dict(date=day, ticker=ticker, cash=state["cash"], shares=state["shares"],
                                  spot=spot, option_type=active["type"] if active else "",
                                  option_strike=active["strike"] if active else "",
                                  option_qty=active["qty"] if active else 0,
                                  option_expiry=active["expiry"] if active else "",
                                  option_mark=state["last_mark"] if active else 0,
                                  margin_proxy=required_margin, collateral=collateral,
                                  margin_headroom=collateral-required_margin, equity=equity))
        daily["wheel"] = sum(daily[t] for t in TICKERS)
        daily["nifty_bh"] = CAPITAL*px["NIFTY"]/prices[0][1]["NIFTY"]
        if nifty_tr is not None:
            daily["nifty_tr"] = CAPITAL*nifty_tr[day]/nifty_tr[prices[0][0]]
        daily["universe_bh"] = sum(h["shares"]*px[t] + h["cash"] + sum(
            qty*h["spin_off_marks"][symbol] for symbol,qty in h["spin_offs"].items())
            for t,h in benchmark.items())
        equity_rows.append(daily)
        previous_prices = px
    return states, trades, equity_rows, mark_gaps, expiry_adjustments, corporate_action_log, positions


def metrics(series, dates, initial_capital=CAPITAL):
    years = (date.fromisoformat(dates[-1])-date.fromisoformat(dates[0])).days/365.25
    rets = [series[0]/initial_capital-1] + [series[i]/series[i-1]-1 for i in range(1,len(series))]
    mean = sum(rets)/len(rets)
    sd = (sum((x-mean)**2 for x in rets)/(len(rets)-1))**0.5
    peak=initial_capital;mdd=0
    for x in series:
        peak=max(peak,x);mdd=min(mdd,x/peak-1)
    downside = [x for x in rets if x < 0]
    downside_sd = (sum(x*x for x in downside) / max(1, len(downside)))**0.5
    peak = initial_capital
    mdd = 0.0
    peak_date = dates[0]
    best_peak_date = dates[0]
    trough_date = dates[0]
    for d, x in zip(dates, series):
        if x > peak:
            peak, peak_date = x, d
        drawdown = x / peak - 1
        if drawdown < mdd:
            mdd, best_peak_date, trough_date = drawdown, peak_date, d
    recovery_date = ""
    trough_index = dates.index(trough_date)
    prior_peak = series[dates.index(best_peak_date)]
    for d, x in zip(dates[trough_index:], series[trough_index:]):
        if x >= prior_peak:
            recovery_date = d
            break
    cagr = (series[-1]/initial_capital)**(1/years)-1
    return dict(start=initial_capital,end=series[-1],CAGR=cagr,
                AnnVol=sd*math.sqrt(252),
                Sharpe=(mean-RISK_FREE_RATE/252)/sd*math.sqrt(252) if sd else None,
                Sortino=(mean-RISK_FREE_RATE/252)/downside_sd*math.sqrt(252) if downside_sd else None,
                MDD=mdd, MDD_peak=best_peak_date, MDD_trough=trough_date,
                MDD_recovery=recovery_date, Calmar=cagr/abs(mdd) if mdd else None)


def load_dividends(path):
    """Load optional per-share cash dividends: date,ticker,dividend_per_share."""
    result = {}
    if not path.exists():
        return result
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("date") and row.get("ticker") and row.get("dividend_per_share"):
                result[(row["date"], row["ticker"])] = float(row["dividend_per_share"])
    return result


def load_spin_off_prices(path):
    quotes = defaultdict(dict)
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            quotes[row["date"]][row["symbol"]] = float(row["close"])
    return quotes


def load_nifty_tr(path, dates):
    with path.open(newline="") as handle:
        values = {row["date"]: float(row["total_return_index"]) for row in csv.DictReader(handle)}
    missing = sorted(set(dates) - set(values))
    if missing:
        raise ValueError(f"Official NIFTY TRI missing {len(missing)} price dates: {missing[:5]}")
    return values


def write_csv(path, rows):
    fields = sorted({k for row in rows for k in row})
    with path.open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields)
        writer.writeheader();writer.writerows(rows)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2020-01-29",
                    help="First trading date; default follows the 20-session formation window")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--out",type=Path,default=BASE/"outputs_real")
    ap.add_argument("--strike-otm", type=float, default=0.05)
    ap.add_argument("--slippage-bps", type=float, default=costs.DEFAULT_SLIPPAGE_BPS)
    ap.add_argument("--cash-rate", type=float, default=DEFAULT_CASH_RATE)
    args=ap.parse_args()
    prices=load_prices(BASE/"data/real_prices.csv",args.end,args.start)
    from main.backtest.select_universe import screen
    selection = screen(BASE/"data/real_options.csv", prices[0][0])
    nifty_tr = load_nifty_tr(BASE/"data/nifty50_tr.csv", [day for day, _ in prices])
    lots=infer_lots(BASE/"data/real_options.csv",args.end)
    dividends = load_dividends(BASE / "data" / "dividends.csv")
    corporate_actions = load_corporate_actions(BASE / "data" / "corporate_actions.csv")
    spin_off_prices = load_spin_off_prices(BASE / "data" / "spinoff_prices.csv")
    states,trades,equity,mark_gaps,expiry_adjustments,corporate_action_log,positions=run(
        prices, BASE/"data/real_options.csv", lots,
        strike_otm=args.strike_otm, slippage_bps=args.slippage_bps, dividends=dividends,
        corporate_actions=corporate_actions, spin_off_prices=spin_off_prices, nifty_tr=nifty_tr,
        cash_rate=args.cash_rate)
    args.out.mkdir(parents=True,exist_ok=True)
    write_csv(args.out/"trade_log.csv",trades)
    write_csv(args.out/"equity_curve.csv",equity)
    write_csv(args.out/"mark_gaps.csv",mark_gaps)
    write_csv(args.out/"expiry_adjustments.csv",expiry_adjustments)
    write_csv(args.out/"corporate_action_adjustments.csv",corporate_action_log)
    write_csv(args.out/"daily_positions.csv", positions)
    write_csv(BASE/"data/universe_selection.csv", selection)
    dates=[r["date"] for r in equity]
    summary=[dict(series=s,**metrics([r[s] for r in equity],dates)) for s in ("wheel","nifty_tr","nifty_bh","universe_bh")]
    write_csv(args.out/"summary.csv",summary)
    per_name = [dict(ticker=t, **metrics([r[t] for r in equity], dates, CAPITAL/len(TICKERS))) for t in TICKERS]
    write_csv(args.out/"per_name_summary.csv", per_name)
    attribution=[]
    for ticker, st in states.items():
        end_px = prices[-1][1][ticker]
        stock_pnl = st["stock_cash_flow"] + st["shares"]*end_px
        spin_value = st["spin_off_proceeds"] + sum(
            qty*st["spin_off_marks"][symbol] for symbol, qty in st["spin_offs"].items())
        option_liability = st["last_mark"]*st["option"]["qty"] if st["option"] else 0.0
        components = dict(premium_received=st["premium"], stock_delivery_and_mark_pnl=stock_pnl,
                          dividends=st["dividends"], rights_value=st["rights_proceeds"],
                          spinoff_value=spin_value, cash_interest=st["interest"],
                          costs=-st["costs"], open_option_liability=-option_liability)
        explained = CAPITAL/len(TICKERS)+sum(components.values())
        actual = equity[-1][ticker]
        if abs(explained-actual)>0.01:
            raise AssertionError(f"P&L attribution does not reconcile for {ticker}: {explained} vs {actual}")
        attribution.append(dict(ticker=ticker, **components, starting_capital=CAPITAL/len(TICKERS),
                                ending_equity=actual, reconciliation_error=explained-actual))
    write_csv(args.out/"pnl_attribution.csv", attribution)
    diag=[]
    for st in states.values():
        row={k:(v if k!="option" else bool(v)) for k,v in st.items()}
        row["assignment_rate"] = st["assignments"] / st["put_entries"] if st["put_entries"] else 0.0
        row["call_away_rate"] = st["calls_away"] / st["call_entries"] if st["call_entries"] else 0.0
        row["premium_capture_ratio"] = (st["option_realized_pnl"] / st["closed_premium"]
                                        if st["closed_premium"] else 0.0)
        row["average_post_delivery_days"] = st["post_delivery_days"] / st["calls_away"] if st["calls_away"] else 0.0
        diag.append(row)
    write_csv(args.out/"diagnostics.csv",diag)
    (args.out/"assumptions.json").write_text(json.dumps({
        "start_date": args.start,
        "universe_formation_window": "2020-01-01 through 2020-01-28 (20 trading sessions)",
        "source":"NSE bhavcopy, data/real_prices.csv and data/real_options.csv",
        "universe_selection":"Top 10 NSE stock-option names by 20-session average option turnover, plus the declared ADANIENT stress override; ranking in data/universe_top15_liquidity.csv",
        "nifty_tr":"Official NSE Indices total-return index; data/nifty50_tr.csv",
        "end_date":args.end,"entry_price":"traded option close, volume>0 and OI>0",
        "strike_reference":"previous trading day's close, transformed to ex-action basis when needed",
        "mark_price":"NSE settlement; last observed settlement when contract row missing",
        "lot_size":"UDiFF NewBrdLotQty or data/legacy_lot_sizes.csv; GCD of legacy share open interest is the fallback",
        "dividends":"NSE ex-date cash distributions credited to prior-close share holdings in wheel and equal-weight universe",
        "dividend_file": "data/dividends.csv (archived NSE register plus documented supplemental public rows)",
        "cash_interest_rate":args.cash_rate,"slippage_bps":args.slippage_bps,"strike_otm":args.strike_otm,
        "corporate_actions":"Verified NSE split/bonus/rights and demerger contract events; spun-off shares marked then sold by wheel at first listing close",
        "corporate_action_file": "data/corporate_actions.csv",
        "spin_off_prices":"data/spinoff_prices.csv (NSE cached equity bhavcopies; BE and EQ series)",
        "universe_benchmark":"Equal initial rupee allocation; corporate-action share units adjusted and spun-off shares retained; cash dividends included",
        "expiry_revisions":"detected when the same strike/type moves to an earlier expiry within 3 days",
        "residual_shares":"sold at stock close after call-away, with conservative delivery cost, to reset wheel to cash",
        "margin":"cash-secured puts and covered calls; 20% notional SPAN+exposure proxy, 35% for ITM deliverables in final 7 calendar days; 80% stock collateral value; no exchange SPAN file",
        "stt":"short-option writer pays option-sale STT and 0.1% share-delivery STT; purchaser, not writer, pays option-exercise STT",
        "equity_delivery_stamp":"0.015% on assigned share purchases; constant-rate approximation",
        "premium_capture":"realized option premium net of intrinsic settlement divided by premium sold on closed contracts",
    },indent=2))
    scenarios = [("base", args.strike_otm, args.slippage_bps),
                 ("strike_3pct", 0.03, args.slippage_bps),
                 ("strike_8pct", 0.08, args.slippage_bps),
                 ("slippage_10bps", args.strike_otm, 10),
                 ("slippage_50bps", args.strike_otm, 50)]
    sensitivity=[]
    for name, strike, slip in scenarios:
        if name == "base":
            scenario_equity = equity
        else:
            _, _, scenario_equity, _, _, _, _ = run(prices, BASE/"data/real_options.csv", lots,
                                               strike_otm=strike, slippage_bps=slip, dividends=dividends,
                                               corporate_actions=corporate_actions,
                                               spin_off_prices=spin_off_prices, nifty_tr=nifty_tr,
                                               cash_rate=args.cash_rate)
        row = {"scenario": name, "strike_otm": strike, "slippage_bps": slip}
        row.update({f"wheel_{metric}": value for metric, value in
                    metrics([r["wheel"] for r in scenario_equity], dates).items()})
        sensitivity.append(row)
    write_csv(args.out/"sensitivity_summary.csv", sensitivity)
    for row in summary:
        print(row)
    print(f"Trades: {len(trades)}; option entries with inferred lots: "
          f"{sum(st['inferred_entries'] for st in states.values())}; stale marks: {len(mark_gaps)}; "
          f"expiry revisions: {len(expiry_adjustments)}")


if __name__=="__main__":
    main()
