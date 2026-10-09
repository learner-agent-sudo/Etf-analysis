#!/usr/bin/env python3
"""
Daily market-data refresher — the static-hosting replacement for the old
serverless /api/etf endpoint.

GitHub Pages can only serve files, so instead of fetching prices from the
browser (which needs a server + API key), a scheduled GitHub Action runs this
script every weekday after the US close and publishes the result as
public/data/market.json. The site reads that file, so every fund — curated
cards AND full-universe roster tickers — shows a fresh price, average volume
and trailing returns without any server.

For every ticker found in public/data/<theme>.json (etfs[] + roster[]):
    price, 3-month average daily volume (shares and $), 52-week range,
    % below the 52-week high, 1-year max drawdown,
    YTD / 1-yr / 3-yr annualized / last two calendar-year total returns.

Returns use dividend-adjusted closes (≈ total return, which matters a lot for
income funds). If the primary source fails for a ticker, a price-only
fallback is tried, and if that fails too the ticker keeps its previous entry
(so one bad day never blanks the site).

Zero dependencies (stdlib only).

Usage:
    python3 scripts/refresh_market.py               # refresh everything
    python3 scripts/refresh_market.py QTUM UFO      # just these tickers (merged in)
    python3 scripts/refresh_market.py --dry-run     # fetch + print, don't write
"""
import csv
import datetime as dt
import glob
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "public", "data")
OUT = os.path.join(DATA, "market.json")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
TRADING_DAYS_3M = 63
TRADING_DAYS_1Y = 252


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


def fmt_dollars(n):
    if n is None:
        return None
    if n >= 1e9:
        return f"~${n / 1e9:.1f}B/day"
    if n >= 1e6:
        return f"~${n / 1e6:.1f}M/day"
    if n >= 1e3:
        return f"~${round(n / 1e3)}K/day"
    return f"~${round(n)}/day"


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- sources --
def fetch_yahoo(ticker):
    """Daily bars for ~5 years from Yahoo's public chart endpoint (no key)."""
    last_err = None
    for host in YAHOO_HOSTS:
        url = (f"https://{host}/v8/finance/chart/{ticker}"
               "?range=5y&interval=1d&includeAdjustedClose=true&events=div%2Csplit")
        for attempt in range(3):
            try:
                return parse_yahoo(json.loads(_get(url)))
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}"
                if e.code == 404:
                    raise LookupError(f"{ticker}: not found on Yahoo")
                if e.code == 429:
                    time.sleep(2 * (attempt + 1))
                    continue
                break
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                last_err = str(e)
                time.sleep(1)
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
    """Price-only fallback (daily CSV, no key). Returns are price returns."""
    url = f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d"
    text = _get(url)
    if not text.lstrip().lower().startswith("date"):
        raise ValueError("stooq: unexpected response")
    bars = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            d = dt.date.fromisoformat(row["Date"])
            c = float(row["Close"])
        except (KeyError, ValueError):
            continue
        v = row.get("Volume")
        bars.append((d, c, c, float(v) if v not in (None, "", "0") else None))
    cutoff = dt.date.today() - dt.timedelta(days=5 * 366)
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

    # YTD: since the last close of the previous year.
    prev_ye = dt.date(last_day.year - 1, 12, 31)
    ytd = ret_since(prev_ye)

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
    # Max drawdown over the last year (on adjusted closes).
    peak, mdd = None, 0.0
    for b in tail1y:
        peak = b[2] if peak is None or b[2] > peak else peak
        mdd = min(mdd, b[2] / peak - 1)

    perf = {
        "ytd": fmt_pct(ytd),
        "y1": fmt_pct(y1),
        "y3_annualized": fmt_pct(y3a, "%/yr"),
        **cal,
        "as_of": last_day.isoformat(),
        "basis": "total return (dividends reinvested)" if returns_basis == "total" else "price return (excludes dividends)",
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
def refresh(tickers, sources=(fetch_yahoo, fetch_stooq), pause=0.35, log=print):
    ok, failed = {}, {}
    for i, t in enumerate(tickers):
        errs = []
        for src in sources:
            try:
                raw = src(t)
                ok[t] = compute_metrics(raw["bars"], raw["returns_basis"], raw["meta"])
                ok[t]["source"] = "Yahoo Finance" if src is fetch_yahoo else "Stooq (price-only fallback)"
                break
            except Exception as e:  # noqa: BLE001 — any source failure falls through to the next
                errs.append(f"{src.__name__}: {e}")
        if t not in ok:
            failed[t] = "; ".join(errs)
        log(f"[{i + 1}/{len(tickers)}] {t}: " + ("ok " + ok[t]["price_display"] if t in ok else "FAILED " + failed[t]))
        time.sleep(pause)
    return ok, failed


def merge(previous, fresh, failed, now_iso):
    """New data wins; failed tickers keep their last good entry (flagged stale)."""
    tickers = dict((previous or {}).get("tickers") or {})
    for t, e in fresh.items():
        tickers[t] = e
    for t in failed:
        if t in tickers:
            tickers[t]["stale"] = True
    dates = [e.get("price_asof") for t, e in tickers.items() if t in fresh and e.get("price_asof")]
    return {
        "as_of": max(dates) if dates else (previous or {}).get("as_of"),
        "generated_at": now_iso,
        "source": "Yahoo Finance daily chart data (returns use dividend-adjusted closes); "
                  "refreshed automatically by GitHub Actions every weekday after the US close.",
        "count": len(tickers),
        "failed": sorted(failed),
        "tickers": dict(sorted(tickers.items())),
    }


def main(argv):
    dry = "--dry-run" in argv
    only = [a.upper() for a in argv if not a.startswith("-")]
    tickers = only or theme_tickers()
    print(f"Refreshing {len(tickers)} tickers…")
    fresh, failed = refresh(tickers)
    previous = None
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as fh:
            previous = json.load(fh)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    doc = merge(previous, fresh, failed, now)
    print(f"\n{len(fresh)} ok, {len(failed)} failed" + (f": {', '.join(sorted(failed))}" if failed else ""))
    if dry:
        print(json.dumps({t: doc["tickers"][t] for t in list(fresh)[:3]}, indent=1))
        return 0 if fresh else 1
    if not fresh:
        print("No data fetched — keeping the existing market.json untouched.")
        return 1
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote {os.path.relpath(OUT, ROOT)}")
    # Fail the step (but not the deploy — the workflow uses continue-on-error)
    # when most tickers failed, so a blocked source is visible in the Actions tab.
    return 0 if len(fresh) >= len(tickers) / 2 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
