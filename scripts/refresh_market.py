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
    YTD / 1-yr / 3-yr annualized / last two calendar-year returns
  * from the fund profile (best effort): AUM, expense ratio, trailing yield,
    top-10 holdings with weights, sector weights, fund family

Returns use dividend-adjusted closes (≈ total return, which matters a lot for
income funds). Sources are tried in order (Yahoo Finance → Stooq → Nasdaq);
the fallbacks are price-only. A source that keeps failing is switched off for
the rest of the run, and a ticker that fails everywhere keeps its previous
entry (flagged "stale"), so one bad day never blanks the site.

Zero dependencies (stdlib only).

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
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "public", "data")
OUT = os.path.join(DATA, "market.json")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
TRADING_DAYS_3M = 63
TRADING_DAYS_1Y = 252
HISTORY_DAYS = 5 * 366

# Fields that come from the fund profile; carried over from the previous run
# when today's profile fetch fails (they change slowly).
PROFILE_KEYS = ("aum_musd", "aum_display", "expense_ratio", "yield_ttm", "holdings",
                "top10_weight_pct", "sectors", "fund_family", "profile_asof")

SECTOR_LABELS = {
    "realestate": "Real estate", "consumer_cyclical": "Consumer cyclical",
    "basic_materials": "Materials", "consumer_defensive": "Consumer staples",
    "technology": "Technology", "communication_services": "Communication",
    "financial_services": "Financials", "utilities": "Utilities",
    "industrials": "Industrials", "energy": "Energy", "healthcare": "Health care",
}


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- helpers --
def theme_tickers(data_dir=DATA):
    """Every ticker referenced by any theme file (curated + roster), sorted."""
    out = set()
    for path in glob.glob(os.path.join(data_dir, "*.json")):
        if os.path.basename(path) == "market.json":
            continue
        with open(path, encoding="utf-8") as fh:
            theme = json.load(fh)
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


