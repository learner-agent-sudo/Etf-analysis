#!/usr/bin/env python3
"""
Income Lab — screen every option-income ETF, not just a dozen favourites.

Reads the Explorer universe (public/data/universe-{us,hk,lse}.json), keeps the
funds whose names say they run an option-income strategy, fetches ~5 years of
daily prices + distribution history for each, and writes
public/data/income-lab.json for the site's Income Lab tab.

Three layers (adapted from the user's brief):

  1. Tiered hard gates — AUM, age and expense limits differ for systematic vs
     actively managed strategies; liquidity >= 100K shares/day OR >= $2M/day
     (a shares-only rule unfairly fails high-priced funds); leveraged funds
     and ETNs never pass.
  2. Quality components, each scored 0-100:
       gap        total return vs the fund's OWN underlying (QQQ for Nasdaq-100
                  writers, IWM for Russell, TSLA for TSLY …), annualised;
                  -4 pp/yr scores 50 (the brief's "income costs too much" line)
       coverage   share of the distributions paid out of total return rather
                  than out of shrinking NAV — the economic version of the
                  brief's ROC test (tax-labelled ROC is misleading for funds
                  like SPYI whose NAV holds up); < 70% covered is flagged
       nav        price (≈ NAV) trend, annualised
       quality    underlying exposure (broad index > sector > single stock >
                  leveraged), extreme-yield penalty, distribution track record
       tax        US-taxable view only (index options / §1256 vs ELN ordinary
                  income); dropped for the non-US view and for HK/London funds
       fees, counterparty/transparency (ELNs), vix (short-vol sensitivity),
       stability (distribution volatility)
  3. Strategy-family weights — e.g. systematic covered calls: NAV 40 / gap 30
     / tax 30; active+ELN: counterparty 30 / gap 30 / fees 20 / ELN
     transparency 20; call spreads: tax 40 / gap 30 / NAV 30; short vol:
     VIX sensitivity 40 / gap 30 / stability 30; everything else uses the
     layer-2 default 30/25/20/15/10.

Holding-experience metrics (max drawdown, volatility, Sharpe vs T-bills,
upside/downside capture vs the benchmark) are reported for every fund.

On top of the brief's layers, every fund gets the headline Value Score (see
score_value): one 0-100 number, the same formula for every strategy, so any
two funds can be compared — earned income, paycheck trend, growth kept and
smooth ride, 25 points each, minus red flags.

Usage:
    python3 scripts/build_income.py              # build income-lab.json
    python3 scripts/build_income.py --dry-run    # fetch + summarise only
    python3 scripts/build_income.py --limit 40   # quick partial run
    python3 scripts/build_income.py --rescore    # re-score the existing file, no network
"""
import datetime as dt
import json
import math
import os
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refresh_market as rm  # noqa: E402

DATA = rm.DATA
OUT = os.path.join(DATA, "income-lab.json")
WINDOW_YEARS = 3
MIN_YEARS_SCORED = 1.0
MIN_GAP_OVERLAP_YEARS = 1.0       # a late-starting benchmark must still share this much history

# ------------------------------------------------------------------ selection --
OPTION_KW = re.compile(
    r"covered call|buy-?write|premium income|option income|options? income|option strateg|yieldmax|yieldboost"
    r"|weekly ?pay|0dte|put-?write|cash-secured put|high income|enhanced income|volatility premium|autocall"
    r"|overwrite|equity premium|target income|enhanced dividend|short vix|enhanced options|\boptions?\b"
    r"|weekly distribution|target \d+(?!(\.\d+)?x)",
    re.I)
# Names that say outright the fund writes or sells options.
STRONG_OPTION = re.compile(
    r"covered call|buy-?write|option income|options? income|option strateg|\boptions?\b|yieldmax|yieldboost"
    r"|weekly ?pay|0dte|put-?write|cash-secured put|volatility premium|autocall|overwrite|premium income"
    r"|equity premium|enhanced options|short vix|weekly distribution|target \d+(?!(\.\d+)?x)|premium yield"
    r"|target income|enhanced dividend", re.I)
# 'High income' / 'enhanced income' alone also names credit and closed-end-fund products, so
# without a strong option word they are admitted only from issuers known for option strategies.
OPTION_ISSUERS = re.compile(r"\bneos\b|proshares|\bkurv\b|defiance|roundhill|yieldmax|global x|graniteshares|\brex\b", re.I)
NOT_INCOME = re.compile(r"buffer|defined outcome|hedged equity|\bprotect|\bfloor\b|barrier|accelerat|tail risk|convexity"
                        r"|structured outcome|downside|max(imum)? (buffer|protection)", re.I)
PLAIN_LEVERAGED = re.compile(r"daily target \d+(\.\d+)?x|\b\d(\.\d+)?x (long|short)\b|daily (inverse|leveraged)", re.I)
CEF = re.compile(r"\bcef\b|closed-end", re.I)
BOND = re.compile(r"\bbond|treasur|\bmuni|\bcredit\b|fixed income|\bloan|mortgage|\bclo\b|preferred|maturity|ultra-?short"
                  r"|floating|aggregate|t-bill|money market|\bbdc\b|specialty finance|cash management|high yield"
                  r"|investment grade", re.I)
BOND_WITH_OPTIONS = re.compile(r"covered call|buy-?write|option income|weekly ?pay|put-?write|premium income|\boptions?\b", re.I)
TRADEMARK = re.compile(r"\((TM|R|SM)\)|[™®]")
# Words that can sit right before 'Option Income' etc. but aren't stock tickers.
NOT_TICKER = {
    "ETF", "ETFS", "ETP", "ETN", "UCITS", "USD", "GBP", "EUR", "HKD", "ACC", "DIST", "DIS", "INC", "CLASS", "PLC", "LP",
    "OFC", "SERIES", "TRUST", "FUND", "ACTIVE", "THE", "AND", "OF", "TOP", "S&P", "SPDR", "MSCI", "FTSE", "NASDAQ",
    "NDX", "SPX", "RUT", "DOW", "HSI", "HSCEI", "HSTECH", "KOSPI", "NIKKEI", "STOXX", "EURO", "EAFE", "EM", "NEOS",
    "CSOP", "GOLD", "SILVER", "OIL", "CRUDE", "COPPER", "BITCOIN", "ETHER", "CRYPTO", "MAG", "SEVEN", "FANG", "TECH",
    "INCOME", "HIGH", "MLP", "REIT", "BDC", "ENERGY", "MINERS", "RUSSELL", "EQUITY", "LARGE", "CAP", "SMALL", "MID",
    "GLOBAL", "WORLD", "EUROPE", "JAPAN", "CHINA", "KOREA", "INDIA", "SECTOR", "SELECT", "BOOST", "BOOSTED", "ULTRA",
    "UNIVERSE", "SHORT", "LONG", "DAILY", "WEEKLY", "MONTHLY", "TARGET", "BOND", "YIELD", "PREMIUM", "ENHANCED",
    "DIVIDEND", "GROWTH", "VALUE", "QUALITY", "SEMIS", "BIOTECH", "HEALTH", "VOL", "VIX", "STRATEGY", "N100", "US",
    "MAX", "PLUS", "CORE", "LOW", "NEXT", "GEN", "INNOVATION", "INTERNET", "CLOUD", "DATA", "SPACE", "DEFENSE",
    "ESG", "SRI", "BIG", "CARE", "REAL", "ETPS",
}
TICKER_FIX = {"BRKB": "BRK-B", "BRK.B": "BRK-B", "BRK-B": "BRK-B", "JP": "JPM"}
# Underlyings that are ETFs, not single stocks (benchmark = the ETF, exposure = sector/broad).
ETF_UNDERLYINGS = {"COWS", "KWEB", "SOXX", "SMH", "ARKK", "GDX", "GDXJ", "SLV", "GLD", "TLT", "HYG", "LQD", "IWM",
                   "QQQ", "SPY", "DIA", "XBI", "IBIT", "MSOS", "EEM", "FXI", "EWZ", "USO", "BITO", "URA", "XLE", "XLF",
                   "XLK", "XLU", "XLV", "XLI", "XLY", "XLP", "XLB", "XLC", "XLRE", "SVXY", "TQQQ", "SOXL", "TSLL"}
