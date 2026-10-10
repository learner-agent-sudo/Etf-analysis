#!/usr/bin/env python3
"""
Build the Explorer universe: every ETF listed on a market, with daily numbers.

Writes public/data/universe-<market>.json (us, hk, lse), which the site's
Explorer loads on demand. Runs in the daily GitHub Action after
refresh_market.py. Each market is built independently: if one source fails,
the others still update and the failed market keeps its previous file.

Discovery (which ETFs exist):
  US     NASDAQ Trader symbol directory — every US-listed security with an ETF
         flag (Nasdaq, NYSE, NYSE Arca, Cboe, IEX). Fallback: Nasdaq screener.
  HK     HKEX "List of Securities" spreadsheet — category "Exchange Traded
         Products" (ETFs + leveraged & inverse products), with ISINs, so the
         real domicile is known. Fallback: Yahoo screener (exchange HKG).
  London Yahoo screener (exchange LSE, quote type ETF).
Numbers: Yahoo Finance batch quotes, ~100 tickers per request — price,
52-week change, YTD, AUM, expense ratio, yield, volume, inception.

Prices stay in their trading currency (London pence are converted to pounds);
AUM is also converted to US$ with the day's FX rates so funds compare across
markets. Yahoo's quote fields come in mixed units, so they are calibrated
against SPY (and the YTD/yield already computed for SPY in market.json); the
calibration and a few anchor funds per market are logged.

Usage:
    python3 scripts/build_universe.py                 # all markets
    python3 scripts/build_universe.py us hk           # only these
    python3 scripts/build_universe.py --dry-run       # fetch + summarise only
"""
import datetime as dt
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refresh_market as rm  # noqa: E402  (shared HTTP + Yahoo session helpers)

DATA = rm.DATA
NASDAQ_DIR = ("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
              "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt")
HKEX_LIST = "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
EXCHANGE = {"Q": "Nasdaq", "N": "NYSE", "P": "NYSE Arca", "A": "NYSE American",
            "Z": "Cboe BZX", "V": "IEX"}
QUOTE_FIELDS = ("longName,shortName,quoteType,currency,fullExchangeName,regularMarketPrice,"
                "regularMarketTime,fiftyTwoWeekLow,fiftyTwoWeekHigh,fiftyTwoWeekChangePercent,"
                "ytdReturn,netAssets,netExpenseRatio,trailingAnnualDividendYield,dividendYield,yield,"
                "averageDailyVolume3Month,fundInceptionDate,firstTradeDateMilliseconds")
BATCH = 100
COLS = ["t", "n", "x", "p", "c1y", "ytd", "aum", "er", "yld", "vol", "f", "inc", "cur", "dom", "aumu", "acur"]
FX_FALLBACK = {"USD": 1.0, "GBP": 1.30, "EUR": 1.10, "HKD": 0.128, "CHF": 1.15, "JPY": 0.0068,
               "SEK": 0.095, "NOK": 0.093, "DKK": 0.15, "CAD": 0.73, "AUD": 0.66}
# flags (f): L = leveraged/inverse, N = exchange-traded note, F = futures-based commodity/VIX
LEVERAGED = re.compile(r"(?<![\w.])-?[1-9](\.\d+)?x\b|\bultra(pro)?(short)?\b|\bleveraged\b|\binverse\b"
                       r"|\bbear\b|\bdaily\b.*\bbull\b|^proshares short\b", re.I)
ETN = re.compile(r"\bETNs?\b|exchange traded notes?", re.I)
FUTURES = re.compile(r"\bfutures\b|\bvix\b|^united states (oil|natural gas|gasoline|brent|12 month)", re.I)


def log(*a):
    print(*a, flush=True)


def clean_name(name):
    """'iShares Gold Trust Shares' / 'SPDR ... ETF Trust' -> tidy display name."""
    name = re.sub(r"\s+", " ", name or "").strip()
    return re.sub(r"\s+(Shares|Common Shares( of Beneficial Interest)?|Units|ETF Shares)$", "", name)


def flags(name):
    f = ""
    if LEVERAGED.search(name or ""):
        f += "L"
    if ETN.search(name or ""):
        f += "N"
    if FUTURES.search(name or ""):
        f += "F"
    return f


def _bytes(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": rm.UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ----------------------------------------------------------------- US discovery --
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
                    "x": EXCHANGE.get(exch, "")})
    return out


def discover_us(yahoo=None):
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
        log(f"  symbol directory gave {len(found)} ETFs — trying the Nasdaq screener")
        for r in screener_rows():
            found.setdefault(r["t"], {"t": r["t"], "n": r["n"], "x": ""})
    for r in found.values():
        r["dom"] = "US"
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


