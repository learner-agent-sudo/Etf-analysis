// Vercel serverless function — live ETF refresh.
//
// GET /api/etf?ticker=QTUM
//   -> { ok, ticker, source, as_of, data: { expense_ratio, aum_*, holdings_count,
//        top10_weight_pct, holdings[], sectors[], performance{...} } }
//
// Why this exists: the static site (public/data/*.json) holds the CURATED analysis
// (scores, memos, theme-purity judgments) that no API can produce. This endpoint
// refreshes the HARD FACTS (expense ratio, AUM, holdings, performance) live, and
// lets the user pull ANY ticker — including newly launched ETFs not in our files.
//
// Runs on Vercel (which has outbound internet, unlike the dev sandbox). The data
// provider API key lives in the ALPHAVANTAGE_KEY env var (server-side only —
// never shipped to the browser).
//
// Provider: Alpha Vantage (free tier). ETF_PROFILE gives expense ratio, net assets,
// sectors and ~top holdings; TIME_SERIES_MONTHLY_ADJUSTED is used to compute YTD
// and 1-year returns. Free tier is rate-limited (~25 calls/day), so the frontend
// treats live data as a bonus layered on top of the always-available static data.

const PROVIDER_BASE = "https://www.alphavantage.co/query";

function pct(numNow, numThen) {
  if (!numThen || !numNow) return null;
  return Math.round(((numNow / numThen) - 1) * 1000) / 10; // one decimal, as %
}

async function avFetch(params) {
  const key = process.env.ALPHAVANTAGE_KEY || "demo";
  const url = `${PROVIDER_BASE}?${new URLSearchParams({ ...params, apikey: key })}`;
  const r = await fetch(url, { headers: { "User-Agent": "etf-analysis" } });
  if (!r.ok) throw new Error(`provider HTTP ${r.status}`);
  const j = await r.json();
  // Alpha Vantage signals problems in-band with these keys:
  if (j.Note || j.Information) throw new Error("rate_limited");
  if (j["Error Message"]) throw new Error("bad_ticker");
  return j;
}

function parseProfile(p) {
  if (!p || (!p.net_assets && !p.expense_ratio && !p.holdings)) return null;
  const holdings = Array.isArray(p.holdings)
    ? p.holdings.slice(0, 15).map(h => ({
        symbol: h.symbol,
        name: h.description || h.symbol,
        weight: h.weight != null ? Math.round(parseFloat(h.weight) * 10000) / 100 : null,
      }))
    : [];
  const top10 = holdings.slice(0, 10).reduce((s, h) => s + (h.weight || 0), 0);
  const sectors = Array.isArray(p.sectors)
    ? p.sectors.map(s => ({ sector: s.sector, weight: Math.round(parseFloat(s.weight) * 10000) / 100 }))
    : [];
  const naRaw = parseFloat(p.net_assets);
  return {
    expense_ratio: p.expense_ratio != null ? Math.round(parseFloat(p.expense_ratio) * 10000) / 100 : null,
    aum_musd: isFinite(naRaw) ? Math.round(naRaw / 1e6) : null,
    aum_display: isFinite(naRaw) ? humanUSD(naRaw) : null,
    inception: p.inception_date || null,
    holdings_count: holdings.length ? null : null, // profile gives ~top only, not full count
    top10_weight_pct: holdings.length >= 10 ? Math.round(top10) : null,
    holdings,
    sectors,
  };
}

function humanUSD(n) {
  if (n >= 1e9) return `~$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `~$${(n / 1e6).toFixed(0)}M`;
  return `~$${n.toLocaleString()}`;
}

function parsePerformance(ts) {
  const series = ts && ts["Monthly Adjusted Time Series"];
  if (!series) return null;
  const dates = Object.keys(series).sort(); // ascending
  if (dates.length < 2) return null;
  const closeAt = d => parseFloat(series[d]["5. adjusted close"]);
  const last = dates[dates.length - 1];
  const lastClose = closeAt(last);

  // 1-year: ~12 months back
  const y1idx = Math.max(0, dates.length - 13);
  const y1 = pct(lastClose, closeAt(dates[y1idx]));

  // YTD: last close of previous year
  const curYear = last.slice(0, 4);
  const prevYearDates = dates.filter(d => d < `${curYear}-01-01`);
  const ytd = prevYearDates.length
    ? pct(lastClose, closeAt(prevYearDates[prevYearDates.length - 1]))
    : null;

  // 3-year annualized: ~36 months back
  let y3a = null;
  if (dates.length >= 37) {
    const start = closeAt(dates[dates.length - 37]);
    if (start) y3a = Math.round(((Math.pow(lastClose / start, 1 / 3) - 1) * 1000)) / 10;
  }
  return {
    ytd: ytd != null ? `${ytd > 0 ? "+" : ""}${ytd}%` : null,
    y1: y1 != null ? `${y1 > 0 ? "+" : ""}${y1}%` : null,
    y3_annualized: y3a != null ? `${y3a > 0 ? "+" : ""}${y3a}%/yr` : null,
    as_of: last,
  };
}

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "s-maxage=3600, stale-while-revalidate=86400");
  const ticker = String((req.query && req.query.ticker) || "").trim().toUpperCase();
  if (!ticker || !/^[A-Z.\-]{1,8}$/.test(ticker)) {
    return res.status(400).json({ ok: false, error: "Provide a valid ?ticker= (1-8 letters)." });
  }
  if (!process.env.ALPHAVANTAGE_KEY) {
    return res.status(200).json({
      ok: false, ticker, error: "live_not_configured",
      message: "Live refresh isn't configured yet. Add an ALPHAVANTAGE_KEY env var in Vercel (free key at alphavantage.co) to enable it. Static analysis still works.",
    });
  }
  try {
    // Fetch in parallel; tolerate partial failure of either call.
    const [profile, perf] = await Promise.allSettled([
      avFetch({ function: "ETF_PROFILE", symbol: ticker }),
      avFetch({ function: "TIME_SERIES_MONTHLY_ADJUSTED", symbol: ticker }),
    ]);
    const data = {};
    if (profile.status === "fulfilled") Object.assign(data, parseProfile(profile.value) || {});
    if (perf.status === "fulfilled") data.performance = parsePerformance(perf.value);

    const anyData = Object.keys(data).length > 0 &&
      (data.expense_ratio != null || (data.holdings && data.holdings.length) || data.performance);
    if (!anyData) {
      const reason = [profile, perf].find(p => p.status === "rejected");
      const msg = reason && reason.reason && reason.reason.message;
      return res.status(200).json({
        ok: false, ticker,
        error: msg === "rate_limited" ? "rate_limited" : (msg === "bad_ticker" ? "bad_ticker" : "no_data"),
        message: msg === "rate_limited"
          ? "Data provider rate limit hit (free tier ~25/day). Try again later; static data is unaffected."
          : `No live data returned for ${ticker}. Check the ticker or try later.`,
      });
    }
    return res.status(200).json({
      ok: true, ticker, source: "Alpha Vantage", as_of: new Date().toISOString().slice(0, 10), data,
    });
  } catch (e) {
    return res.status(200).json({ ok: false, ticker, error: "exception", message: String(e.message || e) });
  }
}
