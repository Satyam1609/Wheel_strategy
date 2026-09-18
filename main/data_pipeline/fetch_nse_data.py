"""Download or import NSE daily reports into the project's real-data CSV layout.

No synthetic values are inserted. Requires only the Python standard library.
"""

import argparse
import csv
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path


TICKERS = (
    "RELIANCE", "SBIN", "INDUSINDBK", "ICICIBANK", "INFY", "AXISBANK",
    "BHARTIARTL", "BAJFINANCE", "TCS", "KOTAKBANK", "ADANIENT",
)
SYMBOL_ALIASES = {}
PRICE_COLUMNS = ("date", "NIFTY", *TICKERS)
OPTION_COLUMNS = (
    "date", "ticker", "expiry", "option_type", "strike", "bid", "ask",
    "close", "settlement", "volume", "open_interest", "lot_size",
)
CHANGEOVER = date(2024, 7, 8)


def report_url(kind, day):
    ymd = day.strftime("%Y%m%d")
    ddmonyyyy = day.strftime("%d%b%Y").upper()
    mon = day.strftime("%b").upper()
    if kind == "index":
        return f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{day:%d%m%Y}.csv"
    if day >= CHANGEOVER:
        segment = "CM" if kind == "equity" else "FO"
        folder = "cm" if kind == "equity" else "fo"
        return (f"https://nsearchives.nseindia.com/content/{folder}/"
                f"BhavCopy_NSE_{segment}_0_0_0_{ymd}_F_0000.csv.zip")
    if kind == "equity":
        return (f"https://archives.nseindia.com/content/historical/EQUITIES/"
                f"{day:%Y}/{mon}/cm{ddmonyyyy}bhav.csv.zip")
    return (f"https://archives.nseindia.com/content/historical/DERIVATIVES/"
            f"{day:%Y}/{mon}/fo{ddmonyyyy}bhav.csv.zip")


def normalized(row):
    return {k.strip().upper(): (v or "").strip() for k, v in row.items() if k}


def field(row, *names):
    for name in names:
        value = row.get(name.upper(), "")
        if value:
            return value
    return ""


def iso_date(value):
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d-%m-%Y", "%d/%m/%Y", "%d/%m/%y", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognized date: {value!r}")


def csv_rows(payload):
    if payload[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if not members:
                raise ValueError("ZIP contains no CSV")
            payload = archive.read(members[0])
    if payload.lstrip().startswith((b"<", b"{")):
        raise ValueError("Received HTML/JSON instead of a bhavcopy CSV")
    text = payload.decode("utf-8-sig", errors="replace")
    return [normalized(r) for r in csv.DictReader(io.StringIO(text))]


def require_columns(rows, groups, kind):
    if not rows:
        raise ValueError(f"Empty {kind} report")
    names = set(rows[0])
    missing = [" or ".join(g) for g in groups if not any(n.upper() in names for n in g)]
    if missing:
        raise ValueError(f"{kind} report missing columns: {', '.join(missing)}; got {sorted(names)}")


def parse_equity(rows, day):
    require_columns(rows, [("SYMBOL", "TCKRSYMB"), ("SERIES", "SCTYSRS"),
                           ("CLOSE", "CLSPRIC")], "equity")
    result = {}
    for row in rows:
        symbol = field(row, "SYMBOL", "TCKRSYMB")
        symbol = SYMBOL_ALIASES.get(symbol, symbol)
        if symbol not in TICKERS or field(row, "SERIES", "SCTYSRS") != "EQ":
            continue
        stamp = field(row, "TIMESTAMP", "TRADDT", "BIZDT")
        if stamp and iso_date(stamp) != day:
            raise ValueError(f"Equity report date {stamp} does not match {day}")
        result[symbol] = field(row, "CLOSE", "CLSPRIC")
    return result


def parse_index(rows, day):
    require_columns(rows, [("INDEX NAME", "INDEXNAME"), ("CLOSING INDEX VALUE", "CLOSE"),
                           ("INDEX DATE", "DATE")], "index")
    for row in rows:
        if field(row, "INDEX NAME", "INDEXNAME").upper() != "NIFTY 50":
            continue
        stamp = field(row, "INDEX DATE", "DATE")
        # A few official index snapshots use MM-DD-YYYY amid DD-MM-YYYY files.
        # Accept the alternate reading only when it matches the requested day.
        parsed_date = iso_date(stamp)
        if parsed_date != day and "-" in stamp:
            try:
                parsed_date = datetime.strptime(stamp, "%m-%d-%Y").date()
            except ValueError:
                pass
        if parsed_date != day:
            raise ValueError(f"Index report date {stamp} does not match {day}")
        return field(row, "CLOSING INDEX VALUE", "CLOSE").replace(",", "")
    return ""


def parse_options(rows, day):
    require_columns(rows, [("SYMBOL", "TCKRSYMB"), ("EXPIRY_DT", "XPRYDT"),
                           ("STRIKE_PR", "STRKPRIC"), ("OPTION_TYP", "OPTNTP"),
                           ("CLOSE", "CLSPRIC")], "options")
    result = []
    for row in rows:
        symbol = field(row, "SYMBOL", "TCKRSYMB")
        typ = field(row, "OPTION_TYP", "OPTNTP").upper()
        symbol = SYMBOL_ALIASES.get(symbol, symbol)
        if symbol not in TICKERS or typ not in ("PE", "CE"):
            continue
        stamp = field(row, "TIMESTAMP", "TRADDT", "BIZDT")
        if stamp and iso_date(stamp) != day:
            raise ValueError(f"Options report date {stamp} does not match {day}")
        result.append(dict(
            date=day.isoformat(), ticker=symbol,
            expiry=iso_date(field(row, "EXPIRY_DT", "XPRYDT")).isoformat(),
            option_type="put" if typ == "PE" else "call",
            strike=field(row, "STRIKE_PR", "STRKPRIC"),
            bid="", ask="", close=field(row, "CLOSE", "CLSPRIC"),
            settlement=field(row, "SETTLE_PR", "STTLMPRIC"),
            volume=field(row, "CONTRACTS", "TTLTRADGVOL"),
            open_interest=field(row, "OPEN_INT", "OPNINTRST"),
            lot_size=field(row, "NEWBRDLOTQTY"),
        ))
    return result


def fetch(url, delay):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; research data downloader)",
        "Accept": "text/csv,application/zip,application/octet-stream,*/*",
        "Referer": "https://www.nseindia.com/",
    })
    with urllib.request.urlopen(req, timeout=25) as response:
        body = response.read()
    if delay:
        time.sleep(delay)
    return body