# Issuers whose single-stock funds put the underlying ticker in the name (sometimes in mixed case).
TICKER_ISSUERS = re.compile(r"yieldmax|roundhill|incomeshares|\bkurv\b|graniteshares|defiance|rex\b|tradr|\bneos\b", re.I)

FAMILIES = {
    "systematic_cc": "Systematic covered call",
    "active_premium": "Active premium income",
    "call_spread": "Call spread / tax-aware",
    "daily_0dte": "Daily & 0DTE options",
    "single_stock": "Single-stock option income",
    "short_vol": "Short volatility",
    "put_write": "Put-write",
    "dividend_options": "Dividend + options",
    "crypto_income": "Crypto option income",
    "structured": "Autocallable / structured",
    "leveraged_income": "Leveraged income",
}
# Benchmarks: the fund's own underlying, always as a TOTAL-return series (an ETF's
# dividend-adjusted closes). Price-only indices (^HSI, ^HSCE …) would flatter the fund
# by the index dividend yield, so tradable ETFs stand in for them.
BENCH_RULES = [                                   # order matters: specific before generic
    (r"\bus equity|u\.s\. equity|\bus large", "SPY"),       # before 'hang seng' (issuer name on HK funds)
    (r"\bfang\b", "QQQ"), (r"magnificent|\bmag ?7\b|\bmag seven", "MAGS"),
    (r"hscei|china enterprises|h-share", "2828.HK"), (r"hang seng tech|hstech|hs tech", "3067.HK"),
    (r"hang seng|\bhsi\b", "2800.HK"), (r"kospi", "069500.KS"),
    (r"nasdaq[- ]?100|nasdaq 100|\bqqq\b|\bndx\b|nasdaq|nadaq|\bn100\b", "QQQ"),   # 'nadaq': a listed name's typo
    (r"russell 2000|\br2000\b|small[- ]?cap|\biwm\b|\brut\b|russell", "IWM"),
    (r"\bkweb\b|china internet", "KWEB"), (r"dow jones internet|\binternet\b", "FDN"),
    (r"\bdow\b|dow jones|\bdjia\b|dow 30", "DIA"),
    (r"euro stoxx|eurozone|euro area", "FEZ"), (r"\beurope|european", "VGK"),
    (r"all-?world|\bworld\b|\bglobal equity|\bacwi\b", "ACWI"), (r"canad", "EWC"),
    (r"\bmlp\b|midstream|energy infrastructure", "AMLP"),
    (r"crude|\boil\b", "USO"), (r"copper", "COPX"),
    (r"20\+|long[- ]term treasur|\btlt\b", "TLT"), (r"high yield|\bhyg\b", "HYG"),
    (r"investment grade|corporate bond|\blqd\b", "LQD"), (r"treasur|t-bill|\bbond|aggregate", "AGG"),
    (r"semiconductor", "SOXX"), (r"\barkk\b|ark innovation", "ARKK"), (r"innovation", "QQQ"),
    (r"crypto (equit|industry)|blockchain", "BKCH"),
    (r"information technology|technology|\btech\b", "XLK"), (r"\bai\b|artificial intelligence", "QQQ"),
    (r"financial", "XLF"), (r"industrial", "XLI"),
    (r"utilit", "XLU"), (r"health ?care|biotech", "XLV"), (r"\benergy\b", "XLE"), (r"real estate|\breit", "XLRE"),
    (r"consumer discretionary", "XLY"), (r"consumer staples|\bstaples\b", "XLP"), (r"materials", "XLB"),
    (r"communication", "XLC"),
    (r"silver miners", "SILJ"), (r"gold miners", "GDX"), (r"\bgold\b", "GLD"), (r"\bsilver\b", "SLV"),
    (r"bitcoin", "BTC-USD"), (r"\bether", "ETH-USD"), (r"crypto", "BTC-USD"),
    (r"emerging", "EEM"), (r"international|developed|eafe|world ex", "EFA"),
    (r"s&p 500|sp500|\bspx\b|\bspy\b|s&p|large[- ]cap|equity premium|500", "SPY"),
]
BROAD = {"SPY", "QQQ", "IWM", "DIA", "2800.HK", "2828.HK", "069500.KS", "EFA", "EEM", "FEZ", "VGK", "ACWI", "EWC"}
# A handful of names on a broad benchmark (Magnificent 7, FANG, 'Dogs of the Dow', AI baskets): concentrated.
CONCENTRATED = re.compile(r"\bfang\b|magnificent|\bmag ?7\b|\bmag seven|\bdogs\b|\bai\b|artificial intelligence", re.I)
BENCH_BY_TICKER = {"OARK": "ARKK"}                   # names that don't say what they write options on
BONDS = {"TLT", "HYG", "LQD", "AGG"}
COMMODITIES = {"GLD", "SLV", "USO", "COPX"}
RISK_FREE, VIX = "BIL", "^VIX"

# Tax view for a US taxable investor (fund-level character of the income).
TAX_SCORE = {"call_spread": 90, "systematic_cc": 70, "daily_0dte": 65, "put_write": 65, "short_vol": 70,
             "dividend_options": 60, "single_stock": 30, "crypto_income": 30, "leveraged_income": 20,
             "structured": 30}
TAX_NOTE = {
    "call_spread": "Index options taxed under §1256 (60% long-term / 40% short-term) and loss harvesting — distributions often classed as return of capital (tax-deferred).",
    "systematic_cc": "Index options usually §1256 (60/40) for the fund; distributions are a mix of ordinary income and return of capital.",
    "daily_0dte": "Index options usually §1256 (60/40); frequent rolls create mostly short-term gains inside the fund.",
    "put_write": "Index put options usually §1256 (60/40) at fund level.",
    "short_vol": "VIX futures are §1256 contracts (60/40) at fund level.",
    "dividend_options": "Part qualified dividends from the stocks, part option income (ordinary).",
    "single_stock": "Options on single stocks/ETFs are not §1256 — option income is mostly ordinary / short-term.",
    "crypto_income": "Option income mostly ordinary; crypto exposure via ETPs adds its own tax quirks.",
    "leveraged_income": "Swap and option income mostly ordinary.",
    "structured": "Income from notes / swaps is mostly ordinary.",
    "active_premium": "Option premium earned through equity-linked notes (ELNs) is ordinary income; directly written options may be §1256.",
}
WEIGHTS = {
    "systematic_cc": {"nav": 40, "gap": 30, "tax": 30},
    # The brief's active + ELN weights apply to funds that actually use ELNs; other
    # actively managed funds use the default weights (so NAV and coverage count).
    "active_premium_eln": {"counterparty": 30, "gap": 30, "fees": 20, "transparency": 20},
    "call_spread": {"tax": 40, "gap": 30, "nav": 30},
    "short_vol": {"vix": 40, "gap": 30, "stability": 30},
    "default": {"gap": 30, "coverage": 25, "nav": 20, "quality": 15, "tax": 10},
}
GATES = {
    "systematic": {"aum": 100, "age": 2, "er": 0.60},
    "active": {"aum": 500, "age": 3, "er": 0.85},
}
LIQ_SHARES, LIQ_DOLLARS = 100_000, 2_000_000


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------- classification --
def _norm_ticker(tok):
    tok = tok.upper()
    return TICKER_FIX.get(tok, tok)


