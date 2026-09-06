# Deployment — free hosting on GitHub Pages

The site is **static** (`public/` — HTML/CSS/JS + JSON data), so it hosts free on
**GitHub Pages** with no server, no account beyond GitHub, and no usage limits
that matter for a page like this. A GitHub Actions workflow auto-deploys on every
push, exactly like a connected host would.

## One-time setup (≈1 minute, from any browser)

1. Go to the repo → **Settings** → **Pages**.
2. Under **Build and deployment → Source**, choose **GitHub Actions**.
3. Done. The workflow (`.github/workflows/pages.yml`) runs on the next push (or
   run it now: **Actions** tab → "Deploy to GitHub Pages" → **Run workflow**).

Your site will be live at:

> **https://learner-agent-sudo.github.io/Etf-analysis/**

Every future push that touches `public/` redeploys automatically — so when I add
or update ETF data, the live page updates within a minute of the push.

## What works on GitHub Pages

Everything except the live serverless refresh:

- ✅ All curated analysis: comparison tables, memos, scores, holdings, the
  green-light screen and "Meets my criteria" filter, the full-universe rosters.
- ✅ Sorting, filtering, mobile card layout, the abbreviations glossary.
- ⚠️ The **↻ live-refresh / "Look up" box**: GitHub Pages is static-only, so
  there's no `api/etf` server. Clicking a roster ticker shows the graceful
  **"not yet curated" stub** instead of live prices. The curated data is a dated
  snapshot; refresh it by asking me to re-pull and commit.

## Local preview

```bash
python3 app/server.py        # http://127.0.0.1:8000
```
Zero dependencies (Python stdlib). Serves the same `public/` folder.

## Migrating off the paused Vercel project

Nothing to clean up is required — the paused Vercel deployment simply stops
serving. If you want, delete the Vercel project from your Vercel dashboard and
update the repo's **homepage** (Settings → General) to the Pages URL above. The
`vercel.json` / `api/etf.js` files are left in the repo but are inert without a
Vercel deploy.

## Want the live ↻ refresh back later? (optional)

The live feature needs a serverless runtime + a data API key. Free options that
don't have Vercel's limits:

- **Cloudflare Pages** — connect the repo, set the build output directory to
  `public`, and port `api/etf.js` to a Pages Function (`functions/api/etf.js`).
  Add the `ALPHAVANTAGE_KEY` as an environment variable. Generous free tier.
- **Netlify** — similar; `api/etf.js` → a Netlify Function, output dir `public`.

Ask me and I'll wire up whichever you pick. Until then, GitHub Pages gives you
the full analysis for free.
