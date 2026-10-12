#!/usr/bin/env python3
"""Offline tests for scripts/build_income.py (no network)."""
import datetime as dt
import math
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


class Streak(unittest.TestCase):
    def test_month_boundary_slip_is_not_a_break(self):
        # monthly payer whose ex-date slips from the 31st to the 1st (an empty calendar month)
        d = [dt.date(2025, 1, 30) + dt.timedelta(days=30 * i) for i in range(20)]
        d[10] = d[10] + dt.timedelta(days=2)
        divs = [(x, 0.2) for x in d]
        self.assertGreaterEqual(bi.payout_streak_months(divs, d[-1] + dt.timedelta(days=5)), 18)

    def test_real_gap_and_stopped_paying(self):
        d = [dt.date(2024, 1, 15) + dt.timedelta(days=30 * i) for i in range(10)] + \
            [dt.date(2025, 3, 15) + dt.timedelta(days=30 * i) for i in range(6)]       # 4-month pause
        divs = [(x, 0.1) for x in d]
        self.assertEqual(bi.payout_streak_months(divs, d[-1] + dt.timedelta(days=10)), 5)
        self.assertEqual(bi.payout_streak_months(divs, d[-1] + dt.timedelta(days=200)), 0)

    def test_switch_from_monthly_to_weekly_is_not_a_break(self):
        d = [dt.date(2023, 1, 15) + dt.timedelta(days=30 * i) for i in range(30)]
        d += [d[-1] + dt.timedelta(days=7 * (i + 1)) for i in range(20)]
        self.assertGreaterEqual(bi.payout_streak_months([(x, 0.1) for x in d], d[-1]), 30)

    def test_weekly_payer(self):
        d = [dt.date(2025, 1, 3) + dt.timedelta(days=7 * i) for i in range(60)]
        self.assertGreaterEqual(bi.payout_streak_months([(x, 0.05) for x in d], d[-1]), 13)


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

    def test_evidence_shrinkage_for_short_history(self):
        f = self.base()
        m_full = {"gap": 0.02, "price_cagr": 0.05, "window_years": 3.0, "streak_months": 30}
        m_young = dict(m_full, window_years=1.0)
        full = bi.components(f, m_full, False)
        self.assertEqual((full["gap"], full["nav"]), (91.7, 96.6))          # smooth curves, no saturation
        # young fund: pulled toward the family's typical seasoned value, not toward 50
        young = bi.components(f, m_young, False, priors={"gap": 20.0, "nav": 60.0})
        self.assertAlmostEqual(young["gap"], 20 + (91.7 - 20) / 3, places=0)
        self.assertAlmostEqual(young["nav"], 60 + (96.6 - 60) / 3, places=0)
        self.assertEqual(young["tax"], full["tax"])                           # non-history components untouched

    def test_more_classification(self):
        g = bi.classify("IncomeShares Alphabet (GOOG) Options ETP")
        self.assertEqual((g["family"], g["bench"], g["note"]), ("single_stock", "GOOG", True))
        self.assertEqual(bi.classify("FT Vest Technology Dividend Target Income ETF")["bench"], "XLK")
        self.assertEqual(bi.classify("FT Vest Dow Jones Internet & Target Income ETF")["bench"], "FDN")
        self.assertEqual(bi.classify("KraneShares KWEB Covered Call Strategy ETF")["bench"], "KWEB")
        self.assertEqual(bi.classify("Global X MLP & Energy Infrastructure Covered Call ETF")["bench"], "AMLP")
        self.assertEqual(bi.classify("Global X Hang Seng TECH Covered Call Active ETF")["bench"], "3067.HK")
        self.assertEqual(bi.classify("NEOS S&P 500(R) High Income ETF")["bench"], "SPY")   # '(R)' is not a ticker

    def test_missing_evidence_not_scored(self):
        score, _ = bi.weighted({"tax": 70}, "systematic_cc", us_view=True)
        self.assertIsNone(score)
        # a brand-new active fund: fees/counterparty/transparency alone must not produce a score
        score, _ = bi.weighted({"counterparty": 90, "transparency": 90, "fees": 85}, "active_premium", us_view=True)
        self.assertIsNone(score)

    def test_eln_and_extreme_yield(self):
        c = bi.components(self.base(family="active_premium", eln=True), {"streak_months": 2}, extreme_yield=True)
        self.assertEqual((c["counterparty"], c["transparency"], c["tax"]), (50, 50, 35))
        self.assertEqual(c["quality"], 90 - 25 - 10)

    def test_extreme_yield_cutoff_is_per_family(self):
        def fund(fam, y):
            return {"family": fam, "metrics": {"yield_regular": y}}
        funds = [fund("single_stock", 0.5 + i / 20) for i in range(20)] + \
                [fund("systematic_cc", 0.08 + i / 200) for i in range(20)] + [fund("short_vol", 0.2)]
        cut = bi.extreme_yield_cutoffs(funds)
        self.assertLess(cut["systematic_cc"], 0.2)          # an index covered call at 20% IS extreme
        self.assertGreater(cut["single_stock"], 1.0)        # 60-140% is normal for single-stock funds
        self.assertEqual(cut["short_vol"], 0.30)            # small family -> flat 30%
        # a 10-fund family with modest yields never flags its top fund (old p95 bug)
        small = [fund("dividend_options", 0.05 + i / 200) for i in range(10)]
        self.assertGreater(bi.extreme_yield_cutoffs(small)["dividend_options"], 0.1)

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
        self.assertFalse(bi.gates(self.base(note=True), m, 1.0)["structure"])


