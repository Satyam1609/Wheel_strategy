"""Build cash dividends from the saved NSE register and documented supplements."""

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from main.data_pipeline.fetch_nse_data import TICKERS


BASE = Path(__file__).resolve().parents[2]
AMOUNT = re.compile(r"\b(?:Rs|Re)\.?\s*([0-9]+(?:\.[0-9]+)?)\s*Per\s*(?:Share|Sh)\b", re.I)


def generate():
    raw = json.loads((BASE / "data/nse_corporate_actions_raw.json").read_text())
    totals = defaultdict(float)
    source_rows = defaultdict(list)
    for symbol, payload in raw.items():
        if symbol not in {*TICKERS, "JIOFIN"}:
            continue
        for row in payload["rows"]:
            subject = row["subject"]
            if "dividend" not in subject.lower():
                continue
            amounts = [float(x) for x in AMOUNT.findall(subject)]
            if not amounts:
                raise ValueError(f"Unparsed NSE dividend: {symbol} {row['exDate']} {subject}")
            day = datetime.strptime(row["exDate"], "%d-%b-%Y").date().isoformat()
            ticker = symbol
            key = (day, ticker)
            totals[key] += sum(amounts)
            source_rows[key].append(subject.strip())
    supplement = BASE / "data/additional_dividends.csv"
    if supplement.exists():
        with supplement.open(newline="") as handle:
            for row in csv.DictReader(handle):
                key = (row["date"], row["ticker"])
                if key in totals:
                    raise ValueError(f"Duplicate dividend in NSE register and supplement: {key}")
                totals[key] = float(row["dividend_per_share"])
                source_rows[key].append(row["subject"].strip())
    sources = {}
    for symbol, payload in raw.items():
        if symbol not in {*TICKERS, "JIOFIN"}:
            continue
        ticker = symbol
        for row in payload["rows"]:
            if "dividend" in row["subject"].lower():
                day = datetime.strptime(row["exDate"], "%d-%b-%Y").date().isoformat()
                sources[(day, ticker)] = payload["source"]
    if supplement.exists():
        with supplement.open(newline="") as handle:
            for row in csv.DictReader(handle):
                sources[(row["date"], row["ticker"])] = row["source"]
    output = BASE / "data/dividends.csv"
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("date", "ticker", "dividend_per_share", "source", "nse_subject"))
        writer.writeheader()
        for (day, ticker), value in sorted(totals.items()):
            writer.writerow(dict(date=day, ticker=ticker, dividend_per_share=f"{value:g}",
                source=sources[(day, ticker)], nse_subject=" | ".join(source_rows[(day, ticker)])))
    print(f"{output}: {len(totals)} dated dividends")


if __name__ == "__main__":
    generate()
