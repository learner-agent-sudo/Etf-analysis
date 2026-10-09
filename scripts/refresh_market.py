#!/usr/bin/env python3
"""
Daily market-data refresher — the static-hosting replacement for the old
serverless /api/etf endpoint.

GitHub Pages can only serve files, so instead of fetching prices from the
browser (which needs a server + API key), a scheduled GitHub Action runs this
script every weekday after the US close and publishes the result as
public/data/market.json. The site reads that file, so every fund — curated
cards AND full-universe roster tickers — shows fresh numbers without a server.

For every ticker found in public/data/<theme>.json (etfs[] + roster[]):
  * from daily price history: price, 3-month average daily volume (shares
    and $), 52-week range, % below the 52-week high, 1-year max drawdown,
    YTD / 1-yr / 3-yr annualized / last two calendar-year TOTAL returns
    (distributions reinvested — essential for income funds)
  * from the fund profile (Yahoo only, best effort): AUM, expense ratio,
    trailing yield, top-10 holdings with weights, sector weights

Sources, tried in order per ticker:
  1. Yahoo Finance — adjusted closes + fund profile. Yahoo answers plain
     Python HTTP clients from cloud IPs with "429 Too Many Requests", so when
     the optional `curl_cffi` package is installed (the workflow installs it)
     requests go out with a real browser's TLS fingerprint.
  2. Nasdaq — price history + dividend history (→ total return), with a
     cross-check against the live quote so a wrong instrument (e.g. the Dow
     index instead of the DJIA covered-call ETF) is rejected.
  3. Stooq — price-only last resort.
A source that keeps failing is switched off for the rest of the run, and a
ticker that fails everywhere keeps its previous entry (flagged "stale"), so
one bad day never blanks the site.

Usage:
    python3 scripts/refresh_market.py               # refresh everything
    python3 scripts/refresh_market.py QTUM UFO      # just these tickers (merged in)
    python3 scripts/refresh_market.py --dry-run     # fetch + print, don't write
"""
import csv
import datetime as dt
import glob
import http.cookiejar
import io
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

try:  # optional: browser-grade TLS fingerprint for Yahoo (pip install curl_cffi)
    from curl_cffi import requests as cffi_requests
except Exception:  # noqa: BLE001 — absent locally; the CI workflow installs it
    cffi_requests = None

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "public", "data")
OUT = os.path.join(DATA, "market.json")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TRADING_DAYS_3M = 63
TRADING_DAYS_1Y = 252
HISTORY_DAYS = 5 * 366

# Fields that come from the fund profile; carried over from the previous run
# when today's profile fetch fails (they change slowly).
PROFILE_KEYS = ("aum_musd", "aum_display", "expense_ratio", "yield_ttm", "holdings",
                "top10_weight_pct", "sectors", "fund_family", "profile_asof")

# Failure reasons that mean the old entry must not be kept as "stale".
DROP_ON = ("wrong instrument", "not listed")

SECTOR_LABELS = {
    "realestate": "Real estate", "consumer_cyclical": "Consumer cyclical",
    "basic_materials": "Materials", "consumer_defensive": "Consumer staples",
    "technology": "Technology", "communication_services": "Communication",
    "financial_services": "Financials", "utilities": "Utilities",
    "industrials": "Industrials", "energy": "Energy", "healthcare": "Health care",
}


def log(*a):
    print(*a, flush=True)