class ReviewFindings(unittest.TestCase):
    """Regression tests for the adversarial review of the first real build."""

    def test_classification_cases(self):
        none = ["Defiance Daily Target 2X Long AVGO ETF", "State Street Blackstone High Income ETF",
                "NYLIM MacKay High Income ETF", "Amplify CEF High Income ETF"]
        for n in none:
            self.assertIsNone(bi.classify(n), n)
        cases = {
            "YieldMax(TM) RBLX Option Income Strategy ETF": ("single_stock", "RBLX"),
            "Yieldmax Gme Option Income Strategy ETF": ("single_stock", "GME"),
            "YieldMax BRK.B Option Income Strategy ETF": ("single_stock", "BRK-B"),
            "IncomeShares Berkshire Hathaway (BRK-B) Options ETP": ("single_stock", "BRK-B"),
            "YieldMax AI Option Income Strategy ETF": ("single_stock", "AI"),
            "IncomeShares Taiwan Semiconductors (TSM) Options ETP": ("single_stock", "TSM"),
            "Amplify COWS Covered Call ETF": ("systematic_cc", "COWS"),
            "Graniteshares Autocallable Hood ETF": ("structured", "HOOD"),
            "State Street Communication Services Select Sector SPDR Premium Income ETF": ("active_premium", "XLC"),
            "iShares 20+ Year Treasury Bond BuyWrite Strategy ETF": ("systematic_cc", "TLT"),
            "Global X Euro Stoxx 50 Covered Call UCITS ETF EUR Distributing": ("systematic_cc", "FEZ"),
            "Global X Hang Seng High Dividend Yield Covered Call ETF": ("dividend_options", "2800.HK"),
            "NEOS S&P 500(R) High Income ETF": ("call_spread", "SPY"),
            "Neuberger Berman Option Strategy ETF": ("put_write", "SPY"),
        }
        for n, (fam, bench) in cases.items():
            c = bi.classify(n)
            self.assertIsNotNone(c, n)
            self.assertEqual((c["family"], c["bench"]), (fam, bench), n)
        self.assertEqual(bi.classify("Amplify COWS Covered Call ETF")["exposure"], "sector")
        self.assertEqual(bi.classify("Graniteshares Autocallable Hood ETF")["exposure"], "single stock")
        self.assertEqual(bi.classify("iShares 20+ Year Treasury Bond BuyWrite Strategy ETF")["exposure"], "bond")
        inv = bi.classify("YieldMax MSTR Short Option Income Strategy ETF")
        self.assertTrue(inv["inverse"])
        self.assertIsNone(inv["bench"])                       # no meaningful long benchmark
        self.assertNotEqual(bi.classify("REX IncomeMax Option Strategy ETF")["bench"], "REX")
        self.assertIsNone(bi.classify("Some Covered Call UCITS ETF", ticker="ABCD.L")["bench"])   # no silent SPY abroad
        self.assertTrue(bi.classify("Thornburg Premium Income Builder ETF")["bench_assumed"])
        for sym in ("2800.HK", "2828.HK", "3067.HK", "069500.KS"):
            self.assertFalse(sym.startswith("^"))
        self.assertFalse(any(b.startswith("^") for _, b in bi.BENCH_RULES))   # total-return benchmarks only

    def test_coverage_is_log_consistent(self):
        self.assertEqual(bi.coverage_share(0.08, 0.01), 1.0)
        self.assertEqual(bi.coverage_share(-0.20, -0.60), 0.0)          # negative total return -> nothing covered
        self.assertEqual(bi.coverage_share(0.0, -0.40), 0.0)
        self.assertAlmostEqual(bi.coverage_share(0.05, -0.40), math.log(1.05) / (math.log(1.05) - math.log(0.6)), places=6)
        self.assertLess(bi.coverage_share(0.05, -0.40), 0.1)

    def test_bad_ticks_dropped(self):
        days = DAYS[:200]
        bars = [(d, 15.0, 15.0, 1e5) for d in days]
        for i in (50, 120, 121):                              # single-day bad prints (one, then a pair)
            bars[i] = (bars[i][0], 1.93, 1.93, 1e5)
        clean, n = bi.drop_bad_ticks(bars)
        self.assertEqual(n, 1)                                # the isolated spike; a 2-day run isn't a 'tick'
        m = bi.compute([b for b in clean if b[1] > 5], [])
        self.assertGreater(m.get("max_drawdown", 0) if "max_drawdown" in m else 0, -0.05)

    def test_specials_excluded_from_regular_yield(self):
        base = dt.date(2025, 10, 15)
        divs = [(base + dt.timedelta(days=30 * i), 0.2) for i in range(12)]
        divs.append((dt.date(2025, 12, 20), 2.9))           # year-end capital gains
        regular, special = bi.split_specials(divs, dt.date(2026, 10, 9))
        self.assertAlmostEqual(special, 2.9)
        self.assertAlmostEqual(regular, 0.2 * 12, places=6)

    def test_stale_benchmark_end_rejected(self):
        bars, divs = fund(0.0, 0.08)
        bench = [(d, v) for d, v in series(0.15) if d <= END - dt.timedelta(days=365)]
        m = bi.compute(bars, divs, bench=bench)
        self.assertNotIn("gap", m)

    def test_benchmark_alignment_tolerates_holiday_gaps(self):
        bars, divs = fund(0.0, 0.08)
        w0 = dt.date.fromisoformat(bi.compute(bars, divs)["window_start"])
        bench = [(d, v) for d, v in series(0.10) if d >= w0 + dt.timedelta(days=4)]       # starts 4 days late
        m = bi.compute(bars, divs, bench=bench)
        self.assertIn("gap", m)
        late = [(d, v) for d, v in series(0.10) if d >= w0 + dt.timedelta(days=60)]       # 2 months late
        m2 = bi.compute(bars, divs, bench=late)
        self.assertNotIn("gap", m2)
        self.assertIn("bench_span", m2)

    def test_logistic_breaks_ties(self):
        f = Scoring.base(Scoring())
        a = bi.components(f, {"gap": -0.18, "price_cagr": 0.0005, "window_years": 3}, False)
        b = bi.components(f, {"gap": -0.084, "price_cagr": 0.052, "window_years": 3}, False)
        sa, _ = bi.weighted(a, "systematic_cc", True)
        sb, _ = bi.weighted(b, "systematic_cc", True)
        self.assertGreater(sb, sa)

    def test_eln_weights_only_for_eln_funds(self):
        base = Scoring.base(Scoring())
        self.assertEqual(bi.weights_key(dict(base, family="active_premium", eln=True)), "active_premium_eln")
        self.assertEqual(bi.weights_key(dict(base, family="active_premium", eln=False)), "default")
        # an eroding non-ELN active fund can no longer score high on constants
        eroding = bi.components(dict(base, family="active_premium"), {"gap": -0.50, "price_cagr": -0.30,
                                                                     "coverage": 0.0, "window_years": 3}, False)
        score, _ = bi.weighted(eroding, "default", True)
        self.assertLess(score, 35)

    def test_family_priors(self):
        funds = [{"family": "x", "metrics": {"window_years": 3}, "raw": {"gap": g}} for g in (10, 20, 30, 40, 50)]
        funds.append({"family": "x", "metrics": {"window_years": 1}, "raw": {"gap": 99}})     # young: not a prior
        self.assertEqual(bi.family_priors(funds)["x"]["gap"], 30)

    def test_currency_compatibility(self):
        self.assertTrue(bi.currencies_compatible("HKD", "USD"))
        self.assertFalse(bi.currencies_compatible("GBP", "USD"))
        self.assertEqual(bi.bench_currency("069500.KS"), "KRW")


if __name__ == "__main__":
    unittest.main()
