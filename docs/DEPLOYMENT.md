# Deployment — free hosting on GitHub Pages

The site is **static** (`public/` — HTML/CSS/JS + JSON data), so it hosts free
on **GitHub Pages**: no server, no account beyond GitHub, no usage limits that
matter for a page like this.

Live at **https://learner-agent-sudo.github.io/Etf-analysis/**

## How it stays up to date — no server needed

One GitHub Actions workflow (`.github/workflows/pages.yml`) does everything:

| When | What happens |
|---|---|
| Every weekday ~21:41 UTC (after the US close) | `scripts/refresh_market.py` fetches price, volume, returns, AUM and top holdings for **every** ticker in `public/data/*.json` (curated + full-universe roster), writes `public/data/market.json`, commits it, and redeploys the site |
| Same run | `scripts/build_universe.py` lists **every** ETF on three markets — US (NASDAQ Trader symbol directory, all exchanges), Hong Kong (HKEX List of Securities, with ISIN-based domicile) and London (Yahoo screener; international-order-book duplicates dropped) — with Yahoo batch quotes (price, 52-week change, YTD, AUM, expense ratio, yield, volume) into `public/data/universe-{us,hk,lse}.json` for the Explorer tab. Each market builds independently and keeps yesterday's file if its source fails |
| Every push that touches `public/`, `scripts/` or the workflow | same refresh + redeploy, so analysis changes go live within ~5 minutes |
| On demand | **Actions** tab → "Deploy to GitHub Pages" → **Run workflow** |

The page reads `market.json` on load, so fresh numbers replace the dated
hand-researched snapshot automatically (snapshot values show faded until fresh
data exists). The **↻ check for update** button re-loads that file; the
**Live quote** link in each memo opens an intraday quote for the fund.

### Data sources (no API keys)

1. **Yahoo Finance** — dividend-adjusted closes (total return) + fund profile
   (AUM, expense ratio, top-10 holdings, sectors). Yahoo throttles plain Python
   clients from cloud servers, so the workflow installs `curl_cffi`, which sends
   requests with a real browser's TLS fingerprint.
2. **Nasdaq** — price history + dividend history, combined into total returns.
   Each history is cross-checked against the live quote, so a wrong instrument
   (e.g. the Dow index instead of the DJIA covered-call ETF) is rejected.
3. **Stooq** — price-only last resort.

A source that keeps failing is switched off for that run; a ticker that fails
everywhere keeps yesterday's value (marked stale), and a ticker that turns out
to be closed/non-US is dropped and flagged "⚠ no data" in the roster. If every
source is down, the site still deploys with the last good `market.json`.

## One-time setup (already done)

Repo → **Settings** → **Pages** → **Build and deployment → Source: GitHub
Actions**. Nothing else to configure — no secrets, no API keys.

## Local preview

```bash
python3 app/server.py                     # http://127.0.0.1:8000
python3 scripts/refresh_market.py --dry-run QTUM   # try the fetcher (needs internet)
python3 -m unittest discover -s tests     # offline tests for the return maths
```
Zero dependencies (Python stdlib; `curl_cffi` is optional).

## History: why not Vercel any more

The site started on Vercel with a serverless function (`api/etf.js`, Alpha
Vantage) for live refresh. The Vercel account hit its usage limit and was
paused, so the site moved to GitHub Pages and the serverless function was
replaced by the scheduled data refresh above (more data, no key, no limits).
The old Vercel files were removed; they remain in git history.
