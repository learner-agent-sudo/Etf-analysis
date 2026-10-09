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
        self.assertEqual(doc["failed"], {"BBB": "boom"})

    def test_wrong_instrument_and_delisted_entries_are_dropped(self):
        prev = {"tickers": {"DJIA": {"price": 51231.64}, "GONE": {"price": 3}, "BUSY": {"price": 5}}}
        failed = {"DJIA": "Nasdaq: history close 51231.64 doesn't match quote 22.1 — wrong instrument",
                  "GONE": "Nasdaq: GONE: not listed (closed, non-US or wrong ticker?)",
                  "BUSY": "Yahoo Finance: HTTP 503"}
        doc = rm.merge(prev, {}, failed, "x")
        self.assertNotIn("DJIA", doc["tickers"])
        self.assertNotIn("GONE", doc["tickers"])
        self.assertTrue(doc["tickers"]["BUSY"]["stale"])

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


class CircuitBreaker(unittest.TestCase):
    def test_dead_source_is_switched_off_and_fallback_used(self):
        calls = {"a": 0, "b": 0}
        days = list(business_days(dt.date(2026, 1, 5), dt.date(2026, 3, 2)))
        good = {"bars": [(d, 10.0, 10.0, 100.0) for d in days], "returns_basis": "price", "meta": {}}

        def a(t):
            calls["a"] += 1
            raise RuntimeError("blocked")

        def b(t):
            calls["b"] += 1
            return good

        ok, failed = rm.refresh([f"T{i}" for i in range(20)], sources=[("a", a), ("b", b)], workers=1, pause=0, log=lambda *_: None, trip_after=3)
        self.assertEqual(len(ok), 20)
        self.assertEqual(failed, {})
        self.assertEqual(calls["a"], 3)          # tripped after 3 straight failures
        self.assertEqual(calls["b"], 20)

    def test_unknown_ticker_does_not_trip_breaker(self):
        def a(t):
            raise LookupError("not found")
        ok, failed = rm.refresh(["X1", "X2", "X3", "X4"], sources=[("a", a)], workers=1, pause=0, log=lambda *_: None, trip_after=2)
        self.assertEqual(sorted(failed), ["X1", "X2", "X3", "X4"])
        self.assertTrue(all("not found" in v for v in failed.values()))

    def test_all_sources_down_stops_early(self):
        def a(t):
            raise RuntimeError("down")
        ok, failed = rm.refresh([f"T{i}" for i in range(10)], sources=[("a", a)], workers=1, pause=0, log=lambda *_: None, trip_after=2)
        self.assertEqual(ok, {})
        self.assertEqual(len(failed), 10)
        self.assertEqual(failed["T9"], "all sources switched off")


