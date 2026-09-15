"""Download the NSE corporate-action register for the backtest universe.

The raw JSON is retained so dividend parsing can be audited. This script does
not rewrite hand-reviewed F&O adjustment rows in corporate_actions.csv.
"""

import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from main.data_pipeline.fetch_nse_data import TICKERS


BASE = Path(__file__).resolve().parents[2]
API = "https://www.nseindia.com/api/corporates-corporateActions"


def fetch(symbol):
    url = API + "?" + urlencode({"index": "equities", "symbol": symbol,
                                  "from_date": "01-01-2020", "to_date": "30-06-2026"})
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer":
                               "https://www.nseindia.com/companies-listing/corporate-filings-actions"})
    with urlopen(req, timeout=30) as response:
        return {"source": url, "rows": json.load(response)}


def main():
    result = {}
    for symbol in (*TICKERS, "TMPV", "JIOFIN", "TMCV"):
        result[symbol] = fetch(symbol)
        print(symbol, len(result[symbol]["rows"]))
        time.sleep(0.25)
    path = BASE / "data/nse_corporate_actions_raw.json"
    path.write_text(json.dumps(result, indent=2))
    print(path)


if __name__ == "__main__":
    main()
