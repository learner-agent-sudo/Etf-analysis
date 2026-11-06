# ETF Analysis — web app

A **hosted, mobile-friendly web app** for side-by-side ETF comparison with deep
memos. It's a plain static site on **GitHub Pages**
(<https://learner-agent-sudo.github.io/Etf-analysis/>), so it opens on any device
with no install, no download and no server to keep running.

## Two layers (this is the key idea)

1. **Curated analysis** — `public/data/<theme>.json`. The judgment calls no API
   can make: theme-purity ratings, red flags, bull/bear, decision logs, scored
   dimensions, the green-light screen. Version-controlled.
2. **Daily market data** — `public/data/market.json`, generated every weekday
   after the US close by `scripts/refresh_market.py` in GitHub Actions: price,
   3-month average volume (shares and $), YTD / 1-yr / 3-yr / calendar-year
   total returns, 52-week range, 1-yr max drawdown, and (when Yahoo answers)
   AUM, expense ratio, trailing yield, top-10 holdings and sector weights — for
   every curated **and** roster ticker.

The page merges the two: fresh market numbers replace the dated snapshot in the
theme files (snapshot values are shown faded until fresh data exists).

## Layout

```
public/                 ← static site (deployed as-is)
├── index.html
├── style.css
├── app.js              ← loads data/<theme>.json + data/market.json
└── data/
    ├── <theme>.json    ← curated: 10 themes
    └── market.json     ← generated daily — don't edit by hand
scripts/
├── refresh_market.py   ← the daily fetcher (stdlib; curl_cffi optional)
└── screen.py           ← the green-light screener (stamps meets_criteria)
tests/                  ← offline tests for the market-data maths
.github/workflows/pages.yml  ← refresh + commit market.json + deploy
```

## Run locally

```bash
python3 app/server.py            # http://127.0.0.1:8000
```
Serves the same `public/` files with the last committed `market.json`.

## What you can do on the page

- **Theme picker** — remembered between visits; deep links like `…/#space`.
- **Sortable, filterable table** — click any header to sort (blanks always
  sort last); filter by ticker/name, "theme funds only", "✓ meets my criteria",
  or by any rating.
- **Full-universe roster** — every fund tagged to the theme, with its 1-yr
  return. ✓ = curated card; others open a card built from the daily data
  (mechanical cost / concentration / liquidity ratings, clearly marked "not
  curated"). "⚠ no data" = the feed can't find it (closed, non-US or wrong
  ticker — verify).
- **Look-up box** — type any ticker: opens its curated card (switching theme if
  needed), a daily-data card, or an honest "not tracked yet" stub.
- **Memo drawer** — thesis, performance, key facts (52-wk range, drawdown,
  $ volume, AUM, expense drift warning), scored dimensions, strategy, latest
  top-10 holdings next to the analyst's purity classification, red flags,
  bull/bear, decision log, plus links to the official holdings and a live quote.
- **↻ check for update** — re-loads `market.json` (it changes once a day).

## Add / update a curated theme or fund

1. Edit (or copy) a file in `public/data/`. Keep the field names — a fund needs
   the table fields, a `performance` block, a `scores` block (all five
   dimensions, each `{rating, note}`), and a `memo` block. Add new funds to the
   theme's `roster` too.
2. Add the theme id to `THEME_FILES` in `public/app.js`.
3. Run `python3 scripts/screen.py --stamp` to refresh the criteria badges.
4. Commit and push. The workflow fetches market data for any new tickers and
   redeploys within ~5 minutes.

> Market data refreshes the **numbers**; curated JSON holds the **judgment**.
> When you ask me to "add fund X" or "re-check theme Y," I research public
> sources, cross-check, and commit updated JSON.
