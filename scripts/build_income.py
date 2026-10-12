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

Usage:
    python3 scripts/build_income.py              # build income-lab.json
    python3 scripts/build_income.py --dry-run    # fetch + summarise only
    python3 scripts/build_income.py --limit 40   # quick partial run
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

# ------------------------------------------------------------------ selection --
OPTION_KW = re.compile(
    r"covered call|buy-?write|premium income|option income|options? income|option strateg|yieldmax|yieldboost"
    r"|weekly ?pay|0dte|put-?write|cash-secured put|high income|enhanced income|volatility premium|autocall"
    r"|overwrite|equity premium|target income|enhanced dividend|short vix|enhanced options|\boptions?\b"
    r"|weekly distribution|target \d+",
    re.I)
NOT_INCOME = re.compile(r"buffer|defined outcome|hedged equity|\bprotect|\bfloor\b|barrier|accelerat|tail risk|convexity"
                        r"|structured outcome|downside|max(imum)? (buffer|protection)", re.I)
BOND = re.compile(r"\bbond|treasur|muni|credit|fixed income|\bloan|mortgage|\bclo\b|preferred|maturity|ultra-?short"
                  r"|floating|aggregate|t-bill|money market|\bbdc\b|specialty finance|cash management", re.I)
# Words that look like tickers in fund names but aren't single-stock underlyings.
NOT_STOCK = {"ETF", "ETFS", "USD", "GBP", "EUR", "HKD", "NASDAQ", "SPDR", "MSCI", "FTSE", "NDX", "SPX", "RUT", "QQQ",
             "SPY", "IWM", "DIA", "KWEB", "MLP", "BDC", "REIT", "AI", "US", "UCITS", "ACC", "DIST", "DIS", "OFC",
             "HSI", "HSCEI", "CSOP", "TECH", "ARK", "ARKK", "XLK", "XLF", "XLE", "XLU", "XLV", "XLI", "XLY", "XLP",
             "XLB", "XLC", "XLRE", "SOXX", "SMH", "GLD", "SLV", "TLT", "EEM", "EFA", "BTC", "ETH", "S&P", "DOW",
             "NEOS", "JPM", "II", "III", "IV", "PLC", "LP", "THE", "AND", "OF", "TOP", "MAG", "FANG", "KOSPI",
             "HSTECH", "WEEKLY", "DAILY", "TARGET", "INCOME", "OPTION", "PREMIUM", "COVERED", "CALL", "HIGH"}
SINGLE_STOCK = re.compile(r"\b([A-Z]{1,5})\b\s+(?:Option Income|Enhanced Income|Covered Call|WeeklyPay|YieldBOOST|"
                          r"Performance & Distribution|Income|Option)", re.I)

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
# Benchmarks: the fund's own underlying, as a total-return series.
BENCH_RULES = [
    (r"\bus equity|u\.s\. equity|\bus large", "SPY"),       # before 'hang seng' (issuer name on HK funds)
    (r"\bfang\b", "QQQ"),
    (r"nasdaq[- ]?100|nasdaq 100|\bqqq\b|\bndx\b|nasdaq", "QQQ"),
    (r"russell 2000|\br2000\b|small[- ]?cap|\biwm\b|\brut\b|russell", "IWM"),
    (r"\bdow\b|dow jones|\bdjia\b|dow 30", "DIA"),
    (r"utilities select", "XLU"), (r"financial select", "XLF"), (r"industrial select", "XLI"),
    (r"consumer discretionary select", "XLY"), (r"consumer staples select", "XLP"),
    (r"technology select", "XLK"), (r"health care select", "XLV"), (r"energy select", "XLE"),
    (r"materials select", "XLB"), (r"real estate select", "XLRE"), (r"communication services select", "XLC"),
    (r"\bmlp\b|midstream|energy infrastructure", "AMLP"),
    (r"semiconductor", "SOXX"), (r"\bkweb\b|china internet", "KWEB"), (r"innovation|\barkk\b", "ARKK"),
    (r"gold miners", "GDX"), (r"\bgold\b", "GLD"), (r"crypto", "BTC-USD"), (r"\bsilver\b", "SLV"), (r"bitcoin", "BTC-USD"), (r"\bether", "ETH-USD"),
    (r"hscei|china enterprises|h-share", "^HSCE"), (r"hang seng tech|hstech|hs tech", "3067.HK"),
    (r"hang seng|\bhsi\b", "^HSI"), (r"kospi", "^KS200"),
    (r"emerging", "EEM"), (r"international|developed|eafe|world ex", "EFA"),
    (r"real estate|\breit", "VNQ"), (r"treasury|bond", "AGG"),
    (r"s&p 500|sp500|\bspx\b|\bspy\b|s&p|large[- ]cap|equity premium|500", "SPY"),
]
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
    "active_premium": {"counterparty": 30, "gap": 30, "fees": 20, "transparency": 20},
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
def stock_underlying(name):
    """Ticker of a single-stock underlying named in the fund name, if any."""
    m = re.search(r"YieldBOOST\s+([A-Z]{2,5})\b", name or "")
    if m and m.group(1) not in NOT_STOCK:
        return m.group(1)
    for m in SINGLE_STOCK.finditer(name or ""):
        tok = m.group(1)
        if tok.isupper() and tok not in NOT_STOCK and len(tok) >= 2:
            return tok
    return None


