# Systematic Options: The Wheel Strategy on NSE Derivatives

This repository contains the real-data NSE bhavcopy backtest. Production code is isolated under `main/`; tests and the exploratory notebook are kept separately.

## Repository layout

- `main/backtest/` — strategy engine, costs, universe rules, and chart generation.
- `main/data_pipeline/` — NSE download and corporate-action preparation tools.
- `main/report/` — PDF report builder.
- `tests/` — automated unit and integration checks.
- `notebooks/` — optional interactive validation notebook.
- `data/` — processed research inputs and audit records.
- `outputs_real/` — generated tables, trade log, diagnostics, and PNG charts.
- `output_pdf/` — final research report.

Only production code belongs under `main/`. The root contains the single README, dependency file, Git ignore rules, data, and generated deliverables expected in the repository.

## Real-data workflow

The checked-in data covers 2020-01-01 through 2026-06-30 where NSE reports are available, including the March 2020 crash. The real-data run applies recorded rights, bonus, split, demerger, and symbol changes. `data/corporate_action_audit.csv` screens every one of the twelve names for large residual price breaks; it is not a complete dividend or corporate-action feed.

```bash
python3 -m pip install -r requirements.txt
python3 -m main.backtest.run_real_backtest
python3 -m main.backtest.plot_real_results
python3 -m main.report.build_report
```

The report is written to `output_pdf/Wheel_Strategy_Research_Report.pdf`. The backtest also writes base results and sensitivity scenarios to `outputs_real/`. Use `--strike-otm` and `--slippage-bps` to run a different base case. The standard sensitivity grid includes 3%, 5%, and 8% OTM strikes plus 10, 25, and 50 bps slippage.

## How the 12 stocks were selected

The original selection rule, preserved in `main/backtest/select_universe.py`, was a fixed shortlist of liquid NSE F&O stocks spanning sectors, with a lower-volatility name (TCS) and stressed, high-idiosyncratic-risk names (TATAMOTORS and ADANIENT). It was a qualitative research selection, not an all-market liquidity ranking. The runner verifies all 12 against the first day's option participation: at least 250 contracts traded, 1 million summed share open interest, and 15 strike/expiry rows with both positive volume and open interest. `data/universe_selection.csv` records the actual 2020-01-01 readings, sectors, and selection reasons. The first strategy entry is on the following session. Because the fixed names are known to have data through 2026, survivorship risk remains.

The downloader is `main/data_pipeline/fetch_nse_data.py`. It uses public NSE archive URLs, caches raw reports under `data/raw_nse/`, aliases the post-demerger `TMPV` symbol to the continuous `TATAMOTORS` sleeve, and records source coverage in `data/source_manifest.json`. Raw ZIPs, temporary chunks, probes, and Python caches are excluded by `.gitignore`. The 304 MB consolidated `data/real_options.csv` is tracked with Git LFS. `data/legacy_lot_sizes.csv` is a compact record of legacy contract lots previously validated from NSE turnover and open-interest divisibility, so the backtest itself no longer needs the raw ZIP cache.

To recreate the consolidated market files from NSE archives:

```bash
python3 -m main.data_pipeline.fetch_nse_data --start 2020-01-01 --end 2026-06-30 --download
```

The other tools are `main/data_pipeline/fetch_corporate_actions.py`, `generate_dividends.py`, `generate_spinoff_prices.py`, `audit_corporate_actions.py`, and `fetch_nifty_tr.py`. Run them as modules from the repository root, for example `python3 -m main.data_pipeline.fetch_nifty_tr`.

Run the separated test suite with:

```bash
python3 -m unittest discover -s tests -v
```

## Outputs

- `outputs_real/summary.csv` — portfolio metrics including CAGR, annual volatility, Sharpe, Sortino, maximum drawdown dates, and Calmar.
- `outputs_real/per_name_summary.csv` — the same metrics for each of the 12 sleeves, using its own initial capital.
- `outputs_real/pnl_attribution.csv` — exact per-name reconciliation of premiums, stock delivery/mark, dividends, corporate entitlements, interest, costs, and open option liability to ending equity.
- `outputs_real/daily_positions.csv` — daily cash, shares, open option, mark, and margin proxy/headroom for every ticker.
- `outputs_real/sensitivity_summary.csv` — strike and slippage sensitivity.
- `outputs_real/diagnostics.csv` — per-name cycles, assignment rate, call-away rate, average post-delivery days, premium capture, delivery P&L, dividends, and costs.
- `outputs_real/trade_log.csv` — every entry, expiry, assignment, call-away, residual-share sale, premium, and cost.
- `outputs_real/equity_curve.csv` — wheel, NIFTY, and selected-universe equity curves.
- `outputs_real/corporate_action_adjustments.csv` — daily applied events and position adjustments.
- `outputs_real/real_equity_curves.png` and `outputs_real/real_drawdown.png` — presentation-ready charts.
- `output_pdf/Wheel_Strategy_Research_Report.pdf` — report with results, sensitivity, stress narrative, limitations, and the required Part B design note.

## Data and limitations

The option rows use observed NSE close and settlement values, volume, open interest, and available lot-size fields. Older rows use the compact validated lot reference, with ticker/expiry open-interest GCD as a fallback for newly collected contracts. Bid/ask quotes are absent. The engine uses a previous-day underlying close for strike selection and carries the last settlement when a contract mark is missing. It models physical assignment and call-away cash flows, time-varying STT, brokerage, exchange charges, GST, SEBI fees, stamp duty, and explicit slippage.

The main NIFTY benchmark is the official daily NIFTY 50 total-return index (`data/nifty50_tr.csv`, from [NSE Indices](https://www.niftyindices.com/reports/historical-data)); the price-only series is retained separately in `summary.csv`. The equal-weight stock benchmark carries adjusted share counts, theoretical rights proceeds, JIOFIN/TMCV shares, and NSE-recorded dividends. The wheel sells spun-off shares at their first NSE listing close with delivery costs. Until listing, both use the special pre-open implied price; this produces a flat provisional mark and can understate interim uncertainty. Rights are monetized at NSE theoretical values rather than observed rights-trading executions. Voluntary buybacks listed in the NSE register do not automatically change a nonparticipating holder's share count and are not modeled as tender trades. Small corporate actions outside the NSE register remain a limitation. The twelve-name price-break audit is not an exhaustive adjustment database.

The short-option writer pays option-sale STT on premium and 0.1% equity-delivery STT on delivered shares; option-exercise STT is borne by the option purchaser per [NSE's STT schedule](https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies). Mandatory assignment is at strike without discretionary execution slippage; residual stock sales are charged stock slippage. A 20%-notional SPAN-plus-exposure proxy rises to 35% for in-the-money deliverables in the last seven calendar days, with stock collateral valued at 80% of its close. The engine checks this at entry and logs daily headroom. These percentages are assumptions, not a replay of historical exchange SPAN files or broker-specific pledging rules. Bid/ask data are absent, so option-close execution still carries material uncertainty.

## Part B design

The report includes the required design for a synthetic index wheel: cash-settled NIFTY options combined with a NIFTY futures position, with basis, roll, lot-size, margin-offset, and weekly/monthly-expiry considerations documented. It is design-only; implementation is optional in the assignment.
