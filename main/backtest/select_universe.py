"""Reproduce and audit the original twelve-name selection at inception.

The original synthetic model specified a qualitative cross-sector shortlist
with defensive and idiosyncratically stressed names. This module preserves
that historical choice and applies a transparent first-day F&O participation
check; it does not misrepresent the shortlist as an optimized ranking.
"""
import csv
from collections import defaultdict
from pathlib import Path

from main.data_pipeline.fetch_nse_data import TICKERS

BASE = Path(__file__).resolve().parents[2]
GROUPS = {
    "RELIANCE": ("Energy", "large diversified energy"),
    "HDFCBANK": ("Private bank", "large bank"),
    "ICICIBANK": ("Private bank", "large bank"),
    "TCS": ("IT services", "lower-volatility / defensive sleeve"),
    "INFY": ("IT services", "IT peer diversification"),
    "SBIN": ("Public bank", "public-sector bank exposure"),
    "AXISBANK": ("Private bank", "bank peer diversification"),
    "KOTAKBANK": ("Private bank", "bank peer diversification"),
    "LT": ("Industrials", "industrial / infrastructure exposure"),
    "TATAMOTORS": ("Autos", "cyclical stressed-name exposure"),
    "BAJFINANCE": ("NBFC", "consumer finance exposure"),
    "ADANIENT": ("Conglomerate", "high idiosyncratic-risk exposure"),
}
# Deliberately permissive eligibility thresholds on the first observed day.
# They are checks on the preselected shortlist, not a cross-market ranking.
MIN_VOLUME = 250
MIN_OPEN_INTEREST = 1_000_000
MIN_ACTIVE_CONTRACTS = 15


def screen(path, first_day):
    stats = defaultdict(lambda: [0, 0, 0])
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["date"] > first_day:
                break
            if row["date"] != first_day or row["ticker"] not in TICKERS:
                continue
            volume = int(float(row["volume"] or 0))
            oi = int(float(row["open_interest"] or 0))
            s = stats[row["ticker"]]
            s[0] += volume
            s[1] += oi
            s[2] += int(volume > 0 and oi > 0)
    result = []
    for ticker in TICKERS:
        volume, oi, active = stats[ticker]
        eligible = volume >= MIN_VOLUME and oi >= MIN_OPEN_INTEREST and active >= MIN_ACTIVE_CONTRACTS
        sector, reason = GROUPS[ticker]
        result.append(dict(ticker=ticker, sector=sector, original_selection_reason=reason,
                           formation_date=first_day, option_contracts_traded=volume,
                           summed_contract_open_interest=oi, active_option_rows=active,
                           passes_inception_liquidity_check=eligible))
    if not all(row["passes_inception_liquidity_check"] for row in result):
        failed = [row["ticker"] for row in result if not row["passes_inception_liquidity_check"]]
        raise ValueError(f"Original shortlist fails inception liquidity check: {failed}")
    return result


if __name__ == "__main__":
    from main.backtest.run_real_backtest import write_csv
    rows = screen(BASE / "data/real_options.csv", "2020-01-01")
    write_csv(BASE / "data/universe_selection.csv", rows)
    print("Wrote inception screen for", len(rows), "original shortlisted names")