class ProfileAndFallbacks(unittest.TestCase):
    PROFILE = {"quoteSummary": {"error": None, "result": [{
        "summaryDetail": {"totalAssets": {"raw": 4_620_000_000, "fmt": "4.62B"}, "yield": {"raw": 0.0071}},
        "defaultKeyStatistics": {"annualReportExpenseRatio": {"raw": 0.004}},
        "fundProfile": {"family": "Defiance ETFs", "feesExpensesInvestment": {"annualReportExpenseRatio": {"raw": 0.004}}},
        "topHoldings": {
            "holdings": [{"symbol": f"S{i}", "holdingName": f"Stock {i}", "holdingPercent": {"raw": 0.025}} for i in range(10)],
            "sectorWeightings": [{"technology": {"raw": 0.81}}, {"industrials": {"raw": 0.04}}, {"realestate": {"raw": 0}}],
        },
    }]}}

    def test_parse_profile(self):
        p = rm.parse_profile(self.PROFILE)
        self.assertEqual(p["aum_musd"], 4620)
        self.assertEqual(p["aum_display"], "~$4.6B")
        self.assertEqual(p["expense_ratio"], 0.4)
        self.assertEqual(p["yield_ttm"], "0.71%")
        self.assertEqual(len(p["holdings"]), 10)
        self.assertEqual(p["holdings"][0], {"symbol": "S0", "name": "Stock 0", "weight": 2.5})
        self.assertEqual(p["top10_weight_pct"], 25.0)
        self.assertEqual(p["sectors"], [{"sector": "Technology", "weight": 81.0}, {"sector": "Industrials", "weight": 4.0}])
        self.assertEqual(p["fund_family"], "Defiance ETFs")

    def test_parse_profile_rejects_bad_expense_and_empty(self):
        bad = json.loads(json.dumps(self.PROFILE))
        r = bad["quoteSummary"]["result"][0]
        r["fundProfile"]["feesExpensesInvestment"]["annualReportExpenseRatio"]["raw"] = 0.75   # nonsense 75%
        r["defaultKeyStatistics"] = {}
        self.assertNotIn("expense_ratio", rm.parse_profile(bad))
        with self.assertRaises(LookupError):
            rm.parse_profile({"quoteSummary": {"result": None, "error": {"description": "Quote not found"}}})
        with self.assertRaises(ValueError):
            rm.parse_profile({"quoteSummary": {"result": [{"summaryDetail": {}}]}})

    def test_parse_stooq(self):
        today = dt.date.today()
        rows = "\n".join(f"{(today - dt.timedelta(days=k)).isoformat()},1,1,1,{10 + k},{1000 * k}" for k in range(5, 0, -1))
        raw = rm.parse_stooq("Date,Open,High,Low,Close,Volume\n" + rows + "\n")
        self.assertEqual(len(raw["bars"]), 5)
        self.assertEqual(raw["returns_basis"], "price")
        with self.assertRaises(ValueError):
            rm.parse_stooq("<html>captcha</html>")

    def test_parse_nasdaq(self):
        j = {"data": {"tradesTable": {"rows": [
            {"date": "10/08/2026", "close": "$169.35", "volume": "1,234,567"},
            {"date": "10/07/2026", "close": "$1,168.10", "volume": "N/A"},
            {"date": "bad", "close": "$1"}]}}}
        raw = rm.parse_nasdaq(j)
        self.assertEqual(raw["bars"][0], (dt.date(2026, 10, 8), 169.35, 169.35, 1234567.0))
        self.assertEqual(raw["bars"][1][1], 1168.10)
        self.assertIsNone(raw["bars"][1][3])
        self.assertEqual(len(raw["bars"]), 2)
        with self.assertRaises(ValueError):
            rm.parse_nasdaq({"data": None})

    def test_profile_failure_carries_previous_profile_and_prunes(self):
        prev = {"tickers": {"AAA": {"price": 1, "aum_musd": 50, "holdings": [1], "profile_asof": "2026-10-01"},
                            "GONE": {"price": 9}}}
        fresh = {"AAA": {"price": 2, "price_asof": "2026-10-08"}}
        doc = rm.merge(prev, fresh, {}, "x", keep={"AAA"})
        self.assertEqual(doc["tickers"]["AAA"]["aum_musd"], 50)
        self.assertEqual(doc["tickers"]["AAA"]["profile_asof"], "2026-10-01")
        self.assertNotIn("GONE", doc["tickers"])

    def test_refresh_adds_profile_and_survives_profile_outage(self):
        days = list(business_days(dt.date(2026, 1, 5), dt.date(2026, 3, 2)))
        good = {"bars": [(d, 10.0, 10.0, 100.0) for d in days], "returns_basis": "total", "meta": {}}
        calls = {"p": 0}

        def prof(t):
            calls["p"] += 1
            if t == "A":
                return {"aum_musd": 5}
            raise RuntimeError("crumb blocked")

        ok, failed = rm.refresh(["A", "B", "C", "D", "E"], sources=[("g", lambda t: good)], profile=prof,
                                workers=1, pause=0, log=lambda *_: None, trip_after=2)
        self.assertEqual(len(ok), 5)
        self.assertEqual(ok["A"]["aum_musd"], 5)
        self.assertIn("profile_asof", ok["A"])
        self.assertNotIn("profile_asof", ok["B"])
        self.assertEqual(calls["p"], 3)          # A ok, B + C fail -> switched off


