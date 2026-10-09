# ETF Analysis

A personal research framework for evaluating thematic and strategy ETFs using
**public information only** (prospectuses, fact sheets, regulatory filings,
issuer holdings files).

The goal is not to predict prices. It is to **filter and structure the public
information about an ETF** so that a buy / hold / sell decision can be made on
clear, comparable facts. The final decision is always the reader's.

## Why this exists

Thematic ETFs — especially in high-risk, fast-moving areas like **space**,
**pharma / biotech**, **defense**, and **options-income** strategies — are
marketed on a story. The story ("invest in the space economy!") often does not
match what the fund actually holds, what it charges, or how it behaves. This
repo is a checklist-driven way to look past the name and at the mechanics.

A real example found while building this repo: a "Space" ETF's marketing-page
top-10 concentration was reported at ~58%, but its own SEC filing showed ~22%,
and the holdings included a furniture retailer and a water-utilities company.
**The label is not the fund.** That gap is exactly what this framework exists to
catch.

## Core principle: where does the risk actually live?

| Fund type | Who controls the holdings | Where the risk concentrates |
|---|---|---|
| **Passive / index** | The index rules (issuer just tracks) | The index design + the theme itself |
| **Active / thematic** | The fund manager, daily | Manager skill + theme + concentration |
| **Strategy (options/leverage)** | The strategy rules + manager | The mechanics of the strategy itself |

> Note: the common intuition that "an ETF's record is the underlying portfolio,
> not the fund house" is true for **passive index** funds. For the **active
> thematic** and **options** ETFs this repo focuses on, the fund house's choices
> drive almost everything — so manager and strategy risk go *up*, not down.

## The web app (hosted, auto-updating)

The main way to use this is a **mobile-friendly, static web app** hosted free on
**GitHub Pages** — <https://learner-agent-sudo.github.io/Etf-analysis/> — a
public URL that opens on any device, no install, no download, no usage limits.
Per theme you get a **sortable / filterable comparison table** (expense ratio,
AUM, price, volume, 1-yr & YTD return, colored score dots), a **full-universe
roster** of every fund tagged to the theme, and a click-to-open **deep memo**
per ETF (strategy, theme-purity holdings, red flags, bull/bear, decision log).

It has **two layers**:
- **Curated analysis** (`public/data/<theme>.json`) — the judgment no API makes:
  theme-purity ratings, red flags, scores, memos, the green-light screen.
- **Daily market data** (`public/data/market.json`) — regenerated every weekday
  after the US close by a GitHub Action (`scripts/refresh_market.py`): price,
  volume, total returns, 52-week range, drawdown, AUM and top-10 holdings for
  every curated **and** roster ticker. No server, no API key.

**Hosting & data pipeline:** [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).
**Run it locally:**
```bash
python3 app/server.py          # then open http://127.0.0.1:8000
```

Ships with 10 themes: quantum, space, income/covered-call, pharma & biotech,
AI & robotics, nuclear/uranium, cybersecurity, water & infrastructure, rare
earths, and obesity/GLP-1. See [`app/README.md`](app/README.md) for how to add one.

> The curated layer is a **dated snapshot** from public sources (re-researched on
> request); the market layer refreshes itself daily. No free API reliably lists
> "every ETF in a theme," so discovering the full universe stays a research task
> (ask me) — the "Look up" box opens any tracked ticker, and new tickers get
> daily data once added to a theme.

## How to use this repo

1. **Pick a theme** → create/open a folder under `themes/`.
2. **Screen the universe** → fill in `comparison.md` from the
   [scorecard template](templates/comparison-scorecard-template.md). This ranks
   competing ETFs on cost, concentration, theme purity, and strategy.
3. **Shortlist 2–3** → write a deep [memo](templates/etf-memo-template.md) for
   each finalist under `themes/<theme>/memos/`.
4. **Run the [red-flags checklist](templates/red-flags-checklist.md)** against
   each finalist before deciding.
5. **Decide.** Record the decision and the reasoning (so you can review it later
   against what actually happened).

## Repository layout

```
.
├── README.md                     ← you are here
├── public/                       ← the web app (static site, deployed as-is)
│   ├── index.html · style.css · app.js
│   └── data/                     ← <theme>.json (curated) + market.json (daily, generated)
├── .github/workflows/pages.yml   ← daily data refresh + deploy to GitHub Pages
├── app/
│   ├── server.py                 ← run the static site locally (stdlib only)
│   └── README.md                 ← app architecture & how to add a theme
├── docs/
│   ├── METHODOLOGY.md            ← the dimensions we score and why
│   ├── DEPLOYMENT.md             ← get a free public URL on GitHub Pages
│   ├── DATA-SOURCES.md           ← where to get the data (and access notes)
│   └── GLOSSARY.md               ← plain-English definitions
├── scripts/
│   ├── screen.py                 ← backend green-light screener
│   └── refresh_market.py         ← daily market-data fetcher (writes market.json)
├── tests/                        ← offline tests for the market-data maths
├── templates/
│   ├── etf-memo-template.md      ← deep one-pager per ETF
│   ├── comparison-scorecard-template.md
│   └── red-flags-checklist.md
└── themes/
    └── space/                    ← worked pilot example (Markdown)
        ├── README.md
        ├── comparison.md         ← ARKX vs UFO vs ROKT vs XAR
        └── memos/
            └── ARKX.md
```

## Important disclaimer

This is a **personal research aid**, not investment advice, not a
recommendation, and not a solicitation. All figures are gathered from public
sources and **can be stale or wrong** — always confirm against the issuer's
official fact sheet and the latest regulatory filing before acting. Every data
point recorded here should carry an `as-of` date and a source.
