"""Extract monthly NIFTY options and futures from cached NSE F&O reports.

Monthly option expiries are identified by matching listed NIFTY futures
expiries. This excludes weekly options without relying on weekday conventions,
which changed during the sample. Legacy contract lots are inferred from NSE
turnover and checked against open-interest divisibility; UDiFF board lots are
used directly when available.
"""

import argparse
import csv
import math
import zipfile
from datetime import date
from pathlib import Path

from main.data_pipeline.fetch_nse_data import field, iso_date, normalized


BASE = Path(__file__).resolve().parents[2]
FIELDS = (
    "date", "instrument", "expiry", "strike", "close", "settlement",
    "volume", "open_interest", "lot_size", "lot_source",
)


def legacy_lot(row, instrument):
    contracts = int(float(field(row, "CONTRACTS") or 0))
    turnover = float(field(row, "VAL_INLAKH") or 0) * 100_000
    close = float(field(row, "CLOSE") or 0)
    strike = float(field(row, "STRIKE_PR") or 0)
    denominator = contracts * (close if instrument == "future" else strike + close)
    if denominator <= 0 or turnover <= 0:
        return 0
    estimate = turnover / denominator
    lot = max(1, round(estimate))
    if abs(lot - estimate) / estimate > 0.05:
        return 0
    oi = int(float(field(row, "OPEN_INT") or 0))
    return lot if not oi or oi % lot == 0 else 0


def parse_archive(path, day):
    with zipfile.ZipFile(path) as archive:
        member = next(name for name in archive.namelist() if name.lower().endswith(".csv"))
        with archive.open(member) as handle:
            rows = [normalized(row) for row in csv.DictReader(
                line.decode("utf-8-sig") for line in handle)]

    nifty = [row for row in rows if field(row, "SYMBOL", "TCKRSYMB") == "NIFTY"]
    futures_expiries = {
        iso_date(field(row, "EXPIRY_DT", "XPRYDT")).isoformat()
        for row in nifty
        if field(row, "INSTRUMENT", "FININSTRMTP") in ("FUTIDX", "IDF")
    }
    output = []
    for row in nifty:
        raw_type = field(row, "INSTRUMENT", "FININSTRMTP")
        option_type = field(row, "OPTION_TYP", "OPTNTP").upper()
        if raw_type in ("FUTIDX", "IDF"):
            instrument = "future"
        elif raw_type in ("OPTIDX", "IDO") and option_type in ("PE", "CE"):
            instrument = "put" if option_type == "PE" else "call"
        else:
            continue
        expiry = iso_date(field(row, "EXPIRY_DT", "XPRYDT")).isoformat()
        if expiry not in futures_expiries:
            continue
        stamp = field(row, "TIMESTAMP", "TRADDT", "BIZDT")
        if stamp and iso_date(stamp) != day:
            raise ValueError(f"Archive date mismatch in {path}: {stamp}")
        close = field(row, "CLOSE", "CLSPRIC")
        settlement = field(row, "SETTLE_PR", "STTLMPRIC") or close
        board_lot = field(row, "NEWBRDLOTQTY")
        lot = int(float(board_lot)) if board_lot else legacy_lot(row, instrument)
        if not close or not settlement or lot <= 0:
            continue
        output.append({
            "date": day.isoformat(), "instrument": instrument, "expiry": expiry,
            "strike": field(row, "STRIKE_PR", "STRKPRIC") or "0",
            "close": close, "settlement": settlement,
            "volume": field(row, "CONTRACTS", "TTLTRADGVOL") or "0",
            "open_interest": field(row, "OPEN_INT", "OPNINTRST") or "0",
            "lot_size": lot,
            "lot_source": "nse_board_lot" if board_lot else "turnover_inference",
        })
    return output


def extract(raw_dir, output, start, end):
    output.parent.mkdir(parents=True, exist_ok=True)
    archives = [p for p in sorted(raw_dir.glob("*.zip")) if start <= p.stem <= end]
    rows_written = dates_written = 0
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for path in archives:
            rows = parse_archive(path, date.fromisoformat(path.stem))
            if rows:
                writer.writerows(rows)
                rows_written += len(rows)
                dates_written += 1
            if dates_written and dates_written % 250 == 0:
                print(f"Through {path.stem}: {dates_written} dates, {rows_written} rows", flush=True)
    if not rows_written:
        raise ValueError(f"No NIFTY derivatives extracted from {raw_dir}")
    print(f"Wrote {rows_written} monthly NIFTY rows across {dates_written} dates to {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--raw-dir", type=Path, default=BASE / "data/raw_nse/options")
    parser.add_argument("--output", type=Path, default=BASE / "data/nifty_derivatives.csv")
    args = parser.parse_args()
    extract(args.raw_dir, args.output, args.start, args.end)


if __name__ == "__main__":
    main()