class NasdaqTotalReturn(unittest.TestCase):
    def test_apply_dividends_turns_flat_price_into_total_return(self):
        days = list(business_days(dt.date(2025, 10, 1), dt.date(2026, 10, 8)))
        bars = [(d, 50.0, 50.0, 1000.0) for d in days]
        exdates = [dt.date(2025, 12, 1), dt.date(2026, 3, 2), dt.date(2026, 6, 1), dt.date(2026, 9, 1)]
        divs = [(d, 0.5) for d in exdates] + [(dt.date(2026, 12, 1), 0.5)]   # last one is in the future
        adj = rm.apply_dividends(bars, divs)
        m = rm.compute_metrics(adj, "total")
        self.assertEqual(m["performance"]["y1"], "+4.1%")     # 1.01^4 - 1 = 4.06%
        self.assertEqual(adj[-1][2], 50.0)                    # latest bar is unadjusted
        self.assertEqual(m["price"], 50.0)

    def test_parse_nasdaq_dividends(self):
        j = {"data": {"dividends": {"rows": [
            {"exOrEffDate": "09/29/2026", "amount": "$0.4512"}, {"exOrEffDate": "N/A", "amount": "$1"},
            {"exOrEffDate": "08/28/2026", "amount": "$0.00"}]}}}
        self.assertEqual(rm.parse_nasdaq_dividends(j), [(dt.date(2026, 9, 29), 0.4512)])
        self.assertEqual(rm.parse_nasdaq_dividends({"data": {"dividends": {"rows": None}}}), [])
        with self.assertRaises(ValueError):
            rm.parse_nasdaq_dividends({"data": None})

    def _fake(self, routes):
        calls = []

        def fake(path):
            calls.append(path)
            for key, val in routes.items():
                if key in path:
                    return val
            return {"data": None}
        return fake, calls

    def _hist(self, price):
        today = dt.date(2026, 10, 8)
        rows = [{"date": (today - dt.timedelta(days=k)).strftime("%m/%d/%Y"), "close": f"${price}", "volume": "1,000"}
                for k in range(0, 400)]
        return {"data": {"tradesTable": {"rows": rows}}}

    def test_fetch_nasdaq_rejects_wrong_instrument(self):
        # DJIA: the history endpoint returned the Dow index (~51,000) while the
        # ETF quotes ~$22 -> must be rejected, not published.
        fake, _ = self._fake({"info?assetclass=etf": {"data": {"companyName": "Global X Dow 30 Covered Call ETF",
                                                               "primaryData": {"lastSalePrice": "$22.10"}}},
                              "historical": self._hist("51,231.64")})
        orig = rm._nasdaq
        rm._nasdaq = fake
        try:
            with self.assertRaises(ValueError):
                rm.fetch_nasdaq("DJIA", today=dt.date(2026, 10, 8))
        finally:
            rm._nasdaq = orig

    def test_fetch_nasdaq_stock_fallback_and_total_return(self):
        fake, calls = self._fake({"info?assetclass=stocks": {"data": {"companyName": "Eli Lilly",
                                                                      "primaryData": {"lastSalePrice": "$100.00"}}},
                                  "historical?assetclass=stocks": self._hist("100.00"),
                                  "dividends?assetclass=stocks": {"data": {"dividends": {"rows": [
                                      {"exOrEffDate": "06/01/2026", "amount": "$2.00"}]}}}})
        orig = rm._nasdaq
        rm._nasdaq = fake
        try:
            raw = rm.fetch_nasdaq("LLY", today=dt.date(2026, 10, 8))
        finally:
            rm._nasdaq = orig
        self.assertEqual(raw["meta"]["instrument_type"], "Stock")
        self.assertEqual(raw["returns_basis"], "total")
        self.assertTrue(any("info?assetclass=etf" in c for c in calls))
        m = rm.compute_metrics(raw["bars"], raw["returns_basis"], raw["meta"])
        self.assertEqual(m["performance"]["y1"], "+2.0%")

    def test_fetch_nasdaq_unknown_ticker(self):
        fake, _ = self._fake({})
        orig = rm._nasdaq
        rm._nasdaq = fake
        try:
            with self.assertRaises(LookupError):
                rm.fetch_nasdaq("ZZZZ")
        finally:
            rm._nasdaq = orig


if __name__ == "__main__":
    unittest.main()
