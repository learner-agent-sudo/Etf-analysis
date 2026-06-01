# ETF Analysis — web app

A **hosted, mobile-friendly web app** for side-by-side ETF comparison with deep
memos, plus **live data refresh**. Designed to be deployed to **Vercel** so you
get a public URL that opens on any device — no install, no download.

## Two layers (this is the key idea)

1. **Curated analysis (static)** — `public/data/*.json`. The judgment calls that
   no API can make: theme-purity ratings, red flags, bull/bear, decision logs,
   scored dimensions. Always available, works offline, version-controlled.
2. **Live hard facts (dynamic)** — `api/etf.js`, a Vercel serverless function.
   Pulls current expense ratio, AUM, holdings, sectors and performance for any
   ticker on demand (the ↻ buttons and the "Look up" box). Runs server-side so
   the API key is never exposed to the browser.

This split is deliberate: the page is useful instantly (static), and the numbers
refresh themselves and can expand to **newly-launched ETFs you type in** (live).

## Layout

```
public/                 ← static site (deployed as-is)
├── index.html
├── style.css
├── app.js              ← loads /data/*.json; wires ↻ refresh + "Look up"
└── data/
    ├── quantum.json    ← QTUM, WQTM, CHPX + SOXX benchmark
    └── space.json      ← UFO, ARKX, ROKT + XAR, SHLD benchmarks
api/
└── etf.js              ← GET /api/etf?ticker=XXX  (live refresh)
vercel.json             ← Vercel config
```

## Run locally

**Option A — static only (no live refresh), zero dependencies:**
```bash
python3 app/server.py            # http://127.0.0.1:8000
```
Serves the same `public/` files. The ↻ button will say live refresh needs Vercel
— expected; the full curated analysis still works.

**Option B — full app with live refresh, using Vercel's dev server:**
```bash
npm i -g vercel
vercel dev                       # runs public/ + api/ together
```
(Needs the `ALPHAVANTAGE_KEY` env var — see deployment.)

## Deploy to Vercel (public URL)

See [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) for the step-by-step. Short
version: connect the GitHub repo to Vercel (zero build config needed), add one
environment variable `ALPHAVANTAGE_KEY` (free key from alphavantage.co), deploy.
You get `https://<project>.vercel.app`.

## What you can do on the page

- **Theme picker** — Quantum, Space, …
- **Sortable, filterable table** — click any header (expense, AUM, 1-yr, YTD,
  concentration, score dots) to sort; filter by ticker/name; "theme funds only".
- **↻ per row / in each memo** — pull live expense ratio, AUM, holdings, sectors,
  performance. Live values are marked with a ● dot.
- **"Look up" box** — type any ETF ticker (e.g. a brand-new quantum fund) and it
  fetches live and adds a clearly-marked, *uncurated* row. Ask for a full memo to
  turn it into a curated entry.
- **Memo drawer** — thesis, strategy, theme-purity holdings (live or curated),
  scored dimensions, performance, red flags, bull/bear, decision log.

## Add / update a curated theme or fund

1. Edit (or copy) a file in `public/data/`. Keep the field names — a fund needs
   the table fields, a `performance` block, a `scores` block (all five
   dimensions, each `{rating, note}`), and a `memo` block.
2. Add the theme id to `THEME_FILES` in `public/app.js`.
3. Commit. Vercel redeploys automatically; the live page updates in ~1 minute.

> Live data refreshes the **numbers**; curated JSON holds the **judgment**. When
> you ask me to "add fund X" or "refresh the data," I research public sources,
> cross-check, and commit updated JSON — that's the reliable path for holdings
> and brand-new funds the free API may not cover well.