def classify(name, flags="", ticker=""):
    """Fund name -> {family, style, eln, under, bench, exposure} or None (not option income)."""
    n = name or ""
    if not OPTION_KW.search(n) or BOND.search(n) or (NOT_INCOME.search(n) and not re.search(r"income|yield", n, re.I)):
        return None
    low = n.lower()
    stock = stock_underlying(n)
    eln = bool(re.search(r"jpmorgan|j\.p\. ?morgan|\bjpm\b", low)) and "premium income" in low
    basket = bool(re.search(r"fund of option income|fund of .*income etfs|ultra option income|universe fund", low))
    # Leveraged by name (the universe 'L' flag also fires on non-leveraged names like
    # 'YieldMax Ultra Option Income', so it is not trusted on its own here).
    if re.search(r"\b[2-9](\.\d+)?x\b|leveraged|yieldboost|\bultra(pro|short)\b|proshares ultra|\binverse\b", low):
        fam = "leveraged_income"
    elif re.search(r"autocall|barrier|buffer", low):
        fam = "structured"
    elif re.search(r"volatility premium|short vix|short volatility|vol premium", low):
        fam = "short_vol"
    elif re.search(r"put[- ]?write|putwrite|cash-secured put", low):
        fam = "put_write"
    elif basket or (stock and not re.search(r"portfolio|magnificent|semiconductor", low)):
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
    bench = stock or next((b for rx, b in BENCH_RULES if re.search(rx, low)), "SPY")
    if basket:
        bench = "QQQ" if re.search(r"magnificent|mag 7|ultra", low) else "SPY"
    if fam == "leveraged_income":
        exposure = "leveraged"
    elif fam == "single_stock":
        exposure = "basket of single-stock strategies" if basket else "single stock"
    elif fam == "crypto_income" or bench in ("BTC-USD", "ETH-USD"):
        exposure = "crypto"
    elif bench in ("GLD", "SLV"):
        exposure = "commodity"
    elif bench in ("SPY", "QQQ", "IWM", "DIA", "^HSI", "^HSCE", "^KS200", "EFA", "EEM"):
        exposure = "broad index"
    else:
        exposure = "sector"
    return {"family": fam, "style": style, "eln": eln, "under": stock, "bench": bench, "exposure": exposure}


def share_class_key(name):
    """Group London share classes of one fund: strip currency / acc / dist / hedged suffixes."""
    n = re.sub(r"\b(USD|GBP|EUR|CHF|JPY)\b|\b(acc|accumulating|accumulation|dist|distributing|dis|inc|income)\b"
               r"|\bhedged\b|\bclass\s+\w+\b|[()]", " ", name or "", flags=re.I)
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


def _ann(ratio, years):
    return ratio ** (1 / years) - 1 if ratio > 0 and years > 0 else None


def month_ends(series):
    """Last value of each calendar month."""
    out = {}
    for d, v in series:
        out[(d.year, d.month)] = (d, v)
    return [out[k] for k in sorted(out)]


