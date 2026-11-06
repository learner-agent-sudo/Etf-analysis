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
        # starts 2 months late (truncated feed): compared over the shared stretch, same answer
        late = [(d, v) for d, v in series(0.10) if d >= w0 + dt.timedelta(days=60)]
        m2 = bi.compute(bars, divs, bench=late)
        self.assertAlmostEqual(m2["gap"], m["gap"], delta=0.005)
        self.assertEqual(m2["gap_window"][0], late[0][0].isoformat())
        self.assertNotIn("gap_window", m)
        # shares under a year with the fund: not comparable
        short = [(d, v) for d, v in series(0.10) if d >= END - dt.timedelta(days=200)]
        m3 = bi.compute(bars, divs, bench=short)
        self.assertNotIn("gap", m3)
        self.assertIn("bench_span", m3)

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


def vfund(t="AAA", family="systematic_cc", exposure="broad index", **m):
    """A rated fund record as score_all() sees it: classification + metrics + gates."""
    metrics = {"window_years": 3.0, "tr_ann": 0.12, "price_cagr": 0.02, "yield_regular": 0.08, "gap": -0.02,
               "max_drawdown": -0.15, "sharpe": 1.0, "rf_ann": 0.04, "dist_yield_ann": 0.08, "bench_tr_ann": 0.14}
    metrics.update(m)
    return {"t": t, "family": family, "style": "systematic", "exposure": exposure, "aum_usd": 5000, "flags": "",
            "inc": "2015-01-01", "age_years": 10, "metrics": metrics, "passes": True,
            "gates": {"aum": True, "age": True, "er": True, "liquidity": True, "structure": True}}