def stock_underlying(name):
    """(ticker, inverse) of a single underlying named in the fund name, or (None, False).

    Handles '(GOOG)'-style and 'YieldBOOST TSLA'-style names, mixed case ('Yieldmax Gme'),
    'BRK.B', trademark marks ('YieldMax(TM) RBLX') and inverse funds ('MSTR Short Option Income').
    """
    n = TRADEMARK.sub(" ", name or "")
    inverse = bool(re.search(r"\bshort\b(?!-term| duration| maturity)", n, re.I)) and not re.search(r"short vix", n, re.I)
    m = re.search(r"\(([A-Z]{1,5}(?:[.-][A-Z])?)\)", n)
    if m and m.group(1).upper() not in NOT_TICKER:
        return _norm_ticker(m.group(1)), inverse
    m = re.search(r"yieldboost\s+([A-Za-z]{2,5}(?:[.-][A-Za-z])?)\b", n, re.I)
    if m and m.group(1).upper() not in NOT_TICKER:
        return _norm_ticker(m.group(1)), inverse
    m = re.search(r"autocallable\s+([A-Za-z]{2,5})\b", n, re.I)
    if m and m.group(1).upper() not in NOT_TICKER and m.group(1).upper() not in ("INCOME", "GROWTH"):
        return _norm_ticker(m.group(1)), inverse
    issuer = TICKER_ISSUERS.search(n)
    for m in re.finditer(r"\b([A-Za-z]{1,5}(?:[.-][A-Za-z])?)\s+(?:short\s+)?(?:option income|enhanced income|covered call"
                         r"|weekly ?pay|performance & distribution|options? etp)\b", n, re.I):
        tok = m.group(1)
        up = tok.upper()
        if up in NOT_TICKER or len(up.replace(".", "").replace("-", "")) < 2:
            continue
        if tok.isupper() or tok == "AI" or issuer:          # mixed case only from ticker-in-name issuers
            return _norm_ticker(tok), inverse
    return None, inverse


def classify(name, flags="", ticker=""):
    """Fund name -> {family, style, eln, under, bench, exposure, note, inverse, bench_assumed} or None."""
    n = name or ""
    if not OPTION_KW.search(n) or PLAIN_LEVERAGED.search(n) or CEF.search(n):
        return None
    if NOT_INCOME.search(n) and not re.search(r"income|yield", n, re.I):
        return None
    if not STRONG_OPTION.search(n) and not OPTION_ISSUERS.search(n):
        return None                                   # e.g. 'Blackstone High Income' — a credit fund
    if BOND.search(n) and not BOND_WITH_OPTIONS.search(n):
        return None                                   # bond fund without an option overlay
    low = TRADEMARK.sub(" ", n).lower()
    under, inverse = stock_underlying(n)
    etf_under = under if under in ETF_UNDERLYINGS else None
    stock = None if etf_under else under
    eln = bool(re.search(r"jpmorgan|j\.p\. ?morgan|\bjpm\b", low)) and "premium income" in low
    basket = bool(re.search(r"fund of option income|fund of .*income etfs|ultra option income|universe fund|incomemax", low))
    # Leveraged by name (the universe 'L' flag also fires on non-leveraged names like
    # 'YieldMax Ultra Option Income', so it is not trusted on its own here).
    if re.search(r"\b[2-9](\.\d+)?x\b|leveraged|yieldboost|\bultra(pro|short)\b|proshares ultra|\binverse\b", low):
        fam = "leveraged_income"
    elif re.search(r"autocall|barrier|buffer", low):
        fam = "structured"
    elif re.search(r"volatility premium|short vix|short volatility|vol premium", low):
        fam = "short_vol"
    elif re.search(r"put[- ]?write|putwrite|cash-secured put", low) or re.search(r"neuberger.*option strateg|nb .*option strateg", low):
        fam = "put_write"
    elif basket or stock:
        fam = "single_stock"
    elif re.search(r"bitcoin|\bether|crypto|solana|\bxrp\b", low):
        fam = "crypto_income"
    elif re.search(r"0dte|\bdaily\b|weekly ?pay|weekly", low) or (re.search(r"proshares", low) and "high income" in low):
        fam = "daily_0dte"
    elif "neos" in low and re.search(r"high income|enhanced income", low):
        fam = "call_spread"
    elif "dividend" in low and re.search(r"covered call|enhanced|premium|option|target income", low):
        fam = "dividend_options"
    elif eln or re.search(r"premium income|equity premium|\bactive\b", low) and not re.search(r"covered call|buy-?write", low):
        fam = "active_premium"
    else:
        fam = "systematic_cc"
    style = "systematic" if fam in ("systematic_cc", "put_write") and "active" not in low else "active"
    bench_assumed = False
    if stock or etf_under:
        bench = stock or etf_under
    else:
        bench = BENCH_BY_TICKER.get(ticker) or next((b for rx, b in BENCH_RULES if re.search(rx, low)), None)
    if basket:
        bench = "QQQ" if re.search(r"magnificent|mag 7|ultra", low) else "SPY"
    if bench is None and not re.search(r"\.(L|HK)$", ticker or ""):
        bench, bench_assumed = "SPY", True            # US equity option funds are mostly US large-cap
    if inverse and fam != "short_vol":
        bench = None                                  # an inverse fund vs the long underlying is meaningless
    if fam == "leveraged_income":
        exposure = "leveraged"
    elif basket:
        exposure = "basket of single-stock strategies"
    elif stock:
        exposure = "single stock"
    elif fam == "crypto_income" or bench in ("BTC-USD", "ETH-USD", "BKCH"):
        exposure = "crypto"
    elif bench in COMMODITIES:
        exposure = "commodity"
    elif bench in BONDS:
        exposure = "bond"
    elif (bench in BROAD or bench is None) and not CONCENTRATED.search(low):
        exposure = "broad index"
    else:
        exposure = "sector"
    note = bool(re.search(r"\bETPs?\b|\bETNs?\b|exchange traded note", n))   # collateralised notes, not funds
    return {"family": fam, "style": style, "eln": eln, "under": stock, "bench": bench, "exposure": exposure,
            "note": note, "inverse": inverse and fam != "short_vol", "bench_assumed": bench_assumed}


def share_class_key(name):
    """Group share classes / trading counters of one fund: strip currency, acc/dist, hedged, counter suffixes."""
    n = re.sub(r"\b(USD|GBP|EUR|CHF|JPY|HKD|RMB)\b|\b(acc|accumulating|accumulation|dist|distributing|dis|inc|income)\b"
               r"|\bhedged\b|\bclass\s+\w+\b|\bcounter\b|-u\b|-r\b|[()]", " ", name or "", flags=re.I)
    return re.sub(r"\s+", " ", n).strip().lower()


# --------------------------------------------------------------------- metrics --
def _on_or_before(series, day):
    """Last (date, value) with date <= day from a sorted [(date, value)] list."""
    best = None
    for d, v in series:
        if d <= day:
            best = (d, v)
        else:
            break
    return best


def _nearest(series, day, tol=10):
    """(date, value) of the bar closest to `day` within `tol` calendar days, either side."""
    best = None
    for d, v in series:
        gap = abs((d - day).days)
        if gap <= tol and (best is None or gap < best[0]):
            best = (gap, d, v)
        if d > day + dt.timedelta(days=tol):
            break
    return (best[1], best[2]) if best else None


def _ann(ratio, years):
    return ratio ** (1 / years) - 1 if ratio > 0 and years > 0 else None


def month_ends(series):
    """Last value of each calendar month."""
    out = {}
    for d, v in series:
        out[(d.year, d.month)] = (d, v)
    return [out[k] for k in sorted(out)]


def payout_streak_months(divs, as_of):
    """How long the fund has paid without an unusually long gap, in months.

    Frequency-aware (weekly / monthly / quarterly payers alike): a gap counts as
    a break only if it exceeds 1.6x the fund's typical gap. Counting calendar
    months instead breaks when an ex-date slips from the 31st to the 1st.
    """
    dates = sorted({d for d, _ in divs})
    if len(dates) < 2:
        return 0
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    limit = max(1.6 * statistics.median(gaps[-12:]), 45)   # 45d floor: a monthly->weekly switch isn't a break
    if (as_of - dates[-1]).days > limit:            # stopped paying
        return 0
    start = dates[-1]
    for a, b in zip(reversed(dates[:-1]), reversed(dates[1:])):
        if (b - a).days > limit:
            break
        start = a
    return round((dates[-1] - start).days / 30.44)