# ----------------------------------------------------------------- HK discovery --
XL_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def read_xlsx(blob):
    """Minimal .xlsx reader (stdlib): first worksheet -> list of {column letter: text}."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(XL_NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(XL_NS + "t")))
    sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    rows = []
    for row in ET.fromstring(z.read(sheets[0])).iter(XL_NS + "row"):
        vals = {}
        for c in row.findall(XL_NS + "c"):
            col = re.match(r"[A-Z]+", c.get("r", "")).group(0)
            v = c.find(XL_NS + "v")
            if c.get("t") == "s" and v is not None:
                vals[col] = shared[int(v.text)]
            elif c.get("t") == "inlineStr":
                vals[col] = "".join(x.text or "" for x in c.iter(XL_NS + "t"))
            else:
                vals[col] = v.text if v is not None else None
        rows.append(vals)
    return rows


def parse_hkex(rows):
    """HKEX List of Securities -> {yahoo symbol: {t, n, x, dom, isin, f}} for ETPs.

    Keeps the HKD counter of each product (5-digit 8xxxx RMB and 9xxxx USD
    counters are the same fund in another currency).
    """
    head_i = next(i for i, r in enumerate(rows) if any((v or "").strip() == "Stock Code" for v in r.values()))
    cols = {(v or "").strip(): k for k, v in rows[head_i].items()}
    get = lambda r, name: (r.get(cols.get(name, "")) or "").strip()  # noqa: E731
    out = {}
    for r in rows[head_i + 1:]:
        if get(r, "Category") != "Exchange Traded Products":
            continue
        try:
            code = int(float(get(r, "Stock Code")))
        except ValueError:
            continue
        if code >= 80000:                         # RMB / USD counters of the same product
            continue
        sym = f"{code:04d}.HK"
        isin = get(r, "ISIN")
        sub = get(r, "Sub-Category")
        out[sym] = {"t": sym, "n": clean_name(get(r, "Name of Securities")), "x": "HKEX",
                    "dom": isin[:2] if re.match(r"^[A-Z]{2}", isin) else "HK", "isin": isin,
                    "f": "L" if "leveraged" in sub.lower() or "inverse" in sub.lower() else ""}
    return out


def discover_hk(yahoo):
    try:
        found = parse_hkex(read_xlsx(_bytes(HKEX_LIST)))
        if len(found) >= 50:
            return found
        log(f"  HKEX list gave only {len(found)} products")
    except Exception as e:  # noqa: BLE001
        log(f"  HKEX list unavailable: {e}")
    found = discover_screener(yahoo, "HKG", "HKEX")
    for r in found.values():
        r["dom"] = "HK"
    return found


# ------------------------------------------------------ Yahoo screener discovery --
def discover_screener(yahoo, exchange, label, max_rows=8000):
    """All ETFs on one exchange via Yahoo's screener -> {symbol: {t, n, x, q}}."""
    out, offset, total = {}, 0, None
    sort_fields = ["fundnetassets", "intradayprice", "ticker"]
    while offset < max_rows:
        res = None
        for sf in list(sort_fields):
            body = {"offset": offset, "size": 250, "sortField": sf, "sortType": "DESC", "quoteType": "ETF",
                    "query": {"operator": "AND", "operands": [{"operator": "EQ", "operands": ["exchange", exchange]}]},
                    "userId": "", "userIdType": "guid"}
            url = ("https://query1.finance.yahoo.com/v1/finance/screener?formatted=false&lang=en-US&region=US"
                   f"&crumb={urllib.parse.quote(yahoo._crumb())}")
            try:
                j = json.loads(yahoo.post_json(url, body))
                res = (((j.get("finance") or {}).get("result")) or [None])[0]
                if res is not None:
                    sort_fields = [sf]
                    break
            except Exception as e:  # noqa: BLE001
                log(f"  screener {exchange} sort={sf} offset={offset}: {e}")
        if not res:
            break
        quotes = res.get("quotes") or []
        total = res.get("total") or total or 0
        for q in quotes:
            sym = q.get("symbol")
            if sym:
                out[sym] = {"t": sym, "n": clean_name(q.get("longName") or q.get("shortName") or sym), "x": label, "q": q}
        offset += len(quotes)
        if not quotes or (total and offset >= total):
            break
    log(f"  Yahoo screener {exchange}: {len(out)} ETFs (reported total {total})")
    return out


IOB_CODE = re.compile(r"^0[A-Z0-9]{3}\.L$")