class HttpStatus(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


# ---------------------------------------------------------------- helpers --
def theme_tickers(data_dir=DATA):
    """Every ticker referenced by any theme file (curated + roster), sorted."""
    out = set()
    for path in glob.glob(os.path.join(data_dir, "*.json")):
        with open(path, encoding="utf-8") as fh:
            theme = json.load(fh)
        if "etfs" not in theme:          # market.json and other non-theme files
            continue
        for e in theme.get("etfs", []):
            out.add(e["ticker"].strip().upper())
        for r in theme.get("roster", []):
            out.add(r["ticker"].strip().upper())
    return sorted(out)


def fmt_pct(x, suffix="%"):
    if x is None:
        return None
    v = round(x * 100, 1)
    return f"{'+' if v > 0 else ''}{v}{suffix}"


def fmt_price(p):
    return None if p is None else f"${p:,.2f}"


def fmt_shares(n):
    if n is None:
        return None
    if n >= 1e6:
        return f"~{n / 1e6:.1f}M/day"
    if n >= 1e3:
        return f"~{round(n / 1e3)}K/day"
    return f"~{round(n)}/day"


def fmt_dollars(n, per_day=True):
    if n is None:
        return None
    tail = "/day" if per_day else ""
    if n >= 1e9:
        return f"~${n / 1e9:.1f}B{tail}"
    if n >= 1e6:
        return f"~${n / 1e6:.1f}M{tail}" if per_day else f"~${round(n / 1e6)}M"
    if n >= 1e3:
        return f"~${round(n / 1e3)}K{tail}"
    return f"~${round(n)}{tail}"


def _num(s):
    return float(str(s).replace("$", "").replace(",", "").strip())


def _get(url, timeout=15, headers=None, opener=None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    op = opener.open if opener else urllib.request.urlopen
    try:
        with op(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise HttpStatus(e.code) from None


# ------------------------------------------------------------------ Yahoo --
class Yahoo:
    """Chart (price history) + quoteSummary (fund profile) from Yahoo Finance.

    One HTTP session per worker thread; quoteSummary needs a cookie + 'crumb'.
    """
    HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")

    def __init__(self):
        self.local = threading.local()
        self.kind = "curl_cffi" if cffi_requests else "urllib"

    def _session(self):
        s = getattr(self.local, "s", None)
        if s is None:
            if cffi_requests:
                s = cffi_requests.Session(impersonate="chrome")
            else:
                s = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            self.local.s, self.local.crumb = s, None
        return s

    def get(self, url, timeout=15):
        s = self._session()
        if cffi_requests:
            r = s.get(url, timeout=timeout)
            if r.status_code >= 400:
                raise HttpStatus(r.status_code)
            return r.text
        return _get(url, timeout=timeout, opener=s)

    def chart(self, ticker):
        last = None
        for host in self.HOSTS:
            url = (f"https://{host}/v8/finance/chart/{urllib.parse.quote(ticker)}"
                   "?range=5y&interval=1d&includeAdjustedClose=true&events=div%2Csplit")
            try:
                return parse_yahoo(json.loads(self.get(url)))
            except HttpStatus as e:
                if e.code == 404:
                    raise LookupError(f"{ticker}: not found on Yahoo") from None
                if e.code == 429:            # throttled: retrying only digs deeper
                    raise RuntimeError("yahoo: HTTP 429 (rate limited)") from None
                last = e
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
                last = e
        raise RuntimeError(f"yahoo: {last}")

    def _crumb(self):
        self._session()
        if getattr(self.local, "crumb", None):
            return self.local.crumb
        try:
            self.get("https://fc.yahoo.com", timeout=8)
        except Exception:  # noqa: BLE001 — a 404 here is normal; we only need the cookie
            pass
        c = self.get("https://query1.finance.yahoo.com/v1/test/getcrumb").strip()
        if not c or "<" in c or " " in c or len(c) > 40:
            raise RuntimeError("yahoo: no crumb")
        self.local.crumb = c
        return c

    def profile(self, ticker):
        url = (f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(ticker)}"
               "?modules=topHoldings%2CfundProfile%2CsummaryDetail%2CdefaultKeyStatistics"
               f"&crumb={urllib.parse.quote(self._crumb())}")
        try:
            return parse_profile(json.loads(self.get(url)))
        except HttpStatus as e:
            if e.code == 404:
                raise LookupError(f"{ticker}: no profile") from None
            raise


def parse_yahoo(j):
    """Yahoo chart JSON -> {'bars': [(date, close, adjclose, volume)], 'meta': {...}}."""
    chart = (j or {}).get("chart") or {}
    if chart.get("error"):
        raise LookupError(str(chart["error"].get("description") or chart["error"]))
    res = (chart.get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise ValueError("empty chart result")
    meta = res.get("meta") or {}
    ts = res["timestamp"]
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    adj = (((res.get("indicators") or {}).get("adjclose") or [{}])[0]).get("adjclose")
    closes, vols = q.get("close") or [], q.get("volume") or []
    off = meta.get("gmtoffset") or 0             # exchange-local trading date
    bars = []
    for i, t in enumerate(ts):
        c = closes[i] if i < len(closes) else None
        if c is None:
            continue
        a = adj[i] if adj and i < len(adj) and adj[i] is not None else c
        v = vols[i] if i < len(vols) else None
        d = dt.datetime.fromtimestamp(t + off, dt.timezone.utc).date()
        bars.append((d, float(c), float(a), float(v) if v is not None else None))
    if not bars:
        raise ValueError("no usable bars")
    first_trade = meta.get("firstTradeDate")
    info = {
        "name": meta.get("longName") or meta.get("shortName"),
        "currency": meta.get("currency"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "instrument_type": meta.get("instrumentType"),
        "first_trade_date": (dt.datetime.fromtimestamp(first_trade, dt.timezone.utc).date().isoformat()
                             if isinstance(first_trade, (int, float)) else None),
        "regular_market_price": meta.get("regularMarketPrice"),
    }
    return {"bars": bars, "meta": info, "returns_basis": "total"}


def _raw(x):
    if isinstance(x, dict):
        x = x.get("raw")
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def parse_profile(j):
    """Yahoo quoteSummary JSON -> AUM / expense ratio / yield / top holdings / sectors."""
    qs = (j or {}).get("quoteSummary") or {}
    res = (qs.get("result") or [None])[0]
    if not res:
        raise LookupError(str((qs.get("error") or {}).get("description") or "no profile"))
    sd = res.get("summaryDetail") or {}
    ks = res.get("defaultKeyStatistics") or {}
    fp = res.get("fundProfile") or {}
    th = res.get("topHoldings") or {}
    out = {}

    aum = _raw(sd.get("totalAssets")) or _raw(ks.get("totalAssets"))
    if aum and aum > 0:
        out["aum_musd"] = round(aum / 1e6)
        out["aum_display"] = fmt_dollars(aum, per_day=False)

    er = (_raw((fp.get("feesExpensesInvestment") or {}).get("annualReportExpenseRatio"))
          or _raw(ks.get("annualReportExpenseRatio")) or _raw(sd.get("expenseRatio")))
    if er is not None and 0 < er < 0.05:          # Yahoo reports a fraction (0.0040 = 0.40%)
        out["expense_ratio"] = round(er * 100, 2)

    y = _raw(sd.get("yield"))
    if y is not None and 0 <= y < 1:
        out["yield_ttm"] = f"{round(y * 100, 2)}%"

    holds = []
    for h in th.get("holdings") or []:
        w = _raw(h.get("holdingPercent"))
        holds.append({"symbol": h.get("symbol") or "", "name": h.get("holdingName") or h.get("symbol") or "?",
                      "weight": round(w * 100, 2) if w is not None else None})
    if holds:
        out["holdings"] = holds
        ws = [h["weight"] for h in holds[:10] if h["weight"] is not None]
        if ws:
            out["top10_weight_pct"] = round(sum(ws), 1)

    secs = []
    for item in th.get("sectorWeightings") or []:
        for k, v in (item or {}).items():
            w = _raw(v)
            if w:
                secs.append({"sector": SECTOR_LABELS.get(k, k.replace("_", " ").title()),
                             "weight": round(w * 100, 1)})
    if secs:
        out["sectors"] = sorted(secs, key=lambda s: -s["weight"])

    if fp.get("family"):
        out["fund_family"] = fp["family"]
    if not out:
        raise ValueError("empty profile")
    return out


# ----------------------------------------------------------------- Nasdaq --
NASDAQ_HDR = {"Accept": "application/json, text/plain, */*",
              "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}


def _nasdaq(path):
    return json.loads(_get("https://api.nasdaq.com/api/quote/" + path, headers=NASDAQ_HDR, timeout=20))


def fetch_nasdaq(ticker, today=None):
    """Price history + dividends (→ total return) from Nasdaq's public quote API."""
    q = urllib.parse.quote(ticker)
    info = asset = None
    for ac in ("etf", "stocks"):                 # ETFs first; roster may include a stock (e.g. LLY)
        data = (_nasdaq(f"{q}/info?assetclass={ac}") or {}).get("data")
        if data:
            info, asset = data, ac
            break
    if not info:
        raise LookupError(f"{ticker}: not listed (closed, non-US or wrong ticker?)")
    today = today or dt.date.today()
    start = dt.date(today.year - 4, 12, 1)      # enough for 3-yr + two calendar years
    raw = parse_nasdaq(_nasdaq(f"{q}/historical?assetclass={asset}&fromdate={start.isoformat()}"
                               f"&todate={today.isoformat()}&limit=9999"))
    try:
        quote = _num((info.get("primaryData") or {}).get("lastSalePrice"))
    except (ValueError, TypeError):
        quote = None
    last = max(raw["bars"])[1]
    if quote and abs(last / quote - 1) > 0.25:
        raise ValueError(f"nasdaq: history close {last} doesn't match quote {quote} — wrong instrument")
    try:
        divs = parse_nasdaq_dividends(_nasdaq(f"{q}/dividends?assetclass={asset}"))
        raw["bars"] = apply_dividends(raw["bars"], divs)
        raw["returns_basis"] = "total"
    except Exception:  # noqa: BLE001 — keep price-only returns, clearly labelled
        pass
    raw["meta"] = {"name": info.get("companyName"), "exchange": info.get("exchange"),
                   "instrument_type": "ETF" if asset == "etf" else "Stock"}
    return raw


def parse_nasdaq(j):
    rows = ((((j or {}).get("data") or {}).get("tradesTable") or {}).get("rows")) or []
    bars = []
    for r in rows:
        try:
            m, d, y = r["date"].split("/")
            day = dt.date(int(y), int(m), int(d))
            c = _num(r["close"])
        except (KeyError, ValueError, AttributeError, TypeError):
            continue
        try:
            v = _num(r.get("volume"))
        except (ValueError, TypeError):
            v = None
        bars.append((day, c, c, v))
    if not bars:
        raise ValueError("nasdaq: no rows")
    return {"bars": bars, "meta": {}, "returns_basis": "price"}


def parse_nasdaq_dividends(j):
    data = (j or {}).get("data")
    if data is None:
        raise ValueError("nasdaq: no dividend data")
    out = []
    for r in ((data.get("dividends") or {}).get("rows")) or []:
        try:
            m, d, y = r["exOrEffDate"].split("/")
            amt = _num(r["amount"])
        except (KeyError, ValueError, AttributeError, TypeError):
            continue
        if amt > 0:
            out.append((dt.date(int(y), int(m), int(d)), amt))
    return out                                    # empty list = fund pays nothing


def apply_dividends(bars, divs):
    """Back-adjust closes for distributions (the standard 'adjusted close').

    For each ex-date, every earlier close is multiplied by (1 - amount / close
    of the day before the ex-date), so adjusted-close returns = total return
    with distributions reinvested. Future (declared, not yet ex) dividends are
    ignored.
    """
    bars = sorted(bars, key=lambda b: b[0])
    last_day = bars[-1][0]
    factors = []
    for ex, amt in sorted(divs):
        if ex > last_day:
            continue
        prev = None
        for b in bars:
            if b[0] < ex:
                prev = b
            else:
                break
        if prev and 0 < amt < prev[1]:
            factors.append((ex, 1 - amt / prev[1]))
    out, mult, j = [], 1.0, len(factors) - 1
    for b in reversed(bars):
        while j >= 0 and factors[j][0] > b[0]:
            mult *= factors[j][1]
            j -= 1
        out.append((b[0], b[1], b[1] * mult, b[3]))
    return out[::-1]


# ------------------------------------------------------------------ Stooq --
def fetch_stooq(ticker):
    """Price-only last resort (daily CSV, no key)."""
    return parse_stooq(_get(f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d"))


def parse_stooq(text):
    if not text.lstrip().lower().startswith("date"):
        raise ValueError("stooq: unexpected response")
    bars = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            d = dt.date.fromisoformat(row["Date"])
            c = float(row["Close"])
        except (KeyError, ValueError, TypeError):
            continue
        v = row.get("Volume")
        bars.append((d, c, c, float(v) if v not in (None, "", "0") else None))
    cutoff = dt.date.today() - dt.timedelta(days=HISTORY_DAYS)
    bars = [b for b in bars if b[0] >= cutoff]
    if not bars:
        raise ValueError("stooq: no rows")
    return {"bars": bars, "meta": {}, "returns_basis": "price"}


# ---------------------------------------------------------------- metrics --
def _value_on_or_before(bars, day, idx):
    """Value (column idx) of the last bar dated <= day, or None if history doesn't reach."""
    best = None
    for b in bars:
        if b[0] <= day:
            best = b
        else:
            break
    return best[idx] if best else None


def compute_metrics(bars, returns_basis="total", meta=None):
    """Pure function: daily bars -> the market.json entry for one ticker."""
    bars = sorted(bars, key=lambda b: b[0])
    first_day, last = bars[0][0], bars[-1]
    last_day, last_close, last_adj = last[0], last[1], last[2]
    meta = meta or {}
    price = meta.get("regular_market_price") or last_close
    A = 2  # adjusted-close column

    def ret_since(day):
        if first_day > day:
            return None              # fund didn't exist / history too short
        base = _value_on_or_before(bars, day, A)
        return None if not base else last_adj / base - 1

    def year_end(y):
        return _value_on_or_before(bars, dt.date(y, 12, 31), A)

    ytd = ret_since(dt.date(last_day.year - 1, 12, 31))   # since last close of prior year
    y1 = ret_since(last_day - dt.timedelta(days=365))
    y3 = ret_since(last_day - dt.timedelta(days=3 * 365 + 1))
    y3a = (1 + y3) ** (1 / 3) - 1 if y3 is not None and y3 > -1 else None

    # Two most recent COMPLETE calendar years (needs the prior year-end close).
    cal = {}
    for y in (last_day.year - 1, last_day.year - 2):
        if first_day <= dt.date(y - 1, 12, 31):
            start, end = year_end(y - 1), year_end(y)
            if start and end:
                cal[f"y{y}"] = fmt_pct(end / start - 1)

    tail3m = bars[-TRADING_DAYS_3M:]
    vols = [b[3] for b in tail3m if b[3] is not None]
    vol_avg = sum(vols) / len(vols) if vols else None
    dvol = [b[1] * b[3] for b in tail3m if b[3] is not None]
    dvol_avg = sum(dvol) / len(dvol) if dvol else None

    tail1y = bars[-TRADING_DAYS_1Y:]
    closes_1y = [b[1] for b in tail1y]
    hi, lo = max(closes_1y), min(closes_1y)
    peak, mdd = None, 0.0                          # max drawdown over the last year
    for b in tail1y:
        peak = b[2] if peak is None or b[2] > peak else peak
        mdd = min(mdd, b[2] / peak - 1)

    perf = {
        "ytd": fmt_pct(ytd),
        "y1": fmt_pct(y1),
        "y3_annualized": fmt_pct(y3a, "%/yr"),
        **cal,
        "as_of": last_day.isoformat(),
        "basis": ("total return (distributions reinvested)" if returns_basis == "total"
                  else "price return only (excludes distributions)"),
    }
    entry = {
        "price": round(price, 2),
        "price_display": fmt_price(price),
        "price_asof": last_day.isoformat(),
        "volume_avg": round(vol_avg) if vol_avg is not None else None,
        "volume_display": fmt_shares(vol_avg),
        "dollar_volume_avg": round(dvol_avg) if dvol_avg is not None else None,
        "dollar_volume_display": fmt_dollars(dvol_avg),
        "high_52w": round(hi, 2),
        "low_52w": round(lo, 2),
        "pct_below_high": fmt_pct(last_close / hi - 1) if hi else None,
        "max_drawdown_1y": fmt_pct(mdd),
        "history_start": first_day.isoformat(),
        "performance": perf,
    }
    for k in ("name", "exchange", "instrument_type", "first_trade_date"):
        if meta.get(k):
            entry[k] = meta[k]
    return entry


# ------------------------------------------------------------------- main --
def default_sources(yahoo):
    return [("Yahoo Finance", yahoo.chart), ("Nasdaq", fetch_nasdaq),
            ("Stooq (price-only)", fetch_stooq)]


def refresh(tickers, sources, profile=None, workers=4, pause=0.2, log=log,
            budget_s=600, trip_after=5):
    """Fetch every ticker (`workers` at a time), trying each price source in
    order, then the profile.

    `sources` is a list of (label, fetch_fn). Circuit breaker: a source that
    fails `trip_after` tickers in a row is switched off for the rest of the
    run, and the run stops after `budget_s` seconds — so a blocked/hanging
    source can't stall the deploy. Unknown tickers (LookupError) don't count.
    """
    lock = threading.Lock()
    streak = {label: 0 for label, _ in sources}
    prof = {"streak": 0, "ok": 0, "off_logged": False}
    today = dt.date.today().isoformat()
    deadline = time.monotonic() + budget_s

    def one(t):
        if time.monotonic() > deadline:
            return t, None, "time budget exhausted"
        with lock:
            live = [(lab, fn) for lab, fn in sources if streak[lab] < trip_after]
        if not live:
            return t, None, "all sources switched off"
        errs, entry = [], None
        for lab, fn in live:
            try:
                raw = fn(t)
                entry = compute_metrics(raw["bars"], raw["returns_basis"], raw["meta"])
                entry["source"] = lab
                with lock:
                    streak[lab] = 0
                break
            except LookupError as e:      # unknown/delisted ticker — not a source outage
                errs.append(f"{lab}: {e}")
            except Exception as e:  # noqa: BLE001 — any source failure falls through to the next
                errs.append(f"{lab}: {e}")
                with lock:
                    streak[lab] += 1
        if entry is not None and profile is not None:
            with lock:
                use = prof["streak"] < trip_after
            if use:
                try:
                    entry.update(profile(t))
                    entry["profile_asof"] = today
                    with lock:
                        prof["streak"], prof["ok"] = 0, prof["ok"] + 1
                except LookupError:
                    pass
                except Exception as e:  # noqa: BLE001
                    with lock:
                        prof["streak"] += 1
                        if prof["streak"] >= trip_after and not prof["off_logged"]:
                            prof["off_logged"] = True
                            log(f"Fund-profile source switched off after {trip_after} straight failures ({e}).")
        time.sleep(pause)
        return t, entry, "; ".join(errs)

    ok, failed = {}, {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for i, (t, entry, err) in enumerate(ex.map(one, tickers)):
            if entry is not None:
                ok[t] = entry
                log(f"[{i + 1}/{len(tickers)}] {t}: ok {entry['price_display']} via {entry['source']}"
                    + ("" if entry["performance"]["basis"].startswith("total") else " (price-only)")
                    + (" +profile" if "profile_asof" in entry else ""))
            else:
                failed[t] = err
                log(f"[{i + 1}/{len(tickers)}] {t}: FAILED {err}")
    if profile is not None:
        log(f"Fund profiles: {prof['ok']}/{len(ok)}")
    return ok, failed


def merge(previous, fresh, failed, now_iso, keep=None):
    """New data wins; failed tickers keep their last good entry (flagged stale).

    Profile fields missing from today's fetch are carried over from the
    previous entry. `keep` (a set) drops tickers no longer in any theme.
    """
    old = dict((previous or {}).get("tickers") or {})
    tickers = dict(old)
    for t, e in fresh.items():
        prev = old.get(t) or {}
        if "profile_asof" not in e:
            for k in PROFILE_KEYS:
                if k in prev:
                    e[k] = prev[k]
        tickers[t] = e
    for t, why in failed.items():
        if t not in tickers:
            continue
        if any(k in (why or "") for k in DROP_ON):   # previous value was wrong / fund is gone
            del tickers[t]
        else:
            tickers[t]["stale"] = True               # transient outage: keep last good value
    if keep is not None:
        tickers = {t: e for t, e in tickers.items() if t in keep}
    dates = [e.get("price_asof") for t, e in tickers.items() if t in fresh and e.get("price_asof")]
    return {
        "as_of": max(dates) if dates else (previous or {}).get("as_of"),
        "generated_at": now_iso,
        "source": "Daily closes from Yahoo Finance or Nasdaq (returns reinvest distributions); "
                  "fund profile (AUM, expense ratio, top-10 holdings) from Yahoo Finance/Morningstar "
                  "when available. Refreshed automatically by GitHub Actions every weekday after the US close.",
        "count": len(tickers),
        "failed": {t: failed[t] for t in sorted(failed) if keep is None or t in keep},
        "tickers": dict(sorted(tickers.items())),
    }


def main(argv):
    dry = "--dry-run" in argv
    only = [a.upper() for a in argv if not a.startswith("-")]
    tickers = only or theme_tickers()
    yahoo = Yahoo()
    log(f"Refreshing {len(tickers)} tickers (Yahoo via {yahoo.kind})…")
    fresh, failed = refresh(tickers, default_sources(yahoo), profile=yahoo.profile)
    previous = None
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as fh:
            previous = json.load(fh)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    doc = merge(previous, fresh, failed, now, keep=None if only else set(tickers))
    by_src = {}
    for e in fresh.values():
        by_src[e["source"]] = by_src.get(e["source"], 0) + 1
    log(f"\n{len(fresh)} ok {by_src}, {len(failed)} failed" + (f": {', '.join(sorted(failed))}" if failed else ""))
    if dry:
        log(json.dumps({t: doc["tickers"][t] for t in list(fresh)[:2]}, indent=1))
        return 0 if fresh else 1
    if not fresh:
        log("No data fetched — keeping the existing market.json untouched.")
        return 1
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    log(f"Wrote {os.path.relpath(OUT, ROOT)}")
    # Fail the step (the workflow uses continue-on-error, so the deploy still
    # happens) when most tickers failed, so a blocked source shows in Actions.
    return 0 if len(fresh) >= len(tickers) / 2 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
