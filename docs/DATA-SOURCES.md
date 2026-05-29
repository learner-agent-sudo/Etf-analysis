# Data sources — where to get the numbers

All ETF data here comes from **public** sources. This file lists them in order of
trustworthiness and notes how to access each one from this environment.

## Trust hierarchy (prefer top to bottom)

1. **Issuer official documents** — the ground truth.
   - **Prospectus / SAI** — full strategy, risks, fees. The legal document.
   - **Fact sheet** (monthly/quarterly PDF) — expense ratio, top holdings, sector
     mix, performance. The best single summary.
   - **Daily holdings file** (CSV/XLSX on issuer site) — the *complete* portfolio.
     Essential for theme-purity analysis.
   - **Annual / semi-annual report** (N-CSR) — audited, most reliable but lagged.
2. **Regulatory filings (SEC EDGAR)** — `sec.gov`. Forms: `485BPOS`/`485APOS`
   (prospectus), `N-CSR`/`N-CSRS` (shareholder reports), `497K` (summary
   prospectus). Authoritative, free, but lagged and dense.
3. **Reputable aggregators** — etf.com, ETFdb, Morningstar, StockAnalysis,
   issuer-independent. Convenient and current, but **can be wrong or stale** —
   always cross-check the headline numbers against the fact sheet.
4. **Financial news / commentary** — context and narrative only, never as the
   sole source for a number.

## ⚠️ Access notes for THIS environment (verified 2026-05-29)

The sandbox network is restricted. What works:

| Channel | Status | Use for |
|---|---|---|
| `curl` / direct HTTP to sec.gov, issuer sites, Yahoo | ❌ **Blocked (HTTP 403)** | — |
| Python `yfinance` / `pandas` | ❌ Not installed | — |
| **WebSearch tool** | ✅ Works well | Pulling current expense ratios, AUM, holdings, sector mixes from indexed aggregators |
| **WebFetch tool** | ⚠️ Partial | Works on permissive sites; **403s on most issuer sites** (bot protection) |
| **User-pasted documents** | ✅ Best for precision | Drop a fact-sheet PDF / holdings CSV into the chat or repo and it gets parsed directly |

**Practical workflow given these constraints:**
- For *current headline metrics* (expense ratio, AUM, top-10, sectors) →
  WebSearch, and record the source + as-of date.
- For *ground-truth precision* (exact prospectus wording, full holdings file,
  audited figures) → **paste the official PDF/CSV** and it will be parsed.
- **Always cross-check** an aggregator number against the issuer doc before it
  drives a decision. (We already caught a 58% vs 22% concentration discrepancy
  between an aggregator and an SEC filing — see the space example.)

## Recording discipline

Every number in a memo or scorecard must carry:
- an **as-of date** (ETF data changes daily), and
- a **source** (which doc / site).

Use the footnote/source rows built into the templates. A figure without a date
and source is not usable for a decision.