def compute(bars, divs, bench=None, rf=None, vix=None, years=WINDOW_YEARS):
    """Pure function: one fund's history -> income metrics (fractions, not %)."""
    bars = sorted(bars, key=lambda b: b[0])
    last = bars[-1][0]
    start_target = last - dt.timedelta(days=round(365.25 * years))
    first = bars[0][0]
    start = max(first, start_target)
    win = [b for b in bars if b[0] >= start]
    yrs = (last - win[0][0]).days / 365.25
    m = {"as_of": last.isoformat(), "history_start": first.isoformat(), "window_start": win[0][0].isoformat(),
         "window_years": round(yrs, 2), "price": round(bars[-1][1], 4)}
    closes = [b[1] for b in win]
    adj = [(b[0], b[2]) for b in win]
    # distributions
    divs = sorted(divs or [])
    ttm = sum(a for d, a in divs if last - dt.timedelta(days=365) < d <= last)
    m["yield_ttm"] = ttm / bars[-1][1] if bars[-1][1] else None
    m["payments_12m"] = sum(1 for d, _ in divs if last - dt.timedelta(days=365) < d <= last)
    recent = [a for d, a in divs if d > last - dt.timedelta(days=400)][-12:]
    m["stability_cv"] = (statistics.pstdev(recent) / statistics.mean(recent)) if len(recent) >= 4 and statistics.mean(recent) > 0 else None
    months = {(d.year, d.month) for d, _ in divs}
    streak, y, mo = 0, last.year, last.month
    if (y, mo) not in months:                      # current month may not have paid yet
        y, mo = (y, mo - 1) if mo > 1 else (y - 1, 12)
    while (y, mo) in months:
        streak += 1
        y, mo = (y, mo - 1) if mo > 1 else (y - 1, 12)
    m["streak_months"] = streak
    hist = {}
    for d, a in divs:
        if d > last - dt.timedelta(days=731):
            k = f"{d.year:04d}-{d.month:02d}"
            hist[k] = round(hist.get(k, 0) + a, 4)
    m["dist_hist"] = sorted(hist.items())
    if yrs < MIN_YEARS_SCORED:
        m["short_history"] = True
        return m
    # total return, price (≈NAV) trend, distribution coverage
    m["tr_ann"] = _ann(adj[-1][1] / adj[0][1], yrs)
    m["price_cagr"] = _ann(closes[-1] / closes[0], yrs)
    paid = sum(a for d, a in divs if win[0][0] < d <= last)
    avg_px = statistics.mean(closes)
    m["dist_yield_ann"] = (paid / avg_px) / yrs if avg_px else None
    if m["price_cagr"] is None or not m["dist_yield_ann"]:
        m["coverage"] = None
    elif m["price_cagr"] >= 0:
        m["coverage"] = 1.0
    else:
        m["coverage"] = max(0.0, min(1.0, 1 + m["price_cagr"] / m["dist_yield_ann"]))
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
        if a and b and a[1] > 0:
            rf_ann = _ann(b[1] / a[1], yrs)
    m["rf_ann"] = rf_ann
    if m["vol_ann"] and m["tr_ann"] is not None:
        m["sharpe"] = (m["tr_ann"] - (rf_ann or 0.0)) / m["vol_ann"]
    # vs the fund's own underlying
    if bench:
        a, b = _on_or_before(bench, win[0][0]), _on_or_before(bench, last)
        if a and b and a[1] > 0 and (win[0][0] - a[0]).days < 10:
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


def components(f, m, extreme_yield):
    """0-100 component scores (None = not available)."""
    c = {}
    if m.get("gap") is not None:
        c["gap"] = clamp(100 + 12.5 * m["gap"] * 100)            # -4 pp/yr -> 50, -8 -> 0
    if m.get("coverage") is not None:
        c["coverage"] = 100 * m["coverage"]
    if m.get("price_cagr") is not None:
        c["nav"] = clamp(100 + 10 * m["price_cagr"] * 100)       # -5 %/yr -> 50, -10 -> 0
    q = {"broad index": 90, "sector": 70, "commodity": 55, "basket of single-stock strategies": 45,
         "crypto": 30, "single stock": 25, "leveraged": 10}[f["exposure"]]
    if extreme_yield:
        q -= 25
    q += 5 if m.get("streak_months", 0) >= 24 else (-10 if m.get("streak_months", 0) < 6 else 0)
    c["quality"] = clamp(q)
    if f["market"] == "US":                                      # tax view only meaningful for US funds
        c["tax"] = (35 if f["eln"] else 55) if f["family"] == "active_premium" else TAX_SCORE.get(f["family"], 55)
    if f.get("er") is not None:
        c["fees"] = clamp(100 - (f["er"] - 0.2) * 100)
    c["counterparty"] = 50 if f["eln"] else 90
    c["transparency"] = 50 if f["eln"] else 90
    if m.get("vix_beta") is not None:
        c["vix"] = clamp(100 + m["vix_beta"] * 300)
    if m.get("stability_cv") is not None:
        c["stability"] = clamp(100 - m["stability_cv"] * 100)
    return {k: round(v, 1) for k, v in c.items()}


def weighted(comp, family, us_view):
    w = dict(WEIGHTS.get(family, WEIGHTS["default"]))
    if not us_view:
        w.pop("tax", None)
    avail = {k: v for k, v in w.items() if comp.get(k) is not None}
    tot = sum(avail.values())
    if tot < 0.6 * sum(w.values()):                              # too little evidence to score
        return None, {}
    used = {k: round(v / tot * 100, 1) for k, v in avail.items()}
    return round(sum(comp[k] * v for k, v in avail.items()) / tot, 1), used


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
    out["structure"] = f["family"] != "leveraged_income" and "N" not in (f.get("flags") or "")
    return out