def _get(url, timeout=12, headers=None, opener=None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    op = opener.open if opener else urllib.request.urlopen
    with op(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ------------------------------------------------------- price-history sources --
def fetch_yahoo(ticker):
    """Daily bars for ~5 years from Yahoo's public chart endpoint (no key)."""
    last_err = None
    for host in YAHOO_HOSTS:
        url = (f"https://{host}/v8/finance/chart/{urllib.parse.quote(ticker)}"
               "?range=5y&interval=1d&includeAdjustedClose=true&events=div%2Csplit")
        for attempt in range(3):
            try:
                return parse_yahoo(json.loads(_get(url)))
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}"
                if e.code == 404:
                    raise LookupError(f"{ticker}: not found on Yahoo")
                if e.code == 429:                 # rate limited: back off, same host
                    time.sleep(2 * (attempt + 1))
                    continue
                break                             # other HTTP error: try next host
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                last_err = str(e)
                break                             # network/parse error: try next host
    raise RuntimeError(f"{ticker}: yahoo failed ({last_err})")


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
    # Exchange-local date: shift the UTC timestamp by the exchange's offset.
    off = meta.get("gmtoffset") or 0
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


def fetch_stooq(ticker):
    """Price-only fallback (daily CSV, no key)."""
    text = _get(f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d")
    return parse_stooq(text)


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


def fetch_nasdaq(ticker):
    """Second price-only fallback: Nasdaq's public quote-history JSON."""
    today = dt.date.today()
    url = (f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(ticker)}/historical?assetclass=etf"
           f"&fromdate={(today - dt.timedelta(days=HISTORY_DAYS)).isoformat()}"
           f"&todate={today.isoformat()}&limit=9999")
    text = _get(url, headers={"Accept": "application/json, text/plain, */*",
                              "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"})
    return parse_nasdaq(json.loads(text))


def _num(s):
    return float(str(s).replace("$", "").replace(",", "").strip())


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


SOURCE_LABEL = {
    "fetch_yahoo": "Yahoo Finance",
    "fetch_stooq": "Stooq (price-only fallback)",
    "fetch_nasdaq": "Nasdaq (price-only fallback)",
}


# ------------------------------------------------------------ fund profile --
class YahooProfile:
    """quoteSummary needs a cookie + 'crumb'; get them once per run."""

    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.crumb = None

    def _crumb(self):
        if self.crumb:
            return self.crumb
        try:
            _get("https://fc.yahoo.com", timeout=8, opener=self.opener)
        except Exception:  # noqa: BLE001 — a 404 here is normal; we only need the cookie
            pass
        c = _get("https://query1.finance.yahoo.com/v1/test/getcrumb", opener=self.opener).strip()
        if not c or "<" in c or " " in c or len(c) > 40:
            raise RuntimeError("no crumb")
        self.crumb = c
        return c

    def __call__(self, ticker):
        crumb = self._crumb()
        url = (f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(ticker)}"
               "?modules=topHoldings%2CfundProfile%2CsummaryDetail%2CdefaultKeyStatistics"
               f"&crumb={urllib.parse.quote(crumb)}")
        try:
            return parse_profile(json.loads(_get(url, opener=self.opener)))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise LookupError(f"{ticker}: no profile")
            raise


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
def refresh(tickers, sources=(fetch_yahoo, fetch_stooq, fetch_nasdaq), profile=None,
            pause=0.35, log=log, budget_s=600, trip_after=5):
    """Fetch every ticker, trying each price source in order, then the profile.

    Circuit breaker: a source that fails `trip_after` tickers in a row is
    switched off for the rest of the run, and the run stops after `budget_s`
    seconds — so a blocked/hanging source can't stall the deploy. Unknown
    tickers (LookupError) don't count as a source failure.
    """
    ok, failed = {}, {}
    streak = {src: 0 for src in sources}
    prof_streak, prof_ok = 0, 0
    today = dt.date.today().isoformat()
    deadline = time.monotonic() + budget_s
    for i, t in enumerate(tickers):
        live = [s for s in sources if streak[s] < trip_after]
        if not live or time.monotonic() > deadline:
            why = "all sources tripped" if not live else "time budget exhausted"
            for rest in tickers[i:]:
                failed[rest] = why
            log(f"Stopping early ({why}); {len(tickers) - i} tickers skipped.")
            break
        errs = []
        for src in live:
            try:
                raw = src(t)
                ok[t] = compute_metrics(raw["bars"], raw["returns_basis"], raw["meta"])
                ok[t]["source"] = SOURCE_LABEL.get(src.__name__, src.__name__)
                streak[src] = 0
                break
            except LookupError as e:      # unknown/delisted ticker — not a source outage
                errs.append(f"{src.__name__}: {e}")
            except Exception as e:  # noqa: BLE001 — any source failure falls through to the next
                errs.append(f"{src.__name__}: {e}")
                streak[src] += 1
        if t not in ok:
            failed[t] = "; ".join(errs)
        elif profile is not None and prof_streak < trip_after:
            try:
                ok[t].update(profile(t))
                ok[t]["profile_asof"] = today
                prof_streak, prof_ok = 0, prof_ok + 1
            except LookupError:
                pass
            except Exception as e:  # noqa: BLE001
                prof_streak += 1
                if prof_streak >= trip_after:
                    log(f"Fund-profile source switched off after {trip_after} straight failures ({e}).")
        log(f"[{i + 1}/{len(tickers)}] {t}: " + (
            f"ok {ok[t]['price_display']} via {ok[t]['source']}" + (" +profile" if "profile_asof" in ok[t] else "")
            if t in ok else "FAILED " + failed[t]))
        time.sleep(pause)
    if profile is not None:
        log(f"Fund profiles: {prof_ok}/{len(ok)}")
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
    for t in failed:
        if t in tickers:
            tickers[t]["stale"] = True
    if keep is not None:
        tickers = {t: e for t, e in tickers.items() if t in keep}
    dates = [e.get("price_asof") for t, e in tickers.items() if t in fresh and e.get("price_asof")]
    return {
        "as_of": max(dates) if dates else (previous or {}).get("as_of"),
        "generated_at": now_iso,
        "source": "Daily closes from Yahoo Finance (returns use dividend-adjusted closes; "
                  "Stooq/Nasdaq price-only fallbacks); fund profile (AUM, expense ratio, top-10 "
                  "holdings) from Yahoo Finance/Morningstar. Refreshed automatically by GitHub "
                  "Actions every weekday after the US close.",
        "count": len(tickers),
        "failed": sorted(t for t in failed if keep is None or t in keep),
        "tickers": dict(sorted(tickers.items())),
    }


def main(argv):
    dry = "--dry-run" in argv
    only = [a.upper() for a in argv if not a.startswith("-")]
    tickers = only or theme_tickers()
    log(f"Refreshing {len(tickers)} tickers…")
    fresh, failed = refresh(tickers, profile=YahooProfile())
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
