# Deployment — get a public URL on Vercel

Goal: a webpage you can open from any device (phone, any browser), where the
analysis happens on the page and the data can refresh itself.

## Why Vercel

- Serves the static site (`public/`) on a free public URL.
- Runs the serverless function (`api/etf.js`) for **live data refresh** — Vercel
  has outbound internet (the dev sandbox does not), so live fetching works there.
- Auto-redeploys whenever the GitHub branch updates: ask me to add a fund or
  refresh data → I commit → the live page updates in about a minute.

## One-time setup (≈5 minutes, from any browser)

1. Go to **vercel.com** and sign in with **GitHub**.
2. **Add New → Project → Import** the `learner-agent-sudo/etf-analysis` repo.
3. Framework preset: **Other** (no build step). Leave build/output settings
   empty — `vercel.json` already configures everything.
4. **Set the production branch** to the working branch
   (`claude/keen-feynman-NnG7I`) under Project → Settings → Git, *or* merge that
   branch to `main` first. (Ask me if you want a PR to merge it.)
5. **Add the live-data API key** (optional but recommended) under
   Settings → Environment Variables:
   - Name: `ALPHAVANTAGE_KEY`
   - Value: a free key from **alphavantage.co/support/#api-key**
   - Apply to Production (and Preview).
6. **Deploy.** You get `https://<project>.vercel.app`. Open it on your phone.

> Without the API key the site still works fully — you get the curated analysis;
> the ↻ live-refresh buttons just report that live data isn't configured yet.

## How "refresh" works once deployed

- **Curated data** (scores, memos, theme purity) — updated by committing JSON.
  This is the trustworthy layer for holdings and brand-new funds.
- **Live numbers** (expense ratio, AUM, holdings, performance) — fetched on the
  page via ↻ and the "Look up" box, from the data provider. Free tier is
  rate-limited (~25 calls/day); live values are a bonus on top of static data.

## Data provider notes / limits

- Default provider: **Alpha Vantage** `ETF_PROFILE` (expense ratio, net assets,
  sectors, ~top holdings) + monthly prices (for YTD / 1-yr / 3-yr returns).
- Free tier limits: ~25 requests/day, ~5/min. Fine for occasional lookups, not
  for hammering. Upgrade the key or swap providers in `api/etf.js` if you need
  more. The function degrades gracefully (clear message, static data unaffected).
- No free API reliably lists *"every ETF in a theme."* Theme discovery stays a
  research task (ask me); the "Look up" box covers pulling a specific new ticker.

## Alternative hosts

The static `public/` folder works on any static host (GitHub Pages, Netlify,
Cloudflare Pages). Only the **live refresh** needs a serverless platform —
Netlify/Cloudflare Functions work too, with small tweaks to `api/etf.js`.
