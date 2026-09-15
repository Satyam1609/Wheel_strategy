"""Extract spun-off share closes from the cached NSE equity bhavcopies."""

import csv
import zipfile
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
SYMBOLS = {"JIOFIN": "2023-08-21", "TMCV": "2025-11-12"}


def extract(raw_dir, output):
    rows = []
    for path in sorted(raw_dir.glob("*.zip")):
        day = path.stem
        if day < min(SYMBOLS.values()):
            continue
        with zipfile.ZipFile(path) as archive:
            name = next(n for n in archive.namelist() if n.lower().endswith(".csv"))
            with archive.open(name) as handle:
                reader = csv.DictReader(line.decode("utf-8-sig") for line in handle)
                found = {}
                for row in reader:
                    symbol = row.get("SYMBOL") or row.get("TckrSymb")
                    series = row.get("SERIES") or row.get("SctySrs")
                    if symbol in SYMBOLS and day >= SYMBOLS[symbol] and series in ("EQ", "BE"):
                        price = row.get("CLOSE") or row.get("ClsPric")
                        # EQ supersedes BE if both series are present.
                        if price and (symbol not in found or series == "EQ"):
                            found[symbol] = (series, price)
                for symbol, (series, price) in sorted(found.items()):
                    rows.append(dict(date=day, symbol=symbol, series=series,
                                     close=price, source_archive=str(path.relative_to(BASE))))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("date", "symbol", "series", "close", "source_archive"))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{output}: {len(rows)} closes")


if __name__ == "__main__":
    extract(BASE / "data/raw_nse/equity", BASE / "data/spinoff_prices.csv")