def drop_bad_ticks(bars, jump=0.4):
    """Remove one-day price spikes (a print >40% away from both neighbours, which agree
    with each other) — bad Yahoo ticks that would otherwise fake huge drawdowns."""
    if len(bars) < 3:
        return bars, 0
    keep, dropped = [bars[0]], 0
    for i in range(1, len(bars) - 1):
        p0, p1, p2 = keep[-1][1], bars[i][1], bars[i + 1][1]
        if p0 > 0 and p2 > 0 and abs(p1 / p0 - 1) > jump and abs(p1 / p2 - 1) > jump and abs(p2 / p0 - 1) < jump / 2:
            dropped += 1
            continue
        keep.append(bars[i])
    keep.append(bars[-1])
    return keep, dropped


def split_specials(divs, as_of):
    """Year-end capital-gain specials vs regular distributions over the last 12 months.

    A payment is 'special' if it is > 2.5x the median of the fund's own payments in
    the last 12 months and falls in Nov-Jan (when funds pay out realised gains).
    """
    last12 = [(d, a) for d, a in divs if as_of - dt.timedelta(days=365) < d <= as_of]
    if len(last12) < 3:
        return sum(a for _, a in last12), 0.0
    med = statistics.median(a for _, a in last12)
    special = sum(a for d, a in last12 if a > 2.5 * med and d.month in (11, 12, 1))
    return sum(a for _, a in last12) - special, special


def coverage_share(tr_ann, price_cagr):
    """Share of the distributions paid out of total return rather than out of NAV.

    Log-consistent: total return ln(1+TR) = NAV change ln(1+P) + distributions D, so
    D = ln(1+TR) - ln(1+P). If NAV grew, everything was covered; if total return was
    zero or negative, nothing was.
    """
    if tr_ann is None or price_cagr is None:
        return None
    if price_cagr >= 0:
        return 1.0
    if tr_ann <= 0:
        return 0.0
    d = math.log(1 + tr_ann) - math.log(1 + price_cagr)
    return max(0.0, min(1.0, math.log(1 + tr_ann) / d)) if d > 0 else None


def compute(bars, divs, bench=None, rf=None, vix=None, years=WINDOW_YEARS):
    """Pure function: one fund's history -> income metrics (fractions, not %)."""
    bars, bad_ticks = drop_bad_ticks(sorted(bars, key=lambda b: b[0]))
    last = bars[-1][0]
    start_target = last - dt.timedelta(days=round(365.25 * years))
    first = bars[0][0]
    start = max(first, start_target)
    win = [b for b in bars if b[0] >= start]
    yrs = (last - win[0][0]).days / 365.25
    m = {"as_of": last.isoformat(), "history_start": first.isoformat(), "window_start": win[0][0].isoformat(),
         "window_years": round(yrs, 2), "price": round(bars[-1][1], 4)}
    if bad_ticks:
        m["bad_ticks_removed"] = bad_ticks
    closes = [b[1] for b in win]
    adj = [(b[0], b[2]) for b in win]
    # distributions
    divs = sorted(divs or [])
    ttm = sum(a for d, a in divs if last - dt.timedelta(days=365) < d <= last)
    regular, special = split_specials(divs, last)
    px = bars[-1][1]
    m["yield_ttm"] = ttm / px if px else None                 # everything paid in 12 months
    m["yield_regular"] = regular / px if px else None         # excluding year-end specials
    m["specials_ttm"] = special / px if px and special else 0.0
    m["payments_12m"] = sum(1 for d, _ in divs if last - dt.timedelta(days=365) < d <= last)
    recent = [a for d, a in divs if d > last - dt.timedelta(days=400)][-12:]
    m["stability_cv"] = (statistics.pstdev(recent) / statistics.mean(recent)) if len(recent) >= 4 and statistics.mean(recent) > 0 else None
    m["streak_months"] = payout_streak_months(divs, last)
    hist, y, mo = {}, last.year, last.month          # 24 months, empty months included as 0
    for _ in range(24):
        hist[f"{y:04d}-{mo:02d}"] = 0.0
        y, mo = (y, mo - 1) if mo > 1 else (y - 1, 12)
    for d, a in divs:
        k = f"{d.year:04d}-{d.month:02d}"
        if k in hist:
            hist[k] = round(hist[k] + a, 4)
    first_pay = min((d for d, _ in divs), default=None)
    m["dist_hist"] = [(k, v) for k, v in sorted(hist.items())
                      if first_pay and k >= f"{first_pay.year:04d}-{first_pay.month:02d}"]
    if yrs < MIN_YEARS_SCORED:
        m["short_history"] = True
        return m
    # total return, price (≈NAV) trend, distribution coverage
    m["tr_ann"] = _ann(adj[-1][1] / adj[0][1], yrs)
    m["price_cagr"] = _ann(closes[-1] / closes[0], yrs)
    paid = sum(a for d, a in divs if win[0][0] < d <= last)
    avg_px = statistics.mean(closes)
    m["dist_yield_ann"] = (paid / avg_px) / yrs if avg_px else None
    m["cash_paid_10k"] = round(10000 * paid / closes[0], 2) if closes[0] > 0 else None   # $10k bought at the window start, payouts taken as cash
    m["coverage"] = coverage_share(m["tr_ann"], m["price_cagr"]) if m["dist_yield_ann"] else None
    # risk: drawdown, volatility, Sharpe
    peak, mdd = None, 0.0
    for _, v in adj:
        peak = v if peak is None or v > peak else peak
        mdd = min(mdd, v / peak - 1)
    m["max_drawdown"] = mdd
    rets = [math.log(adj[i][1] / adj[i - 1][1]) for i in range(1, len(adj)) if adj[i - 1][1] > 0 and adj[i][1] > 0]
    m["vol_ann"] = statistics.pstdev(rets) * math.sqrt(252) if len(rets) > 20 else None
    rf_ann = None
    if rf:
        a, b = _on_or_before(rf, win[0][0]), _on_or_before(rf, last)
        if a and b and a[1] > 0 and (win[0][0] - a[0]).days < 10 and (last - b[0]).days < 10:
            rf_ann = _ann(b[1] / a[1], yrs)
    m["rf_ann"] = rf_ann
    if m["vol_ann"] and m["tr_ann"] is not None:
        m["sharpe"] = (m["tr_ann"] - (rf_ann or 0.0)) / m["vol_ann"]
    # vs the fund's own underlying
    if bench:
        # both ends of the benchmark must line up with the fund's window (within 10 days,
        # either side — holiday calendars differ); a stale series would be annualised
        # over the wrong span
        a, b = _nearest(bench, win[0][0]), _nearest(bench, last)
        s0 = next((p for p in bench if p[0] >= win[0][0]), None) if b and not a else None
        oy = (last - s0[0]).days / 365.25 if s0 else 0
        fa = _nearest(adj, s0[0]) if s0 else None
        if b and s0 and fa and s0[1] > 0 and fa[1] > 0 and oy >= MIN_GAP_OVERLAP_YEARS and oy >= 0.6 * yrs:
            # benchmark history starts late (e.g. a truncated feed): compare both over the
            # stretch they share, and say so on the card
            m["bench_tr_ann"] = _ann(b[1] / s0[1], oy)
            fund_ov = _ann(adj[-1][1] / fa[1], oy)
            if m["bench_tr_ann"] is not None and fund_ov is not None:
                m["gap"] = fund_ov - m["bench_tr_ann"]
                m["gap_window"] = [s0[0].isoformat(), last.isoformat()]
        elif not (a and b and a[1] > 0):
            m["bench_span"] = [bench[0][0].isoformat(), bench[-1][0].isoformat()] if bench else None
        else:
            m["bench_tr_ann"] = _ann(b[1] / a[1], yrs)
            if m["bench_tr_ann"] is not None and m["tr_ann"] is not None:
                m["gap"] = m["tr_ann"] - m["bench_tr_ann"]
        fm = month_ends(adj)
        bm = dict((k[0].replace(day=1), k[1]) for k in month_ends([(d, v) for d, v in bench if d >= win[0][0]]))
        fr, br = [], []
        for i in range(1, len(fm)):
            k0, k1 = fm[i - 1][0].replace(day=1), fm[i][0].replace(day=1)
            if k0 in bm and k1 in bm and bm[k0] > 0:
                fr.append(fm[i][1] / fm[i - 1][1] - 1)
                br.append(bm[k1] / bm[k0] - 1)
        up = [(f, b) for f, b in zip(fr, br) if b > 0]
        dn = [(f, b) for f, b in zip(fr, br) if b < 0]
        if len(up) >= 3:
            m["up_capture"] = statistics.mean(f for f, _ in up) / statistics.mean(b for _, b in up)
        if len(dn) >= 3:
            m["down_capture"] = statistics.mean(f for f, _ in dn) / statistics.mean(b for _, b in dn)
    # sensitivity to volatility spikes
    if vix:
        vd = dict(vix)
        pairs = []
        for i in range(1, len(adj)):
            d0, d1 = adj[i - 1][0], adj[i][0]
            if d0 in vd and d1 in vd and vd[d0] > 0 and adj[i - 1][1] > 0:
                pairs.append((vd[d1] / vd[d0] - 1, adj[i][1] / adj[i - 1][1] - 1))
        if len(pairs) > 60:
            mx = statistics.mean(x for x, _ in pairs)
            my = statistics.mean(y for _, y in pairs)
            var = sum((x - mx) ** 2 for x, _ in pairs)
            if var > 0:
                m["vix_beta"] = sum((x - mx) * (y - my) for x, y in pairs) / var
            worst = max(pairs, key=lambda p: p[0])
            m["vix_spike_day"] = {"vix_change": worst[0], "fund_return": worst[1]}
    return m


