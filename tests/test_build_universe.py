#!/usr/bin/env python3
"""Offline tests for scripts/build_universe.py (no network)."""
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
        self.assertEqual(bu.calibrate(q, 15.1), {"er": 1.0, "ytd": 1.0, "c1y": 1.0})

    def test_calibrate_fraction_units(self):
        q = {"SPY": {"netExpenseRatio": 0.000945, "ytdReturn": 0.149, "fiftyTwoWeekChangePercent": 0.172}}
        self.assertEqual(bu.calibrate(q, 15.1), {"er": 100.0, "ytd": 100.0, "c1y": 100.0})

    def test_build_rows(self):
        listing = {"SPY": {"t": "SPY", "n": "SPDR S&P 500 ETF Trust", "x": "NYSE Arca"},
                   "NEWX": {"t": "NEWX", "n": "Brand New ETF", "x": "Cboe BZX"}}
        quotes = {"SPY": {"longName": "State Street SPDR S&P 500 ETF Trust", "regularMarketPrice": 776.65,
                          "fiftyTwoWeekChangePercent": 17.24, "ytdReturn": 14.93, "netAssets": 6.5e11,
                          "netExpenseRatio": 0.0945, "trailingAnnualDividendYield": 0.0118,
                          "averageDailyVolume3Month": 61234567.8, "fundInceptionDate": 727660800}}
        screener = {"NEWX": {"t": "NEWX", "n": "Brand New ETF", "p": 25.1, "c1y": None}}
        rows = bu.build_rows(listing, quotes, {"er": 1.0, "ytd": 1.0, "c1y": 1.0}, screener)
        spy = dict(zip(bu.COLS, rows[1]))
        self.assertEqual(spy["t"], "SPY")
        self.assertEqual((spy["p"], spy["c1y"], spy["ytd"], spy["aum"], spy["er"], spy["yld"], spy["vol"]),
                         (776.65, 17.2, 14.9, 650000.0, 0.09, 1.18, 61234567))
        self.assertEqual(spy["inc"], "1993-01-22")
        newx = dict(zip(bu.COLS, rows[0]))
        self.assertEqual((newx["p"], newx["aum"], newx["n"]), (25.1, None, "Brand New ETF"))


if __name__ == "__main__":
    unittest.main()
