import io
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

from main.data_pipeline.fetch_nse_data import (
    collect, csv_rows, parse_equity, parse_index, parse_options, report_url,
)


def zipped(text):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("bhav.csv", text)
    return buffer.getvalue()


class NSEDataTests(unittest.TestCase):
    def test_archive_urls_change_on_july_2024(self):
        self.assertEqual(
            report_url("options", date(2023, 8, 1)),
            "https://archives.nseindia.com/content/historical/DERIVATIVES/2023/AUG/fo01AUG2023bhav.csv.zip",
        )
        self.assertIn("BhavCopy_NSE_FO_0_0_0_20240708_F_0000.csv.zip",
                      report_url("options", date(2024, 7, 8)))

    def test_old_and_udiff_rows(self):
        day = date(2023, 8, 1)
        old_equity = csv_rows(zipped(
            "SYMBOL,SERIES,CLOSE,TIMESTAMP\nRELIANCE,EQ,2510.50,01-AUG-2023\n"))
        self.assertEqual(parse_equity(old_equity, day)["RELIANCE"], "2510.50")
        old_fo = csv_rows(zipped(
            "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,CLOSE,SETTLE_PR,CONTRACTS,OPEN_INT,TIMESTAMP\n"
            "OPTSTK,RELIANCE,31-AUG-2023,2400,PE,22.5,23.0,123,456,01-AUG-2023\n"))
        self.assertEqual(parse_options(old_fo, day)[0]["open_interest"], "456")
        self.assertEqual(parse_options(old_fo, day)[0]["lot_size"], "")
        udiff = csv_rows(zipped(
            "TckrSymb,XpryDt,StrkPric,OptnTp,ClsPric,SttlmPric,TtlTradgVol,OpnIntrst,NewBrdLotQty,TradDt\n"
            "RELIANCE,2024-07-25,2800,CE,18.1,18.5,97,205,250,2024-07-08\n"))
        self.assertEqual(parse_options(udiff, date(2024, 7, 8))[0]["lot_size"], "250")

    def test_collect_cached_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            day = date(2024, 7, 8)
            for kind, payload in {
                "equity": zipped("TckrSymb,SctySrs,ClsPric,TradDt\nRELIANCE,EQ,3100,2024-07-08\n"),
                "options": zipped("TckrSymb,XpryDt,StrkPric,OptnTp,ClsPric,SttlmPric\n"
                                  "RELIANCE,2024-07-25,3000,PE,20,21\n"),
                "index": b"Index Name,Index Date,Closing Index Value\nNIFTY 50,08-07-2024,24000\n",
            }.items():
                folder = base / "raw" / kind
                folder.mkdir(parents=True)
                (folder / f"{day.isoformat()}{'.csv' if kind == 'index' else '.zip'}").write_bytes(payload)
            prices, options, errors = collect(day, day, base / "raw", base / "out")
            self.assertEqual((prices, options, errors), (1, 1, 1))
            self.assertIn("24000", (base / "out" / "real_prices.csv").read_text())
            self.assertIn("2024-07-25", (base / "out" / "real_options.csv").read_text())

    def test_index_snapshot_with_month_first_date(self):
        rows = csv_rows(b"Index Name,Index Date,Closing Index Value\nNifty 50,04-06-2023,17599.15\n")
        self.assertEqual(parse_index(rows, date(2023, 4, 6)), "17599.15")


if __name__ == "__main__":
    unittest.main()