# --------------------------------------------------------------------- scoring --
def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


HISTORY_BASED = ("gap", "coverage", "nav", "vix", "stability")


def logistic(x, mid, scale):
    """Smooth 0-100 curve: 50 at `mid`. Unlike a clamped line it never saturates, so a
    fund lagging 18 pp/yr no longer ties with one lagging 8 pp/yr."""
    return 100 / (1 + math.exp(-(x - mid) / scale))


def components(f, m, extreme_yield, priors=None, shrink=True):
    """0-100 component scores (None = not available).

    gap:  -4 pp/yr vs the benchmark scores 50 (the brief's "income costs too much"
          line); 0 pp ≈ 83, +4 pp ≈ 96, -8 pp ≈ 17.
    nav:  -5 %/yr scores 50; flat ≈ 84; -10 %/yr ≈ 16.
    Evidence shrinkage: history-based components of funds with < 3 years of data are
    pulled toward `priors` — the typical value among seasoned funds of the same
    family — so a short record is judged against what the strategy usually delivers
    (shrinking toward a flat 50 would lift poor young funds above most seasoned ones).
    """
    c = {}
    if m.get("gap") is not None:
        c["gap"] = logistic(m["gap"] * 100, -4, 2.5)
    if m.get("coverage") is not None:
        c["coverage"] = 100 * m["coverage"]
    if m.get("price_cagr") is not None:
        c["nav"] = logistic(m["price_cagr"] * 100, -5, 3)
    q = {"broad index": 90, "bond": 80, "sector": 70, "commodity": 55, "basket of single-stock strategies": 45,
         "crypto": 30, "single stock": 25, "leveraged": 10}[f["exposure"]]
    if extreme_yield:
        q -= 25
    q += 5 if m.get("streak_months", 0) >= 24 else (-10 if m.get("streak_months", 0) < 6 else 0)
    c["quality"] = clamp(q)
    if f["market"] == "US":                                      # tax view only meaningful for US funds
        if f["family"] == "active_premium":
            c["tax"] = 35 if f["eln"] else 55
        elif f["family"] == "systematic_cc" and f["exposure"] != "broad index":
            c["tax"] = 45                                        # options on ETFs/sectors: usually not §1256
        else:
            c["tax"] = TAX_SCORE.get(f["family"], 55)
    if f.get("er") is not None:
        c["fees"] = clamp(100 - (f["er"] - 0.2) * 100)
    c["counterparty"] = 50 if f["eln"] else 90
    c["transparency"] = 50 if f["eln"] else 90
    if m.get("vix_beta") is not None:
        c["vix"] = clamp(100 + m["vix_beta"] * 300)
    if m.get("stability_cv") is not None:
        c["stability"] = clamp(100 - m["stability_cv"] * 100)
    if shrink:
        conf = min(1.0, (m.get("window_years") or WINDOW_YEARS) / WINDOW_YEARS)
        pri = priors or {}
        for k in HISTORY_BASED:
            if k in c:
                p0 = pri.get(k, 50.0)
                c[k] = p0 + (c[k] - p0) * conf
    return {k: round(v, 1) for k, v in c.items()}


def family_priors(funds, min_n=5, seasoned_years=2.5):
    """Median raw history-based component per family among funds with a full record."""
    def med(xs):
        return statistics.median(xs) if xs else None
    seasoned = [f for f in funds if (f["metrics"].get("window_years") or 0) >= seasoned_years]
    overall = {k: med([f["raw"][k] for f in seasoned if k in f["raw"]]) for k in HISTORY_BASED}
    out = {}
    for fam in {f["family"] for f in funds}:
        grp = [f for f in seasoned if f["family"] == fam]
        out[fam] = {}
        for k in HISTORY_BASED:
            vals = [f["raw"][k] for f in grp if k in f["raw"]]
            v = med(vals) if len(vals) >= min_n else overall.get(k)
            if v is not None:
                out[fam][k] = round(v, 1)
    return out


def extreme_yield_cutoffs(funds, min_n=20, floor=0.15, small_family=0.30):
    """Yield above which a fund is 'extreme for its strategy family' (regular yield,
    year-end specials excluded): above the family's 95th percentile AND at least 15%
    AND 1.5x the family median. Families with fewer than `min_n` funds use a flat 30%."""
    def pct(xs, q):
        xs = sorted(xs)
        return xs[int(q * (len(xs) - 1))] if xs else 1.0
    fams = {}
    for f in funds:
        fams.setdefault(f["family"], []).append(f["metrics"].get("yield_regular") or 0)
    out = {"_all": small_family}
    for k, v in fams.items():
        out[k] = max(pct(v, 0.95), floor, 1.5 * statistics.median(v)) if len(v) >= min_n else small_family
    return out


def weights_key(f):
    if f["family"] == "active_premium":
        return "active_premium_eln" if f["eln"] else "default"
    return f["family"] if f["family"] in WEIGHTS else "default"


def weighted(comp, key, us_view):
    w = dict(WEIGHTS.get(key, WEIGHTS["default"]))
    if not us_view:
        w.pop("tax", None)
    avail = {k: v for k, v in w.items() if comp.get(k) is not None}
    tot = sum(avail.values())
    # Too little evidence: every family weighs total return vs benchmark, which needs
    # about a year of history — without it a fund would be scored on fees and
    # structure alone.
    if comp.get("gap") is None or tot < 0.6 * sum(w.values()):
        return None, {}
    used = {k: round(v / tot * 100, 1) for k, v in avail.items()}
    return round(sum(comp[k] * v for k, v in avail.items()) / tot, 1), used


def rank_key(f, view):
    """Sort key: score, then raw gap, then coverage, so equal scores aren't ordered by ticker."""
    m = f["metrics"]
    return (-f[f"score_{view}"], -(m.get("gap") if m.get("gap") is not None else -9),
            -(m.get("coverage") if m.get("coverage") is not None else 0), f["t"])


