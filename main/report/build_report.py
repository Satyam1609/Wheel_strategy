"""Build a reviewable PDF report from the real-data backtest outputs."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BASE = Path(__file__).resolve().parents[2]
REAL = BASE / "outputs_real"
DATA = BASE / "data"


def read_csv(name):
    with (REAL / name).open(newline="") as f:
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
styles.add(ParagraphStyle(name="Body2", parent=styles["BodyText"], fontSize=9, leading=12, spaceAfter=6))
styles.add(ParagraphStyle(name="Section", parent=styles["Heading1"], fontSize=14, leading=17, textColor=colors.HexColor("#18324b"), spaceBefore=8, spaceAfter=7))
styles.add(ParagraphStyle(name="Sub", parent=styles["Heading2"], fontSize=10.5, leading=13, textColor=colors.HexColor("#18324b"), spaceBefore=6, spaceAfter=4))
styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=7.5, leading=9.5, textColor=colors.HexColor("#4c5661"), spaceAfter=4))
styles.add(ParagraphStyle(name="Callout", parent=styles["BodyText"], fontSize=8.5, leading=11, backColor=colors.HexColor("#fff6df"), borderColor=colors.HexColor("#d6a63a"), borderWidth=.5, borderPadding=6, spaceAfter=8))


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
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.drawString(1.7 * cm, 1.1 * cm, "Real-data NSE bhavcopy backtest | exploratory research")
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
    with (DATA / "corporate_action_audit.csv").open(newline="") as handle:
        action_audit = list(csv.DictReader(handle))
    with (DATA / "dividends.csv").open(newline="") as handle:
        dividend_count = sum(1 for _ in csv.DictReader(handle))
    assumptions = read_json(REAL / "assumptions.json")
    coverage = read_json(DATA / "coverage_summary.json")
    by_series = {r["series"]: r for r in summary}
    actions = Counter(r["action"] for r in trades)

    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=1.7 * cm, leftMargin=1.7 * cm, topMargin=1.5 * cm, bottomMargin=1.7 * cm, title="Real-data Wheel Backtest Report")
    story = [
        P("Systematic Options: The Wheel Strategy on NSE Derivatives", "Title"),
        P("Research Report — Brindco Quant Researcher Take-Home Assignment", "Sub"),
        P(f"Prepared by: Satyam &nbsp;|&nbsp; Report generated {date.today().isoformat()}", "Small"),
        P(f"<b>Scope.</b> This report reads the current outputs from <tt>outputs_real/</tt>, produced from downloaded NSE equity and derivatives bhavcopies through {assumptions['end_date']}. Verified split, bonus, rights, demerger, and symbol events are applied to the wheel and equal-weight universe. The action screen and limitations below define the remaining gaps.", "Callout"),
        P("1. Overview and verdict", "Section"),
        P("The table below is generated directly from <tt>outputs_real/summary.csv</tt>. NIFTY 50 uses the official NSE Indices total-return series, which reinvests constituent dividends. The selected-universe benchmark includes recorded dividends and non-cash entitlements.", "Body2"),
    ]
    rows = [["Series", "End value", "CAGR", "Annual vol", "Sharpe", "Sortino", "MDD", "Calmar"]]
    labels = {"wheel": "Wheel portfolio", "nifty_tr": "NIFTY 50 total return", "universe_bh": "Universe buy-and-hold"}
    for key in ("wheel", "nifty_tr", "universe_bh"):
        r = by_series[key]
        rows.append([labels[key], money(r["end"]), pct(r["CAGR"]), pct(r["AnnVol"]), num(r["Sharpe"]), num(r["Sortino"]), pct(r["MDD"]), num(r["Calmar"])])
    story += [table(rows, [2.7 * cm, 2.7 * cm, 1.7 * cm, 1.8 * cm, 1.4 * cm, 1.5 * cm, 1.7 * cm, 1.4 * cm], 6.5), Spacer(1, 8)]
    story += [Image(str(REAL / "real_equity_curves.png"), width=17.0 * cm, height=8.4 * cm), P("Figure 1. Portfolio equity curves from the real-data run.", "Small")]
    story += [Image(str(REAL / "real_drawdown.png"), width=17.0 * cm, height=6.8 * cm), P("Figure 2. Drawdown calculated from the wheel equity curve.", "Small")]

    story += [P("2. Part A strategy specification and diagnostics", "Section"),
              P("<b>Capital and entry.</b> INR 20 million is split equally across 12 fixed sleeves. Each sleeve waits until the second price date, uses the previous trading day's adjusted underlying close as its strike reference, and models sale at that day's observed option close. A contract needs positive premium, volume and open interest. The nearest listed monthly expiry must be at least seven calendar days away; size is rounded down to whole exchange lots. Unused cash earns an assumed 6.5% annual rate, accrued over 252 sessions.", "Body2"),
              P("<b>Wheel rules.</b> With no shares, sell the liquid put nearest 5% below the reference close and reserve the full strike obligation. An ITM put at expiry delivers shares at strike. With shares, sell the call nearest 5% above the reference close, never below the assigned net cost basis; if no qualifying quoted strike exists, sit out. An ITM call delivers the covered shares at strike and any residual shares are sold to reset to cash. Otherwise the expired leg is replaced in the next eligible session. There are no discretionary early profit takes, stops or rolls. Mandatory assignment has delivery costs but no execution slippage; modeled market sales do. A 20% option-margin proxy rises to 35% for ITM deliverables in the final seven calendar days, with pledged shares valued at 80% of close.", "Body2"),
              P(f"The engine recorded <b>{len(trades):,} trade-log events</b>, including {actions.get('SELL_PUT', 0)} short-put entries, {actions.get('ASSIGNED', 0)} assignments, {actions.get('SELL_CALL', 0)} covered-call entries, and {actions.get('CALLED_AWAY', 0)} call-aways. It inferred lots for {sum(int(r['inferred_entries']) for r in diagnostics):,} option entries, carried {sum(int(r['stale_marks']) for r in diagnostics):,} stale marks, and recorded {len(read_csv('expiry_adjustments.csv'))} expiry-date revisions.", "Body2")]
    drows = [["Ticker", "CSPs", "Assign %", "Call %", "Avg days", "Capture", "Premium", "Costs"]]
    for r in diagnostics:
        drows.append([r["ticker"], r["put_entries"], pct(r["assignment_rate"]), pct(r["call_away_rate"]), num(r["average_post_delivery_days"], 1), pct(r["premium_capture_ratio"]), money(r["premium"]), money(r["costs"])])
    story += [table(drows, [2.7 * cm, 1.2 * cm, 1.6 * cm, 1.4 * cm, 1.7 * cm, 1.5 * cm, 2.5 * cm, 2.3 * cm], 6.1),
              P("CSPs counts short-put entries. Avg days covers completed delivery-to-call-away episodes. Capture is realized option premium less intrinsic settlement losses, divided by total premium sold; open contracts enter the denominator until expiry.", "Small")]
    story += [P("Per-name risk and return", "Sub")]
    nrows = [["Ticker", "CAGR", "Vol", "Sharpe", "Sortino", "MDD", "Peak", "Trough", "Recovery", "Calmar"]]
    for r in per_name:
        nrows.append([r["ticker"], pct(r["CAGR"]), pct(r["AnnVol"]), num(r["Sharpe"]),
                      num(r["Sortino"]), pct(r["MDD"]), r["MDD_peak"], r["MDD_trough"],
                      r["MDD_recovery"] or "not yet", num(r["Calmar"])])
    story += [table(nrows, [2.4*cm, 1.5*cm, 1.4*cm, 1.3*cm, 1.3*cm, 1.5*cm,
                            1.9*cm, 1.9*cm, 1.9*cm, 1.2*cm], 5.6),
              P("Each sleeve begins with INR 20 million / 12; 'not yet' means unrecovered by the end date. Exact figures are in <tt>outputs_real/per_name_summary.csv</tt>.", "Small")]
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

    story += [P("3. Data and methodology", "Section"), P(f"The downloader checked weekdays from {coverage['window'][0]} through {coverage['window'][1]}. It found {coverage['price_dates']:,} price dates, {coverage['option_dates']:,} option dates, and {coverage['option_rows']:,} option rows. {coverage['dates_with_all_three_reports_missing']} weekdays had all three NSE reports missing; one date had prices but no options report.", "Body2")]
    story += [P("Universe selection", "Sub"),
              P(f"The original model defined a fixed {len(selection)}-name F&amp;O shortlist spanning energy, banks, IT, industrials, autos, and NBFCs. TCS represented the lower-volatility sleeve; TATAMOTORS and ADANIENT supplied cyclical and idiosyncratic stress. We retained this qualitative choice and tested option participation on {selection[0]['formation_date']} before the first strategy entry. Eligibility required at least 250 option contracts traded, 1 million summed share open interest, and 15 rows with both volume and open interest; all 12 passed. Exact readings are in <tt>data/universe_selection.csv</tt>.", "Body2"),
              P("<b>Assignment gap.</b> This checks liquidity only within an already chosen shortlist. It does not satisfy the brief's requested objective selection from the full F&amp;O candidate pool, and the fixed names have survivorship bias. A compliant new universe needs an ex-ante all-market screen and a rebuilt backtest; the present performance should be read with that limitation.", "Callout")]
    crows = [["Coverage check", "Value"], ["Price dates", f"{coverage['price_dates']:,}"], ["Option dates", f"{coverage['option_dates']:,}"], ["Option rows", f"{coverage['option_rows']:,}"], ["Duplicate contract keys", str(coverage['duplicate_option_contract_keys'])], ["Price cells missing", str(sum(coverage['missing_price_cells'].values()))], ["Missing bid/ask fields", f"{coverage['missing_option_fields'].get('bid', 0):,} / {coverage['missing_option_fields'].get('ask', 0):,}"], ["Zero volume fields", f"{coverage['zero_option_fields'].get('volume', 0):,}"]]
    story += [table(crows, [5.7 * cm, 9.0 * cm]), Spacer(1, 8)]
    story += [P("Execution uses traded option closes and prior-day stock closes for strike choice. Lot sizes come from NSE fields or checked legacy inference. Dividends and corporate events are applied on ex-dates; short-option sale STT and share-delivery STT are charged. Puts are fully cash-secured and calls share-covered. The 20%/35% SPAN-plus-delivery proxy is checked daily against cash and haircut share collateral. Full assumptions are machine-readable in <tt>outputs_real/assumptions.json</tt>.", "Body2")]
    story += [P("For splits and bonuses, held share and open-option quantities scale by the exchange factor while strike, premium and cost basis scale inversely. The rights event uses the NSE strike and lot adjustment and credits modeled rights value; demergers create a separate spun-off claim, provisionally marked then sold at its first NSE listing close. Recorded cash dividends are credited to prior-close holdings on the ex-date. Expiry resets and symbol changes are recorded in the action log.", "Body2")]
    audit_rows = [["Ticker", "Recorded event(s)", "Largest adjusted 1-day drop"]]
    for row in action_audit:
        audit_rows.append([row["ticker"], row["recorded_events"] or "No large action found",
                           f"{row['adjusted_largest_one_day_drop_pct']}% ({row['adjusted_largest_one_day_drop_date']})"])
    story += [KeepTogether([P("Corporate-action screen for all twelve names", "Sub"),
              table(audit_rows, [2.3 * cm, 9.4 * cm, 3.5 * cm], 6.5)]),
              P("The screen compares adjacent raw closes after applying recorded entitlements. It can identify large discontinuities; it cannot establish that every small corporate distribution is captured. Cash dividends are extracted separately from the NSE action register.", "Small"),
              P(f"<b>Interpretation limits.</b> Bid and ask quotes were absent, so entry and mark prices use traded close and settlement fields. The {dividend_count} dated dividend records in <tt>data/dividends.csv</tt> are credited to shares held before each ex-date session. Rights are monetized at NSE theoretical values; spun-off shares use the special pre-open implied value until listing, then NSE closes. Margin is a proxy, not a historical exchange SPAN replay; see <tt>outputs_real/daily_positions.csv</tt>. Performance is exploratory, not a production claim.", "Callout")]

    if sensitivity:
        srows = [["Scenario", "Strike OTM", "Slippage", "CAGR", "Vol", "Sharpe", "MDD"]]
        for r in sensitivity:
            srows.append([r["scenario"], pct(r["strike_otm"]), f"{r['slippage_bps']} bps", pct(r["wheel_CAGR"]), pct(r["wheel_AnnVol"]), num(r["wheel_Sharpe"]), pct(r["wheel_MDD"])])
        story += [KeepTogether([P("4. Sensitivity and stress narrative", "Section"),
                               table(srows, [3.2 * cm, 2.2 * cm, 2.1 * cm, 1.8 * cm, 1.8 * cm, 1.7 * cm, 1.9 * cm], 6.8)])]
        story += [P("The strike choice matters: moving from 5% to 3% OTM lowers Sharpe from 0.66 to 0.58; moving to 8% lowers it to 0.53. The 10-50 bps slippage range changes CAGR by only about 0.05 percentage points, but that narrow modeled range cannot validate fills when every bid/ask field is missing.", "Body2")]
    else:
        story += [P("4. Sensitivity and stress narrative", "Section")]
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
    axis_loss = next(loss for ticker, loss in contributors if ticker == "AXISBANK")
    axis_stock_move = float(trough_positions["AXISBANK"]["spot"])/float(peak_positions["AXISBANK"]["spot"])-1
    story += [P(f"The wheel's worst drawdown was {pct(wheel['MDD'])}, from {peak_day} to {trough_day}, with recovery on {wheel['MDD_recovery'] or 'no date in the sample'}. Cash-secured short puts were already open at the peak. At the 27 February expiry, the rules forced two assignments, in TATAMOTORS and LT; both then sold covered calls. Stock exposure rose from {money(start_shares)} to {money(end_shares)}. The five largest sleeve losses and endpoint positions are below.", "Body2"),
              table(stress_rows, [2.2*cm, 4.1*cm, 4.1*cm, 2.2*cm, 2.8*cm], 6.4),
              P(f"AXISBANK lost {money(axis_loss)} without holding shares at either endpoint: its open short put was marked against a {pct(axis_stock_move)} underlying move. TATAMOTORS and LT lost through delivered shares after the two assignments. The trade log shows {sum(r['action'].startswith('SELL_') for r in episode_trades)} new option sales and {money(sum(float(r.get('cost') or 0) for r in episode_trades))} of logged event costs during this episode. Daily option liabilities, cash and shares are in <tt>outputs_real/daily_positions.csv</tt>.", "Body2")]

    story += [KeepTogether([P("5. Part B: synthetic index wheel design", "Section"), P("NIFTY and BANKNIFTY options are cash-settled, so a stock-style physical wheel cannot be copied directly. A concrete synthetic construction is: sell a cash-secured OTM NIFTY put; if it finishes ITM, buy one NIFTY futures lot and carry the futures position as the synthetic delivered index; while the futures position is held, sell an OTM call; if the call finishes ITM, close the futures lot at the call strike and return to the cash-secured put state. If either option expires out of the money, retain the premium and sell the next monthly contract. The implementation must mark futures basis daily, charge futures roll costs, enforce option and futures margin offsets, and round every position to the current lot size. Weekly expiries can raise premium turnover and gamma risk; monthly expiries align more closely with the stock-wheel cycle. The index wheel removes single-name gap risk but concentrates market beta and basis risk. This design is included as required; it is not presented as an implemented result.", "Body2")])]
    story += [P("A precise state transition would use the expiry-day index settlement S and short-put strike K. If S is below K, the put settles for a cash debit of (K-S) times the current lot size. The system then buys one matching near-month futures lot, subject to next-session execution and basis slippage, and keeps enough free cash for daily variation margin. That combined exposure behaves approximately like index ownership from K, but cannot deliver the index basket itself. When long futures are held, calls are written against the same lot count. If S exceeds a short-call strike, the cash option debit is offset by the futures gain; the futures are closed and the cash-secured put state resumes. Call strikes must also respect the synthetic position's net entry level, so a large index decline can leave calls far out of the money and premiums small.", "Body2"),
              P("For a test, choose one index and one contract tenor ex ante; use dated NSE options and futures settlements, actual historical lot sizes and expiry calendars, and the same close-to-next-open execution convention for every transition. Maintain a separate cash ledger for premiums, option cash settlement, futures daily mark-to-market, financing, transaction charges, STT, and slippage. Reserve worst-case put cash obligation and upfront option/futures margins; after an ITM put, test whether the account can fund the new futures margin plus a stress buffer before entering. If it cannot, record a missed transition rather than silently assuming leverage. Roll the futures before expiry, explicitly paying the old/new basis spread and fees. A weekly schedule needs more frequent re-hedging, more event risk near expiry, and higher turnover; the monthly schedule is the closer analogue to the stock-wheel experiment.", "Body2"),
              P("Report the index-wheel equity alongside NIFTY 50 total return, not just the price index, and compare both variants under common strike and slippage sensitivities. A futures overlay introduces basis, roll, and margin-call risk even though it removes stock-specific dividends and corporate actions. NIFTY 50 and BANKNIFTY should be evaluated separately because contract size and volatility change cash requirements. The index contracts are cash-settled and futures are marked to market daily under the <link href='https://www.nseindia.com/static/products-services/equity-derivatives-settlement-mechanism'>NSE settlement mechanism</link>. This section defines an implementable study; no index-wheel performance is claimed here.", "Body2")]

    story += [P("6. Limitations, sources and reproducibility", "Section"),
              P("Daily equity and F&amp;O bhavcopies come from <link href='https://www.nseindia.com/all-reports'>NSE reports</link>; cache paths and missing dates appear in <tt>data/source_manifest.json</tt>, while archive URL patterns are in <tt>main/data_pipeline/fetch_nse_data.py</tt>. Event links are in <tt>data/corporate_actions.csv</tt>. Benchmark: <link href='https://www.niftyindices.com/reports/historical-data'>NSE Indices historical TRI</link>. Tax: <link href='https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies'>NSE STT rates and payer</link>. Margin: <link href='https://www.nseindia.com/static/trade/members-faqs-margin-collection-and-reporting'>NSE margin FAQ</link>. The 20%/35% coefficients are proxies, not daily exchange SPAN calculations. Unlisted strikes and stale option marks are possible; bid/ask fields are absent. Previous-day stock prices avoid strike-selection look-ahead, but filling at the same day's observed option close remains optimistic. Fixed 2026-observable names introduce survivorship bias.", "Body2"),
              P(f"<b>Deployability verdict.</b> The wheel returned {pct(by_series['wheel']['CAGR'])} annualized versus {pct(by_series['nifty_tr']['CAGR'])} for NIFTY 50 total return, but the selected stock buy-and-hold earned {pct(by_series['universe_bh']['CAGR'])}. Interest on idle or secured cash contributed {money(sum(float(r['cash_interest']) for r in attribution))} of the wheel's {money(float(by_series['wheel']['end'])-float(by_series['wheel']['start']))} gain. The evidence is not sufficient for a production deployment claim until the universe is selected objectively and executions/margins are tested with more realistic data.", "Callout"),
              P("Run <tt>python3 -m main.data_pipeline.fetch_nifty_tr</tt>, then <tt>python3 -m main.backtest.run_real_backtest</tt>, <tt>python3 -m main.backtest.plot_real_results</tt>, and <tt>python3 -m main.report.build_report</tt>. Corporate-data utilities are grouped under <tt>main/data_pipeline/</tt>; tests are isolated under <tt>tests/</tt>. Install <tt>requirements.txt</tt> first.", "Body2")]
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=BASE / "output_pdf" / "Wheel_Strategy_Research_Report.pdf")
    args = parser.parse_args()
    build(args.output)
    print(args.output)
