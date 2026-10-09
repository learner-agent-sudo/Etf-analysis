#!/usr/bin/env python3
"""Offline tests for scripts/refresh_market.py (no network).

Run:  python3 -m unittest discover -s tests -v
"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import refresh_market as rm  # noqa: E402


def business_days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


def yahoo_payload(days, close_fn, adj_fn=None, vol=1_000_000, gmtoffset=-14400):
    """Build a Yahoo-chart-shaped JSON for the given trading days."""
    adj_fn = adj_fn or close_fn
    # Yahoo stamps daily bars at the session open (13:30 UTC); keep it simple.
    ts = [int(dt.datetime(d.year, d.month, d.day, 13, 30, tzinfo=dt.timezone.utc).timestamp()) for d in days]
    return {"chart": {"error": None, "result": [{
        "meta": {"currency": "USD", "longName": "Test Fund ETF", "instrumentType": "ETF",
                 "gmtoffset": gmtoffset, "firstTradeDate": ts[0],
                 "regularMarketPrice": round(close_fn(days[-1]), 2)},
        "timestamp": ts,
        "indicators": {
            "quote": [{"close": [close_fn(d) for d in days], "volume": [vol for _ in days]}],
            "adjclose": [{"adjclose": [adj_fn(d) for d in days]}],
        },
    }]}}


class ParseAndCompute(unittest.TestCase):
    def setUp(self):
        self.end = dt.date(2026, 10, 8)
        self.days = list(business_days(dt.date(2021, 10, 11), self.end))

    def test_flat_price_with_dividends_gives_total_return(self):
        # Price flat at $50, but adjusted closes grow 10%/yr (dividends reinvested):
        # the site must show TOTAL return, not 0%.
        base = self.days[0]
        adj = lambda d: 50 * 1.10 ** ((d - base).days / 365.0)  # noqa: E731
        raw = rm.parse_yahoo(yahoo_payload(self.days, lambda d: 50.0, adj))
        m = rm.compute_metrics(raw["bars"], raw["returns_basis"], raw["meta"])
        self.assertEqual(m["price"], 50.0)
        self.assertEqual(m["price_display"], "$50.00")
        self.assertEqual(m["price_asof"], "2026-10-08")
        self.assertEqual(m["performance"]["y1"], "+10.0%")
        self.assertEqual(m["performance"]["y3_annualized"], "+10.0%/yr")
        self.assertEqual(m["performance"]["y2025"], "+10.0%")
        # 2024: leap year + Dec 29 '23 (Fri) → Dec 31 '24 span is 368 days → ~+10.1%
        self.assertIn(m["performance"]["y2024"], ("+10.0%", "+10.1%"))
        self.assertTrue(m["performance"]["ytd"].startswith("+7."))  # ~Jan 1 → Oct 8
        self.assertIn("total return", m["performance"]["basis"])
        self.assertEqual(m["pct_below_high"], "0.0%")     # flat price → at the high
        self.assertEqual(m["volume_avg"], 1_000_000)
        self.assertEqual(m["volume_display"], "~1.0M/day")
        self.assertEqual(m["dollar_volume_display"], "~$50.0M/day")
        self.assertEqual(m["name"], "Test Fund ETF")

    def test_young_fund_has_no_long_returns(self):
        days = list(business_days(dt.date(2026, 3, 2), self.end))
        raw = rm.parse_yahoo(yahoo_payload(days, lambda d: 20.0 + (d - days[0]).days * 0.01))
        m = rm.compute_metrics(raw["bars"], raw["returns_basis"], raw["meta"])
        p = m["performance"]
        self.assertIsNone(p["ytd"])            # launched after Dec 31 → no YTD
        self.assertIsNone(p["y1"])
        self.assertIsNone(p["y3_annualized"])
        self.assertNotIn("y2025", p)
        self.assertNotIn("y2024", p)
        self.assertEqual(m["history_start"], "2026-03-02")

    def test_drawdown_and_52w_range(self):
        days = list(business_days(dt.date(2025, 9, 1), self.end))
        mid = days[len(days) // 2]
        price = lambda d: 100.0 if d <= mid else 60.0  # noqa: E731  — a 40% crash
        raw = rm.parse_yahoo(yahoo_payload(days, price))
        m = rm.compute_metrics(raw["bars"], raw["returns_basis"], raw["meta"])
        self.assertEqual(m["high_52w"], 100.0)
        self.assertEqual(m["low_52w"], 60.0)
        self.assertEqual(m["max_drawdown_1y"], "-40.0%")
        self.assertEqual(m["pct_below_high"], "-40.0%")

    def test_null_bars_are_skipped(self):
        p = yahoo_payload(self.days[-30:], lambda d: 10.0)
        p["chart"]["result"][0]["indicators"]["quote"][0]["close"][5] = None
        raw = rm.parse_yahoo(p)
        self.assertEqual(len(raw["bars"]), 29)

    def test_yahoo_error_payload(self):
        with self.assertRaises(LookupError):
            rm.parse_yahoo({"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}})


class MergeAndTickers(unittest.TestCase):
    def test_failed_ticker_keeps_last_good_entry(self):
        prev = {"tickers": {"AAA": {"price": 1, "price_asof": "2026-10-01"},
                            "BBB": {"price": 2, "price_asof": "2026-10-01"}}}
        fresh = {"AAA": {"price": 3, "price_asof": "2026-10-08"}}
        doc = rm.merge(prev, fresh, {"BBB": "boom"}, "2026-10-08T22:00:00+00:00")
        self.assertEqual(doc["tickers"]["AAA"]["price"], 3)
        self.assertEqual(doc["tickers"]["BBB"]["price"], 2)
        self.assertTrue(doc["tickers"]["BBB"]["stale"])
        self.assertEqual(doc["as_of"], "2026-10-08")
        self.assertEqual(doc["failed"], ["BBB"])

    def test_theme_tickers_reads_curated_and_roster_but_not_market_json(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.json"), "w") as fh:
                json.dump({"etfs": [{"ticker": "qtum"}], "roster": [{"ticker": "QTUM"}, {"ticker": "WQTM"}]}, fh)
            with open(os.path.join(d, "market.json"), "w") as fh:
                json.dump({"tickers": {"ZZZ": {}}}, fh)
            self.assertEqual(rm.theme_tickers(d), ["QTUM", "WQTM"])

    def test_real_theme_files_parse(self):
        tickers = rm.theme_tickers()
        self.assertGreater(len(tickers), 50)
        self.assertIn("QTUM", tickers)


if __name__ == "__main__":
    unittest.main()