class ValueScore(unittest.TestCase):
    def test_curve_anchors(self):
        self.assertEqual(round(bi.saturate(4, bi.INCOME_K)), 55)
        self.assertEqual(round(bi.saturate(8, bi.INCOME_K)), 80)
        self.assertEqual(bi.saturate(-3, bi.INCOME_K), 0)
        self.assertEqual(round(bi.logistic(0, bi.NAV_MID, bi.NAV_SCALE)), 73)
        self.assertEqual(round(bi.logistic(-4, bi.GAP_MID, bi.GAP_SCALE)), 50)       # the brief's line still scores 50
        self.assertEqual(round(bi.logistic(-20, bi.DD_MID, bi.DD_SCALE)), 70)
        self.assertEqual(round(bi.logistic(1.0, bi.SH_MID, bi.SH_SCALE)), 88)

    def test_earned_income_never_exceeds_total_return(self):
        self.assertEqual(bi.earned_yield({"yield_regular": 0.08, "tr_ann": 0.20}), 0.08)
        self.assertEqual(bi.earned_yield({"yield_regular": 0.77, "tr_ann": 0.05}), 0.05)   # TSLY-style
        self.assertEqual(bi.earned_yield({"yield_regular": 0.12, "tr_ann": -0.10}), 0.0)
        self.assertEqual(bi.paid_yield({"yield_regular": None, "yield_ttm": 0.05}), 0.05)

    def test_grade_follows_the_displayed_integer(self):
        self.assertEqual(bi.grade_of(79.5), ("A", "Excellent value"))
        self.assertEqual(bi.grade_of(79.4)[0], "B")
        self.assertEqual(bi.grade_of(44.5)[0], "D")
        self.assertEqual(bi.grade_of(0)[0], "F")

    def test_four_equal_pillars(self):
        f = vfund()
        v = bi.value_score(f, {})
        self.assertAlmostEqual(v["value_base"], sum(v["value_pillars"].values()) / 4, places=0)
        self.assertEqual(v["value_flags"], [])
        self.assertIsNone(v["value_ceiling"])
        self.assertEqual(v["value_display"], round(v["value_score"]))

    def test_flags_cap_and_deduct(self):
        good = bi.value_score(vfund(), {})["value_score"]
        self.assertGreater(good, 70)
        lev = bi.value_score(vfund(family="leveraged_income", exposure="leveraged"), {})
        self.assertEqual((lev["value_score"], lev["value_ceiling"]), (44.0, 44.0))
        spec = bi.value_score(vfund(family="single_stock", exposure="single stock"), {})
        self.assertEqual((spec["value_score"], spec["value_grade"]), (59.0, "D"))
        own = bi.value_score(vfund(yield_regular=0.30, tr_ann=0.10), {})          # earned 10% of 30% paid
        self.assertIn("own_money", own["value_flags"])
        self.assertLessEqual(own["value_score"], 59)
        cash = bi.value_score(vfund(tr_ann=0.05, rf_ann=0.04), {})
        self.assertIn("cash_like", cash["value_flags"])
        self.assertEqual(cash["value_deduction"], 10.0)
        young = bi.value_score(vfund(window_years=1.5), {})
        self.assertEqual(young["value_deduction"], 5.0)                            # 10 x (2 - 1.5)
        small = bi.value_score(dict(vfund(), aum_usd=40), {})
        self.assertEqual(small["value_deduction"], 5.0)
        thin = bi.value_score(dict(vfund(), gates=dict(vfund()["gates"], liquidity=False)), {})
        self.assertIn("small", thin["value_flags"])
        crash = bi.value_score(vfund(max_drawdown=-0.6), {})
        self.assertLessEqual(crash["value_score"], 44)
        # a ceiling that doesn't bite isn't reported
        weak_spec = bi.value_score(vfund(family="single_stock", exposure="single stock", tr_ann=-0.2, price_cagr=-0.3,
                                         gap=-0.2, max_drawdown=-0.45, sharpe=-0.5), {})
        self.assertIsNone(weak_spec["value_ceiling"])

    def test_unrated_reasons(self):
        self.assertIn("inverse", bi.unrated_reason(dict(vfund(), inverse=True)))
        self.assertIn("Too new", bi.unrated_reason(vfund(window_years=0.6)))
        self.assertIn("currency", bi.unrated_reason(dict(vfund(), currency_mismatch=True)))
        self.assertIn("benchmark", bi.unrated_reason(vfund(gap=None)))
        self.assertIsNone(bi.value_score(vfund(gap=None), {})["value_score"])

    def test_young_funds_lean_on_their_family(self):
        # Seasoned funds chosen so the family, risk-bucket and all-fund priors all differ:
        # rules-based covered calls hold their price, dividend/put-write funds slide 6%/yr,
        # single-stock funds collapse.
        nav = lambda px: bi.logistic(px * 100, bi.NAV_MID, bi.NAV_SCALE)
        seasoned = ([vfund(f"S{i}", price_cagr=0.05) for i in range(5)] +
                    [vfund(f"D{i}", family="dividend_options", price_cagr=-0.06) for i in range(6)] +
                    [vfund(f"W{i}", family="put_write", price_cagr=-0.06) for i in range(2)] +
                    [vfund(f"X{i}", family="single_stock", exposure="single stock", price_cagr=-0.40) for i in range(15)])
        priors = bi.value_priors(seasoned)
        self.assertAlmostEqual(priors["systematic_cc"]["nav"], nav(0.05), places=0)
        self.assertNotIn("put_write", priors)                                   # only 2 seasoned: no family prior
        self.assertAlmostEqual(priors["_diversified"]["nav"], nav(-0.06), places=0)
        self.assertAlmostEqual(priors["_speculative"]["nav"], nav(-0.40), places=0)
        self.assertNotAlmostEqual(priors["_all"]["nav"], priors["_diversified"]["nav"], places=0)

        def blended(f, prior_nav):
            v = bi.value_score(f, priors)
            w = f["metrics"]["window_years"] / bi.WINDOW_YEARS
            self.assertAlmostEqual(v["value_pillars"]["nav"], prior_nav + (v["value_raw"]["nav"] - prior_nav) * w, places=0)
        blended(vfund("Y", window_years=1.5, price_cagr=-0.20), priors["systematic_cc"]["nav"])        # own family
        blended(vfund("P", family="put_write", window_years=1.5, price_cagr=0.10), priors["_diversified"]["nav"])  # bucket
        blended(vfund("C", family="crypto_income", exposure="crypto", window_years=1.2, price_cagr=0.10),
                priors["_speculative"]["nav"])                                  # a young crypto fund isn't judged like an index fund
        full = vfund("F", price_cagr=0.10)                                      # a full record is not blended at all
        v = bi.value_score(full, priors)
        self.assertEqual(v["value_pillars"], v["value_raw"])

    def test_age_grace_and_safety_check(self):
        gates = {"systematic": {"age": 2}, "active": {"age": 3}}
        f = dict(vfund(), style="active", age_years=2.7, inc="2024-02-29", passes=False,
                 gates={"aum": True, "age": False, "er": True, "liquidity": True, "structure": True})
        self.assertEqual(bi.age_grace_until(f, gates), "2027-02-28")              # 29 Feb rolls back
        self.assertIsNone(bi.age_grace_until(dict(f, age_years=2.4), gates))      # more than 6 months short
        self.assertIsNone(bi.age_grace_until(dict(f, gates=dict(f["gates"], aum=False)), gates))   # not the only failure
        self.assertIsNone(bi.age_grace_until(dict(f, gates=dict(f["gates"], aum=None)), gates))    # unknown != pass
        funds = [f, dict(vfund("B"), passes=False, gates=dict(vfund()["gates"], er=False))]
        bi.score_value(funds, gates)
        self.assertEqual([x["safety_checked"] for x in funds], [True, False])

    def test_ranks_and_tie_break(self):
        funds = [vfund("BBB"), vfund("AAA"), vfund("CCC", gap=-0.10), vfund("ZZZ", gap=None)]
        top = bi.score_value(funds, {"systematic": {"age": 2}, "active": {"age": 3}})
        by = {f["t"]: f for f in funds}
        self.assertEqual((by["AAA"]["value_rank"], by["BBB"]["value_rank"], by["CCC"]["value_rank"]), (1, 2, 3))
        self.assertEqual((by["AAA"]["value_pct"], by["CCC"]["value_pct"]), (100, 0))
        self.assertNotIn("value_rank", by["ZZZ"])
        self.assertEqual(top["rated"], 3)
        self.assertEqual(top["flags"]["small"]["amount"], bi.SMALL_DEDUCT)

    def test_growth_of_10k(self):
        g = bi.growth_10k({"window_years": 2.0, "tr_ann": 0.10, "price_cagr": 0.0, "dist_yield_ann": 0.05,
                           "bench_tr_ann": 0.20})
        self.assertEqual((g["reinvested"], g["shares_now"], g["bench_reinvested"]), (12100, 10000, 14400))
        self.assertEqual((g["cash_paid"], g["cash_paid_exact"]), (1000, False))
        g = bi.growth_10k({"window_years": 2.0, "tr_ann": 0.10, "price_cagr": 0.0, "cash_paid_10k": 987.6,
                           "bench_tr_ann": 0.2, "gap_window": ["2025-01-01", "2026-01-01"]})
        self.assertEqual((g["cash_paid"], g["cash_paid_exact"]), (988, True))
        self.assertNotIn("bench_reinvested", g)                                   # different period: not comparable
        bars, divs = fund(0.0, 0.08)
        m = bi.compute(bars, divs)
        self.assertAlmostEqual(m["cash_paid_10k"], 10000 * 0.08 * m["window_years"], delta=60)

    def test_rescore_is_idempotent(self):
        funds = [vfund(f"F{i}", tr_ann=0.04 + i / 50, window_years=1.2 + i / 4) for i in range(8)]
        for f in funds:
            f.update({"t": f["t"], "n": f["t"], "market": "US", "cur": "USD", "eln": False, "er": 0.5, "vol": 1e6,
                      "bench": "SPY", "note": False, "inverse": False})
        bi.score_all(funds, {})
        first = [(f["value_score"], f["value_rank"], f["score_us"]) for f in funds]
        for f in funds:
            for k in bi.DERIVED:
                f.pop(k, None)
        bi.score_all(funds, {})
        self.assertEqual(first, [(f["value_score"], f["value_rank"], f["score_us"]) for f in funds])

    def test_vix_gauge(self):
        days = DAYS[-400:]
        vix = [(d, 12 + (i % 10)) for i, d in enumerate(days)]
        g = bi.vix_gauge(vix)
        self.assertEqual(g["vix"], vix[-1][1])
        self.assertTrue(0 <= g["pct_below"] <= 100)
        self.assertIsNone(bi.vix_gauge(vix[:10]))
        self.assertIsNone(bi.vix_gauge(None))

    def test_each_flag_trigger(self):
        # price sliding > 10%/yr is 'paying with your own money' even when the payout was covered
        slide = bi.value_score(vfund(yield_regular=0.05, tr_ann=0.06, price_cagr=-0.12), {})
        self.assertIn("own_money", slide["value_flags"])
        self.assertLessEqual(slide["value_score"], bi.CEIL_D)
        for rec in (dict(vfund(), note=True), dict(vfund(), flags="N")):     # ETN / ETP notes
            v = bi.value_score(rec, {})
            self.assertIn("note", v["value_flags"])
            self.assertEqual(v["value_score"], bi.CEIL_D)
        # smooth ride: half worst fall, half Sharpe
        a, b = bi.value_raw_pillars(vfund(sharpe=0.2)["metrics"]), bi.value_raw_pillars(vfund(sharpe=1.2)["metrics"])
        dd = bi.logistic(-15, bi.DD_MID, bi.DD_SCALE)
        self.assertAlmostEqual(b["ride"], 0.5 * dd + 0.5 * bi.logistic(1.2, bi.SH_MID, bi.SH_SCALE))
        self.assertGreater(b["ride"], a["ride"])
        self.assertAlmostEqual(bi.value_raw_pillars(vfund(sharpe=None)["metrics"])["ride"], dd)

    def test_tie_break_by_base_then_gap(self):
        # both capped at 59 (single stock): the one with the better underlying record ranks first,
        # whatever the ticker order
        # (base decides before gap: the stronger fund has the slightly worse gap)
        strong = vfund("AAA", family="single_stock", exposure="single stock", gap=-0.01, price_cagr=0.08, sharpe=1.5)
        weak = vfund("ZZZ", family="single_stock", exposure="single stock", gap=0.0, price_cagr=-0.025, sharpe=0.3)
        strong["t"], weak["t"] = "ZZZ", "AAA"
        bi.score_value([strong, weak], {"systematic": {"age": 2}, "active": {"age": 3}})
        self.assertEqual((strong["value_score"], weak["value_score"]), (59.0, 59.0))
        self.assertEqual((strong["value_rank"], weak["value_rank"]), (1, 2))

    def test_priors_ignore_young_funds(self):
        seasoned = [vfund(f"S{i}", price_cagr=0.03) for i in range(5)]
        base = bi.value_priors(seasoned)
        noisy = bi.value_priors(seasoned + [vfund(f"Y{i}", window_years=1.5, price_cagr=-0.9) for i in range(6)])
        self.assertEqual(base["systematic_cc"], noisy["systematic_cc"])

    def test_cash_paid_uses_the_starting_price(self):
        bars, divs = fund(-0.05, 0.03)                       # price slides, so the first close is above the average
        m = bi.compute(bars, divs)
        w0 = dt.date.fromisoformat(m["window_start"])
        first = next(b[1] for b in bars if b[0] == w0)
        paid = sum(a for d, a in divs if w0 < d <= bars[-1][0])
        self.assertAlmostEqual(m["cash_paid_10k"], 10000 * paid / first, places=1)

    def test_vix_gauge_counts_strictly_lower_days(self):
        flat = [(d, 15.0) for d in DAYS[-300:]]
        self.assertEqual(bi.vix_gauge(flat)["pct_below"], 0)                  # an ordinary day isn't 'higher than 100%'

    def test_rescore_clears_stale_value_fields(self):
        self.assertTrue(set(bi.VALUE_FIELDS) <= set(bi.DERIVED))
        funds = [vfund(f"F{i}") for i in range(3)]
        for f in funds:
            f.update({"n": f["t"], "market": "US", "cur": "USD", "eln": False, "er": 0.5, "vol": 1e6,
                      "bench": "SPY", "note": False, "inverse": False})
        bi.score_all(funds, {})
        funds[0]["metrics"]["gap"] = None                     # its benchmark disappears
        for f in funds:
            for k in bi.DERIVED:
                f.pop(k, None)
        bi.score_all(funds, {})
        self.assertNotIn("value_rank", funds[0])
        self.assertEqual(sorted(f["value_rank"] for f in funds[1:]), [1, 2])

    def test_classification_fixes(self):
        self.assertEqual(bi.classify("YieldMax Innovation Option Income Strategy ETF", ticker="OARK")["bench"], "ARKK")
        self.assertEqual(bi.classify("Global X NADAQ 100 Covered Call Active ETF", ticker="3451.HK")["bench"], "QQQ")
        for n in ("Roundhill Magnificent Seven Covered Call ETF", "REX FANG & Innovation Equity Premium Income ETF",
                  "FT Vest DJIA Dogs 10 Target Income ETF", "REX AI Equity Premium Income ETF"):
            self.assertEqual(bi.classify(n)["exposure"], "sector", n)
        self.assertEqual(bi.classify("REX AI Equity Premium Income ETF")["bench"], "QQQ")
        self.assertEqual(bi.classify("YieldMax AI & Tech Portfolio Option Income ETF")["bench"], "XLK")
        self.assertEqual(bi.classify("Global X NASDAQ 100 Covered Call ETF")["exposure"], "broad index")


if __name__ == "__main__":
    unittest.main()
