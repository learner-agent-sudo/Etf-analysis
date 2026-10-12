#!/usr/bin/env python3
"""Offline tests for scripts/build_income.py (no network)."""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_income as bi  # noqa: E402


def bdays(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


END = dt.date(2026, 10, 9)
DAYS = list(bdays(dt.date(2021, 10, 11), END))


def series(rate_per_year, start_val=100.0, days=DAYS):
    """Smooth series growing at `rate_per_year`."""
    return [(d, start_val * (1 + rate_per_year) ** ((d - days[0]).days / 365.25)) for d in days]


def fund(price_rate, total_rate, monthly=True, days=DAYS):
    """Bars where price drifts at price_rate and adjusted closes at total_rate."""
    px = series(price_rate, days=days)
    adj = series(total_rate, days=days)
    bars = [(d, p, a, 500_000.0) for (d, p), (_, a) in zip(px, adj)]
    divs = []
    if monthly:
        for (d, p) in px:
            if d.day <= 3 and (not divs or divs[-1][0].month != d.month):
                divs.append((d, p * (total_rate - price_rate) / 12))
    return bars, divs


class Classify(unittest.TestCase):
    def test_families_and_benchmarks(self):
        cases = {
            "Global X NASDAQ 100 Covered Call ETF": ("systematic_cc", "QQQ", False),
            "JPMorgan Equity Premium Income ETF": ("active_premium", "SPY", True),
            "NEOS S&P 500(R) High Income ETF": ("call_spread", "SPY", False),
            "Simplify Volatility Premium ETF": ("short_vol", "SPY", False),
            "YieldMax TSLA Option Income Strategy ETF": ("single_stock", "TSLA", False),
            "Roundhill S&P 500 0DTE Covered Call Strategy ETF": ("daily_0dte", "SPY", False),
            "Amplify CWP Enhanced Dividend Income ETF": ("dividend_options", "SPY", False),
            "GraniteShares YieldBOOST TSLA ETF": ("leveraged_income", "TSLA", False),
            "Global X Russell 2000 Covered Call ETF": ("systematic_cc", "IWM", False),
        }
        for name, (fam, bench, eln) in cases.items():
            c = bi.classify(name)
            self.assertIsNotNone(c, name)
            self.assertEqual((c["family"], c["bench"], c["eln"]), (fam, bench, eln), name)

    def test_non_income_funds_excluded(self):
        for name in ["Vanguard Total Stock Market ETF", "Schwab Ultra-Short Income ETF",
                     "FT Confluence BDC & Specialty Finance Income ETF", "Innovator U.S. Equity Buffer ETF - July",
                     "iShares Core U.S. Aggregate Bond ETF"]:
            self.assertIsNone(bi.classify(name), name)

    def test_style_drives_gates(self):
        self.assertEqual(bi.classify("Global X S&P 500 Covered Call ETF")["style"], "systematic")
        self.assertEqual(bi.classify("JPMorgan Nasdaq Equity Premium Income ETF")["style"], "active")
        self.assertEqual(bi.classify("Hang Seng HSCEI Covered Call Active ETF")["style"], "active")

    def test_share_class_key(self):
        a = bi.share_class_key("YieldMax Semiconductor Option Income UCITS ETF USD Dis")
        b = bi.share_class_key("YieldMax Semiconductor Option Income UCITS ETF GBP Hedged Acc")
        self.assertEqual(a, b)


class Metrics(unittest.TestCase):
    def test_covered_by_total_return(self):
        # price flat, 8%/yr total return -> distributions fully covered, NAV trend 0
        bars, divs = fund(0.0, 0.08)
        bench = series(0.10)
        m = bi.compute(bars, divs, bench=bench)
        self.assertAlmostEqual(m["tr_ann"], 0.08, places=3)
        self.assertAlmostEqual(m["price_cagr"], 0.0, places=3)
        self.assertEqual(m["coverage"], 1.0)
        self.assertAlmostEqual(m["gap"], -0.02, places=3)
        self.assertEqual(m["payments_12m"], 12)
        self.assertEqual(m["streak_months"] >= 24, True)
        self.assertGreater(m["yield_ttm"], 0.07)

    def test_paid_from_capital(self):
        # price falls 6%/yr while total return is +4% -> ~10% distributions, 40% covered
        bars, divs = fund(-0.06, 0.04)
        m = bi.compute(bars, divs, bench=series(0.10))
        self.assertAlmostEqual(m["price_cagr"], -0.06, places=3)
        self.assertGreater(m["dist_yield_ann"], 0.09)
        self.assertLess(m["coverage"], 0.5)
        self.assertGreater(m["coverage"], 0.3)

    def test_short_history_not_scored(self):
        days = list(bdays(dt.date(2026, 3, 2), END))
        bars, divs = fund(0.0, 0.10, days=days)
        m = bi.compute(bars, divs)
        self.assertTrue(m.get("short_history"))
        self.assertNotIn("tr_ann", m)
        self.assertGreater(len(m["dist_hist"]), 3)

    def test_capture_and_vix_beta(self):
        # fund = half the benchmark's daily moves -> capture ~0.5 both ways; VIX beta from inverse link
        import math
        days = DAYS
        bench, fundb, vix = [], [], []
        b = f = 100.0
        v = 20.0
        for i, d in enumerate(days):
            r = 0.01 * math.sin(i / 3.0)
            b *= 1 + r
            f *= 1 + r / 2
            v *= 1 - 3 * r
            bench.append((d, b)); fundb.append((d, f, f, 1e6)); vix.append((d, v))
        m = bi.compute(fundb, [], bench=bench, vix=vix)
        self.assertAlmostEqual(m["up_capture"], 0.5, delta=0.1)
        self.assertAlmostEqual(m["down_capture"], 0.5, delta=0.1)
        self.assertLess(m["vix_beta"], 0)


class Scoring(unittest.TestCase):
    def base(self, **kw):
        f = {"family": "systematic_cc", "style": "systematic", "eln": False, "exposure": "broad index",
             "market": "US", "er": 0.60, "aum_usd": 8000, "age_years": 10, "vol": 5_000_000, "flags": ""}
        f.update(kw)
        return f

    def test_components_and_family_weights(self):
        f = self.base()
        m = {"gap": -0.04, "coverage": 0.5, "price_cagr": -0.05, "streak_months": 60}
        c = bi.components(f, m, extreme_yield=False)
        self.assertEqual((c["gap"], c["coverage"], c["nav"], c["tax"]), (50.0, 50.0, 50.0, 70))
        score, used = bi.weighted(c, "systematic_cc", us_view=True)
        self.assertEqual(used, {"nav": 40.0, "gap": 30.0, "tax": 30.0})
        self.assertEqual(score, round(50 * 0.4 + 50 * 0.3 + 70 * 0.3, 1))
        score_intl, used_intl = bi.weighted(c, "systematic_cc", us_view=False)
        self.assertNotIn("tax", used_intl)
        self.assertEqual(score_intl, 50.0)

    def test_missing_evidence_not_scored(self):
        score, _ = bi.weighted({"tax": 70}, "systematic_cc", us_view=True)
        self.assertIsNone(score)

    def test_eln_and_extreme_yield(self):
        c = bi.components(self.base(family="active_premium", eln=True), {"streak_months": 2}, extreme_yield=True)
        self.assertEqual((c["counterparty"], c["transparency"], c["tax"]), (50, 50, 35))
        self.assertEqual(c["quality"], 90 - 25 - 10)

    def test_tiered_gates(self):
        m = {"price": 50.0}
        g = bi.gates(self.base(), m, 1.0)
        self.assertTrue(all(g.values()))
        g = bi.gates(self.base(style="active", aum_usd=300, age_years=2.5, er=0.80), m, 1.0)
        self.assertEqual((g["aum"], g["age"], g["er"]), (False, False, True))
        # liquidity: 50K shares but $2.5M/day passes on dollars
        g = bi.gates(self.base(vol=50_000), m, 1.0)
        self.assertTrue(g["liquidity"])
        g = bi.gates(self.base(vol=20_000), m, 1.0)
        self.assertFalse(g["liquidity"])
        self.assertFalse(bi.gates(self.base(family="leveraged_income"), m, 1.0)["structure"])


if __name__ == "__main__":
    unittest.main()
