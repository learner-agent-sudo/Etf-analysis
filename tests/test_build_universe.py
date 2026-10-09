#!/usr/bin/env python3
"""Offline tests for scripts/build_universe.py (no network)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_universe as bu  # noqa: E402

NASDAQ_LISTED = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
ZZTEST|Test ETF Shares|G|Y|N|100|Y|N
QTUM|Defiance Quantum ETF|G|N|N|100|Y|N
File Creation Time: 1009202617:00|||||||
"""
OTHER_LISTED = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
GLD|SPDR Gold Trust, SPDR Gold Shares|P|GLD|Y|100|N|GLD
XOM|Exxon Mobil Corporation Common Stock|N|XOM|N|100|N|XOM
File Creation Time: 1009202617:00|||||||
"""


class Discovery(unittest.TestCase):
    def test_parse_symbol_directories(self):
        a = bu.parse_symbol_directory(NASDAQ_LISTED, "nasdaq")
        b = bu.parse_symbol_directory(OTHER_LISTED, "other")
        self.assertEqual([r["t"] for r in a], ["QQQ", "QTUM"])           # stock + test issue dropped
        self.assertEqual([r["t"] for r in b], ["SPY", "GLD"])
        self.assertEqual(a[0]["x"], "Nasdaq")
        self.assertEqual(b[0]["x"], "NYSE Arca")
        with self.assertRaises(ValueError):
            bu.parse_symbol_directory("<html>blocked</html>", "nasdaq")

    def test_parse_screener(self):
        j = {"data": {"data": {"rows": [{"symbol": "SPY", "companyName": "SPDR S&P 500 ETF Trust",
                                          "lastSalePrice": "$776.65", "oneYearPercentage": "15.2%"},
                                         {"symbol": "", "companyName": "x"}]}}}
        self.assertEqual(bu.parse_screener(j), [{"t": "SPY", "n": "SPDR S&P 500 ETF Trust", "p": 776.65, "c1y": 15.2}])


class Flags(unittest.TestCase):
    def test_flags(self):
        cases = {
            "Direxion Daily Semiconductor Bull 3X Shares": "L",
            "ProShares UltraPro QQQ": "L",
            "ProShares Short S&P500": "L",
            "Tradr 2X Long XNDU Daily ETF": "L",
            "-1x Short VIX Futures ETF": "LF",
            "iShares Short Treasury Bond ETF": "",            # 'short' maturity, not inverse
            "iShares MSCI USA Min Vol Factor ETF": "",
            "Invesco S&P 500 Low Volatility ETF": "",        # low-vol equity, not VIX futures
            "iPath Series B S&P 500 VIX Short-Term Futures ETN": "NF",
            "United States Natural Gas Fund, LP": "F",
            "Vanguard Total Stock Market ETF": "",
        }
        for name, want in cases.items():
            self.assertEqual(bu.flags(name), want, name)


class Units(unittest.TestCase):
    def test_calibrate_percent_units(self):
        q = {"SPY": {"netExpenseRatio": 0.0945, "ytdReturn": 14.9, "fiftyTwoWeekChangePercent": 17.2}}
        m = bu.calibrate(q, 15.1)
        self.assertEqual((m["er"], m["ytd"], m["c1y"]), (1.0, 1.0, 1.0))

    def test_calibrate_fraction_units(self):
        q = {"SPY": {"netExpenseRatio": 0.000945, "ytdReturn": 0.149, "fiftyTwoWeekChangePercent": 0.172}}
        m = bu.calibrate(q, 15.1)
        self.assertEqual((m["er"], m["ytd"], m["c1y"]), (100.0, 100.0, 100.0))

    def test_yield_units_anchor_on_spy(self):
        q = {"SPY": {"dividendYield": 1.13, "trailingAnnualDividendYield": 0.0073}}
        m = bu.calibrate(q, 15.0, 1.1)
        self.assertEqual((m["dividendYield"], m["trailingAnnualDividendYield"]), (1.0, 100.0))
        self.assertEqual(bu.pick_yield({"dividendYield": 7.9}, m), 7.9)                  # JEPI-like, percent
        self.assertEqual(bu.pick_yield({"trailingAnnualDividendYield": 0.05}, m), 5.0)   # fraction -> percent
        self.assertIsNone(bu.pick_yield({}, m))

    def test_build_rows(self):
        listing = {"SPY": {"t": "SPY", "n": "SPDR S&P 500 ETF Trust", "x": "NYSE Arca"},
                   "NEWX": {"t": "NEWX", "n": "Brand New ETF", "x": "Cboe BZX"}}
        quotes = {"SPY": {"longName": "State Street SPDR S&P 500 ETF Trust", "regularMarketPrice": 776.65,
                          "fiftyTwoWeekChangePercent": 17.24, "ytdReturn": 14.93, "netAssets": 6.5e11,
                          "netExpenseRatio": 0.0945, "trailingAnnualDividendYield": 0.0118,
                          "averageDailyVolume3Month": 61234567.8, "fundInceptionDate": 727660800}}
        screener = {"NEWX": {"t": "NEWX", "n": "Brand New ETF", "p": 25.1, "c1y": None}}
        listing["SPY"]["dom"] = "US"
        rows = bu.build_rows(listing, quotes, {"er": 1.0, "ytd": 1.0, "c1y": 1.0, "trailingAnnualDividendYield": 100.0}, screener)
        spy = dict(zip(bu.COLS, rows[1]))
        self.assertEqual(spy["t"], "SPY")
        self.assertEqual((spy["p"], spy["c1y"], spy["ytd"], spy["aum"], spy["er"], spy["yld"], spy["vol"]),
                         (776.65, 17.2, 14.9, 650000.0, 0.09, 1.18, 61234567))
        self.assertEqual(spy["inc"], "1993-01-22")
        self.assertEqual((spy["cur"], spy["dom"], spy["aumu"], spy["acur"]), ("USD", "US", 650000.0, "USD"))
        newx = dict(zip(bu.COLS, rows[0]))
        self.assertEqual((newx["p"], newx["aum"], newx["n"]), (25.1, None, "Brand New ETF"))


def make_xlsx(rows):
    """Tiny .xlsx (shared strings) for parser tests."""
    import io, zipfile
    strings, cells = [], []
    def sidx(v):
        if v not in strings:
            strings.append(v)
        return strings.index(v)
    for ri, row in enumerate(rows, start=1):
        cs = "".join(f'<c r="{chr(65 + ci)}{ri}" t="s"><v>{sidx(v)}</v></c>' for ci, v in enumerate(row) if v is not None)
        cells.append(f'<row r="{ri}">{cs}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    sst = f'<sst {ns}>' + "".join(f"<si><t>{x.replace('&', '&amp;')}</t></si>" for x in strings) + "</sst>"
    sheet = f'<worksheet {ns}><sheetData>{"".join(cells)}</sheetData></worksheet>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", sst)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


class HongKong(unittest.TestCase):
    def test_parse_hkex_list(self):
        rows = [["List of Securities"], ["Updated as at 09/10/2026"],
                ["Stock Code", "Name of Securities", "Category", "Sub-Category", "Board Lot", "ISIN"],
                ["00700", "TENCENT", "Equity", "Equity Securities (Main Board)", "100", "KYG875721634"],
                ["02800", "TRACKER FUND", "Exchange Traded Products", "Exchange Traded Funds", "500", "HK2800008867"],
                ["82800", "TRACKER FUND-R", "Exchange Traded Products", "Exchange Traded Funds", "500", "HK0000000001"],
                ["07226", "CSOP HSTECH 2X L", "Exchange Traded Products", "Leveraged and Inverse Products", "200", "HK0000664723"],
                ["03067", "ISHARES HSTECH", "Exchange Traded Products", "Exchange Traded Funds", "200", "HK0000655093"],
                ["09000", "SOME IE ETF", "Exchange Traded Products", "Exchange Traded Funds", "100", "IE00B4L5Y983"]]
        got = bu.parse_hkex(bu.read_xlsx(make_xlsx(rows)))
        self.assertEqual(sorted(got), ["2800.HK", "3067.HK", "7226.HK", "9000.HK"])
        self.assertEqual(got["2800.HK"]["dom"], "HK")
        self.assertEqual(got["9000.HK"]["dom"], "IE")              # domicile from the ISIN
        self.assertEqual(got["7226.HK"]["f"], "L")                 # leveraged & inverse product
        self.assertEqual(got["2800.HK"]["n"], "TRACKER FUND")

    def test_hk_and_london_rows_currency_and_usd_aum(self):
        listing = {"2800.HK": {"t": "2800.HK", "n": "TRACKER FUND", "x": "HKEX", "dom": "HK", "f": ""},
                   "VUSA.L": {"t": "VUSA.L", "n": "Vanguard S&P 500 UCITS ETF", "x": "London", "dom": "IE/LU",
                              "q": {"currency": "GBp", "regularMarketPrice": 9512.0, "netAssets": 4.0e10}}}
        quotes = {"2800.HK": {"currency": "HKD", "regularMarketPrice": 25.6, "netAssets": 1.6e11}}
        fx = {"USD": 1.0, "HKD": 0.128, "GBP": 1.30}
        hk = dict(zip(bu.COLS, bu.build_rows({"2800.HK": listing["2800.HK"]}, quotes, {"er": 1, "ytd": 1, "c1y": 1}, fx=fx)[0]))
        ln = dict(zip(bu.COLS, bu.build_rows({"VUSA.L": listing["VUSA.L"]}, {}, {"er": 1, "ytd": 1, "c1y": 1}, fx=fx,
                                             default_cur="GBP", aum_in_usd=True)[0]))
        self.assertEqual((hk["cur"], hk["p"], hk["aum"], hk["aumu"], hk["acur"]), ("HKD", 25.6, 160000.0, 20480.0, "HKD"))
        # London: price in pounds (from pence), AUM reported in the fund's USD base currency
        self.assertEqual((ln["cur"], ln["p"], ln["dom"], ln["aum"], ln["aumu"], ln["acur"]), ("GBP", 95.12, "IE/LU", 40000.0, 40000.0, "USD"))

    def test_yahoo_symbol(self):
        self.assertEqual(bu.yahoo_symbol("BRK.B"), "BRK-B")
        self.assertEqual(bu.yahoo_symbol("2800.HK"), "2800.HK")
        self.assertEqual(bu.yahoo_symbol("URNU.L"), "URNU.L")


class London(unittest.TestCase):
    def test_iob_duplicates_dropped_and_domicile(self):
        orig = bu.discover_screener
        bu.discover_screener = lambda y, ex, label: {
            "VUSA.L": {"t": "VUSA.L", "n": "Vanguard S&P 500 UCITS ETF", "x": label},
            "0LOS.L": {"t": "0LOS.L", "n": "Vanguard Total Stock Market ETF", "x": label},
            "PHAU.L": {"t": "PHAU.L", "n": "WisdomTree Physical Gold", "x": label}}
        try:
            got = bu.discover_lse(None)
        finally:
            bu.discover_screener = orig
        self.assertEqual(sorted(got), ["PHAU.L", "VUSA.L"])
        self.assertEqual((got["VUSA.L"]["dom"], got["PHAU.L"]["dom"]), ("IE/LU", ""))


class AumCurrency(unittest.TestCase):
    def test_name_hint(self):
        self.assertEqual(bu.aum_currency("Goldman Sachs Japan Equity UCITS ETF Class JPY (Acc)"), "JPY")
        self.assertEqual(bu.aum_currency("iShares Core MSCI Europe UCITS ETF EUR (Acc)"), "EUR")
        self.assertEqual(bu.aum_currency("Vanguard S&P 500 UCITS ETF"), "USD")


class Screener(unittest.TestCase):
    def test_paging_and_sort_field_fallback(self):
        class FakeYahoo:
            def __init__(self):
                self.calls = []
            def _crumb(self):
                return "c"
            def post_json(self, url, body):
                self.calls.append((body["sortField"], body["offset"]))
                if body["sortField"] == "fundnetassets":
                    raise RuntimeError("HTTP 400")
                start = body["offset"]
                quotes = [{"symbol": f"E{i}.L", "longName": f"Fund {i} UCITS ETF"} for i in range(start, min(start + 250, 300))]
                return json.dumps({"finance": {"result": [{"quotes": quotes, "total": 300}]}})
        y = FakeYahoo()
        got = bu.discover_screener(y, "LSE", "London")
        self.assertEqual(len(got), 300)
        self.assertEqual(y.calls, [("fundnetassets", 0), ("intradayprice", 0), ("intradayprice", 250)])


if __name__ == "__main__":
    unittest.main()
