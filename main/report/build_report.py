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
    canvas.drawString(1.7 * cm, 1.1 * cm, "Real-data NSE bhavcopy backtests | exploratory research")
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
        P(f"<b>Scope.</b> This report reads the current Part A stock-wheel outputs from <tt>outputs_real/</tt> and Part B synthetic NIFTY-wheel outputs from <tt>outputs_nifty/</tt>, produced from downloaded NSE equity and derivatives bhavcopies through {assumptions['end_date']}. Verified split, bonus, rights, demerger, and symbol events are applied to the stock wheel and equal-weight universe. The action screen and limitations below define the remaining gaps.", "Callout"),
        P("1. Universe selection", "Section"),
        P("All NSE stock-option underlyings are ranked by average option turnover during the first 20 trading sessions of 2020. The ten highest-turnover names form the objective liquidity core. The formation window ends on 28 January and trading begins on 29 January, so subsequent prices do not enter the turnover ranking.", "Body2"),
    ]
    universe_rows = [["Rank", "Ticker", "Avg option turnover", "Avg OI contracts"]]
    for row in liquidity_ranking[:10]:
        universe_rows.append([row["turnover_rank"], row["ticker"],
                              f"INR {float(row['average_daily_option_turnover_inr_crore']):,.2f} crore/day",
                              f"{float(row['average_daily_open_interest_contracts']):,.0f}"])
    story += [table(universe_rows, [1.3*cm, 3.0*cm, 6.0*cm, 4.3*cm], 6.6),
              P("ADANIENT is an explicit handpicked eleventh stress override. This means ten names satisfy the objective turnover rule, while the complete eleven-name portfolio does not strictly satisfy the assignment's request to avoid hand-picking. Selecting ADANIENT because its later path is known introduces hindsight bias. The override is retained for the stated stress test, so the results are a strategy demonstration rather than an unbiased universe-selection study.", "Callout"),
              P("The complete top-15 ranking and open-interest context are stored in <tt>data/universe_top15_liquidity.csv</tt>; first-day participation checks for the configured eleven names are stored in <tt>data/universe_selection.csv</tt>.", "Small"),
              P("2. Overview and verdict", "Section"),
        P("The table below is generated directly from <tt>outputs_real/summary.csv</tt>. NIFTY 50 uses the official NSE Indices total-return series, which reinvests constituent dividends. The selected-universe benchmark includes recorded dividends and non-cash entitlements.", "Body2"),
    ]
    rows = [["Series", "End value", "CAGR", "Annual vol", "Sharpe", "Sortino", "MDD", "Calmar"]]
    labels = {"wheel": "Wheel portfolio", "nifty_tr": "NIFTY 50 total return", "universe_bh": "Universe buy-and-hold"}
    for key in ("wheel", "nifty_tr", "universe_bh"):
        r = by_series[key]
        rows.append([labels[key], money(r["end"]), pct(r["CAGR"]), pct(r["AnnVol"]), num(r["Sharpe"]), num(r["Sortino"]), pct(r["MDD"]), num(r["Calmar"])])
    story += [table(rows, [2.7 * cm, 2.7 * cm, 1.7 * cm, 1.8 * cm, 1.4 * cm, 1.5 * cm, 1.7 * cm, 1.4 * cm], 6.5), Spacer(1, 8)]
    drawdown_rows = [["Series", "Peak / MDD start", "Trough", "Recovery"]]
    for key in ("wheel", "nifty_tr", "universe_bh"):
        r = by_series[key]
        drawdown_rows.append([labels[key], r["MDD_peak"], r["MDD_trough"],
                              r["MDD_recovery"] or "Not recovered"])
    story += [table(drawdown_rows, [5.4 * cm, 3.1 * cm, 3.1 * cm, 3.1 * cm], 6.6), Spacer(1, 6)]
    story += [P(f"<b>Finding.</b> The stock wheel finished below both benchmarks: {pct(by_series['wheel']['CAGR'])} CAGR versus {pct(by_series['nifty_tr']['CAGR'])} for NIFTY 50 TR and {pct(by_series['universe_bh']['CAGR'])} for the selected-universe buy-and-hold. It reduced volatility and maximum drawdown relative to both, but its Sharpe ratio remained below NIFTY TR. Premium collection therefore did not translate into superior total or risk-adjusted return. The March 2020 episode confirms the expected short-volatility and left-tail exposure.", "Body2")]
    story += [Image(str(REAL / "real_equity_curves.png"), width=17.0 * cm, height=8.4 * cm), P("Figure 1. Portfolio equity curves from the real-data run.", "Small")]
    story += [Image(str(REAL / "real_drawdown.png"), width=17.0 * cm, height=6.8 * cm), P("Figure 2. Drawdown calculated from the wheel equity curve.", "Small")]

    story += [P("3. Part A strategy specification and diagnostics", "Section"),
              P(f"<b>Capital and entry.</b> INR 20 million is split equally across {len(selection)} fixed sleeves. The universe is formed over the first 20 trading sessions (1-28 January 2020), and trading begins on 29 January. Each sleeve uses the previous trading day's adjusted underlying close as its strike reference and models sale at that day's observed option close. A contract needs positive premium, volume and open interest. The nearest listed monthly expiry must be at least seven calendar days away; size is rounded down to whole exchange lots. Cash collateral earns no interest. The 6.5% rate used in Sharpe and Sortino is a performance hurdle, not portfolio income; a yield-bearing collateral alternative is available through <tt>--cash-rate</tt> but is not the base case because no Treasury-bill or liquid-fund position is modeled.", "Body2"),
              P("<b>Wheel rules.</b> With no shares, sell the liquid put nearest 5% below the reference close and reserve the full strike obligation. An ITM put at expiry delivers shares at strike. With shares, sell the call nearest 5% above the reference close, never below the assigned net cost basis; if no qualifying quoted strike exists, sit out. An ITM call delivers the covered shares at strike and any residual shares are sold to reset to cash. Otherwise the expired leg is replaced in the next eligible session. There are no discretionary early profit takes, stops or rolls. Mandatory assignment has delivery costs but no execution slippage; modeled market sales do. A 20% option-margin proxy rises to 35% for ITM deliverables in the final seven calendar days, with pledged shares valued at 80% of close.", "Body2"),
              P("<b>Design rationale.</b> A 5% distance rule is transparent and reproducible without an implied-volatility surface; the 3% and 8% cases test its fragility. Monthly contracts limit turnover and are the standard stock-option maturity, while the seven-day entry floor avoids opening an almost-expired contract after a calendar disruption. Holding to expiry matches the physical wheel and avoids inventing unobserved intraday exit quotes. The call basis floor prevents the rules from deliberately crystallising a stock loss, although it can leave a deeply impaired holding without a quoted eligible call. Full cash security and whole-lot rounding keep leverage within the stated INR 2 crore capital base.", "Body2"),
              P(f"The engine recorded <b>{len(trades):,} trade-log events</b>, including {actions.get('SELL_PUT', 0)} short-put entries, {actions.get('ASSIGNED', 0)} assignments, {actions.get('SELL_CALL', 0)} covered-call entries, and {actions.get('CALLED_AWAY', 0)} call-aways. It inferred lots for {sum(int(r['inferred_entries']) for r in diagnostics):,} option entries, carried {sum(int(r['stale_marks']) for r in diagnostics):,} stale marks, and recorded {len(read_csv('expiry_adjustments.csv'))} expiry-date revisions.", "Body2")]
    stock_logic = [["Decision", "Rule used by the engine"],
                   ["Reference price", "Previous trading-day stock close, transformed to today's ex-action basis"],
                   ["Expiry", "Nearest quoted expiry after entry with at least 7 calendar days remaining"],
                   ["Put strike", "Listed strike nearest reference x 95%; strike must remain below reference"],
                   ["Call strike", "Listed strike nearest reference x 105%, but never below net share basis"],
                   ["Quote filter", "Observed option close &gt; 0, volume &gt; 0 and open interest &gt; 0"],
                   ["Execution / mark", "Sell at current-day option close; subsequently mark at NSE settlement"],
                   ["Sizing", "Put: floor(cash / strike / lot). Call: floor(shares / lot). Whole lots only"],
                   ["Expiry", "Stock close below put strike assigns shares; above call strike calls shares away"]]
    story += [KeepTogether([P("Part A decision logic", "Sub"),
                            table(stock_logic, [3.5*cm, 12.0*cm], 6.7),
                            P("Example: on 30 January 2020 RELIANCE used the 29 January close of INR 1,479.85. The 5% put target was INR 1,405.86; the nearest eligible strike was INR 1,400, sold at the observed INR 24.95 option close. The INR 1.818 million sleeve could secure two 500-share lots. At expiry on 27 February the put was ITM, so 1,000 shares were delivered at INR 1,400 and the net share basis became INR 1,375.05 before delivery costs.", "Small")])]
    drows = [["Ticker", "CSP entries", "Assign %", "Call %", "Avg days", "Capture", "Premium", "Costs"]]
    for r in diagnostics:
        drows.append([r["ticker"], r["put_entries"], pct(r["assignment_rate"]), pct(r["call_away_rate"]), num(r["average_post_delivery_days"], 1), pct(r["premium_capture_ratio"]), money(r["premium"]), money(r["costs"])])
    story += [table(drows, [2.7 * cm, 1.2 * cm, 1.6 * cm, 1.4 * cm, 1.7 * cm, 1.5 * cm, 2.5 * cm, 2.3 * cm], 6.1),
              P("CSP entries counts completed or still-open short-put initiations. Avg days covers completed delivery-to-call-away episodes. Premium capture is premium retained after intrinsic expiry settlement divided by premium sold on closed contracts; open contracts are excluded from both parts of that ratio.", "Small")]
    story += [P("Per-name risk and return", "Sub")]
    nrows = [["Ticker", "CAGR", "Vol", "Sharpe", "Sortino", "MDD", "Peak", "Trough", "Recovery", "Calmar"]]
    for r in per_name:
        nrows.append([r["ticker"], pct(r["CAGR"]), pct(r["AnnVol"]), num(r["Sharpe"]),
                      num(r["Sortino"]), pct(r["MDD"]), r["MDD_peak"], r["MDD_trough"],
                      r["MDD_recovery"] or "not yet", num(r["Calmar"])])
    story += [table(nrows, [2.4*cm, 1.5*cm, 1.4*cm, 1.3*cm, 1.3*cm, 1.5*cm,
                            1.9*cm, 1.9*cm, 1.9*cm, 1.2*cm], 5.6),
              P(f"Each sleeve begins with INR 20 million / {len(selection)}; 'not yet' means unrecovered by the end date. Exact figures are in <tt>outputs_real/per_name_summary.csv</tt>.", "Small")]
    components = [("premium_received", "Option premiums"), ("stock_delivery_and_mark_pnl", "Stock delivery + mark"),
                  ("dividends", "Dividends"), ("rights_value", "Rights value"),
                  ("spinoff_value", "Spun-off stock"), ("cash_interest", "Cash interest"),
                  ("costs", "All costs"), ("open_option_liability", "Open option liability")]
    arows = [["P&amp;L component", "Portfolio INR"]]
    for key, label in components:
        arows.append([label, money(sum(float(r[key]) for r in attribution))])
    arows.append(["Ending equity (incl. INR 20m start)", money(sum(float(r["ending_equity"]) for r in attribution))])
    story += [KeepTogether([P("Reconciled P&amp;L decomposition", "Sub"),
                           table(arows, [8*cm, 6.5*cm]),
                           P(f"Realized stock delivery P&amp;L was {money(sum(float(r['delivery_pnl']) for r in diagnostics))}; it is a subset of the stock line, which also marks remaining shares to the final close. Adding it again would double-count returns.", "Small")])]
    name_attr_rows = [["Ticker", "Premium", "Stock P&amp;L", "Dividends + actions", "Costs", "Ending equity"]]
    for r in attribution:
        actions_value = float(r["dividends"]) + float(r["rights_value"]) + float(r["spinoff_value"])
        name_attr_rows.append([r["ticker"], money(r["premium_received"]),
                               money(r["stock_delivery_and_mark_pnl"]), money(actions_value),
                               money(r["costs"]), money(r["ending_equity"])])
    story += [P("Per-name P&amp;L decomposition", "Sub"),
              table(name_attr_rows, [2.5*cm, 2.7*cm, 2.9*cm, 3.2*cm, 2.4*cm, 2.8*cm], 6.1),
              P("Costs are shown as negative values. The full reconciliation, including cash interest and open-option liability, is in <tt>outputs_real/pnl_attribution.csv</tt>.", "Small")]

    story += [P("4. Data and methodology", "Section"), P(f"The downloader checked weekdays from {coverage['window'][0]} through {coverage['window'][1]}. It found {coverage['price_dates']:,} price dates, {coverage['option_dates']:,} option dates, and {coverage['option_rows']:,} option rows. {coverage['dates_with_all_three_reports_missing']} weekdays had all three NSE reports missing; one date had prices but no options report.", "Body2")]
    data_rows = [["Dataset", "Granularity and use", "Known deficiency"],
                 ["NSE equity/index bhavcopy", f"Daily closes for {len(selection)} stocks and NIFTY 50", "No intraday path or executable close quote"],
                 ["NSE F&amp;O bhavcopy", "Daily contract close, settlement, volume, OI and lot fields", "No bid/ask or Greeks; many zero-volume rows"],
                 ["NSE and public action notices", "Ex-date dividends, splits, bonuses, rights and demergers", "Supplemental public rows are required where the saved NSE register lacks a selected name"],
                 ["NSE Indices NIFTY 50 TRI", "Official daily total-return benchmark", "Benchmark is investable only through a tracking vehicle"]]
    story += [KeepTogether([P("Source inventory", "Sub"), table(data_rows, [3.5*cm, 6.2*cm, 5.8*cm], 6.4)])]
    crows = [["Coverage check", "Value"], ["Price dates", f"{coverage['price_dates']:,}"], ["Option dates", f"{coverage['option_dates']:,}"], ["Option rows", f"{coverage['option_rows']:,}"], ["Duplicate contract keys", str(coverage['duplicate_option_contract_keys'])], ["Price cells missing", str(sum(coverage['missing_price_cells'].values()))], ["Missing bid/ask fields", f"{coverage['missing_option_fields'].get('bid', 0):,} / {coverage['missing_option_fields'].get('ask', 0):,}"], ["Zero volume fields", f"{coverage['zero_option_fields'].get('volume', 0):,}"]]
    story += [table(crows, [5.7 * cm, 9.0 * cm]), Spacer(1, 8)]
    story += [P("Execution uses traded option closes and prior-day stock closes for strike choice. Lot sizes come from NSE fields or checked legacy inference. Dividends and corporate events are applied on ex-dates; short-option sale STT and share-delivery STT are charged. Puts are fully cash-secured and calls share-covered. The 20%/35% SPAN-plus-delivery proxy is checked daily against cash and haircut share collateral. Full assumptions are machine-readable in <tt>outputs_real/assumptions.json</tt>.", "Body2")]
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
                            P(f"Cumulative modeled costs are {money(sum(float(r['costs']) for r in diagnostics))} for Part A and {money(-float(nifty_attr['costs']))} for Part B. Option exercise STT is borne by the purchaser and is therefore not charged to this short-option writer; delivery STT is charged where shares move.", "Small")])]
    story += [P("For splits and bonuses, held share and open-option quantities scale by the exchange factor while strike, premium and cost basis scale inversely. The rights event uses the NSE strike and lot adjustment and credits modeled rights value; demergers create a separate spun-off claim, provisionally marked then sold at its first NSE listing close. Recorded cash dividends are credited to prior-close holdings on the ex-date. Expiry resets and symbol changes are recorded in the action log.", "Body2")]
    audit_rows = [["Ticker", "Recorded event(s)", "Largest adjusted 1-day drop"]]
    for row in action_audit:
        audit_rows.append([row["ticker"], row["recorded_events"] or "No large action found",
                           f"{row['adjusted_largest_one_day_drop_pct']}% ({row['adjusted_largest_one_day_drop_date']})"])
    story += [KeepTogether([P(f"Corporate-action screen for all {len(selection)} names", "Sub"),
              table(audit_rows, [2.3 * cm, 9.4 * cm, 3.5 * cm], 6.5)]),
              P("The screen compares adjacent raw closes after applying recorded entitlements. It can identify large discontinuities; it cannot establish that every small corporate distribution is captured. Cash dividends come from the saved NSE register plus documented supplemental public rows for newly selected names.", "Small"),
              P(f"<b>Interpretation limits.</b> Bid and ask quotes were absent, so entry and mark prices use traded close and settlement fields. The {dividend_count} dated dividend records in <tt>data/dividends.csv</tt> are credited to shares held before each ex-date session. Rights are monetized at NSE theoretical values; spun-off shares use the special pre-open implied value until listing, then NSE closes. Margin is a proxy, not a historical exchange SPAN replay; see <tt>outputs_real/daily_positions.csv</tt>. Performance is exploratory, not a production claim.", "Callout")]

    if sensitivity:
        srows = [["Scenario", "Strike OTM", "Slippage", "CAGR", "Vol", "Sharpe", "MDD"]]
        for r in sensitivity:
            srows.append([r["scenario"], pct(r["strike_otm"]), f"{r['slippage_bps']} bps", pct(r["wheel_CAGR"]), pct(r["wheel_AnnVol"]), num(r["wheel_Sharpe"]), pct(r["wheel_MDD"])])
        story += [KeepTogether([P("5. Sensitivity and stress narrative", "Section"),
                               table(srows, [3.2 * cm, 2.2 * cm, 2.1 * cm, 1.8 * cm, 1.8 * cm, 1.7 * cm, 1.9 * cm], 6.8)])]
        sensitivity_by_name = {r["scenario"]: r for r in sensitivity}
        story += [P(f"The strike choice matters: moving from 5% to 3% OTM changes Sharpe from {num(sensitivity_by_name['base']['wheel_Sharpe'])} to {num(sensitivity_by_name['strike_3pct']['wheel_Sharpe'])}; moving to 8% changes it to {num(sensitivity_by_name['strike_8pct']['wheel_Sharpe'])}. The 10-50 bps slippage range changes CAGR by only about 0.05 percentage points, but that narrow modeled range cannot validate fills when every bid/ask field is missing.", "Body2")]
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
    story += [P(f"The wheel's worst drawdown was {pct(wheel['MDD'])}, from {peak_day} to {trough_day}, with recovery on {wheel['MDD_recovery'] or 'no date in the sample'}. Cash-secured short puts were already open at the peak. During the episode the rules forced assignments in {', '.join(assignment_names)}. Stock exposure rose from {money(start_shares)} to {money(end_shares)}. The five largest sleeve losses and endpoint positions are below.", "Body2"),
              table(stress_rows, [2.2*cm, 4.1*cm, 4.1*cm, 2.2*cm, 2.8*cm], 6.4),
              P(f"The largest sleeve contributor was {largest_ticker}, which changed by {money(largest_loss)} as its underlying moved {pct(largest_stock_move)}. Assigned sleeves then carried delivered stock into the sell-off. The trade log shows {sum(r['action'].startswith('SELL_') for r in episode_trades)} new option sales and {money(sum(float(r.get('cost') or 0) for r in episode_trades))} of logged event costs during this episode. Daily option liabilities, cash and shares are in <tt>outputs_real/daily_positions.csv</tt>.", "Body2")]

    nw = nifty_summary["synthetic_nifty_wheel"]
    nb = nifty_summary["nifty_tr"]
    part_b_rows = [["Series", "End value", "CAGR", "Vol", "Sharpe", "Sortino", "MDD", "Calmar"]]
    for label, row in (("Synthetic NIFTY wheel", nw), ("NIFTY 50 total return", nb)):
        part_b_rows.append([label, money(row["end"]), pct(row["CAGR"]), pct(row["AnnVol"]),
                            num(row["Sharpe"]), num(row["Sortino"]), pct(row["MDD"]), num(row["Calmar"])])
    story += [KeepTogether([P("6. Part B: implemented synthetic NIFTY wheel", "Section"),
              P("NIFTY options settle in cash, so an ITM put cannot deliver an index basket. This implementation sells monthly cash-secured puts and, after an ITM expiry, buys the nearest monthly NIFTY futures contract on the next session. It then writes calls against the same number of index units. An ITM call settles in cash and closes the futures; an OTM call leaves the futures in place and triggers a roll at futures expiry. Calls cannot be struck below the recovery basis. Futures are marked to NSE settlement daily, transaction costs and slippage are charged on every futures leg, and lot changes preserve index units rounded down to a whole new lot.", "Body2")]),
              table(part_b_rows, [2.8*cm, 2.5*cm, 1.6*cm, 1.6*cm, 1.4*cm, 1.5*cm, 1.7*cm, 1.4*cm], 6.5),
              P(f"The synthetic wheel's maximum drawdown ran from {nw['MDD_peak']} to {nw['MDD_trough']} and recovered on {nw['MDD_recovery'] or 'no date in the sample'}; NIFTY TR ran from {nb['MDD_peak']} to {nb['MDD_trough']} and recovered on {nb['MDD_recovery'] or 'no date in the sample'}.", "Small"),
              Spacer(1, 6), Image(str(NIFTY / "equity_curve.png"), width=17.0*cm, height=7.8*cm),
              P("Figure 3. Implemented monthly synthetic NIFTY wheel versus NIFTY 50 total return.", "Small")]
    nifty_logic = [["Decision", "Rule used by the engine"],
                   ["Contract set", "NIFTY option expiries matching listed futures expiries; weekly options excluded"],
                   ["Reference / strike", "Previous-day NIFTY close; put near 95%, call at or above max(105%, recovery basis)"],
                   ["Execution / mark", "Option and futures entry at current close; options marked to settlement"],
                   ["Synthetic assignment", "ITM put pays intrinsic; next session buys futures preserving index units"],
                   ["Recovery basis", "Futures entry + put intrinsic per unit - original put premium per unit"],
                   ["Futures accounting", "Daily settlement variation margin is credited/debited directly to cash"],
                   ["Call-away / roll", "ITM call pays intrinsic and closes futures; OTM call retains and rolls futures"],
                   ["NAV / cash", "Cash - short-option liability; futures P&amp;L is already in cash; zero cash interest"]]
    story += [KeepTogether([P("Part B decision logic", "Sub"),
                            table(nifty_logic, [3.5*cm, 12.0*cm], 6.7)])]
    story += [P(f"Across 2020-01-01 to 2026-06-30, the engine sold {nifty_diag['put_entries']} puts; {pct(nifty_diag['assignment_rate'])} settled ITM and initiated futures exposure. It sold {nifty_diag['call_entries']} calls, with {pct(nifty_diag['call_away_rate'])} ending in a synthetic call-away, and completed {nifty_diag['futures_rolls']} futures rolls. It recorded {nifty_diag['stale_option_marks']} stale option marks and {nifty_diag['stale_future_marks']} stale futures marks, which retain the last settlement. The account reserves the full put strike obligation; while futures and a short call are held it uses the larger of 15% of futures notional and 20% of call notional as a documented margin proxy. Cash posted as security or margin earns no interest in the Part B base case.", "Body2")]
    comparison_rows = [["Issue", "Stock wheel", "Synthetic NIFTY wheel"],
                       ["Assignment", "Physical shares move at strike", "Option pays cash intrinsic; futures bought next session"],
                       ["Primary risk", "Market beta plus single-name gaps and corporate events", "Diversified index beta, but concentrated market-crash exposure"],
                       ["Basis / timing", "Option and delivered stock share one underlying", "Expiry spot settlement versus next-session futures entry creates gap and basis risk"],
                       ["Roll", "No stock roll after delivery", f"{nifty_diag['futures_rolls']} futures rolls; each pays two legs; cumulative raw calendar spread {float(nifty_diag['roll_basis_points']):,.2f} index points"],
                       ["Margin offsets", "Cash-secured put; covered stock supports call after 20% haircut", "Uses max(15% futures, 20% call), assuming an offset; actual historical SPAN may differ"],
                       ["Lot granularity", "Each stock sleeve rounds independently to its exchange lot", "One index lot controls all units; lot revisions round exposure down to a whole new lot"],
                       ["Expiry choice", "Nearest monthly with at least 7 DTE", "Monthly expiries aligned to futures; weekly would add turnover and near-expiry gamma"]]
    story += [KeepTogether([P("Part A versus Part B mechanics and risk", "Sub"),
                            table(comparison_rows, [3.2*cm, 6.1*cm, 6.2*cm], 6.2)]),
              P("Futures basis normally converges toward spot at expiry, but this engine can still lose from the gap between option settlement and the next-session futures purchase, and from the price difference between expiring and next-month futures at a roll. Margin offsets reduce the proxy requirement rather than eliminating economic leverage. The index removes company-specific delivery shocks, while leaving the portfolio exposed to a common market sell-off across every constituent.", "Body2")]
    part_b_attr = [["Reconciled component", "INR"],
                   ["Starting capital", money(nifty_attr["starting_capital"])],
                   ["Option premium", money(nifty_attr["premium_received"])],
                   ["Option cash settlement", money(nifty_attr["option_cash_settlement"])],
                   ["Futures variation margin", money(nifty_attr["futures_mtm"])],
                   ["Cash interest", money(nifty_attr["cash_interest"])],
                   ["Costs", money(nifty_attr["costs"])],
                   ["Ending equity", money(nifty_attr["ending_equity"])]]
    nsrows = [["Scenario", "OTM", "Opt slip", "Fut slip", "CAGR", "Sharpe", "MDD"]]
    for row in nifty_sensitivity:
        nsrows.append([row["scenario"], pct(row["strike_otm"]), f"{row['option_slippage_bps']} bps",
                       f"{row['futures_slippage_bps']} bps", pct(row["CAGR"]),
                       num(row["Sharpe"]), pct(row["MDD"])])
    story += [KeepTogether([P("Part B ledger and sensitivity", "Sub"),
                            table(part_b_attr, [7.5*cm, 5.2*cm], 7.0)]),
              Spacer(1, 6), table(nsrows, [3.3*cm, 1.5*cm, 2.0*cm, 2.0*cm, 1.7*cm, 1.6*cm, 1.8*cm], 6.5),
              P("The base case ended below NIFTY total return but with lower volatility and a materially smaller maximum drawdown. The 3% OTM case improved return while deepening drawdown; 8% OTM reduced both premium income and return. Futures slippage matters more than option-premium slippage because it is charged on full futures notional.", "Body2"),
              P("The option expiry cash debit uses intrinsic value calculated from the expiry-day NIFTY close because the historical archive does not supply the official final-settlement index as a clean separate field throughout the sample. Entry uses the next session's observed close, not its open, and historical SPAN files and executable bid/ask quotes are unavailable. These are material implementation limits. Weekly expiries were excluded by matching option expiries to listed NIFTY futures expiries; a weekly version would have higher turnover and near-expiry gamma exposure.", "Callout")]

    coverage_rows = [["Assignment item", "Report evidence", "Status"],
                     ["2020-01-01 to 2026-06-30 EOD data", "Section 4; 20-session formation window; backtest starts 2020-01-29", "Covered"],
                     ["Objective 8-15 stock liquidity screen", "Section 1; top 10 by turnover; ADANIENT is a disclosed override", "Partial"],
                     ["Put, delivery, call, sizing, exits and margin", "Section 3 rules, decision table and worked RELIANCE example", "Covered"],
                     ["Costs, STT and slippage sensitivity", "Section 4 cost table; Section 5 sensitivity", "Covered"],
                     ["Portfolio and per-name metrics / diagnostics", "Sections 2-3 tables and reconciled P&amp;L", "Covered"],
                     ["Benchmarks and worst-drawdown narrative", "NIFTY 50 TR, universe buy-and-hold, and March 2020 walk-through", "Covered"],
                     ["Synthetic-index design and comparison", "Section 6 mechanics, basis, roll, margin, lots and risk comparison", "Covered"],
                     ["Biases, sources, verdict and reproducibility", "Section 7 and machine-readable output files", "Covered"]]
    story += [P("7. Assignment coverage, limitations and reproducibility", "Section"),
              table(coverage_rows, [4.6*cm, 8.5*cm, 2.0*cm], 6.3),
              P("Daily equity and F&amp;O bhavcopies come from <link href='https://www.nseindia.com/all-reports'>NSE reports</link>; cache paths and missing dates appear in <tt>data/source_manifest.json</tt>, while archive URL patterns are in <tt>main/data_pipeline/fetch_nse_data.py</tt>. Event and dividend sources are recorded row by row in <tt>data/corporate_actions.csv</tt> and <tt>data/dividends.csv</tt>. Benchmark: <link href='https://www.niftyindices.com/reports/historical-data'>NSE Indices historical TRI</link>. Tax: <link href='https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies'>NSE STT rates and payer</link>. Margin: <link href='https://www.nseindia.com/static/trade/members-faqs-margin-collection-and-reporting'>NSE margin FAQ</link>.", "Body2"),
              P("<b>Remaining biases.</b> The turnover ranking uses only the 20 sessions before trading, so it avoids using later turnover directly. However, ADANIENT is a hindsight-based stress override, and requiring clean records through June 2026 can favour names with continuous surviving listings. Same-day option closes are not executable quotes; choosing from the day's chain and filling at that close remains optimistic even though strike targets use the prior close. Bid/ask fields are absent, zero-volume rows are rejected, missing marks use the last settlement, and the final-settlement index is approximated by the expiry-day NIFTY close. Corporate-action and dividend screens may miss small events. The 20%/35% stock and 15%/20% index margin coefficients are static proxies rather than historical SPAN replays. Part A starts on 29 January after formation, while the independent Part B implementation uses the full 1 January window; their headline CAGRs are therefore not perfectly matched-window estimates.", "Body2"),
              P(f"<b>Deployability verdict.</b> The stock wheel returned {pct(by_series['wheel']['CAGR'])} annualized and the synthetic NIFTY wheel returned {pct(nw['CAGR'])}, versus {pct(by_series['nifty_tr']['CAGR'])} for NIFTY 50 total return. Neither implementation credits interest on option security or futures-margin cash. The evidence is not sufficient for a production deployment claim until execution prices and historical margins are tested with more realistic data.", "Callout"),
              P("Run <tt>python3 -m main.data_pipeline.fetch_nifty_tr</tt>, <tt>python3 -m main.data_pipeline.extract_nifty_derivatives</tt>, <tt>python3 -m main.backtest.run_real_backtest</tt>, <tt>python3 -m main.backtest.plot_real_results</tt>, <tt>python3 -m main.backtest.run_nifty_wheel</tt>, and finally <tt>python3 -m main.report.build_report</tt>. Tests are isolated under <tt>tests/</tt>. Install <tt>requirements.txt</tt> first.", "Body2")]
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=BASE / "output_pdf" / "Wheel_Strategy_Research_Report.pdf")
    args = parser.parse_args()
    build(args.output)
    print(args.output)
