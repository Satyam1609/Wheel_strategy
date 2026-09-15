"""Extract and validate cash dividends from the saved official NSE register."""

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
AMOUNT = re.compile(r"\b(?:Rs|Re)\.?\s*([0-9]+(?:\.[0-9]+)?)\s*Per\s*(?:Share|Sh)\b", re.I)


def generate():
    raw = json.loads((BASE / "data/nse_corporate_actions_raw.json").read_text())
    totals = defaultdict(float)
    source_rows = defaultdict(list)
    for symbol, payload in raw.items():
        for row in payload["rows"]:
            subject = row["subject"]
            if "dividend" not in subject.lower():
                continue
            amounts = [float(x) for x in AMOUNT.findall(subject)]
            if not amounts:
                raise ValueError(f"Unparsed NSE dividend: {symbol} {row['exDate']} {subject}")
            day = datetime.strptime(row["exDate"], "%d-%b-%Y").date().isoformat()
            # The backtest keeps the renamed passenger-vehicle security in its
            # continuous TATAMOTORS sleeve on both sides of the symbol change.
            ticker = "TATAMOTORS" if symbol == "TMPV" else symbol
            key = (day, ticker)
            totals[key] += sum(amounts)
            source_rows[key].append(subject.strip())
    output = BASE / "data/dividends.csv"
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("date", "ticker", "dividend_per_share", "source", "nse_subject"))
        writer.writeheader()
        for (day, ticker), value in sorted(totals.items()):
            source_symbol = "TMPV" if ticker == "TATAMOTORS" else ticker
            writer.writerow(dict(date=day, ticker=ticker, dividend_per_share=f"{value:g}",
                source=raw[source_symbol]["source"], nse_subject=" | ".join(source_rows[(day, ticker)])))
    print(f"{output}: {len(totals)} dated dividends")


if __name__ == "__main__":
    generate()
