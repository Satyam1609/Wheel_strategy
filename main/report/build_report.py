"""Build a reviewable PDF report from the real-data backtest outputs."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BASE = Path(__file__).resolve().parents[2]
REAL = BASE / "outputs_real"
NIFTY = BASE / "outputs_nifty"
DATA = BASE / "data"


def read_csv(name):
    with (REAL / name).open(newline="") as f:
        return list(csv.DictReader(f))


def read_nifty_csv(name):
    with (NIFTY / name).open(newline="") as f:
        return list(csv.DictReader(f))


def read_json(path):
    with path.open() as f:
        return json.load(f)


def pct(value):
    return f"{float(value) * 100:.2f}%"


def money(value):
    return f"INR {float(value):,.0f}"


def num(value, digits=2):
    return f"{float(value):.{digits}f}"


styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="Body2", parent=styles["BodyText"], fontSize=8.7, leading=11, spaceAfter=5))
styles.add(ParagraphStyle(name="Section", parent=styles["Heading1"], fontSize=14, leading=17, textColor=colors.HexColor("#18324b"), spaceBefore=7, spaceAfter=6))
styles.add(ParagraphStyle(name="Sub", parent=styles["Heading2"], fontSize=10.3, leading=12.5, textColor=colors.HexColor("#18324b"), spaceBefore=5, spaceAfter=3))
styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=7.3, leading=9, textColor=colors.HexColor("#4c5661"), spaceAfter=3))
styles.add(ParagraphStyle(name="Callout", parent=styles["BodyText"], fontSize=8.2, leading=10.5, backColor=colors.HexColor("#fff6df"), borderColor=colors.HexColor("#d6a63a"), borderWidth=.5, borderPadding=5, spaceAfter=6))


def P(text, style="Body2"):
    return Paragraph(text, styles[style])


def table(rows, widths=None, size=7.4):
    header_style = ParagraphStyle("table_header", parent=styles["Small"], fontSize=size, leading=size + 1, textColor=colors.white)
    cell_style = ParagraphStyle("table_cell", parent=styles["Small"], fontSize=size, leading=size + 1.5, textColor=colors.black)
    wrapped = []
    for row_index, row in enumerate(rows):
        style = header_style if row_index == 0 else cell_style
        wrapped.append([value if isinstance(value, Paragraph) else Paragraph(str(value), style) for value in row])
    t = Table(wrapped, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#18324b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), size),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#c6ccd2")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6f8")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.drawRightString(A4[0] - 1.7 * cm, 1.1 * cm, f"Page {doc.page}")
    canvas.restoreState()


def build(output):
    summary = read_csv("summary.csv")
    diagnostics = read_csv("diagnostics.csv")
    trades = read_csv("trade_log.csv")
    equity = read_csv("equity_curve.csv")
    sensitivity = read_csv("sensitivity_summary.csv") if (REAL / "sensitivity_summary.csv").exists() else []
    per_name = read_csv("per_name_summary.csv")
    attribution = read_csv("pnl_attribution.csv")
    positions = read_csv("daily_positions.csv")
    with (DATA / "universe_selection.csv").open(newline="") as handle:
        selection = list(csv.DictReader(handle))
    with (DATA / "universe_top15_liquidity.csv").open(newline="") as handle:
        liquidity_ranking = list(csv.DictReader(handle))
    with (DATA / "corporate_action_audit.csv").open(newline="") as handle:
        action_audit = list(csv.DictReader(handle))
    with (DATA / "dividends.csv").open(newline="") as handle:
        dividend_count = sum(1 for _ in csv.DictReader(handle))
    assumptions = read_json(REAL / "assumptions.json")
    coverage = read_json(DATA / "coverage_summary.json")
    by_series = {r["series"]: r for r in summary}
    actions = Counter(r["action"] for r in trades)
    nifty_summary = {r["series"]: r for r in read_nifty_csv("summary.csv")}
    nifty_diag = read_nifty_csv("diagnostics.csv")[0]
    nifty_attr = read_nifty_csv("pnl_attribution.csv")[0]
    nifty_sensitivity = read_nifty_csv("sensitivity_summary.csv")

    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=1.7 * cm, leftMargin=1.7 * cm, topMargin=1.35 * cm, bottomMargin=1.5 * cm, title="Real-data Wheel Backtest Report")
    story = [
        P("Systematic Options: The Wheel Strategy on NSE Derivatives", "Title"),
        P(f"<b>What this report covers.</b> Part A tests the wheel on 11 NSE stock options. Part B tests a wheel-like strategy on NIFTY options and futures. Both use public daily market data through {assumptions['end_date']}. The stock results account for recorded dividends and corporate actions. The data and modelling limits are explained below.", "Callout"),
        P("1. Universe selection", "Section"),
        P("I ranked NSE stocks with listed options by their average daily option turnover over the first 20 trading days of 2020. The top ten form the main universe. This ranking ends on 28 January, before the backtest starts on 29 January, so later trading activity does not affect the ranking.", "Body2"),
    ]
    universe_rows = [["Rank", "Ticker", "Avg option turnover", "Avg OI contracts"]]
    for row in liquidity_ranking[:10]:
        universe_rows.append([row["turnover_rank"], row["ticker"],
                              f"INR {float(row['average_daily_option_turnover_inr_crore']):,.2f} crore/day",
                              f"{float(row['average_daily_open_interest_contracts']):,.0f}"])
    story += [table(universe_rows, [1.3*cm, 3.0*cm, 6.0*cm, 4.3*cm], 6.6),
              P("ADANIENT is the eleventh stock, added by hand to test a more volatile name. Because the assignment asks for rule-based selection, the full 11-stock list meets that requirement only partly. Its later price path was already known when it was added, which can bias the result. Treat this as a stress-test example, not an unbiased test of stock selection.", "Callout"),
              P("The top-15 ranking is in <tt>data/universe_top15_liquidity.csv</tt>. The first-day trading-activity check for the 11 stocks is in <tt>data/universe_selection.csv</tt>.", "Small"),
              P("2. Results at a glance", "Section"),
        P("All three portfolios start with INR 20 million. NIFTY 50 total return includes reinvested dividends. The 11-stock buy-and-hold benchmark includes recorded dividends and corporate-action benefits.", "Body2"),
    ]
    rows = [["Series", "End value", "CAGR", "Annual vol", "Sharpe", "Sortino", "MDD", "Calmar"]]
    labels = {"wheel": "Wheel portfolio", "nifty_tr": "NIFTY 50 total return", "universe_bh": "Universe buy-and-hold"}
    for key in ("wheel", "nifty_tr", "universe_bh"):
        r = by_series[key]
        rows.append([labels[key], money(r["end"]), pct(r["CAGR"]), pct(r["AnnVol"]), num(r["Sharpe"]), num(r["Sortino"]), pct(r["MDD"]), num(r["Calmar"])])
    story += [table(rows, [2.7 * cm, 2.7 * cm, 1.7 * cm, 1.8 * cm, 1.4 * cm, 1.5 * cm, 1.7 * cm, 1.4 * cm], 6.5), Spacer(1, 8)]
    story += [P("CAGR is average yearly growth. Annual volatility measures how much daily returns vary. Sharpe and Sortino compare return with risk; higher is better. MDD is the largest fall from a previous peak. Calmar compares yearly growth with that largest fall.", "Small")]
    drawdown_rows = [["Series", "Peak / MDD start", "Trough", "Recovery"]]
    for key in ("wheel", "nifty_tr", "universe_bh"):
        r = by_series[key]
        drawdown_rows.append([labels[key], r["MDD_peak"], r["MDD_trough"],
                              r["MDD_recovery"] or "Not recovered"])
    story += [table(drawdown_rows, [5.4 * cm, 3.1 * cm, 3.1 * cm, 3.1 * cm], 6.6), Spacer(1, 6)]
    story += [P(f"<b>Main result.</b> The stock wheel grew at {pct(by_series['wheel']['CAGR'])} a year, compared with {pct(by_series['nifty_tr']['CAGR'])} for NIFTY 50 total return and {pct(by_series['universe_bh']['CAGR'])} for buying and holding the same 11 stocks. Its day-to-day swings and worst loss from a peak were smaller, but its Sharpe ratio was below NIFTY 50. Option premiums did not make up for the return it missed. The March 2020 crash shows how short puts can lose sharply when stocks fall.", "Body2")]
    story += [Image(str(REAL / "real_equity_curves.png"), width=17.0 * cm, height=8.4 * cm), P("Figure 1. Portfolio equity curves from the real-data run.", "Small")]
    story += [Image(str(REAL / "real_drawdown.png"), width=17.0 * cm, height=6.8 * cm), P("Figure 2. Drawdown calculated from the wheel equity curve.", "Small")]

    story += [P("3. Part A: how the stock wheel works", "Section"),
              P(f"<b>Capital and entry.</b> INR 20 million is divided equally among {len(selection)} stocks. For each new trade, the strategy uses yesterday's stock close to choose a strike and today's recorded option close as the assumed sale price. It requires a positive option price, trading volume, and open interest. It chooses the nearest listed expiry that is at least seven calendar days away, and trades only whole exchange lots. Unused cash earns no interest in the base case. The 6.5% rate in Sharpe and Sortino is used only to judge performance; it is not added to the account.", "Body2"),
              P("<b>The cycle.</b> When a stock sleeve holds cash, it sells a put with a strike near 5% below the reference stock price and keeps enough cash to buy all shares if assigned. If the stock ends below the strike at expiry, the sleeve buys those shares at the strike. It then sells covered calls near 5% above the reference price, but never below its net purchase cost. If the stock ends above the call strike, the shares are delivered and the sleeve returns to cash. Otherwise it keeps the shares and tries another call. The strategy holds options to expiry; it has no early exit, stop, or roll rule. A mandatory delivery pays delivery costs. The margin estimate rises from 20% to 35% of the option's value when delivery risk is high in the final seven days.", "Body2"),
              P("<b>Why these rules?</b> A 5% strike rule can be repeated without estimating option delta or implied volatility; the 3% and 8% tests show how much results depend on that choice. Monthly expiries avoid frequent trading. Holding to expiry avoids assuming an unknown intraday exit price. The call price floor avoids knowingly selling shares below their net purchase cost, although it can leave a losing stock without an eligible call. Cash security and whole-lot rounding keep positions within the INR 2 crore account.", "Body2"),
              P(f"The trade log has <b>{len(trades):,} events</b>: {actions.get('SELL_PUT', 0)} put sales, {actions.get('ASSIGNED', 0)} put assignments, {actions.get('SELL_CALL', 0)} call sales, and {actions.get('CALLED_AWAY', 0)} call assignments, along with other events. Lot size had to be inferred for {sum(int(r['inferred_entries']) for r in diagnostics):,} entries. A missing current option price led to {sum(int(r['stale_marks']) for r in diagnostics):,} carried-forward marks, and {len(read_csv('expiry_adjustments.csv'))} listed expiries changed.", "Body2")]
    stock_logic = [["Decision", "Rule used by the engine"],
                   ["Reference price", "Yesterday's stock close, adjusted if a corporate action takes effect today"],
                   ["Expiry", "Nearest listed expiry with at least 7 calendar days left"],
                   ["Put strike", "Listed strike closest to 95% of the reference price, and below it"],
                   ["Call strike", "Listed strike closest to 105% of the reference price, but not below net share cost"],
                   ["Option data", "Recorded close, volume, and open interest must all be above zero"],
                   ["Sale / daily value", "Assume a sale at today's option close; use NSE settlement to value it later"],
                   ["Position size", "Round cash-backed puts and share-backed calls down to whole exchange lots"],
                   ["At expiry", "A put below its strike buys shares; a call above its strike delivers shares"]]
    story += [KeepTogether([P("Part A decision rules", "Sub"),
                            table(stock_logic, [3.5*cm, 12.0*cm], 6.7),
                            P("Example: RELIANCE closed at INR 1,479.85 on 29 January 2020. Five percent below that was INR 1,405.86. On 30 January, the strategy sold the available INR 1,400 put for INR 24.95 per share. Its INR 1.818 million allocation covered two lots of 500 shares. On 27 February the put finished in the money, so it bought 1,000 shares at INR 1,400. After the premium, the net share cost was INR 1,375.05 each, before delivery fees.", "Small")])]
    drows = [["Ticker", "CSP entries", "Assign %", "Call %", "Avg days", "Capture", "Premium", "Costs"]]
    for r in diagnostics:
        drows.append([r["ticker"], r["put_entries"], pct(r["assignment_rate"]), pct(r["call_away_rate"]), num(r["average_post_delivery_days"], 1), pct(r["premium_capture_ratio"]), money(r["premium"]), money(r["costs"])])
    story += [table(drows, [2.7 * cm, 1.2 * cm, 1.6 * cm, 1.4 * cm, 1.7 * cm, 1.5 * cm, 2.5 * cm, 2.3 * cm], 6.1),
              P("CSP entries counts every put sale, including contracts still open at the end. Avg days measures how long shares were held in cycles that ended with a call assignment. Capture compares option profit at expiry with the premiums received on completed contracts. It can be negative when assignment losses exceed premiums.", "Small")]
    story += [P("Risk and return by stock", "Sub")]
    nrows = [["Ticker", "CAGR", "Vol", "Sharpe", "Sortino", "MDD", "Peak", "Trough", "Recovery", "Calmar"]]
    for r in per_name:
        nrows.append([r["ticker"], pct(r["CAGR"]), pct(r["AnnVol"]), num(r["Sharpe"]),
                      num(r["Sortino"]), pct(r["MDD"]), r["MDD_peak"], r["MDD_trough"],
                      r["MDD_recovery"] or "not yet", num(r["Calmar"])])
    story += [table(nrows, [2.4*cm, 1.5*cm, 1.4*cm, 1.3*cm, 1.3*cm, 1.5*cm,
                            1.9*cm, 1.9*cm, 1.9*cm, 1.2*cm], 5.6),
              P(f"Each stock starts with INR 20 million divided by {len(selection)}. 'Not yet' means its earlier peak had not been regained by the final date. Exact values are in <tt>outputs_real/per_name_summary.csv</tt>.", "Small")]
    components = [("premium_received", "Option premiums"), ("stock_delivery_and_mark_pnl", "Stock delivery + mark"),
                  ("dividends", "Dividends"), ("rights_value", "Rights value"),
                  ("spinoff_value", "Spun-off stock"), ("cash_interest", "Cash interest"),
                  ("costs", "All costs"), ("open_option_liability", "Open option liability")]
    arows = [["P&amp;L component", "Portfolio INR"]]
    for key, label in components:
        arows.append([label, money(sum(float(r[key]) for r in attribution))])
    arows.append(["Ending equity (incl. INR 20m start)", money(sum(float(r["ending_equity"]) for r in attribution))])
    story += [KeepTogether([P("Where the profit and loss came from", "Sub"),
                           table(arows, [8*cm, 6.5*cm]),
                           P(f"Profit on completed share deliveries was {money(sum(float(r['delivery_pnl']) for r in diagnostics))}. It is already included in the stock line, which also values shares still held at the end; adding it again would count it twice.", "Small")])]
    name_attr_rows = [["Ticker", "Premium", "Stock P&amp;L", "Dividends + actions", "Costs", "Ending equity"]]
    for r in attribution:
        actions_value = float(r["dividends"]) + float(r["rights_value"]) + float(r["spinoff_value"])
        name_attr_rows.append([r["ticker"], money(r["premium_received"]),
                               money(r["stock_delivery_and_mark_pnl"]), money(actions_value),
                               money(r["costs"]), money(r["ending_equity"])])
    story += [P("Profit and loss by stock", "Sub"),
              table(name_attr_rows, [2.5*cm, 2.7*cm, 2.9*cm, 3.2*cm, 2.4*cm, 2.8*cm], 6.1),
              P("Costs appear as negative amounts. The full calculation, including any open option value, is in <tt>outputs_real/pnl_attribution.csv</tt>.", "Small")]

    story += [P("4. Data and costs", "Section"), P(f"The data collection checked weekdays from {coverage['window'][0]} through {coverage['window'][1]}. It found {coverage['price_dates']:,} stock-price dates, {coverage['option_dates']:,} option dates, and {coverage['option_rows']:,} option rows. On {coverage['dates_with_all_three_reports_missing']} weekdays none of the three NSE reports was available; one date had prices but no option report.", "Body2")]
    data_rows = [["Data source", "What it provides", "Main limitation"],
                 ["NSE stock and index reports", f"Daily closes for {len(selection)} stocks and NIFTY 50", "No intraday prices or guaranteed trade price"],
                 ["NSE option reports", "Daily option close, settlement, volume, open interest and lot size", "No bid/ask prices; many contracts did not trade"],
                 ["Corporate-action notices", "Dates and amounts for dividends, splits, bonuses, rights and demergers", "Extra public records were needed for two stocks"],
                 ["NIFTY 50 total-return index", "Official index value with dividends reinvested", "An investor would need a tracking fund to follow it"]]
    story += [KeepTogether([P("Data sources", "Sub"), table(data_rows, [3.5*cm, 6.2*cm, 5.8*cm], 6.4)])]
    crows = [["Coverage check", "Value"], ["Price dates", f"{coverage['price_dates']:,}"], ["Option dates", f"{coverage['option_dates']:,}"], ["Option rows", f"{coverage['option_rows']:,}"], ["Duplicate contract keys", str(coverage['duplicate_option_contract_keys'])], ["Price cells missing", str(sum(coverage['missing_price_cells'].values()))], ["Missing bid/ask fields", f"{coverage['missing_option_fields'].get('bid', 0):,} / {coverage['missing_option_fields'].get('ask', 0):,}"], ["Zero volume fields", f"{coverage['zero_option_fields'].get('volume', 0):,}"]]
    story += [table(crows, [5.7 * cm, 9.0 * cm]), Spacer(1, 8)]
    story += [P("The strategy chooses strikes using yesterday's stock close and assumes options sell at today's recorded close. Lot sizes come from NSE data or a checked estimate for older contracts. Dividends and corporate actions are applied on their effective dates. Puts are backed by cash and calls by held shares. The daily margin check uses an estimate of 20% of option value, rising to 35% near expiry when delivery is likely; held shares count at 80% of market value. These rates are assumptions, not actual exchange margin records. Full settings are in <tt>outputs_real/assumptions.json</tt>.", "Body2")]
    cost_rows = [["Cost item", "Applied rule"],
                 ["Brokerage", "INR 20 for every executed option, futures or delivery leg"],
                 ["Option exchange / tax", "0.035% of premium exchange charge; 18% GST on brokerage + exchange; SEBI INR 10/crore"],
                 ["Option-sale STT", "0.050% before Apr-2023; 0.0625% to Sep-2024; 0.100% to Mar-2026; 0.150% thereafter"],
                 ["Option slippage", "25 bps of premium in the base case; 10 and 50 bps sensitivity cases"],
                 ["Stamp duty", "Assigned share purchases pay 0.015% of delivery value (constant-rate approximation); futures buys pay 0.002%; option entries are sells"],
                 ["Physical stock delivery", "0.1% STT plus delivery charges; mandatory strike delivery has no slippage"],
                 ["Market stock sales", "Delivery costs plus 25 bps of notional for residual and spun-off-share sales"],
                 ["Futures legs", "0.00173% exchange charge, GST, SEBI fee, 2 bps notional slippage; buy stamp duty 0.002%"],
                 ["Futures-sale STT", "0.010% before Jun-2023; 0.0125% to Sep-2024; 0.020% thereafter"],
                 ["Futures roll", "Charged as two executions: sell expiring contract and buy next contract"]]
    story += [KeepTogether([P("Transaction-cost model", "Sub"),
                            table(cost_rows, [4.0*cm, 11.5*cm], 6.5),
                            P(f"Total estimated trading costs are {money(sum(float(r['costs']) for r in diagnostics))} for the stock wheel and {money(-float(nifty_attr['costs']))} for the NIFTY wheel. STT is India's securities transaction tax. GST is the goods and services tax. A basis point (bp) is 0.01%. The buyer of an exercised option pays option-exercise STT; this short-option strategy pays share-delivery STT when shares move.", "Small")])]
    story += [P("A split or bonus changes the number of shares and option units, while prices and cost per share adjust in the opposite direction. For a rights issue, the strategy uses the NSE strike and lot changes and adds the estimated value of the rights. A demerger creates shares in the new company; they are valued at an estimate until listing and then sold by the wheel at the first recorded close. A dividend is paid only when shares were held before the ex-date. Contract-expiry and symbol changes are logged.", "Body2")]
    audit_rows = [["Ticker", "Recorded event(s)", "Largest adjusted 1-day drop"]]
    for row in action_audit:
        audit_rows.append([row["ticker"], row["recorded_events"] or "No large action found",
                           f"{row['adjusted_largest_one_day_drop_pct']}% ({row['adjusted_largest_one_day_drop_date']})"])
    story += [KeepTogether([P(f"Corporate-action screen for all {len(selection)} names", "Sub"),
              table(audit_rows, [2.3 * cm, 9.4 * cm, 3.5 * cm], 6.5)]),
              P("This check compares the stock price before and after each day, accounting for recorded corporate actions. It can flag a large unexplained drop, but it cannot prove that every small payment or adjustment was captured. Dividends come from saved NSE records and documented public additions.", "Small"),
              P(f"<b>Data limits.</b> The option files have no bid or ask prices, so a recorded close may not have been available for the strategy to trade. The {dividend_count} dividend records in <tt>data/dividends.csv</tt> are credited only when shares were already held. Rights use NSE estimates. Shares from a demerger use an estimated value until they list. Actual daily exchange margin files were not used; the estimated margin and account balances are in <tt>outputs_real/daily_positions.csv</tt>.", "Callout")]

    if sensitivity:
        srows = [["Scenario", "Strike OTM", "Slippage", "CAGR", "Vol", "Sharpe", "MDD"]]
        scenario_labels = {"base": "Base: 5% target", "strike_3pct": "3% target",
                           "strike_8pct": "8% target", "slippage_10bps": "Low trading friction",
                           "slippage_50bps": "High trading friction"}
        for r in sensitivity:
            srows.append([scenario_labels.get(r["scenario"], r["scenario"]), pct(r["strike_otm"]), f"{r['slippage_bps']} bps", pct(r["wheel_CAGR"]), pct(r["wheel_AnnVol"]), num(r["wheel_Sharpe"]), pct(r["wheel_MDD"])])
        story += [KeepTogether([P("5. Sensitivity and stress narrative", "Section"),
                               table(srows, [3.2 * cm, 2.2 * cm, 2.1 * cm, 1.8 * cm, 1.8 * cm, 1.7 * cm, 1.9 * cm], 6.8)])]
        sensitivity_by_name = {r["scenario"]: r for r in sensitivity}
        story += [P(f"Changing the target strike from 5% to 3% below or above the stock changes the Sharpe ratio from {num(sensitivity_by_name['base']['wheel_Sharpe'])} to {num(sensitivity_by_name['strike_3pct']['wheel_Sharpe'])}; using 8% changes it to {num(sensitivity_by_name['strike_8pct']['wheel_Sharpe'])}. Changing assumed slippage from 10 to 50 basis points (0.10% to 0.50%) changes annual return only slightly. That does not prove real trades would fill at these prices because the data has no bid or ask quotes.", "Body2")]
    else:
        story += [P("5. Sensitivity and stress narrative", "Section")]
    wheel = by_series["wheel"]
    peak_day, trough_day = wheel["MDD_peak"], wheel["MDD_trough"]
    peak_positions = {r["ticker"]: r for r in positions if r["date"] == peak_day}
    trough_positions = {r["ticker"]: r for r in positions if r["date"] == trough_day}
    contributors = sorted(((ticker, float(trough_positions[ticker]["equity"])-float(row["equity"]))
                           for ticker, row in peak_positions.items()), key=lambda pair: pair[1])
    episode_trades = [r for r in trades if peak_day < r["date"] <= trough_day]
    start_shares = sum(float(r["shares"])*float(r["spot"]) for r in peak_positions.values())
    end_shares = sum(float(r["shares"])*float(r["spot"]) for r in trough_positions.values())
    def position_label(row):
        shares = int(float(row["shares"]))
        option = row["option_type"]
        return f"{shares} shares" + (f"; short {option} {float(row['option_strike']):g}" if option else "")
    stress_rows = [["Sleeve", "Peak position", "Trough position", "Stock move", "Equity change"]]
    for ticker, loss in contributors[:5]:
        start, finish = peak_positions[ticker], trough_positions[ticker]
        stress_rows.append([ticker, position_label(start), position_label(finish),
                            pct(float(finish["spot"])/float(start["spot"])-1), money(loss)])
    assignment_names = sorted({r["ticker"] for r in episode_trades if r["action"] == "ASSIGNED"})
    largest_ticker, largest_loss = contributors[0]
    largest_stock_move = float(trough_positions[largest_ticker]["spot"])/float(peak_positions[largest_ticker]["spot"])-1
    story += [P(f"The wheel's largest fall from an earlier peak was {pct(wheel['MDD'])}, from {peak_day} to {trough_day}. It regained that peak on {wheel['MDD_recovery'] or 'no date in the sample'}. Short puts were already open when the fall began. As stocks dropped, puts on {', '.join(assignment_names)} ended in the money and forced share purchases. The value of shares held rose from {money(start_shares)} to {money(end_shares)}. The five largest losses by stock are below.", "Body2"),
              table(stress_rows, [2.2*cm, 4.1*cm, 4.1*cm, 2.2*cm, 2.8*cm], 6.4),
              P(f"{largest_ticker} had the largest change in account value, {money(largest_loss)}, while its stock moved {pct(largest_stock_move)}. Stocks bought through assignment then kept falling. During this period the strategy made {sum(r['action'].startswith('SELL_') for r in episode_trades)} new option sales and paid {money(sum(float(r.get('cost') or 0) for r in episode_trades))} in recorded event costs. Daily cash, shares, and open option values are in <tt>outputs_real/daily_positions.csv</tt>.", "Body2")]

    nw = nifty_summary["synthetic_nifty_wheel"]
    nb = nifty_summary["nifty_tr"]
    part_b_rows = [["Series", "End value", "CAGR", "Vol", "Sharpe", "Sortino", "MDD", "Calmar"]]
    for label, row in (("Synthetic NIFTY wheel", nw), ("NIFTY 50 total return", nb)):
        part_b_rows.append([label, money(row["end"]), pct(row["CAGR"]), pct(row["AnnVol"]),
                            num(row["Sharpe"]), num(row["Sortino"]), pct(row["MDD"]), num(row["Calmar"])])
    story += [KeepTogether([P("6. Part B: implemented synthetic NIFTY wheel", "Section"),
              P("NIFTY options pay cash at expiry; they cannot deliver the index itself. To imitate the stock wheel, the strategy sells a monthly put backed by cash. If it ends in the money, the option pays its loss in cash and the strategy buys NIFTY futures on the next trading day. It then sells calls against the same index exposure. If a call ends in the money, it pays cash and the futures are sold. Otherwise the futures stay open and move to a new contract at expiry. The call strike cannot be below the price needed to recover the earlier put loss. Futures gains and losses are recorded each day, and each trade pays estimated costs.", "Body2")]),
              table(part_b_rows, [2.8*cm, 2.5*cm, 1.6*cm, 1.6*cm, 1.4*cm, 1.5*cm, 1.7*cm, 1.4*cm], 6.5),
              P(f"The synthetic wheel's worst fall ran from {nw['MDD_peak']} to {nw['MDD_trough']} and recovered on {nw['MDD_recovery'] or 'no date in the sample'}. NIFTY total return fell most from {nb['MDD_peak']} to {nb['MDD_trough']} and recovered on {nb['MDD_recovery'] or 'no date in the sample'}.", "Small"),
              Spacer(1, 6), Image(str(NIFTY / "equity_curve.png"), width=17.0*cm, height=7.8*cm),
              P("Figure 3. Implemented monthly synthetic NIFTY wheel versus NIFTY 50 total return.", "Small")]
    nifty_logic = [["Decision", "Rule used by the engine"],
                   ["Contracts", "Monthly NIFTY options that end when listed futures end; weekly options excluded"],
                   ["Strike", "Use yesterday's NIFTY close: put near 95%; call at least 105% and above recovery cost"],
                   ["Trade / daily value", "Assume today's recorded close for entry; use settlement prices for later option values"],
                   ["After put loss", "Pay cash on the put and buy futures next session for the same index units"],
                   ["Recovery cost", "Futures purchase price + put loss per unit - original put premium per unit"],
                   ["Futures gains/losses", "Add or subtract each day's futures price change directly from cash"],
                   ["After call expiry", "An in-the-money call pays cash and futures are sold; otherwise futures continue or roll"],
                   ["Account value", "Cash less the value of the short option; futures gains/losses are already in cash"]]
    story += [KeepTogether([P("Part B decision logic", "Sub"),
                            table(nifty_logic, [3.5*cm, 12.0*cm], 6.7)])]
    story += [P(f"From 1 January 2020 to 30 June 2026, the strategy sold {nifty_diag['put_entries']} puts; {pct(nifty_diag['assignment_rate'])} ended in the money and led to futures purchases. It sold {nifty_diag['call_entries']} calls; {pct(nifty_diag['call_away_rate'])} ended with a futures sale. Futures moved to a new contract {nifty_diag['futures_rolls']} times. On {nifty_diag['stale_option_marks']} option dates and {nifty_diag['stale_future_marks']} futures dates, a missing current value was replaced by the last available settlement. The strategy reserves enough cash to cover every put. While it holds futures and a short call, its estimated margin is the larger of 15% of futures value and 20% of call exposure. Security cash earns no interest in this base case.", "Body2")]
    comparison_rows = [["Issue", "Stock wheel", "Synthetic NIFTY wheel"],
                       ["Assignment", "Physical shares move at strike", "Option pays cash intrinsic; futures bought next session"],
                       ["Main risk", "A stock can fall suddenly; company events also matter", "One company matters less, but a market crash affects all exposure"],
                       ["Timing", "The option and delivered shares use the same stock", "NIFTY can move before futures are bought next day; futures can differ from the index"],
                       ["Roll", "No stock roll after delivery", f"{nifty_diag['futures_rolls']} futures rolls; each pays two legs; cumulative raw calendar spread {float(nifty_diag['roll_basis_points']):,.2f} index points"],
                       ["Margin", "Cash backs puts; held shares back calls at 80% of value", "Uses the larger of 15% futures or 20% call value; actual margin may differ"],
                       ["Lot size", "Each stock allocation rounds down to its own exchange lot", "NIFTY units round down when the exchange lot changes"],
                       ["Expiry choice", "Nearest monthly option with at least 7 days left", "Monthly options match futures; weekly trading would require more trades"]]
    story += [KeepTogether([P("Part A versus Part B mechanics and risk", "Sub"),
                            table(comparison_rows, [3.2*cm, 6.1*cm, 6.2*cm], 6.2)]),
              P("A futures price can differ from the NIFTY index. The strategy can lose if NIFTY moves between option expiry and the next day's futures purchase, or when it switches from an expiring future to a more expensive new one. The estimated margin credit for holding related positions lowers required cash, but it does not remove market risk. Using an index reduces single-company risk while retaining the risk of a broad market fall.", "Body2")]
    part_b_attr = [["Reconciled component", "INR"],
                   ["Starting capital", money(nifty_attr["starting_capital"])],
                   ["Option premium", money(nifty_attr["premium_received"])],
                   ["Option cash settlement", money(nifty_attr["option_cash_settlement"])],
                   ["Futures variation margin", money(nifty_attr["futures_mtm"])],
                   ["Cash interest", money(nifty_attr["cash_interest"])],
                   ["Costs", money(nifty_attr["costs"])],
                   ["Ending equity", money(nifty_attr["ending_equity"])]]
    nsrows = [["Scenario", "OTM", "Opt slip", "Fut slip", "CAGR", "Sharpe", "MDD"]]
    nifty_scenario_labels = {"base": "Base", "strike_3pct": "3% target",
                             "strike_8pct": "8% target", "option_slippage_10bps": "Low option friction",
                             "option_slippage_50bps": "High option friction",
                             "futures_slippage_1bps": "Low futures friction",
                             "futures_slippage_4bps": "High futures friction"}
    for row in nifty_sensitivity:
        nsrows.append([nifty_scenario_labels.get(row["scenario"], row["scenario"]), pct(row["strike_otm"]), f"{row['option_slippage_bps']} bps",
                       f"{row['futures_slippage_bps']} bps", pct(row["CAGR"]),
                       num(row["Sharpe"]), pct(row["MDD"])])
    story += [KeepTogether([P("Part B ledger and sensitivity", "Sub"),
                            table(part_b_attr, [7.5*cm, 5.2*cm], 7.0)]),
              Spacer(1, 6), table(nsrows, [3.3*cm, 1.5*cm, 2.0*cm, 2.0*cm, 1.7*cm, 1.6*cm, 1.8*cm], 6.5),
              P("The base NIFTY strategy earned less than buying and holding NIFTY total return, but its returns moved less and its worst fall was smaller. Choosing a 3% strike target improved return but increased the worst fall; an 8% target brought in less premium and earned less. Futures slippage has a greater effect than option slippage because it is charged on the full futures value.", "Body2"),
              P("At option expiry, the model calculates the cash payment from that day's NIFTY close because the archive does not provide a consistent separate final-settlement index value. It buys futures at the next day's recorded close, not the open. Actual bid/ask prices and past daily exchange margin files are unavailable. Only monthly options were used; weekly trading would create more trades and more risk close to expiry.", "Callout")]

    coverage_rows = [["Assignment item", "Report evidence", "Status"],
                     ["2020-01-01 to 2026-06-30 EOD data", "Section 4; 20-session formation window; backtest starts 2020-01-29", "Covered"],
                     ["Objective 8-15 stock liquidity screen", "Section 1; top 10 by turnover; ADANIENT is a disclosed override", "Partial"],
                     ["Put, delivery, call, sizing, exits and margin", "Section 3 rules, decision table and worked RELIANCE example", "Covered"],
                     ["Costs, STT and slippage sensitivity", "Section 4 cost table; Section 5 sensitivity", "Covered"],
                     ["Portfolio and per-name metrics / diagnostics", "Sections 2-3 tables and reconciled P&amp;L", "Covered"],
                     ["Benchmarks and worst-drawdown narrative", "NIFTY 50 TR, universe buy-and-hold, and March 2020 walk-through", "Covered"],
                     ["Synthetic-index design and comparison", "Section 6 mechanics, basis, roll, margin, lots and risk comparison", "Covered"],
                     ["Biases, sources, verdict and reproducibility", "Section 7 and machine-readable output files", "Covered"]]
    story += [P("7. Assignment checklist and limits", "Section"),
              table(coverage_rows, [4.6*cm, 8.5*cm, 2.0*cm], 6.3),
              P("Daily stock and option prices come from <link href='https://www.nseindia.com/all-reports'>NSE reports</link>. Dates with missing files are listed in <tt>data/source_manifest.json</tt>. Dividend and corporate-action sources appear beside each event in <tt>data/dividends.csv</tt> and <tt>data/corporate_actions.csv</tt>. NIFTY total return comes from <link href='https://www.niftyindices.com/reports/historical-data'>NSE Indices</link>. Tax rules are based on the <link href='https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies'>NSE tax guide</link>, and margin context comes from the <link href='https://www.nseindia.com/static/trade/members-faqs-margin-collection-and-reporting'>NSE margin FAQ</link>.", "Body2"),
              P("<b>What could make the results look too good?</b> The top-ten turnover ranking uses only days before trading starts. ADANIENT was added after its later behaviour was known, however, and choosing stocks with data through June 2026 can leave out companies that disappeared. The model chooses from today's option contracts and assumes it can trade at today's closing price, even though the file has no bid or ask quotes. Missing option prices carry forward the last settlement. Some corporate actions or dividends may be missing. Margin uses fixed estimates rather than actual past exchange requirements. The stock test starts on 29 January, while the NIFTY test starts on 1 January, so their annual returns do not cover exactly the same dates.", "Body2"),
              P(f"<b>Can this be traded as shown?</b> The stock wheel earned {pct(by_series['wheel']['CAGR'])} a year and the NIFTY futures wheel earned {pct(nw['CAGR'])}, compared with {pct(by_series['nifty_tr']['CAGR'])} for NIFTY 50 total return. Neither strategy earns interest on cash held as security. These results are useful for studying the rules, but executable prices and actual historical margins are needed before claiming the strategy is ready for live trading.", "Callout"),
              P("To rebuild the results, install <tt>requirements.txt</tt>, then follow the commands in <tt>README.md</tt>. The main scripts generate the data, backtests, charts, and this report in that order. Automated tests are under <tt>tests/</tt>.", "Body2")]
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=BASE / "output_pdf" / "Wheel_Strategy_Research_Report.pdf")
    args = parser.parse_args()
    build(args.output)
    print(args.output)
