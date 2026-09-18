"""Rank NSE stock-option symbols by 20-session average option turnover."""
import argparse
import csv
import io
import math
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

from main.data_pipeline.fetch_nse_data import TICKERS

BASE = Path(__file__).resolve().parents[2]
MIN_VOLUME = 250
MIN_OPEN_INTEREST = 1_000_000
MIN_ACTIVE_CONTRACTS = 15


def _field(row, *names):
    for name in names:
        value = row.get(name.upper(), "")
        if value:
            return value.strip()
    return ""


def _raw_rows(path):
    with zipfile.ZipFile(path) as archive:
        member = next((name for name in archive.namelist()
                       if name.lower().endswith(".csv")), None)
        if member is None:
            raise ValueError(f"No CSV found in {path}")
        text = archive.read(member).decode("utf-8-sig", errors="replace")
    for row in csv.DictReader(io.StringIO(text)):
        yield {str(key).strip().upper(): (value or "").strip()
               for key, value in row.items() if key}


def rank_by_option_turnover(raw_dir, start="2020-01-01", sessions=20):
    """Return stock-option liquidity statistics ranked by average turnover.

    Old NSE bhavcopies publish ``VAL_INLAKH`` directly. New UDiFF reports use
    rupee traded value, which is converted to lakh. Open interest is divided
    by the symbol's inferred exchange lot so different underlyings are compared
    in contracts. Missing activity on a formation session counts as zero.
    """
    start_day = date.fromisoformat(start)
    files = []
    for path in Path(raw_dir).glob("*.zip"):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if day >= start_day:
            files.append((day, path))
    files = sorted(files)[:sessions]
    if len(files) < sessions:
        raise ValueError(f"Need {sessions} raw option sessions from {start}; found {len(files)}")

    daily = []
    symbols = set()
    lot_gcd = defaultdict(int)
    for day, path in files:
        totals = defaultdict(lambda: [0.0, 0, 0])
        for row in _raw_rows(path):
            instrument = _field(row, "INSTRUMENT", "FININSTRMTP").upper()
            option_type = _field(row, "OPTION_TYP", "OPTNTP").upper()
            if instrument not in ("OPTSTK", "STO") or option_type not in ("CE", "PE"):
                continue
            symbol = _field(row, "SYMBOL", "TCKRSYMB")
            if not symbol:
                continue
            turnover_lakh = _field(row, "VAL_INLAKH")
            if turnover_lakh:
                value = float(turnover_lakh)
            else:
                traded_value = _field(row, "TTLTRADGVAL", "TOTTRDVAL")
                value = float(traded_value or 0) / 100_000.0
            contracts = int(float(_field(row, "CONTRACTS", "TTLTRADGVOL") or 0))
            open_interest = int(float(_field(row, "OPEN_INT", "OPNINTRST") or 0))
            totals[symbol][0] += value
            totals[symbol][1] += contracts
            totals[symbol][2] += open_interest
            if open_interest > 0:
                lot_gcd[symbol] = math.gcd(lot_gcd[symbol], open_interest)
            symbols.add(symbol)
        daily.append((day, totals))

    ranked = []
    for symbol in symbols:
        turnover = sum(totals[symbol][0] for _, totals in daily) / sessions
        contracts = sum(totals[symbol][1] for _, totals in daily) / sessions
        open_interest_units = sum(totals[symbol][2] for _, totals in daily) / sessions
        inferred_lot = lot_gcd[symbol] or 1
        ranked.append({
            "ticker": symbol,
            "formation_start": files[0][0].isoformat(),
            "formation_end": files[-1][0].isoformat(),
            "formation_sessions": sessions,
            "average_daily_option_turnover_lakh": round(turnover, 2),
            "average_daily_option_contracts": round(contracts, 2),
            "average_daily_open_interest_units": round(open_interest_units, 2),
            "inferred_lot_size": inferred_lot,
            "average_daily_open_interest_contracts": round(open_interest_units / inferred_lot, 2),
            "active_sessions": sum(totals[symbol][1] > 0 for _, totals in daily),
        })
    ranked.sort(key=lambda row: (-row["average_daily_option_turnover_lakh"], row["ticker"]))
    for position, row in enumerate(ranked, 1):
        row["turnover_rank"] = position
    by_open_interest = sorted(
        ranked,
        key=lambda row: (-row["average_daily_open_interest_contracts"], row["ticker"]),
    )
    for position, row in enumerate(by_open_interest, 1):
        row["open_interest_rank"] = position
    population = len(ranked)
    for row in ranked:
        turnover_percentile = 1 - (row["turnover_rank"] - 1) / max(population - 1, 1)
        oi_percentile = 1 - (row["open_interest_rank"] - 1) / max(population - 1, 1)
        row["combined_liquidity_score"] = round((turnover_percentile + oi_percentile) / 2, 6)
    for position, row in enumerate(sorted(
            ranked, key=lambda row: (-row["combined_liquidity_score"], row["ticker"])), 1):
        row["combined_liquidity_rank"] = position
    return ranked


