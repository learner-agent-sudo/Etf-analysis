# ETF Analysis — web app

A small **dynamic web app** for side-by-side ETF comparison and deep memos.

## Run it

```bash
python3 app/server.py                 # http://127.0.0.1:8000
python3 app/server.py --port 9000     # custom port
```

No installation, no dependencies — **Python standard library only**. This is a
deliberate choice: the research environment blocks outbound internet, so
`pip install` doesn't work. Stdlib `http.server` runs anywhere.

## What you get

- A **theme picker** (top right) — switch between Quantum, Space, …
- A **sortable, filterable comparison table** — click any column header to sort
  (cost, AUM, concentration, the colored score dots…); filter by ticker/name;
  toggle "theme funds only" to hide the benchmark/reference funds.
- A **memo drawer** — click any row to open the full one-pager: thesis,
  strategy, a theme-purity holdings table (pure / partial / unrelated tags),
  scored dimensions, red flags, bull-vs-bear, and a decision log.
- **Key tensions** for the theme, and a benchmark note explaining why the
  reference funds are included.

## Architecture

```
app/
├── server.py          stdlib HTTP server + JSON API (no deps)
├── data/<theme>.json  one file per theme = the data layer
└── static/            index.html · style.css · app.js (vanilla JS, no build)
```

API:
- `GET /api/themes` → list of themes (id, name, as-of, tagline, count)
- `GET /api/theme/<id>` → one full theme (all ETFs + memos)

The frontend is plain HTML/CSS/JS — no framework, no build step, nothing to
compile. The backend only reads the JSON files and serves static assets, with a
path-traversal guard.

## ⚠️ Data is pre-populated, not live

The backend does **not** fetch ETF data at runtime — outbound internet is blocked
in this environment, so no framework could. Each `data/<theme>.json` is refreshed
**out-of-band** (via web search) and committed. Every theme carries an `as_of`
date; treat figures as a snapshot to **verify against issuer fact sheets / SEC
filings** before deciding. See [`../docs/DATA-SOURCES.md`](../docs/DATA-SOURCES.md).

## Add a new theme

1. Copy an existing file, e.g. `cp app/data/space.json app/data/income.json`.
2. Edit the JSON: set `id`, `name`, `as_of`, `tagline`, `key_tensions`,
   `benchmark_note`, and the `etfs` array.
3. Each ETF needs the table fields (`ticker`, `name`, `is_theme_fund`,
   `expense_ratio`, `aum_musd`/`aum_display`, `structure`, `holdings_count`,
   `top10_weight_pct`/`top10_weight_display`), a `scores` block with all five
   dimensions (`cost`, `purity`, `concentration`, `liquidity`, `track_record`,
   each `{rating: green|yellow|red, note}`), and a `memo` block.
4. Restart the server — the new theme appears in the picker automatically.

> Tip: keep the same field names. The data contract is enforced by a check —
> see the validation snippet in the repo history / commit that added the app.
> A field the frontend expects but the data omits will show as "—" rather than
> crash, but matching the shape keeps the UI complete.

## Limits / next steps

- No screenshot here (no headless browser installed, can't install one offline).
  Verified instead via API tests + a data-contract check over both themes.
- Future: a Markdown→JSON sync so the `themes/*.md` files and `app/data/*.json`
  can't drift; optional charts; export a theme to a static HTML bundle for
  GitHub Pages.
