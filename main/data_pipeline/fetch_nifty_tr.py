"""Fetch the official daily NIFTY 50 total-return index from NSE Indices."""
import csv
import json
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
URL = "https://www.niftyindices.com/Backpage/getTotalReturnIndexString"
SOURCE = "https://www.niftyindices.com/reports/historical-data"


def fetch(start="01-Jan-2020", end="30-Jun-2026"):
    details = "{'name':'NIFTY 50','startDate':'%s','endDate':'%s','indexName':'NIFTY 50'}" % (start, end)
    request = urllib.request.Request(
        URL,
        data=json.dumps({"cinfo": details}).encode(),
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
                 "Content-Type": "application/json; charset=UTF-8",
                 "X-Requested-With": "XMLHttpRequest", "Referer": SOURCE},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read())
    if isinstance(payload, dict) and "d" in payload:
        payload = json.loads(payload["d"])
    if not isinstance(payload, list) or not payload:
        raise ValueError("NSE Indices returned no TRI observations")
    rows = []
    for item in payload:
        if item["Index Name"].upper() != "NIFTY 50":
            continue
        rows.append({"date": datetime.strptime(item["Date"], "%d %b %Y").date().isoformat(),
                     "total_return_index": float(item["TotalReturnsIndex"])})
    rows.sort(key=lambda row: row["date"])
    if len({row["date"] for row in rows}) != len(rows):
        raise ValueError("Duplicate dates in official TRI response")
    path = BASE / "data/nifty50_tr.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "total_return_index"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} official TRI observations to {path}")


if __name__ == "__main__":
    fetch()
