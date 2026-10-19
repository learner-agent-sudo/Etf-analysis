#!/usr/bin/env python3
"""Offline tests for scripts/build_universe.py (no network)."""
import json
import os
import tempfile
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
            "YieldMax Ultra Option Income Strategy ETF": "",   # 'Ultra' here is not leverage
            "ProShares Ultra QQQ": "L",
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
        self.assertEqual((ln["cur"], ln["p"], ln["dom"], ln["aum"], ln["aumu"], ln["acur"]), ("GBP", 95.12, "IE", 40000.0, 40000.0, "USD"))
        # derived from the name: a Vanguard UCITS fund is Irish, its unmarked class pays out, and it's a US core fund
        self.assertEqual((ln["pol"], ln["lane"], hk["pol"], hk["lane"]), ("D", "us", "", ""))

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


class Derived(unittest.TestCase):
    """Payout policy, site lane and UCITS domicile — all read from the listing's name."""

    def test_payout_policy_from_class_names(self):
        pol = lambda n, dom="IE", yld=None, f="": bu.payout_policy(n, dom, yld, f)  # noqa: E731
        for n in ("iShares Core S&P 500 UCITS ETF USD (Acc)", "Vanguard FTSE All-World UCITS ETF USD Accumulation",
                  "UBS Core MSCI World UCITS ETF USD acc", "Xtrackers MSCI World UCITS ETF 1C",
                  "Xtrackers S&P 500 UCITS ETF 2C - GBP Hedged", "Amundi MSCI Em Asia UCITS ETF-C USD",
                  "BNP PARIBAS EASY - S&P 500 II UCITS ETF CAPITALISATION", "BNP Paribas Easy MSCI USA Min TE UCITS ETF Cap",
                  "Robeco 3D Global Equity UCITS ETF USD Acc"):           # '3D' is the product name, not a D class
            self.assertEqual(pol(n), "A", n)
        for n in ("iShares Core S&P 500 UCITS ETF USD Dist", "Invesco MSCI USA UCITS ETF Inc",
                  "UBS Core S&P 500 UCITS ETF USD dis", "Xtrackers MSCI World UCITS ETF 1D",
                  "State Street SPDR S&P 500 UCITS ETF USD Distribution UnHedged", "Amundi S&P 500 UCITS ETF-D"):
            self.assertEqual(pol(n), "D", n)
        self.assertEqual(pol("Invesco S&P 500 UCITS ETF"), "")             # unmarked: not stated (it accumulates)
        self.assertEqual(pol("Vanguard S&P 500 UCITS ETF"), "D")           # Vanguard marks every accumulating class
        self.assertEqual(pol("Vanguard S&P 500 UCITS ETF", dom=""), "")    # …but only for its UCITS funds
        self.assertEqual(pol("Some Fund UCITS ETF", yld=1.2), "D")         # pays a yield: distributes
        self.assertEqual(pol("Some Fund UCITS ETF", yld=0), "")
        self.assertEqual(pol("Vanguard S&P 500 ETF", dom="US"), "D")       # US funds pay out what they earn
        self.assertEqual(pol("Roundhill S&P 500 Accumulating ETF", dom="US"), "A")   # the name wins
        self.assertEqual(pol("Accelerate Diversified Credit Income ETF", dom="US"), "D")   # 'Accelerate' isn't 'Acc'
        self.assertEqual(pol("iPath Bloomberg Commodity ETN", dom="US", f="N"), "")  # notes pay nothing
        self.assertEqual(pol("Odd Fund UCITS ETF Acc Dist"), "")             # both markers: don't guess

    def test_more_class_markers(self):
        pol = lambda n, dom="IE": bu.payout_policy(n, dom, None, "")  # noqa: E731
        for n in ("Amundi Index Solutions - Amundi EUR Corporate Bond ESG UCITS ETF DR (C)",     # Amundi (C)
                  "Amundi Core EUR Corporate Bond UCITS ETF - USD Hedged (C)",
                  "iShares Blockchain Technology UCITS ETF USD Cap", "Global X SuperDividend UCITS ETF USD Cap",
                  "BNP Paribas Easy MSCI Emerging Min TE UCITS ETF EUR Cap",
                  "BNP PARIBAS Easy ICAV - BNP Paribas Easy FTSE EPRA Nareit Global Dev Green CTBUCITSETFUCITSETFEURCAP",
                  "First Trust Indxx Europe Infrastructure UCITS ETF Class A ACCU",
                  "FIRST TRUST VEST US EQUITY MAX BUFFER UCITS ETF - SEPTEMBER CLASS A ACCU CL",
                  "Fidelity US Quality Income UCITS ETF GBP Hedged Acc"):                       # 'Income' mid-name
            self.assertEqual(pol(n), "A", n)
        for n in ("Amundi MSCI Europe SRI Climate Paris Aligned - UCITS ETF DR (D)",
                  "Fidelity US Equity Enhanced Yield UCITS ETF USD Income",
                  "YieldMax Future of Defence Option Income UCITS ETF USD Income",
                  "Fidelity Global Corp Bond Research Enhanced PAB UCITS ETF USD Income Hedged"):
            self.assertEqual(pol(n), "D", n)
        self.assertEqual(pol("Hang Seng CMS Bloomberg US Treasury 1-3 Year Index ETF HKD Income", dom="HK"), "D")
        # '<currency> Income' only as the class at the end of the name; 'Small Cap' is no 'Cap' class
        self.assertEqual(pol("Fidelity US Quality Income UCITS ETF"), "")
        self.assertEqual(pol("Global X SuperDividend UCITS ETF"), "")
        self.assertEqual(pol("iShares MSCI USA Small Cap UCITS ETF"), "")

    def test_us_trusts_and_pools_pay_nothing(self):
        pol = lambda n, yld=None, f="", dom="US": bu.payout_policy(n, dom, yld, f)  # noqa: E731
        for n, f in (("SPDR Gold Shares", ""), ("iShares Gold Trust", ""), ("iShares Gold Trust Micro", ""),
                     ("SPDR Gold MiniShares", ""), ("abrdn Physical Silver Shares ETF", ""),
                     ("iShares Bitcoin Trust ETF", ""), ("Fidelity Wise Origin Bitcoin Fund", ""),
                     ("Grayscale Ethereum Mini Trust ETF", ""), ("Bitwise Solana Staking ETF", ""),
                     ("United States Oil Fund, LP", "F"), ("United States Commodity Index Fund, LP", ""),
                     ("iShares S&P GSCI Commodity-Indexed Trust", ""), ("Invesco CurrencyShares Japanese Yen Trust", ""),
                     ("Alpha Architect 1-3 Month Box ETF", ""), ("Roundhill Box Spread ETF", "")):
            self.assertEqual(pol(n, f=f), "", n)
        self.assertEqual(bu.derived("SPDR Gold Shares", "US", None, "", 0.4, "2840.HK")[1], "")   # GLD's HK line (US ISIN)
        # plain RICs and UITs pay out: 'Trust' alone is no sign, and a reported yield always wins
        self.assertEqual(pol("State Street SPDR S&P 500 ETF Trust", yld=0.99), "D")
        self.assertEqual(pol("State Street SPDR S&P 500 ETF Trust"), "D")
        self.assertEqual(pol("Invesco QQQ Trust"), "D")
        self.assertEqual(pol("Abacus FCF ETF Trust - Abacus FCF Innovation Leaders ETF"), "D")
        self.assertEqual(pol("VanEck Gold Miners ETF", yld=0.72), "D")
        self.assertEqual(pol("VanEck Gold Miners ETF"), "D")                         # miners are equity RICs
        self.assertEqual(pol("Invesco CurrencyShares Euro Currency Trust", yld=0.78), "D")
        for n in ("Global X Ethereum Covered Call ETF", "Bitwise Crypto Industry Innovators ETF",
                  "WisdomTree Physical AI, Humanoids, and Drones Fund", "FT Vest Bitcoin Strategy Floor15 ETF - January"):
            self.assertEqual(pol(n), "D", n)
        self.assertEqual(pol("Direxion Daily Bitcoin Bull 2X ETF", f="L"), "D")     # a leveraged bitcoin fund is a RIC
        self.assertEqual(pol("WisdomTree Physical Gold", dom=""), "")              # London ETC: unchanged
        # commodity pools whose names don't say so: Teucrium crop funds, ProShares Trust II (even leveraged)
        for n, f in (("ProShares Ultra Gold", "L"), ("ProShares UltraShort Bloomberg Crude Oil", "L"),
                     ("ProShares VIX Short-Term Futures ETF", "F"), ("ProShares UltraShort Yen", "L"), ("Teucrium Corn Fund", ""),
                     ("Bitwise Hyperliquid ETF", ""), ("Bitwise NEAR ETF", ""), ("Stellar ETF", ""), ("CoinShares Altcoins ETF", "")):
            self.assertEqual(pol(n, f=f), "", n)
        for n, f in (("ProShares K-1 Free Crude Oil ETF", ""), ("Teucrium Agricultural Strategy No K-1 ETF", ""),
                     ("ProShares Ultra MSCI Europe", "L"), ("Global X Near-Term Treasury ETF", "")):
            self.assertEqual(pol(n, f=f), "D", n)
        self.assertEqual(pol("ProShares Bitcoin ETF", yld=28.6), "D")              # a futures RIC: its payouts show

    def test_same_class_lines_share_payout(self):
        listing = {t: {"t": t, "n": n, "x": "London", "dom": "IE/LU", "q": q} for t, n, q in (
            ("HMWD.L", "HSBC MSCI World UCITS ETF", {"currency": "USD", "dividendYield": 1.18}),
            ("HMWO.L", "HSBC MSCI World UCITS ETF", {"currency": "GBp"}),
            ("HMWA.L", "HSBC MSCI World UCITS ETF USD (Acc)", {"currency": "USD"}))}
        rows = {r[0]: dict(zip(bu.COLS, r)) for r in bu.build_rows(listing, {}, {"er": 1, "ytd": 1, "c1y": 1})}
        self.assertEqual((rows["HMWD.L"]["pol"], rows["HMWO.L"]["pol"], rows["HMWA.L"]["pol"]), ("D", "D", "A"))
        self.assertIsNone(rows["HMWO.L"]["yld"])                                     # only the payout is shared
        row = lambda t, n, pol, f="", dom="HK": [{"t": t, "n": n, "f": f, "dom": dom, "pol": pol}.get(c) for c in bu.COLS]  # noqa: E731
        got = bu.fill_class_payout([
            row("3416.HK", "Global X HSCEI Compnts Cov Cll Actv ETF", "D"),
            row("9416.HK", "Global X HSCEI Compnts Cov Cll Actv ETF", ""),
            row("A.L", "Some UCITS ETF USD", "A", dom="IE"), row("B.L", "Some UCITS ETF GBP", "D", dom="IE"),
            row("C.L", "Some UCITS ETF EUR", "", dom="IE"),                              # class disagrees: no guess
            row("D.L", "Other UCITS ETF GBP Hedged", "", dom="IE"), row("E.L", "Other UCITS ETF", "D", dom="IE"),
            row("VISE.L", "Leverage Shares 2x Visa ETP Securities A", "D", "L", ""),
            row("VIS2.L", "Leverage Shares 2x Visa ETP Securities A", "", "L", "")])
        self.assertEqual([r[bu.COLS.index("pol")] for r in got], ["D", "D", "A", "D", "", "", "D", "D", ""])
        key = bu.payout_class_key
        self.assertEqual(key("iShares Core S&P 500 UCITS ETF USD (Acc)"), key("iShares Core S&P 500 UCITS ETF GBP (Acc)"))
        self.assertNotEqual(key("iShares Core S&P 500 UCITS ETF USD (Acc)"), key("iShares Core S&P 500 UCITS ETF USD (Dist)"))
        self.assertNotEqual(key("Xtrackers S&P 500 UCITS ETF 2C - GBP Hedged"), key("Xtrackers S&P 500 UCITS ETF 2C"))
        self.assertNotEqual(key("iShares S&P 500 GBP Hedged UCITS ETF (Acc)"), key("iShares S&P 500 EUR Hedged UCITS ETF (Acc)"))
        self.assertNotEqual(key("UBS MSCI World UCITS ETF hGBP"), key("UBS MSCI World UCITS ETF hEUR"))

    def test_hk_classes_with_one_name_stay_apart(self):
        # Two classes of one fund can carry the same short name on a given day; HK counters of
        # one class share the code's last three digits (3077 / 9077), another class does not (9078).
        row = lambda t, n, pol: [{"t": t, "n": n, "f": "", "dom": "HK", "pol": pol}.get(c) for c in bu.COLS]  # noqa: E731
        n = "Premia ETF Series - US Treasury Floating Rate ETF"
        got = bu.fill_class_payout([row("3077.HK", n, ""), row("9077.HK", n, "D"), row("9078.HK", n, "")])
        self.assertEqual([r[bu.COLS.index("pol")] for r in got], ["D", "D", ""])

    def test_class_marker_survives_a_short_name(self):
        m = bu.name_marker
        self.assertEqual(m("Bosera 20+ Year Us Treasury Bond Etf", "Bosera 20+ Year US Treasury Bond ETF Distributing"), "D")
        self.assertEqual(m("ChinaAMC 20+ Yr US Trs Bd ETF USDAccLstd"), "A")
        self.assertEqual(m("Some ETF"), "")
        q = {"currency": "HKD"}
        listing = {"3156.HK": {"t": "3156.HK", "n": "Bosera 20+ Year Us Treasury Bond Etf", "x": "HKEX", "dom": "HK", "q": q},
                   "9156.HK": {"t": "9156.HK", "n": "Bosera 20+ Year Us Treasury Bond Etf", "x": "HKEX", "dom": "HK", "q": q},
                   "2848.HK": {"t": "2848.HK", "n": "Xtrackers - MSCI Korea UCITS ETF 1D", "x": "HKEX", "dom": "HK", "q": q}}
        rows = {r[0]: dict(zip(bu.COLS, r)) for r in bu.build_rows(listing, {}, {"er": 1, "ytd": 1, "c1y": 1},
                                                                    prev_marker={"3156.HK": "D", "9156.HK": "A", "2848.HK": "A"})}
        self.assertEqual((rows["3156.HK"]["pol"], rows["3156.HK"]["pm"]), ("D", "D"))        # carried from earlier builds
        self.assertEqual((rows["9156.HK"]["pol"], rows["9156.HK"]["pm"]), ("A", "A"))
        self.assertEqual((rows["2848.HK"]["pol"], rows["2848.HK"]["pm"]), ("D", "D"))        # today's name wins over the old marker

    def test_previous_markers_read_old_and_new_files(self):
        with tempfile.TemporaryDirectory() as d:
            old, new = os.path.join(d, "old.json"), os.path.join(d, "new.json")
            with open(old, "w", encoding="utf-8") as fh:
                json.dump({"cols": ["t", "n"], "rows": [["A.HK", "X ETF Acc"], ["B.HK", "Y ETF"]]}, fh)
            with open(new, "w", encoding="utf-8") as fh:
                json.dump({"cols": ["t", "n", "pm"], "rows": [["A.HK", "X ETF", "A"], ["B.HK", "Y ETF", ""]]}, fh)
            self.assertEqual(bu.previous_markers(old), {"A.HK": "A"})
            self.assertEqual(bu.previous_markers(new), {"A.HK": "A"})
            self.assertEqual(bu.previous_markers(os.path.join(d, "missing.json")), {})

    def test_core_roles(self):
        lane = lambda n, f="", er=0.1: bu.site_lane(n, f, er)  # noqa: E731
        cases = {"Vanguard Total World Stock Index Fund ETF Shares": "world", "iShares MSCI ACWI ETF": "world",
                 "Vanguard FTSE All-World UCITS ETF USD Accumulation": "world",
                 "State Street SPDR MSCI All Country World Investable Market UCITS ETF": "world",
                 "Vanguard Funds PLC - Vanguard FTSE Global All-Cap UCITS ETF USD Acc": "world",
                 "iShares Core MSCI World UCITS ETF USD (Acc)": "dev", "Vanguard FTSE Developed World UCITS ETF USD Accumulation": "dev",
                 "iShares MSCI World ETF": "dev", "Amundi Prime Global UCITS ETF Dist": "dev",
                 "Vanguard S&P 500 ETF": "us", "iShares Core S&P Total U.S. Stock Market ETF": "us",
                 "Schwab U.S. Broad Market ETF": "us", "iShares Russell 1000 ETF": "us", "Xtrackers MSCI USA UCITS ETF 1C": "us",
                 "Amundi Core S&P 500 Swap UCITS ETF Acc": "us",
                 # not core: ex-US, regional, sector, factor, screened, options, small caps
                 "Vanguard FTSE Developed Markets Index Fund ETF Shares": "", "Vanguard FTSE Developed Europe UCITS ETF": "",
                 "iShares MSCI World Small Cap UCITS ETF": "", "Invesco S&P 500 Equal Weight ETF": "",
                 "iShares S&P 500 Information Technology Sector UCITS ETF USD": "", "Invesco S&P 500 GARP ETF": "",
                 "SP Funds S&P 500 Sharia Industry Exclusions ETF": "", "iShares MSCI World ESG Screened UCITS ETF": "",
                 "Invesco S&P 500 High Beta ETF": "", "Global X S&P 500 Collar 95-110 ETF": "",
                 "Vanguard S&P 500 Value ETF": "", "iShares MSCI World ex USA ETF": "",
                 "Goldman Sachs MSCI World Private Equity Return Tracker ETF": "", "Vanguard Total Bond Market ETF": "",
                 "Xtrackers MSCI USA Banks UCITS ETF 1D": "", "Invesco S&P 500 Downside Hedged ETF": ""}
        for n, want in cases.items():
            self.assertEqual(lane(n), want, n)
        self.assertEqual(lane("Direxion Daily S&P 500 Bull 3X Shares", f="L"), "")      # flagged: never core
        self.assertEqual(lane("Hang Seng S&P 500 Index ETF", er=0.9), "")              # too expensive for a core fund
        self.assertEqual(lane("Hang Seng S&P 500 Index ETF", er=None), "us")           # unknown fee doesn't exclude

    def test_more_plain_us_funds_are_core(self):
        lane = lambda n: bu.site_lane(n, "", 0.05)  # noqa: E731
        for n in ("Vanguard Morningstar Large-Cap ETF", "JPMorgan BetaBuilders U.S. Equity ETF", "Schwab 1000 ETF",
                  "Goldman Sachs MarketBeta US Equity ETF", "Goldman Sachs MarketBeta U.S. 1000 Equity ETF",
                  "iShares Dow Jones U.S. ETF",
                  "JPMorgan ETFs (Ireland) ICAV - BetaBuilders US Equity UCITS ETF - USD (acc)",
                  "Xtrackers S&P 500 UCITS ETF 2C - GBP Hedged"):                   # a currency-hedged class stays core
            self.assertEqual(lane(n), "us", n)
        for n in ("iShares Dow Jones U.S. Select Dividend ETF", "iShares Select Dividend ETF",
                  "Vanguard Morningstar Large-Cap Growth ETF", "Vanguard Morningstar Growth ETF",
                  "Schwab U.S. Large-Cap Value ETF", "Vanguard Morningstar Mega Cap ETF",
                  "JPMorgan BetaBuilders U.S. Mid Cap Equity ETF", "JPMorgan BetaBuilders U.S. Small Cap Equity ETF",
                  "Goldman Sachs MarketBeta Russell 1000 Growth Equity ETF", "Goldman Sachs MarketBeta International Equity ETF",
                  "Invesco Dow Jones US Insurance UCITS ETF USD Acc",
                  # an options (tail-hedge) strategy on the S&P 500 is not the index
                  "Global X S&P 500 Annual Tail Hedge UCITS ETF", "Global X S&P 500 Quarterly Tail Hedge UCITS ETF A USD Acc"):
            self.assertEqual(lane(n), "", n)

    def test_income_lane_is_the_income_rankings_universe(self):
        self.assertEqual(bu.site_lane("JPMorgan Equity Premium Income ETF"), "income")
        self.assertEqual(bu.site_lane("Global X S&P 500 Covered Call UCITS ETF USD Acc"), "income")
        self.assertEqual(bu.site_lane("Vanguard High Dividend Yield ETF"), "")          # dividends alone: not option income

    def test_ucits_domicile_from_family(self):
        dom = bu.ucits_domicile
        self.assertEqual(dom("iShares Core MSCI World UCITS ETF USD (Acc)", "IE/LU"), "IE")
        self.assertEqual(dom("State Street SPDR S&P 500 UCITS ETF USD Accumulation UnHedged", "IE/LU"), "IE")
        self.assertEqual(dom("BNP PARIBAS Easy ICAV - BNP Paribas Easy MSCI World UCITS ETF", "IE/LU"), "IE")
        self.assertEqual(dom("Amundi Index Solutions - Amundi S&P 500 Swap UCITS ETF USD Acc", "IE/LU"), "LU")
        self.assertEqual(dom("Xtrackers MSCI World UCITS ETF 1C", "IE/LU"), "IE/LU")     # family runs funds in both
        self.assertEqual(dom("iShares VII PLC - iShares MSCI USA ETF USD Acc", ""), "IE")  # London name without 'UCITS'
        self.assertEqual(dom("Xtrackers FTSE All World ETF 1C USD", ""), "IE/LU")
        self.assertEqual(dom("WisdomTree Physical Gold", ""), "")                     # a commodity ETC, not a UCITS fund
        self.assertEqual(dom("Leverage Shares Plc - LS 3x Tesla Tracker ETP", "", "L"), "")
        self.assertEqual(dom("Vanguard S&P 500 ETF", "US"), "US")
        self.assertEqual(dom("Some HK fund", "HK"), "HK")

    def test_vaneck_dutch_funds(self):
        dom = lambda n: bu.ucits_domicile(n, "IE/LU")  # noqa: E731
        for n in ("VanEck Morningstar Developed Markets Dividend Leaders UCITS ETF",      # TDIV, NL0011683594
                  "VanEck World Equal Weight Screened UCITS ETF",                         # TSWE, NL0010408704
                  "VanEck Global Real Estate UCITS ETF", "VanEck European Equal Weight Screened UCITS ETF"):
            self.assertEqual(dom(n), "NL", n)
        for n in ("VanEck Morningstar Developed Markets ex-US Dividend Leaders UCITS ETF A USD Acc",   # TDVX, IE…
                  "VanEck Gold Miners UCITS ETF", "VanEck Semiconductor UCITS ETF",
                  "VanEck Morningstar Global Wide Moat UCITS ETF A USD", "VANECK UCITS ETFS PLC VANECK AG"):
            self.assertEqual(dom(n), "IE", n)

    def test_reclassify_upgrades_old_files_and_is_idempotent(self):
        import tempfile
        old_cols = bu.COLS[:16]
        row = ["CSPX.L", "iShares Core S&P 500 UCITS ETF USD (Acc)", "London", 600.0, 10.0, 5.0, None, 0.07, None, 1000,
               "", "2010-05-19", "USD", "IE/LU", None, "USD"]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "universe-lse.json")
            with open(path, "w") as fh:
                json.dump({"cols": old_cols, "rows": [row]}, fh)
            bu.reclassify(["lse"], data_dir=d)
            first = json.load(open(path))
            bu.reclassify(["lse"], data_dir=d)
            again = json.load(open(path))
        got = dict(zip(first["cols"], first["rows"][0]))
        self.assertEqual(first["cols"], bu.COLS)
        self.assertEqual((got["dom"], got["pol"], got["lane"], got["er"]), ("IE", "A", "us", 0.07))
        self.assertEqual(first, again)

    def test_reclassify_applies_family_rule_changes(self):
        """A stored London 'IE' / 'LU' is re-derived from the name, so a family-rule change reaches
        the committed files offline; HK (ISIN) and US domiciles are kept as stored."""
        import re
        import tempfile
        from unittest import mock
        row = lambda t, n, dom: [t, n, "x", 1.0, None, None, None, 0.1, None, None, "", None, "USD", dom, None, "USD", "", ""]  # noqa: E731
        files = {"lse": [row("CSPX.L", "iShares Core S&P 500 UCITS ETF USD (Acc)", "IE"),
                         row("TDIV.L", "VanEck Morningstar Developed Markets Dividend Leaders UCITS ETF", "IE"),
                         row("TDVX.L", "VanEck Morningstar Developed Markets ex-US Dividend Leaders UCITS ETF A USD Acc", "IE"),
                         row("PHAU.L", "WisdomTree Physical Gold", "")],
                 "hk": [row("9000.HK", "SOME IE ETF", "IE")], "us": [row("VOO", "Vanguard S&P 500 ETF", "US")]}

        def run(ie_family=bu.IE_FAMILY):
            with tempfile.TemporaryDirectory() as d:
                for k, rows in files.items():
                    with open(os.path.join(d, f"universe-{k}.json"), "w") as fh:
                        json.dump({"cols": bu.COLS, "rows": rows}, fh)
                with mock.patch.object(bu, "IE_FAMILY", ie_family):
                    bu.reclassify(list(files), data_dir=d)
                out = {}
                for k in files:
                    with open(os.path.join(d, f"universe-{k}.json")) as fh:
                        out.update({r[0]: r[bu.COLS.index("dom")] for r in json.load(fh)["rows"]})
                return out
        self.assertEqual(run(), {"CSPX.L": "IE", "TDIV.L": "NL", "TDVX.L": "IE", "PHAU.L": "", "9000.HK": "IE", "VOO": "US"})
        # drop iShares from the Irish families: the stored 'IE' must not survive
        got = run(re.compile(r"^vanguard\b|^vaneck\b", re.I))
        self.assertEqual((got["CSPX.L"], got["TDIV.L"], got["9000.HK"], got["VOO"]), ("IE/LU", "NL", "IE", "US"))