def gates(f, m, fx_usd):
    g = GATES[f["style"]]
    out = {}
    aum = f.get("aum_usd")
    out["aum"] = None if aum is None else aum >= g["aum"]
    age = f.get("age_years")
    out["age"] = None if age is None else age >= g["age"]
    out["er"] = None if f.get("er") is None else f["er"] <= g["er"]
    vol = f.get("vol")
    dvol_usd = (vol * m.get("price", 0) * fx_usd) if vol is not None else None
    out["liquidity"] = None if vol is None else (vol >= LIQ_SHARES or (dvol_usd or 0) >= LIQ_DOLLARS)
    out["structure"] = f["family"] != "leveraged_income" and "N" not in (f.get("flags") or "") and not f.get("note")
    return out


# ----------------------------------------------------------------- value score --
# One headline number, 0-100, computed the same way for every fund so any two can be
# compared ("which is better than which"): how much an income investor got for what it
# cost them over the window. Four pillars, 25 points each:
#   income  earned income   — the regular yield, counted only up to the fund's total return
#                             (anything paid beyond that came out of the investor's capital)
#   nav     paycheck trend  — price (≈ NAV) change per year: a falling price shrinks every payout
#   kept    growth kept     — total return vs the fund's own benchmark (the brief's gap curve)
#   ride    smooth ride     — half worst fall, half Sharpe (return above T-bills per unit of volatility)
# Pre-tax (tax is personal) and fee-neutral (fees are already inside every return). Young funds
# are pulled toward the typical seasoned fund of their family; red flags cap or deduct.
VALUE_WEIGHTS = {"income": 25, "nav": 25, "kept": 25, "ride": 25}
INCOME_K = 5.0                       # income = 100*(1-exp(-earned%/5)): 4% -> 55, 8% -> 80, 12% -> 91
NAV_MID, NAV_SCALE = -3.0, 3.0       # price %/yr: +5 -> 93, 0 -> 73, -3 -> 50, -10 -> 9
GAP_MID, GAP_SCALE = -4.0, 2.5       # pp/yr vs benchmark: 0 -> 83, -4 -> 50, -8 -> 17
DD_MID, DD_SCALE = -25.0, 6.0        # worst fall %: -10 -> 92, -20 -> 70, -35 -> 16
SH_MID, SH_SCALE = 0.5, 0.25         # Sharpe: 0 -> 12, 0.5 -> 50, 1.0 -> 88
SEASONED_YEARS, PRIOR_MIN_N = 2.5, 5
CEIL_F, CEIL_D = 44.0, 59.0          # tops of the F and D bands
CASH_MARGIN, CASH_DEDUCT = 0.02, 10.0
YOUNG_YEARS, YOUNG_DEDUCT_PER_YEAR = 2.0, 10.0
SMALL_AUM_USD_M, SMALL_DEDUCT = 100.0, 5.0
AGE_GRACE_YEARS = 0.5                # 'safety-checked' also admits funds within 6 months of the age gate
GRADES = [(80, "A", "Excellent value"), (70, "B", "Good value"), (60, "C", "Fair value"),
          (45, "D", "Weak value"), (0, "F", "Poor value")]
SPECULATIVE = {"single stock", "basket of single-stock strategies", "crypto"}
VALUE_FLAGS = {                      # id -> (kind, number, plain-English text for the page)
    "leveraged": ("cap", CEIL_F, "Uses leverage — built to trade, not to hold for income"),
    "big_fall": ("cap", CEIL_F, "Lost more than half its value at its worst point"),
    "speculative": ("cap", CEIL_D, "Rides on one stock or on crypto — speculative"),
    "note": ("cap", CEIL_D, "An issuer's note (ETN/ETP), not a fund — you rely on the bank that issued it"),
    "own_money": ("cap", CEIL_D, "Pays you with your own money — most of the payout came out of capital, or the price fell over 10% a year"),
    "cash_like": ("deduct", CASH_DEDUCT, "No better than cash — total return within 2%/yr of T-bills"),
    "young": ("deduct", YOUNG_DEDUCT_PER_YEAR, "Short track record — under 2 years of prices, so the score leans on similar funds"),
    "small": ("deduct", SMALL_DEDUCT, "Small (under $100M) or thinly traded — may close, and buying/selling costs more"),
}
VALUE_FIELDS = ("value_score", "value_display", "value_base", "value_grade", "value_label", "value_pillars",
                "value_raw", "value_flags", "value_deduction", "value_ceiling", "earned_yield", "paid_yield",
                "value_rank", "value_pct", "value_unrated", "safety_checked", "age_grace_until", "growth_10k")


def saturate(x, k):
    """0-100, rising quickly then flattening: extra yield beyond ~10% adds little."""
    return 100.0 * (1.0 - math.exp(-max(0.0, x) / k))


def display_int(score):
    return int(math.floor(score + 0.5))             # half-up, like JS Math.round


def grade_of(score):
    d = display_int(score)                          # the grade follows the integer people see
    return next((g, label) for lo, g, label in GRADES if d >= lo)


def paid_yield(m):
    y = m.get("yield_regular")
    return y if y is not None else (m.get("yield_ttm") or 0.0)


def earned_yield(m):
    """What it paid, but never more than its total return."""
    return min(paid_yield(m), max(m["tr_ann"], 0.0))


def unrated_reason(f):
    m = f.get("metrics") or {}
    if f.get("inverse"):
        return "Bets against its underlying (inverse) — not an income holding"
    if m.get("short_history") or (m.get("window_years") or 0) < MIN_YEARS_SCORED:
        return "Too new — under 1 year of prices"
    if f.get("currency_mismatch"):
        return "Trades in a different currency from its benchmark"
    if m.get("gap") is None:
        return "No usable benchmark history"
    if any(m.get(k) is None for k in ("tr_ann", "price_cagr", "max_drawdown")):
        return "Price history incomplete"
    return None


def value_raw_pillars(m):
    dd = logistic(m["max_drawdown"] * 100, DD_MID, DD_SCALE)
    return {"income": saturate(earned_yield(m) * 100, INCOME_K),
            "nav": logistic(m["price_cagr"] * 100, NAV_MID, NAV_SCALE),
            "kept": logistic(m["gap"] * 100, GAP_MID, GAP_SCALE),
            "ride": dd if m.get("sharpe") is None else 0.5 * dd + 0.5 * logistic(m["sharpe"], SH_MID, SH_SCALE)}


def risk_bucket(f):
    return "speculative" if f.get("exposure") in SPECULATIVE | {"leveraged"} else "diversified"


def value_priors(funds):
    """Typical raw pillars for young funds to lean on: the median among rated funds with
    >= 2.5 years of prices in the same family (needs 5 of them), else in the same risk
    bucket, so a young crypto or leveraged fund isn't assumed to behave like an index fund."""
    rated = [f for f in funds if unrated_reason(f) is None]
    raw = {id(f): value_raw_pillars(f["metrics"]) for f in rated}
    seasoned = [f for f in rated if f["metrics"]["window_years"] >= SEASONED_YEARS]

    def med(grp):
        return {k: round(statistics.median(raw[id(f)][k] for f in grp), 1) for k in VALUE_WEIGHTS} if grp else None
    out = {"_all": med(seasoned)}
    for b in ("diversified", "speculative"):
        out["_" + b] = med([f for f in seasoned if risk_bucket(f) == b])
    for fam in sorted({f["family"] for f in rated}):
        grp = [f for f in seasoned if f["family"] == fam]
        if len(grp) >= PRIOR_MIN_N:
            out[fam] = med(grp)
    return {k: v for k, v in out.items() if v}