def screen(path, first_day):
    """Preserve the backtest's inception-liquidity audit for configured names."""
    stats = defaultdict(lambda: [0, 0, 0])
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["date"] > first_day:
                break
            if row["date"] != first_day or row["ticker"] not in TICKERS:
                continue
            volume = int(float(row["volume"] or 0))
            oi = int(float(row["open_interest"] or 0))
            stats[row["ticker"]][0] += volume
            stats[row["ticker"]][1] += oi
            stats[row["ticker"]][2] += int(volume > 0 and oi > 0)
    result = []
    for ticker in TICKERS:
        volume, oi, active = stats[ticker]
        eligible = volume >= MIN_VOLUME and oi >= MIN_OPEN_INTEREST and active >= MIN_ACTIVE_CONTRACTS
        result.append(dict(ticker=ticker, formation_date=first_day,
                           option_contracts_traded=volume,
                           summed_contract_open_interest=oi, active_option_rows=active,
                           passes_inception_liquidity_check=eligible))
    if not all(row["passes_inception_liquidity_check"] for row in result):
        failed = [row["ticker"] for row in result if not row["passes_inception_liquidity_check"]]
        raise ValueError(f"Configured universe fails inception liquidity check: {failed}")
    return result


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=BASE / "data/raw_nse/options")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--sessions", type=int, default=20)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--output", type=Path, default=BASE / "data/universe_top15_liquidity.csv")
    args = parser.parse_args()
    ranking = rank_by_option_turnover(args.raw_dir, args.start, args.sessions)
    top_rows = [{
        "turnover_rank": row["turnover_rank"],
        "ticker": row["ticker"],
        "formation_start": row["formation_start"],
        "formation_end": row["formation_end"],
        "formation_sessions": row["formation_sessions"],
        "average_daily_option_turnover_inr_crore": round(
            row["average_daily_option_turnover_lakh"] / 100, 2),
        "average_daily_open_interest_units": row["average_daily_open_interest_units"],
        "inferred_lot_size": row["inferred_lot_size"],
        "average_daily_open_interest_contracts": row["average_daily_open_interest_contracts"],
        "open_interest_rank": row["open_interest_rank"],
    } for row in ranking[:args.top]]
    write_csv(args.output, top_rows)
    print(f"Top {args.top} by 20-session average option turnover:")
    for row in ranking[:args.top]:
        print(f"{row['turnover_rank']:>2}. {row['ticker']:<12} "
              f"turnover INR {row['average_daily_option_turnover_lakh'] / 100:,.2f} crore/day; "
              f"OI {row['average_daily_open_interest_contracts']:,.0f} contracts/day "
              f"(OI rank {row['open_interest_rank']})")
    print("Wrote", args.output)


if __name__ == "__main__":
    main()