class CommittedData(unittest.TestCase):
    """Regression checks on the committed public/data/universe-*.json (rebuilt daily). CI runs
    them after the daily build, not before it (SKIP_DATA_TESTS): a bad name from Yahoo that got
    committed must not stop the next build that would repair it."""

    @classmethod
    def setUpClass(cls):
        if os.environ.get("SKIP_DATA_TESTS"):
            raise unittest.SkipTest("data checks run after the daily build")

    @staticmethod
    def rows(key):
        path = os.path.join(os.path.dirname(__file__), "..", "public", "data", f"universe-{key}.json")
        if not os.path.exists(path):
            raise unittest.SkipTest(f"{path} not built")
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return {r[0]: dict(zip(doc["cols"], r)) for r in doc["rows"]}

    def check(self, key, want, field):
        rows = self.rows(key)
        self.assertTrue(any(t in rows for t in want), f"none of {list(want)} in universe-{key}.json")
        for t, ok in want.items():
            if t in rows:                              # a delisted line is no regression
                self.assertIn(rows[t][field], ok, f"{t} {field}")

    def test_core_anchors(self):
        self.check("us", {"VT": ("world",), "VTI": ("us",), "VOO": ("us",), "VV": ("us",)}, "lane")
        self.check("lse", {"CSPX.L": ("us",), "SPYL.L": ("us",), "VWRA.L": ("world",), "SWDA.L": ("dev",),
                           "XDWD.L": ("dev",)}, "lane")

    def test_not_core(self):
        self.check("lse", {"SPQH.L": ("", "income"), "SAHP.L": ("", "income")}, "lane")
        self.check("us", {"QYLD": ("", "income")}, "lane")

    def test_trusts_do_not_distribute(self):
        self.check("us", {"GLD": ("",), "IBIT": ("",), "USO": ("",), "BOXX": ("",), "UGL": ("",), "CORN": ("",),
                          "SPY": ("D",), "QQQ": ("D",)}, "pol")
        self.check("hk", {"9078.HK": ("A", ""), "9077.HK": ("D",)}, "pol")

    def test_vaneck_netherlands(self):
        self.check("lse", {"TDIV.L": ("NL",), "TSWE.L": ("NL",), "TDVX.L": ("IE",)}, "dom")


class AumCurrency(unittest.TestCase):
    def test_name_hint(self):
        self.assertEqual(bu.aum_currency("Goldman Sachs Japan Equity UCITS ETF Class JPY (Acc)"), "JPY")
        self.assertEqual(bu.aum_currency("iShares Core MSCI Europe UCITS ETF EUR (Acc)"), "EUR")
        self.assertEqual(bu.aum_currency("Vanguard S&P 500 UCITS ETF"), "USD")


class HKCounters(unittest.TestCase):
    def test_usd_counter_aum_is_hkd(self):
        row = lambda t, n, cur: [t, n, "HKEX", 10.0, None, None, 21486.1, 0.3, None, 1000, "", None, cur, "HK", 21486.1 if cur == "USD" else 2738.0, cur]
        rows = [row("3416.HK", "Global X HSCEI Covered Call Active ETF", "HKD"),
                row("9416.HK", "Global X HSCEI Covered Call Active ETF", "USD")]
        bu.fix_hk_counters(rows, {"HKD": 0.1274})
        d = dict(zip(bu.COLS, rows[1]))
        self.assertEqual((d["acur"], d["aumu"]), ("HKD", round(21486.1 * 0.1274, 1)))


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