def discover_lse(yahoo):
    found = discover_screener(yahoo, "LSE", "London")
    # Drop International Order Book lines (codes like 0LOS.L): secondary quotes of
    # funds whose primary listing is elsewhere (US ETFs, or the same UCITS fund's
    # main London ticker) — they would only duplicate rows.
    iob = [t for t in found if IOB_CODE.match(t)]
    for t in iob:
        del found[t]
    log(f"  dropped {len(iob)} international-order-book duplicates")
    for r in found.values():
        # Name-based domicile: UCITS funds on London are Irish or Luxembourg
        # funds; other London ETPs (mostly commodity ETCs/notes from Jersey or
        # Ireland) are left unknown rather than guessed.
        r["dom"] = "IE/LU" if "UCITS" in (r["n"] or "").upper() else ""
    return found


# ------------------------------------------------------------------- numbers --
def yahoo_symbol(t):
    if re.search(r"\.(L|HK)$", t):
        return t
    return t.replace(".", "-").replace("/", "-")


def fetch_quotes(yahoo, tickers, workers=4):
    """Batch quotes from Yahoo -> {ticker: raw quote dict}."""
    batches = [tickers[i:i + BATCH] for i in range(0, len(tickers), BATCH)]
    back = {yahoo_symbol(t): t for t in tickers}

    def one(batch):
        syms = ",".join(yahoo_symbol(t) for t in batch)
        err = None
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


def fx_rates(yahoo):
    """USD value of one unit of each currency (Yahoo FX quotes; fallback constants)."""
    rates = dict(FX_FALLBACK)
    try:
        q = fetch_quotes(yahoo, [f"{c}USD=X" for c in FX_FALLBACK if c != "USD"])
        for k, v in q.items():
            p = v.get("regularMarketPrice")
            if isinstance(p, (int, float)) and p > 0:
                rates[k[:3]] = p
    except Exception as e:  # noqa: BLE001
        log(f"  FX quotes unavailable ({e}); using fallback rates")
    return rates


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
    YTD and yield are cross-checked against market.json. Returns multipliers
    that convert each field to percent.
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


NAME_CUR = re.compile(r"\b(JPY|EUR|CHF|GBP|USD|SEK|NOK|DKK|CAD|AUD)\b")


def aum_currency(name):
    """London share classes named with a currency ('... Class JPY (Acc)',
    '... EUR (Dist)') report AUM in that currency; otherwise the fund's base
    currency, which for London UCITS is almost always USD."""
    m = NAME_CUR.search(name or "")
    return m.group(1) if m else "USD"


def build_rows(listing, quotes, mult, screener=None, fx=None, default_cur="USD", aum_in_usd=False):
    """Merge discovery + quotes (+ screener fallback) into compact rows (COLS).

    `aum_in_usd`: Yahoo reports a fund's netAssets in its BASE currency. For
    London UCITS that is almost always USD (checked: VUSA.L's figure matches
    the whole fund in USD, not the £ trading line), so London AUM is taken as
    USD; HK funds report in HKD; US funds in USD.
    """
    screener, fx = screener or {}, fx or FX_FALLBACK
    rows = []
    for t, base in sorted(listing.items()):
        q = quotes.get(t) or base.get("q") or {}
        s = screener.get(t) or {}
        name = q.get("longName") or base.get("n") or q.get("shortName") or s.get("n") or t
        cur = q.get("currency") or default_cur
        scale = 0.01 if cur in ("GBp", "GBX") else 1.0       # London pence -> pounds
        cur = "GBP" if cur in ("GBp", "GBX") else cur
        er = q.get("netExpenseRatio")
        yld = pick_yield(q, mult)
        aum = q.get("netAssets")
        aum_m = round(aum / 1e6, 1) if isinstance(aum, (int, float)) and aum > 0 else None
        inc = q.get("fundInceptionDate") or (q.get("firstTradeDateMilliseconds") or 0) / 1000 or None
        price = q.get("regularMarketPrice")
        price = price * scale if isinstance(price, (int, float)) else s.get("p")
        c1y = q.get("fiftyTwoWeekChangePercent")
        c1y = c1y * mult["c1y"] if isinstance(c1y, (int, float)) else s.get("c1y")
        ytd = q.get("ytdReturn")
        acur = aum_currency(name) if aum_in_usd else cur
        rate = fx.get(acur)
        rows.append([
            t, name, base.get("x") or q.get("fullExchangeName") or "",
            _r(price),
            _r(c1y, 1),
            _r(ytd * mult["ytd"], 1) if isinstance(ytd, (int, float)) else None,
            aum_m,
            _r(er * mult["er"], 2) if isinstance(er, (int, float)) and er > 0 else None,
            _r(yld, 2) if isinstance(yld, (int, float)) and 0 < yld < 100 else None,
            int(q["averageDailyVolume3Month"]) if isinstance(q.get("averageDailyVolume3Month"), (int, float)) else None,
            "".join(sorted(set(flags(name) + base.get("f", "")))),
            dt.datetime.fromtimestamp(inc, dt.timezone.utc).date().isoformat() if isinstance(inc, (int, float)) and inc > 0 else None,
            cur,
            base.get("dom") or "",
            round(aum_m * rate, 1) if aum_m is not None and rate else None,
            acur,
        ])
    return rows


