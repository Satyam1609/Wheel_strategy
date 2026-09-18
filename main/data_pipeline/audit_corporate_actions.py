"""Screen configured sleeves for price discontinuities after recorded events.

This is a diagnostic, not an exhaustive corporate-action database. Cash
dividends are parsed from the NSE action register by generate_dividends.py.
"""

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from main.data_pipeline.fetch_nse_data import TICKERS


BASE = Path(__file__).resolve().parents[2]


def audit():
    with (BASE / "data/real_prices.csv").open(newline="") as handle:
        prices = list(csv.DictReader(handle))
    with (BASE / "data/corporate_actions.csv").open(newline="") as handle:
        actions = list(csv.DictReader(handle))
    events = defaultdict(list)
    by_ticker = defaultdict(list)
    for action in actions:
        events[(action["effective_date"], action["ticker"])].append(action)
        by_ticker[action["ticker"]].append(action)
    register = json.loads((BASE / "data/nse_corporate_actions_raw.json").read_text())
    for symbol, payload in register.items():
        ticker = symbol
        for row in payload["rows"]:
            purpose = row["subject"].lower()
            if "dividend" in purpose or "buyback" in purpose or "buy back" in purpose or "annual general meeting" in purpose:
                continue
            day = datetime.strptime(row["exDate"], "%d-%b-%Y").date().isoformat()
            if ticker in TICKERS and not events[(day, ticker)]:
                raise ValueError(f"Unmodeled NSE corporate event: {ticker} {day} {row['subject']}")
    output = []
    for ticker in TICKERS:
        raw_low = (float("inf"), "")
        economic_low = (float("inf"), "")
        for previous, current in zip(prices, prices[1:]):
            prev = float(previous[ticker])
            close = float(current[ticker])
            economic = close
            for action in events[(current["date"], ticker)]:
                if action["action"] in ("BONUS", "SPLIT", "SPLIT_BONUS"):
                    economic *= float(action["adjustment_factor"])
                elif action["action"] == "SPIN_OFF":
                    economic += float(action["spin_off_ratio"]) * float(action["provisional_value"])
                elif action["action"] == "RIGHTS":
                    economic += float(action["cash_benefit_per_share"])
            raw_low = min(raw_low, (close / prev, current["date"]))
            economic_low = min(economic_low, (economic / prev, current["date"]))
        output.append(dict(ticker=ticker,
            recorded_events="; ".join(a["effective_date"] + " " + a["action"] for a in by_ticker[ticker]),
            raw_largest_one_day_drop_date=raw_low[1],
            raw_largest_one_day_drop_pct=round((1 - raw_low[0]) * 100, 2),
            adjusted_largest_one_day_drop_date=economic_low[1],
            adjusted_largest_one_day_drop_pct=round((1 - economic_low[0]) * 100, 2),
            scope="Large price-discontinuity screen; smaller non-cash actions may remain"))
    path = BASE / "data/corporate_action_audit.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output[0])
        writer.writeheader()
        writer.writerows(output)
    print(path)


if __name__ == "__main__":
    audit()
