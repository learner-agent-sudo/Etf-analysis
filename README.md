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
├── docs/
│   ├── METHODOLOGY.md            ← the dimensions we score and why
│   ├── DATA-SOURCES.md           ← where to get the data (and access notes)
│   └── GLOSSARY.md               ← plain-English definitions
├── templates/
│   ├── etf-memo-template.md      ← deep one-pager per ETF
│   ├── comparison-scorecard-template.md
│   └── red-flags-checklist.md
└── themes/
    └── space/                    ← worked pilot example
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