def load_report(raw_dir, kind, day, download, delay):
    folder = raw_dir / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day.isoformat()}{'.csv' if kind == 'index' else '.zip'}"
    url = report_url(kind, day)
    if path.exists():
        body = path.read_bytes()
        origin = str(path)
    elif download:
        body = fetch(url, delay)
        csv_rows(body)  # reject block pages before caching
        path.write_bytes(body)
        origin = url
    else:
        return None, str(path)
    return csv_rows(body), origin


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def collect(start, end, raw_dir, output_dir, download=False, delay=0.5):
    manifest = []
    price_count = option_count = 0
    price_path = output_dir / "real_prices.csv"
    option_path = output_dir / "real_options.csv"
    write_csv(price_path, PRICE_COLUMNS, [])
    write_csv(option_path, OPTION_COLUMNS, [])
    day = start
    while day <= end:
        if day.weekday() >= 5:
            day += timedelta(days=1)
            continue
        report = {"date": day.isoformat(), "sources": {}, "errors": []}
        parsed = {}
        for kind, parser in (("equity", parse_equity), ("options", parse_options), ("index", parse_index)):
            try:
                rows, origin = load_report(raw_dir, kind, day, download, delay)
                report["sources"][kind] = origin
                if rows is None:
                    raise FileNotFoundError("Source archive unavailable")
                parsed[kind] = parser(rows, day)
            except (OSError, urllib.error.URLError, ValueError, zipfile.BadZipFile, csv.Error) as exc:
                report["errors"].append(f"{kind}: {exc}")
        if parsed.get("equity") or parsed.get("index"):
            row = {column: "" for column in PRICE_COLUMNS}
            row["date"] = day.isoformat()
            row.update(parsed.get("equity", {}))
            row["NIFTY"] = parsed.get("index", "")
            with price_path.open("a", newline="") as handle:
                csv.DictWriter(handle, fieldnames=PRICE_COLUMNS).writerow(row)
            price_count += 1
        option_rows = parsed.get("options", [])
        if option_rows:
            with option_path.open("a", newline="") as handle:
                csv.DictWriter(handle, fieldnames=OPTION_COLUMNS).writerows(option_rows)
            option_count += len(option_rows)
        report["equity_symbols"] = len(parsed.get("equity", {}))
        report["option_contracts"] = len(parsed.get("options", []))
        report["nifty_found"] = bool(parsed.get("index"))
        if "equity" in parsed and len(parsed["equity"]) != len(TICKERS):
            report["errors"].append(f"equity: found {len(parsed['equity'])} of {len(TICKERS)} symbols")
        if "options" in parsed and not parsed["options"]:
            report["errors"].append("options: found no matching stock-option contracts")
        if "index" in parsed and not parsed["index"]:
            report["errors"].append("index: NIFTY 50 row not found")
        manifest.append(report)
        if len(manifest) % 25 == 0:
            (output_dir / "source_manifest.json").write_text(json.dumps(manifest, indent=2))
            print(f"Through {day}: {price_count} price rows, {option_count} option rows, "
                  f"{sum(bool(r['errors']) for r in manifest)} dates with errors", flush=True)
        day += timedelta(days=1)

    (output_dir / "source_manifest.json").write_text(json.dumps(manifest, indent=2))
    return price_count, option_count, sum(bool(r["errors"]) for r in manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--download", action="store_true", help="Fetch missing NSE reports; otherwise use local raw files")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw_nse"))
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between successful downloads")
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("--end must be on or after --start")
    count_prices, count_options, error_days = collect(
        args.start, args.end, args.raw_dir, args.output_dir, args.download, args.delay)
    print(f"Wrote {count_prices} price rows, {count_options} option rows; {error_days} dates have missing/invalid sources")
    print(f"Inspect {args.output_dir / 'source_manifest.json'} before using the CSVs")
    if not count_prices or not count_options:
        raise SystemExit("No usable price or option data was collected; check the manifest")


if __name__ == "__main__":
    main()