# ------------------------------------------------------------------------ main --
def load_candidates():
    cands = {}
    london = {}
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
            if key == "lse":                       # one line per London fund: prefer USD, then most traded
                k = share_class_key(r["n"])
                best = london.get(k)
                rank = (f["cur"] == "USD", f.get("vol") or 0)
                if best is None or rank > best[0]:
                    london[k] = (rank, f)
                continue
            cands[r["t"]] = f
    for _, f in london.values():
        cands[f["t"]] = f
    return cands


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

    syms = sorted(set(cands) | {f["bench"] for f in cands.values()} | {RISK_FREE, VIX})
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(fetch, syms))
    log(f"fetched {len(hist)}/{len(syms)} price histories in {time.monotonic() - t0:.0f}s")

    def series(sym, col=2):
        raw = hist.get(sym)
        return [(b[0], b[col]) for b in raw["bars"]] if raw else None

    rf, vix = series(RISK_FREE), series(VIX, 1)
    fx = {}
    for key in ("hk", "lse"):
        p = os.path.join(DATA, f"universe-{key}.json")
        if os.path.exists(p):
            fx.update(json.load(open(p, encoding="utf-8")).get("fx_usd") or {})
    funds = []
    today = dt.date.today()
    for t, f in sorted(cands.items()):
        raw = hist.get(t)
        if not raw:
            continue
        m = compute(raw["bars"], raw.get("divs"), series(f["bench"]), rf, vix)
        if (m.get("yield_ttm") or 0) < 0.02 and not (m.get("short_history") and m.get("payments_12m", 0) >= 1):
            continue                               # not actually an income payer
        start = f.get("inc") or m["history_start"]
        try:
            f["age_years"] = round((today - dt.date.fromisoformat(start[:10])).days / 365.25, 2)
        except ValueError:
            f["age_years"] = None
        f["metrics"] = m
        funds.append(f)
    ylds = sorted(f["metrics"].get("yield_ttm") or 0 for f in funds)
    p95 = ylds[int(0.95 * (len(ylds) - 1))] if ylds else 1
    for f in funds:
        m = f["metrics"]
        f["extreme_yield"] = (m.get("yield_ttm") or 0) > p95
        f["components"] = components(f, m, f["extreme_yield"])
        f["score_us"], f["weights_us"] = weighted(f["components"], f["family"], True)
        f["score_intl"], f["weights_intl"] = weighted(f["components"], f["family"], False)
        f["gates"] = gates(f, m, fx.get(f["cur"], 1.0))
        f["passes"] = all(v is True for v in f["gates"].values())
        f["tax_note"] = TAX_NOTE.get(f["family"])
        if f["family"] == "active_premium" and not f["eln"]:
            f["tax_note"] = "Options written directly by the manager may be §1256; check the fund's annual report for the income character."
    by_fam = {}
    for f in funds:
        by_fam.setdefault(f["family"], []).append(f)
    for fam, lst in by_fam.items():                # rank within family (US view, then international)
        for view in ("us", "intl"):
            ranked = sorted([f for f in lst if f[f"score_{view}"] is not None], key=lambda f: -f[f"score_{view}"])
            for i, f in enumerate(ranked):
                f[f"rank_{view}"] = i + 1
    log(f"{len(funds)} income funds scored; {sum(f['passes'] for f in funds)} pass every gate; "
        f"families: { {k: len(v) for k, v in sorted(by_fam.items())} }")
    for t in ("JEPI", "QYLD", "SPYI", "SVOL", "TSLY", "DIVO"):
        f = next((x for x in funds if x["t"] == t), None)
        if f:
            mm = f["metrics"]
            log(f"  {t}: {f['family']} bench {f['bench']} score {f['score_us']} gates {f['gates']} "
                f"tr {mm.get('tr_ann')} gap {mm.get('gap')} cov {mm.get('coverage')} yld {mm.get('yield_ttm')}")
    if dry:
        return 0
    if len(funds) < 50:
        log("Too few funds scored — keeping the existing income-lab.json.")
        return 1
    for f in funds:
        f["metrics"] = {k: (round(v, 5) if isinstance(v, float) else v) for k, v in f["metrics"].items()}
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    doc = {"as_of": max(f["metrics"]["as_of"] for f in funds), "generated_at": now,
           "window_years": WINDOW_YEARS, "families": FAMILIES, "weights": WEIGHTS, "gates": GATES,
           "liquidity": {"shares": LIQ_SHARES, "dollars": LIQ_DOLLARS}, "extreme_yield_p95": p95,
           "count": len(funds), "funds": funds}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"), ensure_ascii=False, default=str)
    log(f"Wrote {os.path.relpath(OUT, rm.ROOT)} ({os.path.getsize(OUT) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