def value_red_flags(f):
    m, g = f["metrics"], f.get("gates") or {}
    flags = []
    if f.get("exposure") == "leveraged" or f.get("family") == "leveraged_income":
        flags.append("leveraged")
    if m["max_drawdown"] <= -0.50:
        flags.append("big_fall")
    if f.get("exposure") in SPECULATIVE:
        flags.append("speculative")
    if f.get("note") or "N" in (f.get("flags") or ""):
        flags.append("note")
    paid = paid_yield(m)
    if (paid > 0 and earned_yield(m) < 0.5 * paid) or m["price_cagr"] < -0.10:
        flags.append("own_money")
    rf = m.get("rf_ann") if m.get("rf_ann") is not None else 0.04
    if m["tr_ann"] - rf < CASH_MARGIN:
        flags.append("cash_like")
    if m["window_years"] < YOUNG_YEARS:
        flags.append("young")
    if (f.get("aum_usd") is not None and f["aum_usd"] < SMALL_AUM_USD_M) or g.get("liquidity") is False:
        flags.append("small")
    return flags


def value_score(f, priors):
    why = unrated_reason(f)
    if why:
        return {"value_score": None, "value_unrated": why}
    m = f["metrics"]
    raw = value_raw_pillars(m)
    conf = min(1.0, m["window_years"] / WINDOW_YEARS)
    pri = priors.get(f["family"]) or priors.get("_" + risk_bucket(f)) or priors.get("_all") or raw
    p = {k: pri[k] + (raw[k] - pri[k]) * conf for k in VALUE_WEIGHTS}
    base = sum(p[k] * w for k, w in VALUE_WEIGHTS.items()) / sum(VALUE_WEIGHTS.values())
    flags = value_red_flags(f)
    deduction = sum(YOUNG_DEDUCT_PER_YEAR * (YOUNG_YEARS - m["window_years"]) if fl == "young" else VALUE_FLAGS[fl][1]
                    for fl in flags if VALUE_FLAGS[fl][0] == "deduct")
    ceiling = min([VALUE_FLAGS[fl][1] for fl in flags if VALUE_FLAGS[fl][0] == "cap"], default=100.0)
    score = round(max(0.0, min(base - deduction, ceiling)), 1)
    g, label = grade_of(score)
    return {"value_score": score, "value_unrated": None, "value_display": display_int(score),
            "value_base": round(base, 1), "value_grade": g, "value_label": label,
            "value_pillars": {k: round(v, 1) for k, v in p.items()},      # 0-100 each; a quarter is points of 25
            "value_raw": {k: round(v, 1) for k, v in raw.items()},        # before the young-fund adjustment
            "value_flags": flags, "value_deduction": round(deduction, 1),
            "value_ceiling": ceiling if base - deduction > ceiling else None,   # only when it bit
            "earned_yield": round(earned_yield(m), 5), "paid_yield": round(paid_yield(m), 5)}


def age_grace_until(f, gates_cfg):
    """Date the fund clears the age gate, when age is its only failed gate and it is
    within six months of it; else None."""
    if [k for k, v in (f.get("gates") or {}).items() if v is not True] != ["age"]:
        return None
    need, age = gates_cfg[f["style"]]["age"], f.get("age_years")
    start = f.get("inc") or (f.get("metrics") or {}).get("history_start")
    if age is None or age < need - AGE_GRACE_YEARS or not start:
        return None
    y, mo, d = (int(x) for x in start[:10].split("-"))
    try:
        return dt.date(y + int(need), mo, d).isoformat()
    except ValueError:                                  # 29 February
        return dt.date(y + int(need), mo, 28).isoformat()


def growth_10k(m):
    """What $10,000 did over the window: payouts reinvested, shares if payouts were taken
    as cash, and the cash itself (exact once compute() has stored cash_paid_10k)."""
    yrs = m.get("window_years")
    if not yrs or m.get("tr_ann") is None or m.get("price_cagr") is None:
        return None
    exact = m.get("cash_paid_10k")
    cash = exact if exact is not None else \
        10000 * (m.get("dist_yield_ann") or 0) * yrs * (1 + m["price_cagr"]) ** (yrs / 2)
    out = {"years": yrs, "reinvested": round(10000 * (1 + m["tr_ann"]) ** yrs),
           "shares_now": round(10000 * (1 + m["price_cagr"]) ** yrs),
           "cash_paid": round(cash), "cash_paid_exact": exact is not None}
    if m.get("bench_tr_ann") is not None and not m.get("gap_window"):
        out["bench_reinvested"] = round(10000 * (1 + m["bench_tr_ann"]) ** yrs)
    return out


def value_sort_key(f):
    gap = f["metrics"].get("gap")
    return (-f["value_score"], -f["value_base"], -(gap if gap is not None else -9), f["t"])


def score_value(funds, gates_cfg):
    """Annotate every fund with its Value Score; return the top-level 'value' block."""
    priors = value_priors(funds)
    for f in funds:
        f.update(value_score(f, priors))
        grace = age_grace_until(f, gates_cfg)
        f["safety_checked"] = f["value_score"] is not None and (bool(f.get("passes")) or grace is not None)
        f["age_grace_until"] = grace
        f["growth_10k"] = growth_10k(f["metrics"])
    rated = sorted([f for f in funds if f["value_score"] is not None], key=value_sort_key)
    n = len(rated)
    for i, f in enumerate(rated):
        f["value_rank"] = i + 1
        f["value_pct"] = round(100 * (n - 1 - i) / (n - 1)) if n > 1 else 100   # "better than X% of rated"
    return {"weights": VALUE_WEIGHTS, "grades": [list(g) for g in GRADES],
            "flags": {k: {"kind": v[0], "amount": v[1], "text": v[2]} for k, v in VALUE_FLAGS.items()},
            "age_grace_years": AGE_GRACE_YEARS, "priors": priors, "rated": n,
            "safety_checked": sum(1 for f in funds if f["safety_checked"])}


def vix_gauge(vix, years=WINDOW_YEARS):
    """Today's VIX against its own range: option premiums (the income these funds sell) are
    richer when the VIX is high. Market-wide context only — not part of any fund's score."""
    if not vix:
        return None
    last_day, now = vix[-1]
    past = [v for d, v in vix if d > last_day - dt.timedelta(days=round(365.25 * years))]
    if len(past) < 60 or not now:
        return None
    return {"vix": round(now, 2), "as_of": last_day.isoformat(), "years": years,
            "pct_below": round(100 * sum(1 for v in past if v < now) / len(past)),
            "median": round(statistics.median(past), 2)}


# ------------------------------------------------------------------------ main --
def load_candidates():
    """Option-income funds from the Explorer universe, one row per fund.

    London share classes and Hong Kong trading counters (HKD / USD / RMB) of the same
    fund collapse to one line: the benchmark-currency line for London (USD), the HKD
    counter for Hong Kong, then the most traded.
    """
    cands, groups = {}, {}
    for key in ("us", "hk", "lse"):
        path = os.path.join(DATA, f"universe-{key}.json")
        if not os.path.exists(path):
            continue
        u = json.load(open(path, encoding="utf-8"))
        cols = u["cols"]
        for row in u["rows"]:
            r = dict(zip(cols, row))
            c = classify(r["n"], r.get("f", ""), r["t"])
            if not c:
                continue
            f = {"t": r["t"], "n": r["n"], "market": key.upper(), "cur": r.get("cur") or "USD",
                 "aum_usd": r.get("aumu") if r.get("aumu") is not None else r.get("aum"), "er": r.get("er"),
                 "vol": r.get("vol"), "inc": r.get("inc"), "flags": r.get("f", ""), "dom": r.get("dom"), **c}
            if key in ("lse", "hk"):
                k = (key, share_class_key(r["n"]))
                pref = "USD" if key == "lse" else "HKD"
                rank = (f["cur"] == pref, f.get("vol") or 0)
                best = groups.get(k)
                if best is None or rank > best[0]:
                    groups[k] = (rank, f)
                continue
            cands[r["t"]] = f
    for _, f in groups.values():
        cands[f["t"]] = f
    return cands


def bench_currency(sym):
    if sym.endswith(".HK"):
        return "HKD"
    if sym.endswith(".KS"):
        return "KRW"
    if sym.endswith(".L"):
        return "GBP"
    return "USD"


def currencies_compatible(a, b):
    return a == b or {a, b} == {"HKD", "USD"}           # HKD is pegged to the dollar