MARKETS = {
    "us": {"label": "US", "discover": discover_us, "min": 1000, "cur": "USD",
           "anchors": ["SPY", "QQQ", "JEPI"]},
    "hk": {"label": "Hong Kong", "discover": discover_hk, "min": 50, "cur": "HKD",
           "anchors": ["2800.HK", "3067.HK", "2833.HK"]},
    "lse": {"label": "London", "discover": discover_lse, "min": 200, "cur": "GBP", "aum_in_usd": True,
            "anchors": ["CSPX.L", "VUSA.L", "URNU.L"]},
}
SOURCES = {
    "us": "Listings: NASDAQ Trader symbol directory (all US exchanges).",
    "hk": "Listings: HKEX List of Securities (Exchange Traded Products; HKD counters).",
    "lse": "Listings: Yahoo Finance screener (London Stock Exchange ETFs).",
}


def build_market(key, yahoo, mult, fx, dry):
    m = MARKETS[key]
    log(f"\n== {m['label']} ==")
    listing = m["discover"](yahoo)
    log(f"  {len(listing)} listings")
    if len(listing) < m["min"]:
        log(f"  too few listings — keeping the existing {key} file")
        return False
    need = sorted(t for t, r in listing.items() if not r.get("q"))
    quotes = fetch_quotes(yahoo, need) if need else {}
    log(f"  Yahoo quotes for {len(quotes)}/{len(need)} tickers needing them")
    screener = {}
    if key == "us" and len(quotes) < len(listing) * 0.8:
        try:
            screener = {r["t"]: r for r in screener_rows()}
            log(f"  Nasdaq screener fallback: {len(screener)} rows")
        except Exception as e:  # noqa: BLE001
            log(f"  Nasdaq screener unavailable: {e}")
    rows = build_rows(listing, quotes, mult, screener, fx, m["cur"], m.get("aum_in_usd", False))
    for a in m["anchors"]:
        r = next((x for x in rows if x[0] == a), None)
        log(f"  anchor {a}: {dict(zip(COLS, r)) if r else 'not listed'}")
    with_price = sum(1 for r in rows if r[3] is not None)
    log(f"  rows {len(rows)}, with price {with_price}, AUM {sum(1 for r in rows if r[6] is not None)}, "
        f"expense {sum(1 for r in rows if r[7] is not None)}, yield {sum(1 for r in rows if r[8] is not None)}")
    if dry:
        return True
    if with_price < len(rows) * 0.5:
        log("  most rows lack prices — keeping the existing file")
        return False
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    doc = {"market": key.upper(), "label": m["label"], "currency": m["cur"],
           "as_of": now[:10], "generated_at": now, "fx_usd": fx,
           "source": SOURCES[key] + " Numbers: Yahoo Finance quotes (1-yr = 52-week price change; YTD as "
                     "reported by Yahoo). AUM also shown in US$ at the day's FX rate.",
           "count": len(rows), "cols": COLS, "rows": rows}
    path = os.path.join(DATA, f"universe-{key}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"), ensure_ascii=False)
    log(f"  wrote {os.path.relpath(path, rm.ROOT)} ({os.path.getsize(path) // 1024} KB)")
    return True


def main(argv):
    dry = "--dry-run" in argv
    keys = [a.lower() for a in argv if not a.startswith("-")] or list(MARKETS)
    yahoo = rm.Yahoo()
    spy_ytd = spy_yld = None
    try:
        with open(os.path.join(DATA, "market.json"), encoding="utf-8") as fh:
            spy_m = json.load(fh)["tickers"]["SPY"]
        spy_ytd = rm._num(spy_m["performance"]["ytd"].replace("+", ""))
        spy_yld = rm._num(spy_m["yield_ttm"].replace("%", "")) if spy_m.get("yield_ttm") else None
    except Exception:  # noqa: BLE001
        pass
    mult = calibrate(fetch_quotes(yahoo, ["SPY"]), spy_ytd, spy_yld)
    fx = fx_rates(yahoo)
    log(f"unit calibration {mult} (market.json SPY YTD {spy_ytd}, yield {spy_yld}); FX to USD {fx}")
    ok = 0
    for k in keys:
        try:
            ok += build_market(k, yahoo, mult, fx, dry)
        except Exception as e:  # noqa: BLE001 — one market failing must not stop the others
            log(f"  {k} failed: {e}")
    return 0 if ok == len(keys) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
