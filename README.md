# Systematic Options: The Wheel Strategy on NSE Derivatives

This repository contains the real-data NSE bhavcopy backtest. Production code is isolated under `main/`; tests and the exploratory notebook are kept separately.

## Repository layout

- `main/backtest/` — strategy engine, costs, universe rules, and chart generation.
- `main/data_pipeline/` — NSE download and corporate-action preparation tools.
- `main/report/` — PDF report builder.
- `tests/` — automated unit and integration checks.
- `notebooks/` — optional interactive validation notebook.
- `data/` — processed research inputs and audit records.
- `outputs_real/` — Part A stock-wheel tables, trade log, diagnostics, and PNG charts.
- `outputs_nifty/` — Part B synthetic NIFTY-wheel results and PNG chart.
- `output_pdf/` — final research report.

Only production code belongs under `main/`. The root contains the single README, dependency file, Git ignore rules, data, and generated deliverables expected in the repository.

## Real-data workflow

The checked-in data covers 2020-01-01 through 2026-06-30 where NSE reports are available, including the March 2020 crash. The real-data run applies recorded rights, bonus, split, demerger, and symbol changes. `data/corporate_action_audit.csv` screens every one of the twelve names for large residual price breaks; it is not a complete dividend or corporate-action feed.

```bash
python3 -m pip install -r requirements.txt
python3 -m main.backtest.run_real_backtest
python3 -m main.backtest.plot_real_results
python3 -m main.data_pipeline.extract_nifty_derivatives
python3 -m main.backtest.run_nifty_wheel
python3 -m main.report.build_report
```

The report is written to `output_pdf/Wheel_Strategy_Research_Report.pdf`. The backtest also writes base results and sensitivity scenarios to `outputs_real/`. Use `--strike-otm` and `--slippage-bps` to run a different base case. The standard sensitivity grid includes 3%, 5%, and 8% OTM strikes plus 10, 25, and 50 bps slippage.

## How the 12 stocks were selected

The demonstration universe is RELIANCE, HDFCBANK, ICICIBANK, TCS, INFY, SBIN, AXISBANK, KOTAKBANK, LT, TATAMOTORS, BAJFINANCE, and ADANIENT. These 12 well-known, genuinely liquid large- and mid-cap F&O names were selected directly to span banks, IT, energy, industrials, autos, and NBFCs; ADANIENT and TATAMOTORS deliberately add high-idiosyncratic-volatility stress. The proposed live rule would rank the complete NSE F&O universe by 20-day average option-segment turnover and open interest, take the top 12, and exclude names that spend more than 10% of in-sample days in the F&O ban period. That live rule is documented but was not executed for this demonstration.

The runner audits the fixed 12 against first-day option participation: at least 250 contracts traded, 1 million summed share open interest, and 15 strike/expiry rows with both positive volume and open interest. `data/universe_selection.csv` records the actual 2020-01-01 readings, sectors, and selection reasons. The first strategy entry is on the following session. Because the candidate pool was fixed directly and the names are known to have data through 2026, the result retains selection and survivorship bias.

The downloader is `main/data_pipeline/fetch_nse_data.py`. It uses public NSE archive URLs, caches raw reports under `data/raw_nse/`, aliases the post-demerger `TMPV` symbol to the continuous `TATAMOTORS` sleeve, and records source coverage in `data/source_manifest.json`. Raw ZIPs, temporary chunks, probes, and Python caches are excluded by `.gitignore`. The consolidated `data/real_options.csv` and `data/nifty_derivatives.csv` files are tracked with Git LFS. `data/legacy_lot_sizes.csv` is a compact record of legacy contract lots previously validated from NSE turnover and open-interest divisibility, so the stock backtest itself no longer needs the raw ZIP cache.

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
- `outputs_nifty/summary.csv` — synthetic NIFTY wheel and NIFTY total-return metrics.
- `outputs_nifty/pnl_attribution.csv` — reconciled premium, cash settlement, futures variation margin, interest, and costs.
- `outputs_nifty/daily_positions.csv` — daily option/futures state and margin headroom.
- `outputs_nifty/trade_log.csv` — put, call, futures-entry, roll, and close events.
- `outputs_nifty/sensitivity_summary.csv` — strike and option/futures slippage sensitivity.
- `outputs_nifty/equity_curve.png` — Part B equity comparison chart.
- `output_pdf/Wheel_Strategy_Research_Report.pdf` — report with Part A and implemented Part B results, sensitivity, stress narrative, and limitations.

## Data and limitations

The option rows use observed NSE close and settlement values, volume, open interest, and available lot-size fields. Older rows use the compact validated lot reference, with ticker/expiry open-interest GCD as a fallback for newly collected contracts. Bid/ask quotes are absent. The engine uses a previous-day underlying close for strike selection and carries the last settlement when a contract mark is missing. It models physical assignment and call-away cash flows, time-varying STT, brokerage, exchange charges, GST, SEBI fees, stamp duty, and explicit slippage.

The main NIFTY benchmark is the official daily NIFTY 50 total-return index (`data/nifty50_tr.csv`, from [NSE Indices](https://www.niftyindices.com/reports/historical-data)); the price-only series is retained separately in `summary.csv`. The equal-weight stock benchmark carries adjusted share counts, theoretical rights proceeds, JIOFIN/TMCV shares, and NSE-recorded dividends. The wheel sells spun-off shares at their first NSE listing close with delivery costs. Until listing, both use the special pre-open implied price; this produces a flat provisional mark and can understate interim uncertainty. Rights are monetized at NSE theoretical values rather than observed rights-trading executions. Voluntary buybacks listed in the NSE register do not automatically change a nonparticipating holder's share count and are not modeled as tender trades. Small corporate actions outside the NSE register remain a limitation. The twelve-name price-break audit is not an exhaustive adjustment database.

The short-option writer pays option-sale STT on premium and 0.1% equity-delivery STT on delivered shares; option-exercise STT is borne by the option purchaser per [NSE's STT schedule](https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies). Mandatory assignment is at strike without discretionary execution slippage; residual stock sales are charged stock slippage. A 20%-notional SPAN-plus-exposure proxy rises to 35% for in-the-money deliverables in the last seven calendar days, with stock collateral valued at 80% of its close. The engine checks this at entry and logs daily headroom. These percentages are assumptions, not a replay of historical exchange SPAN files or broker-specific pledging rules. Bid/ask data are absent, so option-close execution still carries material uncertainty.

Cash posted as security or margin earns no interest in either base-case strategy. Both runners expose `--cash-rate` only for an explicit alternative scenario.

## Part B implementation

`main/data_pipeline/extract_nifty_derivatives.py` builds `data/nifty_derivatives.csv` from the cached NSE F&O archives. It retains NIFTY options whose expiry matches a listed NIFTY futures expiry, which selects monthly contracts without relying on weekday conventions, and carries the historical exchange lot size.

`main/backtest/run_nifty_wheel.py` implements the cash-settled index wheel. It sells monthly cash-secured puts; an ITM expiry triggers a next-session near-month futures purchase. Calls then cover the same number of index units and cannot be written below the synthetic recovery basis. An ITM call closes the futures position, while an OTM call leaves it in place for an expiry roll. Futures are marked to settlement daily, lot revisions preserve index units rounded down to a whole new lot, and every option/futures entry, close, and roll includes costs and slippage. Cash posted as option security or futures margin earns no interest in the base case; `--cash-rate` enables an explicit alternative scenario. The output is compared with the official NIFTY 50 total-return index.