def main(argv):
    dry = "--dry-run" in argv
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    cands = load_candidates()
    log(f"{len(cands)} option-income candidates "
        f"({sum(1 for f in cands.values() if f['market'] == 'US')} US, "
        f"{sum(1 for f in cands.values() if f['market'] == 'HK')} HK, "
        f"{sum(1 for f in cands.values() if f['market'] == 'LSE')} London)")
    if limit:
        cands = dict(list(cands.items())[:limit])
    yahoo = rm.Yahoo()
    lock = threading.Lock()
    hist = {}

    def fetch(sym):
        for attempt in range(2):
            try:
                raw = yahoo.chart(sym)
                with lock:
                    hist[sym] = raw
                return True
            except LookupError:
                return False
            except Exception:  # noqa: BLE001
                time.sleep(1.5)
        return False

    syms = sorted(set(cands) | {f["bench"] for f in cands.values() if f["bench"]} | {RISK_FREE, VIX})
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(fetch, syms))
    log(f"fetched {len(hist)}/{len(syms)} price histories in {time.monotonic() - t0:.0f}s")
    missing_bench = sorted({f["bench"] for f in cands.values() if f["bench"] and f["bench"] not in hist})
    if missing_bench:
        log(f"benchmarks unavailable: {missing_bench}")

    def series(sym, col=2):
        raw = hist.get(sym) if sym else None
        return [(b[0], b[col]) for b in raw["bars"]] if raw else None

    rf, vix = series(RISK_FREE), series(VIX, 1)
    funds = []
    today = dt.date.today()
    for t, f in sorted(cands.items()):
        raw = hist.get(t)
        if not raw:
            continue
        bench = series(f["bench"])
        if f["bench"] and not bench:
            f["bench_missing"] = True
        if bench and not currencies_compatible(f["cur"], bench_currency(f["bench"])):
            f["currency_mismatch"] = True             # e.g. a GBP line vs a USD benchmark: FX would pollute the gap
            bench = None
        # VIX is a US-session series; Asian/European closes don't line up day by day.
        m = compute(raw["bars"], raw.get("divs"), bench, rf, vix if f["market"] == "US" else None)
        paying = m.get("payments_12m", 0) >= 2 and (m.get("yield_regular") or 0) >= 0.02
        if not paying and not (m.get("short_history") and m.get("payments_12m", 0) >= 1):
            continue                               # not actually an income payer (e.g. one year-end special)
        start = f.get("inc") or m["history_start"]
        try:
            f["age_years"] = round((today - dt.date.fromisoformat(start[:10])).days / 365.25, 2)
        except ValueError:
            f["age_years"] = None
        f["metrics"] = m
        funds.append(f)
    cut, priors, value = score_all(funds, load_fx())
    market = vix_gauge(vix)
    log(f"VIX gauge: {market}")
    for t in ("JEPI", "QYLD", "SPYI", "SVOL", "TSLY", "DIVO", "RBLY", "GMEY", "3419.HK"):
        f = next((x for x in funds if x["t"] == t), None)
        if f:
            mm = f["metrics"]
            log(f"  {t}: {f['family']} bench {f['bench']} score {f['score_us']} rank {f.get('rank_us')} "
                f"value {f['value_score']} {f.get('value_grade')} #{f.get('value_rank')} "
                f"tr {mm.get('tr_ann')} gap {mm.get('gap')} cov {mm.get('coverage')} yld {mm.get('yield_regular')}")
    if dry:
        return 0
    if len(funds) < 50:
        log("Too few funds scored — keeping the existing income-lab.json.")
        return 1
    for f in funds:
        f["metrics"] = {k: (round(v, 5) if isinstance(v, float) else v) for k, v in f["metrics"].items()}
    write_doc(funds, cut, priors, value, dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(), market)
    return 0


def load_fx():
    fx = {}
    for key in ("hk", "lse"):
        p = os.path.join(DATA, f"universe-{key}.json")
        if os.path.exists(p):
            fx.update(json.load(open(p, encoding="utf-8")).get("fx_usd") or {})
    return fx


def score_all(funds, fx):
    """Layers 1-3 for funds that already carry `metrics`: extreme-yield flags, component
    scores (with family-prior shrinkage), family-weighted scores, gates and ranks."""
    cut = extreme_yield_cutoffs(funds)
    for f in funds:
        f["extreme_yield"] = (f["metrics"].get("yield_regular") or 0) > cut.get(f["family"], cut["_all"])
        f["raw"] = components(f, f["metrics"], f["extreme_yield"], shrink=False)
    priors = family_priors(funds)
    for f in funds:
        m = f["metrics"]
        f["components"] = components(f, m, f["extreme_yield"], priors.get(f["family"]))
        f["prior"] = priors.get(f["family"])
        del f["raw"]
        wk = weights_key(f)
        f["weights_key"] = wk
        f["score_us"], f["weights_us"] = weighted(f["components"], wk, True)
        f["score_intl"], f["weights_intl"] = weighted(f["components"], wk, False)
        f["gates"] = gates(f, m, fx.get(f["cur"], 1.0))
        f["passes"] = all(v is True for v in f["gates"].values())
        f["gates_unknown"] = [k for k, v in f["gates"].items() if v is None]
        f["tax_note"] = TAX_NOTE.get(f["family"])
        if f["family"] == "active_premium" and not f["eln"]:
            f["tax_note"] = "Options written directly by the manager may be §1256; check the fund's annual report for the income character."
    by_fam = {}
    for f in funds:
        by_fam.setdefault(f["family"], []).append(f)
    for fam, lst in by_fam.items():                # rank within family (US view, then international)
        for view in ("us", "intl"):
            ranked = sorted([f for f in lst if f[f"score_{view}"] is not None], key=lambda f: rank_key(f, view))
            for i, f in enumerate(ranked):
                f[f"rank_{view}"] = i + 1
    value = score_value(funds, GATES)
    log(f"{len(funds)} income funds; {sum(f['score_us'] is not None for f in funds)} scored; "
        f"{sum(f['passes'] for f in funds)} pass every gate; {value['rated']} value-rated, "
        f"{value['safety_checked']} safety-checked; families: { {k: len(v) for k, v in sorted(by_fam.items())} }")
    return cut, priors, value


def write_doc(funds, cut, priors, value, generated_at, market=None, path=OUT):
    doc = {"as_of": max(f["metrics"]["as_of"] for f in funds), "generated_at": generated_at,
           "window_years": WINDOW_YEARS, "families": FAMILIES, "weights": WEIGHTS, "gates": GATES,
           "liquidity": {"shares": LIQ_SHARES, "dollars": LIQ_DOLLARS},
           "extreme_yield_cutoffs": {k: round(v, 4) for k, v in cut.items()},
           "priors": priors, "value": value, "market": market, "count": len(funds), "funds": funds}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"), ensure_ascii=False, default=str)
    log(f"Wrote {os.path.relpath(path, rm.ROOT)} ({os.path.getsize(path) // 1024} KB)")


# Everything score_all() derives; the rest of a fund record is classification + metrics.
DERIVED = ("extreme_yield", "components", "prior", "weights_key", "score_us", "weights_us", "score_intl",
           "weights_intl", "gates", "passes", "gates_unknown", "tax_note", "rank_us", "rank_intl") + VALUE_FIELDS


def rescore(path=OUT):
    """Re-run the scoring on the metrics already in income-lab.json — no network, so
    a scoring change can be checked (and shipped) without re-fetching every fund."""
    doc = json.load(open(path, encoding="utf-8"))
    funds = doc["funds"]
    for f in funds:
        for k in DERIVED:
            f.pop(k, None)
    cut, priors, value = score_all(funds, load_fx())
    write_doc(funds, cut, priors, value, doc.get("generated_at"), doc.get("market"), path)
    return 0


if __name__ == "__main__":
    sys.exit(rescore() if "--rescore" in sys.argv else main(sys.argv[1:]))
