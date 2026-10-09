#!/usr/bin/env python3
"""
Build the Explorer universe: every ETF listed on a market, with daily numbers.

Writes public/data/universe-<market>.json, which the site's Explorer loads on
demand. Runs in the daily GitHub Action right after refresh_market.py.

US (this file):
  1. Discovery — NASDAQ Trader's symbol directory lists every US-listed
     security (Nasdaq, NYSE, NYSE Arca, Cboe, IEX) with an ETF flag.
     Fallback: Nasdaq's ETF screener.
  2. Numbers — Yahoo Finance's batch quote endpoint, ~100 tickers per request:
     price, 52-week change, YTD return, AUM, expense ratio, yield, volume.
     Fallback for price / 1-yr change: Nasdaq's ETF screener.

Yahoo's quote fields come in mixed units (some percent, some fractions), so
units are calibrated against SPY's known expense ratio and the YTD return
already computed for SPY in market.json, and the calibration is logged.

Usage:
    python3 scripts/build_universe.py            # build universe-us.json
    python3 scripts/build_universe.py --dry-run  # fetch + summarise only
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refresh_market as rm  # noqa: E402  (shared HTTP + Yahoo session helpers)

DATA = rm.DATA
NASDAQ_DIR = ("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
              "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt")
EXCHANGE = {"Q": "Nasdaq", "N": "NYSE", "P": "NYSE Arca", "A": "NYSE American",
            "Z": "Cboe BZX", "V": "IEX"}
QUOTE_FIELDS = ("longName,shortName,quoteType,currency,fullExchangeName,regularMarketPrice,"
                "regularMarketTime,fiftyTwoWeekLow,fiftyTwoWeekHigh,fiftyTwoWeekChangePercent,"
                "ytdReturn,netAssets,netExpenseRatio,trailingAnnualDividendYield,dividendYield,yield,"
                "averageDailyVolume3Month,fundInceptionDate,firstTradeDateMilliseconds")
BATCH = 100
COLS = ["t", "n", "x", "p", "c1y", "ytd", "aum", "er", "yld", "vol", "f", "inc"]
# flags (f): L = leveraged/inverse, N = exchange-traded note, F = futures-based commodity/VIX
LEVERAGED = re.compile(r"(?<![\w.])-?[1-9](\.\d+)?x\b|\bultra(pro)?(short)?\b|\bleveraged\b|\binverse\b"
                       r"|\bbear\b|\bdaily\b.*\bbull\b|^proshares short\b", re.I)
ETN = re.compile(r"\bETNs?\b|exchange traded notes?", re.I)
FUTURES = re.compile(r"\bfutures\b|\bvix\b|^united states (oil|natural gas|gasoline|brent|12 month)", re.I)


def log(*a):
    print(*a, flush=True)


# ----------------------------------------------------------------- discovery --
def parse_symbol_directory(text, kind):
    """NASDAQ Trader pipe-delimited file -> [{t, n, x}] for ETFs (no test issues)."""
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("File Creation Time")]
    if not lines or "|" not in lines[0]:
        raise ValueError(f"{kind}: unexpected format")
    head = lines[0].split("|")
    out = []
    for ln in lines[1:]:
        row = dict(zip(head, ln.split("|")))
        if row.get("ETF") != "Y" or row.get("Test Issue") == "Y":
            continue
        sym = row.get("Symbol") or row.get("ACT Symbol") or row.get("NASDAQ Symbol")
        if not sym:
            continue
        exch = "Q" if kind == "nasdaq" else row.get("Exchange", "")
        out.append({"t": sym.strip().upper(), "n": clean_name(row.get("Security Name", "")),
                    "x": EXCHANGE.get(exch, exch)})
    return out


def clean_name(name):
    """'iShares Gold Trust Shares' / 'SPDR ... ETF Trust' -> tidy display name."""
    name = re.sub(r"\s+", " ", name or "").strip()
    return re.sub(r"\s+(Shares|Common Shares( of Beneficial Interest)?|Units|ETF Shares)$", "", name)


def discover_us():
    found = {}
    for url, kind in zip(NASDAQ_DIR, ("nasdaq", "other")):
        for u in (url, url.replace("/SymDir/", "/symdir/")):
            try:
                for r in parse_symbol_directory(rm._get(u, timeout=30), kind):
                    found.setdefault(r["t"], r)
                break
            except Exception as e:  # noqa: BLE001
                log(f"  symbol directory {u}: {e}")
    if len(found) < 1000:                         # fallback: Nasdaq ETF screener
        log(f"Symbol directory gave {len(found)} ETFs — trying the Nasdaq screener")
        for r in screener_rows():
            found.setdefault(r["t"], {"t": r["t"], "n": r["n"], "x": ""})
    return found


def screener_rows():
    j = json.loads(rm._get("https://api.nasdaq.com/api/screener/etf?download=true&tableonly=true&limit=10000",
                           headers=rm.NASDAQ_HDR, timeout=40))
    return parse_screener(j)


def parse_screener(j):
    data = (j or {}).get("data") or {}
    rows = (data.get("data") or {}).get("rows") or data.get("rows") or []
    out = []
    for r in rows:
        t = (r.get("symbol") or "").strip().upper()
        if not t:
            continue
        out.append({"t": t, "n": clean_name(r.get("companyName") or ""),
                    "p": _money(r.get("lastSalePrice")), "c1y": _pct(r.get("oneYearPercentage"))})
    return out


def _money(s):
    try:
        return round(rm._num(s), 4)
    except (ValueError, TypeError):
        return None


def _pct(s):
    try:
        return round(float(str(s).replace("%", "").replace(",", "").strip()), 2)
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------- numbers --
def yahoo_symbol(t):
    return t.replace(".", "-").replace("/", "-")


def fetch_quotes(yahoo, tickers, workers=4):
    """Batch quotes from Yahoo -> {ticker: raw quote dict}."""
    batches = [tickers[i:i + BATCH] for i in range(0, len(tickers), BATCH)]
    back = {yahoo_symbol(t): t for t in tickers}

    def one(batch):
        syms = ",".join(yahoo_symbol(t) for t in batch)
        for attempt in range(3):
            try:
                url = (f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={urllib.parse.quote(syms, safe=',')}"
                       f"&fields={QUOTE_FIELDS}&crumb={urllib.parse.quote(yahoo._crumb())}")
                res = (json.loads(yahoo.get(url, timeout=30)).get("quoteResponse") or {}).get("result") or []
                return {back.get(q.get("symbol"), q.get("symbol")): q for q in res}
            except Exception as e:  # noqa: BLE001
                err = e
                time.sleep(1.5 * (attempt + 1))
        log(f"  quote batch failed ({batch[0]}…): {err}")
        return {}

    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for part in ex.map(one, batches):
            out.update(part)
    return out


def pick_yield(q, mult):
    """Best available distribution yield in percent (fields/units vary by fund type)."""
    for field in ("yield", "dividendYield", "trailingAnnualDividendYield"):
        v = q.get(field)
        if isinstance(v, (int, float)) and v > 0:
            return v * mult.get(field, 1.0)
    return None


def calibrate(quotes, spy_ytd_pct=None, spy_yield_pct=None):
    """Detect whether Yahoo's percent-ish fields are fractions or percents.

    Anchors: SPY's expense ratio is ~0.09% (fraction would be ~0.0009); SPY's
    YTD is cross-checked against the value computed from daily closes in
    market.json. Returns multipliers that convert each field to percent.
    """
    spy = quotes.get("SPY") or {}
    mult = {"er": 1.0, "ytd": 1.0, "c1y": 1.0}
    er = spy.get("netExpenseRatio")
    if isinstance(er, (int, float)) and er < 0.01:
        mult["er"] = 100.0
    ytd = spy.get("ytdReturn")
    if isinstance(ytd, (int, float)) and spy_ytd_pct is not None:
        mult["ytd"] = 100.0 if abs(ytd * 100 - spy_ytd_pct) < abs(ytd - spy_ytd_pct) else 1.0
    c1y = spy.get("fiftyTwoWeekChangePercent")
    if isinstance(c1y, (int, float)) and abs(c1y) < 1 and spy_ytd_pct is not None and abs(spy_ytd_pct) > 5:
        mult["c1y"] = 100.0
    # Yield fields: fraction (0.012) or percent (1.2)? Anchor on SPY's ~1% yield
    # (from market.json when available).
    ref = spy_yield_pct if spy_yield_pct else 1.2
    for field in ("yield", "dividendYield", "trailingAnnualDividendYield"):
        v = spy.get(field)
        if isinstance(v, (int, float)) and v > 0:
            mult[field] = 100.0 if abs(v * 100 - ref) < abs(v - ref) else 1.0
        else:
            mult[field] = 100.0 if field != "dividendYield" else 1.0   # documented defaults
    return mult


def _r(x, nd=2):
    return round(x, nd) if isinstance(x, (int, float)) else None


def flags(name):
    f = ""
    if LEVERAGED.search(name or ""):
        f += "L"
    if ETN.search(name or ""):
        f += "N"
    if FUTURES.search(name or ""):
        f += "F"
    return f


def build_rows(listing, quotes, mult, screener=None):
    """Merge discovery + quotes (+ screener fallback) into compact rows."""
    screener = screener or {}
    rows = []
    for t, base in sorted(listing.items()):
        q = quotes.get(t) or {}
        s = screener.get(t) or {}
        name = q.get("longName") or base.get("n") or q.get("shortName") or s.get("n") or t
        er = q.get("netExpenseRatio")
        yld = pick_yield(q, mult)
        aum = q.get("netAssets")
        inc = q.get("fundInceptionDate") or (q.get("firstTradeDateMilliseconds") or 0) / 1000 or None
        price = q.get("regularMarketPrice") if q.get("regularMarketPrice") is not None else s.get("p")
        c1y = q.get("fiftyTwoWeekChangePercent")
        c1y = c1y * mult["c1y"] if isinstance(c1y, (int, float)) else s.get("c1y")
        ytd = q.get("ytdReturn")
        rows.append([
            t, name, base.get("x") or q.get("fullExchangeName") or "",
            _r(price),
            _r(c1y, 1),
            _r(ytd * mult["ytd"], 1) if isinstance(ytd, (int, float)) else None,
            round(aum / 1e6, 1) if isinstance(aum, (int, float)) and aum > 0 else None,
            _r(er * mult["er"], 2) if isinstance(er, (int, float)) and er > 0 else None,
            _r(yld, 2) if isinstance(yld, (int, float)) and 0 < yld < 100 else None,
            int(q["averageDailyVolume3Month"]) if isinstance(q.get("averageDailyVolume3Month"), (int, float)) else None,
            flags(name),
            dt.datetime.fromtimestamp(inc, dt.timezone.utc).date().isoformat() if isinstance(inc, (int, float)) and inc > 0 else None,
        ])
    return rows


def main(argv):
    dry = "--dry-run" in argv
    log("Discovering US-listed ETFs…")
    listing = discover_us()
    log(f"  {len(listing)} ETFs/ETPs found")
    if len(listing) < 500:
        log("Too few listings — keeping the existing universe file.")
        return 1
    yahoo = rm.Yahoo()
    quotes = {}
    try:
        quotes = fetch_quotes(yahoo, sorted(listing))
    except Exception as e:  # noqa: BLE001
        log(f"Yahoo quotes unavailable: {e}")
    log(f"  Yahoo quotes for {len(quotes)} tickers")
    screener = {}
    if len(quotes) < len(listing) * 0.8:
        try:
            screener = {r["t"]: r for r in screener_rows()}
            log(f"  Nasdaq screener fallback: {len(screener)} rows")
        except Exception as e:  # noqa: BLE001
            log(f"  Nasdaq screener unavailable: {e}")
    spy_ytd = spy_yld = None
    try:
        with open(os.path.join(DATA, "market.json"), encoding="utf-8") as fh:
            spy_m = json.load(fh)["tickers"]["SPY"]
        spy_ytd = rm._num(spy_m["performance"]["ytd"].replace("+", ""))
        spy_yld = rm._num(spy_m.get("yield_ttm", "").replace("%", "")) if spy_m.get("yield_ttm") else None
    except Exception:  # noqa: BLE001
        pass
    mult = calibrate(quotes, spy_ytd, spy_yld)
    rows = build_rows(listing, quotes, mult, screener)
    spy = next((r for r in rows if r[0] == "SPY"), None)
    log(f"  unit calibration {mult}; SPY row: {dict(zip(COLS, spy)) if spy else None} (market.json YTD {spy_ytd})")
    with_price = sum(1 for r in rows if r[3] is not None)
    log(f"  rows: {len(rows)}, with price {with_price}, with AUM {sum(1 for r in rows if r[6] is not None)}, "
        f"with expense ratio {sum(1 for r in rows if r[7] is not None)}")
    if dry:
        return 0
    if with_price < len(rows) * 0.5:
        log("Most rows lack prices — keeping the existing universe file.")
        return 1
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    doc = {"market": "US", "currency": "USD", "domicile": "US",
           "as_of": now[:10], "generated_at": now,
           "source": "Listings: NASDAQ Trader symbol directory (all US exchanges). Numbers: Yahoo Finance quotes "
                     "(1-yr = 52-week price change; YTD as reported by Yahoo), Nasdaq screener as fallback.",
           "count": len(rows), "cols": COLS, "rows": rows}
    path = os.path.join(DATA, "universe-us.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"), ensure_ascii=False)
    log(f"Wrote {os.path.relpath(path, rm.ROOT)} ({os.path.getsize(path) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
