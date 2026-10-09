"use strict";

// ====================================================================
// ETF Analysis — static frontend (GitHub Pages; no server needed).
// • Curated analysis: data/<theme>.json (scores, memos, purity judgments).
// • Market data: data/market.json, regenerated every weekday after the US
//   close by a GitHub Action (scripts/refresh_market.py) — price, volume,
//   returns, AUM, expense ratio and top-10 holdings for every curated AND
//   roster ticker. Fresh values replace the dated snapshot in the theme files;
//   snapshot values are shown faded until fresh data exists.
// ====================================================================

let CURRENT = null;                 // current theme object
let MARKET = null;                  // data/market.json (null until first generated)
let SORT = { key: "ticker", dir: 1 };

const RATING_LABEL = { green: "Good", yellow: "Caution", red: "Concern" };
const SCORE_RANK = { green: 0, yellow: 1, red: 2 };

const THEME_FILES = ["quantum", "space", "income", "pharma", "ai-robotics", "energy", "cybersecurity", "water", "rare-earths", "glp1"];  // order in the picker

// Plain-English definitions for abbreviations. Shown as tooltips on column
// headers and listed in the footer, so the page explains its own jargon.
const GLOSSARY = {
  "Expense": "Expense ratio (TER): the annual fee the fund charges, as a % of your money — taken daily, win or lose. Lower is better. 0.50% on $10,000 ≈ $50/yr.",
  "AUM": "Assets Under Management: total money invested in the fund. Bigger = more liquid and less likely to be shut down. Under ~$50M raises closure risk.",
  "Distribution yield": "Annual income paid out as a % of price. For income/covered-call funds this is the headline number — BUT a high yield can be partly 'return of capital' (your own money handed back), so check the 30-day SEC yield and total return too.",
  "30-day SEC yield": "A standardized yield based on what the fund actually EARNS from dividends/interest — it excludes option premium, so for covered-call funds it can look much lower than the distribution yield (not necessarily a red flag).",
  "Price": "Latest closing share price — what one share costs. Mainly tells you the share size; it is NOT a measure of value (a $40 and a $600 ETF can be equally good).",
  "Avg Vol": "Average daily trading volume (shares per day, last 3 months). Higher = easier to buy/sell at a fair price with a tight bid/ask spread. Low volume is a hidden cost and a liquidity risk.",
  "$ volume": "Average dollars traded per day (price × shares, last 3 months). Under ~$1M/day usually means wider bid/ask spreads — use limit orders.",
  "1-yr": "Total return over the trailing 12 months (price change + distributions reinvested). Past performance does not predict the future.",
  "YTD": "Year-to-date return: performance since the last close of the previous year.",
  "3-yr ann.": "3-year annualized return: the average yearly return over the last 3 years (compounded). Blank if the fund is younger than 3 years.",
  "52-wk range": "Lowest and highest closing price over the last year — shows how violently the fund swings.",
  "Max drawdown": "Worst peak-to-trough fall over the last year (distributions reinvested). A gut-check for how much pain you'd have sat through.",
  "Structure": "How the fund is run: Passive = mechanically tracks an index; Active = a manager picks holdings. Also notes weighting (cap- vs equal-weight).",
  "# Hold": "Number of holdings — how many different securities the fund owns. Fewer = more concentrated.",
  "Top-10": "Top-10 weight: the % of the fund held in its ten largest positions. Over ~50% means it's a concentrated bet on a few names.",
  "Cost": "Our rating of the fund's cost vs peers in this theme (green=cheap, yellow=typical, red=expensive).",
  "Purity": "Theme purity: how well the actual holdings match the fund's name/theme. Red = the label and the holdings disagree.",
  "Concen.": "Concentration: how much is riding on a few holdings. Red = top-heavy / single-stock risk.",
  "Yield": "Trailing 12-month distribution yield (income paid ÷ price). Beware: a high yield can be partly 'return of capital'. Compare total return, not just yield.",
  "1-yr price": "52-week change in the share price only — excludes dividends/distributions, so income and bond funds look worse than their real (total) return.",
  "Size": "Explorer rating from fund size (AUM): 🟢 ≥ $500M, 🟡 ≥ $50M, 🔴 smaller — small funds have wider spreads and closure risk.",
  "Pre-screen": "Explorer shortcut: expense ratio ≤ 0.50% (cost 🟢), AUM ≥ $50M, and not leveraged/inverse, an ETN or futures-based. Concentration and purity still need a look at the holdings.",
  "Domicile": "Where a fund is legally based (US, Ireland, Luxembourg, Hong Kong…). It drives the tax drag on dividends and, for non-US investors, US estate-tax exposure — see 'Tax & domicile' in the Explorer. General information only, not tax advice.",
  "Daily data": "Price, volume, returns, AUM and top holdings refresh automatically every weekday after the US market close (end-of-day, not intraday). Faded values are an older hand-researched snapshot, shown until fresh data exists. For an intraday price, open a fund and tap “Live quote”.",
};

// Columns active for the current theme (some columns are theme-specific, e.g. Yield).
function activeColumns() {
  return COLUMNS.filter(c => !c.cond || (CURRENT && c.cond(CURRENT)));
}

const COLUMNS = [
  { key: "ticker", label: "Ticker" },
  { key: "_er", label: "Expense", fmt: e => { const v = erOf(e); return v == null ? nodata("Expense ratio") : v.toFixed(2) + "%"; } },
  { key: "_aum", label: "AUM", fmt: e => aumCell(e) },
  { key: "_price", label: "Price", fmt: e => marketCell(e, "price") },
  { key: "_vol", label: "Avg Vol", fmt: e => marketCell(e, "volume") },
  { key: "_yield", label: "Yield", cond: t => (t.etfs || []).some(e => e.distribution_yield), fmt: e => yieldCell(e) },
  { key: "_perf1y", label: "1-yr", fmt: e => perfCell(e, "y1") },
  { key: "_perfytd", label: "YTD", fmt: e => perfCell(e, "ytd") },
  { key: "_cost", label: "Cost", type: "score" },
  { key: "_purity", label: "Purity", type: "score" },
  { key: "_concentration", label: "Concen.", type: "score" },
];

// ---- tiny DOM helpers ----------------------------------------------
const $ = s => document.querySelector(s);
function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v != null) n.setAttribute(k, v);
  }
  for (const kid of kids) if (kid != null) n.append(kid.nodeType ? kid : document.createTextNode(kid));
  return n;
}
const escapeHtml = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const escapeRe = s => String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const scoreOf = (etf, dim) => (etf.scores && etf.scores[dim]) || null;
const num = v => { const n = parseFloat(String(v ?? "").replace(/[^0-9.\-]/g, "")); return isFinite(n) ? n : null; };
const fmtMusd = a => a >= 1e6 ? `~$${(a / 1e6).toFixed(1)}T` : a >= 1000 ? `~$${(a / 1000).toFixed(1)}B` : `~$${a}M`;
const quoteUrl = t => `https://finance.yahoo.com/quote/${encodeURIComponent(t)}`;
// Make a clickable non-button element reachable and operable by keyboard.
function pressable(node, fn) {
  node.setAttribute("tabindex", "0");
  node.setAttribute("role", "button");
  node.addEventListener("click", fn);
  node.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); fn(ev); } });
  return node;
}

// ---- market-data helpers -------------------------------------------
const daily = t => (MARKET && MARKET.tickers && MARKET.tickers[t]) || null;
// "On hold" = no data source can find the ticker (closed, delisted, moved
// exchange or mistyped). Roster entries are removed automatically once they
// have been missing for the hold period; curated cards are only flagged.
function holdInfo(t) {
  const m = MARKET && MARKET.missing && MARKET.missing[t];
  if (!m) return null;
  const p = (MARKET && MARKET.hold_policy) || { days: 30, min_checks: 10 };
  return { since: m.since, checks: m.checks,
    text: `On hold: not found in the market data since ${m.since} (${m.checks} failed lookup${m.checks === 1 ? "" : "s"}) — the fund may have closed, moved exchange, or the ticker may be wrong. ` +
          `If it is still missing after ${p.days} days it is removed from the roster automatically.` };
}
function failReason(t) {
  const h = holdInfo(t);
  return h ? h.text : "Not found in the daily market data. Verify on the issuer's site.";
}

// Values like "verify", "n/a", "" mean "no confirmed number".
function isPlaceholder(v) {
  if (v == null) return true;
  const s = String(v).trim().toLowerCase();
  return s === "" || s === "n/a" || s === "na" || s.startsWith("verify") || s === "—";
}
const snapTitle = (what, asof) =>
  `${what}: older hand-researched snapshot${asof ? " (" + asof + ")" : ""}. Fresh daily data replaces it automatically once available.`;
function nodata(what) {
  return el("span", { class: "nodata", title: `${what} not available yet — it fills in automatically at the next daily update (weekdays after the US close). A blank does NOT mean the fund is illiquid or not investable.` }, "n/a");
}
const staleNote = d => d && d.stale ? " — the data source failed at the last update, so this may be a day or more old" : "";

// Expense ratio: the hand-verified figure wins; fund data fills gaps.
function erOf(e) {
  if (e.expense_ratio != null) return e.expense_ratio;
  const d = daily(e.ticker);
  return d && d.expense_ratio != null ? d.expense_ratio : null;
}
// AUM: fresh fund data wins over the dated snapshot.
function aumOf(e) {
  const d = daily(e.ticker);
  if (d && d.aum_musd != null) return { musd: d.aum_musd, display: d.aum_display || fmtMusd(d.aum_musd), fresh: true, asof: d.profile_asof };
  if (e.aum_display || e.aum_musd != null) return { musd: e.aum_musd, display: e.aum_display || fmtMusd(e.aum_musd), fresh: !!e._fresh, asof: e._fresh ? CURRENT.as_of : null };
  return null;
}
function aumCell(e) {
  const a = aumOf(e);
  if (!a) return nodata("AUM");
  return a.fresh ? el("span", { title: `Net assets per fund data (${a.asof || "latest"})` }, a.display)
                 : el("span", { class: "snap", title: snapTitle("AUM", CURRENT && CURRENT.as_of) }, a.display);
}
// Where the latest fund data contradicts the numbers a curated rating was
// based on. `screen` marks checks that touch the buy screen (cost/concentration).
function dataChecks(e) {
  if (e._adhoc) return [];
  const h = holdInfo(e.ticker);
  if (h) return [{ dim: "data", screen: !!e.meets_criteria, text: h.text.replace("removed from the roster automatically", "flagged for review (curated cards are never removed automatically)") }];
  const d = daily(e.ticker);
  if (!d) return [];
  const out = [];
  if (d.top10_weight_pct != null && e.top10_weight_pct != null && Math.abs(d.top10_weight_pct - e.top10_weight_pct) >= 8) {
    const over = d.top10_weight_pct > 50 && e.top10_weight_pct <= 50;
    out.push({ dim: "concentration", screen: over || d.top10_weight_pct > e.top10_weight_pct + 8,
      text: `Top-10 weight is now ~${d.top10_weight_pct}% (rated on ~${e.top10_weight_pct}%)${d.top10_weight_pct > 50 ? " — above the 50% red-flag line" : ""}.` });
  }
  if (d.expense_ratio != null && e.expense_ratio != null && Math.abs(d.expense_ratio - e.expense_ratio) >= 0.05) {
    out.push({ dim: "cost", screen: d.expense_ratio > e.expense_ratio,
      text: `Fund data shows a ${d.expense_ratio.toFixed(2)}% expense ratio (rated on ${e.expense_ratio.toFixed(2)}%; the difference may be acquired-fund fees or a fee change — check the issuer).` });
  }
  if (d.aum_musd && e.aum_musd && (d.aum_musd / e.aum_musd > 2 || d.aum_musd / e.aum_musd < 0.5)) {
    out.push({ dim: "liquidity", screen: false, text: `AUM is now ${d.aum_display} (rated on ${fmtMusd(e.aum_musd)}).` });
  }
  return out;
}
function yieldOf(e) {
  const d = daily(e.ticker);
  if (d && d.yield_ttm) return { v: d.yield_ttm, fresh: true };
  if (e.distribution_yield) return { v: e.distribution_yield, fresh: false };
  return null;
}
function yieldCell(e) {
  const y = yieldOf(e);
  if (!y) return el("span", { class: "muted" }, "—");
  return el("span", { class: y.fresh ? "" : "snap", title: y.fresh ? "Trailing 12-month yield (fund data)" : snapTitle("Distribution yield", CURRENT && CURRENT.as_of) }, y.v);
}
function marketCell(e, which) {
  const d = daily(e.ticker), m = e.market || {};
  if (which === "price") {
    if (d && d.price_display) return el("span", { title: `Close on ${d.price_asof}${staleNote(d)}` }, d.price_display);
    if (m.price_display) return el("span", { class: e._fresh ? "" : "snap", title: e._fresh ? `Close on ${m.price_asof}` : snapTitle("Price", m.price_asof) }, m.price_display);
    return nodata("Price");
  }
  if (d && d.volume_display) return el("span", { title: `Average shares/day over 3 months (${d.dollar_volume_display || "?"} in dollars)${staleNote(d)}` }, d.volume_display);
  if (m.volume_display) return el("span", { class: e._fresh ? "" : "snap", title: e._fresh ? "Average shares/day over 3 months" : snapTitle("Average volume", m.price_asof) }, m.volume_display);
  return nodata("Volume");
}
// A return figure: fresh daily data first, else the dated snapshot.
function perfOf(e, key) {
  const d = daily(e.ticker), dp = d && d.performance;
  if (dp && !isPlaceholder(dp[key])) return { v: dp[key], fresh: true, asof: dp.as_of, priceOnly: /^price/.test(dp.basis || "") };
  const sp = e.performance;
  if (sp && !isPlaceholder(sp[key])) return { v: sp[key], fresh: !!e._fresh, asof: isPlaceholder(sp.as_of) ? (CURRENT && CURRENT.as_of) : sp.as_of };
  return null;
}
// Is the fund simply too young to have a figure for this period?
function tooNew(e, key) {
  const d = daily(e.ticker);
  const start = (d && (d.first_trade_date || d.history_start)) || e.inception;
  if (!start) return false;
  const asof = (d && d.price_asof) || new Date().toISOString().slice(0, 10);
  if (key === "ytd") return start > `${+asof.slice(0, 4) - 1}-12-31`;
  const yrs = { y1: 1, y3_annualized: 3 }[key];
  if (!yrs) return false;
  const cut = new Date(asof); cut.setFullYear(cut.getFullYear() - yrs);
  return start > cut.toISOString().slice(0, 10);
}
function perfTitle(p) {
  return p.fresh ? `${p.priceOnly ? "Price return only (excludes distributions)" : "Total return"} as of ${p.asof}` : snapTitle("Return", p.asof);
}
function perfCell(e, key) {
  const p = perfOf(e, key);
  if (!p) return el("span", { class: "muted", title: tooNew(e, key) ? "Not available — the fund is too new for this period." : "Not available yet." }, "—");
  const n = num(p.v);
  return el("span", { class: (n == null ? "muted" : n >= 0 ? "pos" : "neg") + (p.fresh ? "" : " snap"), title: perfTitle(p) },
    String(p.v) + (p.priceOnly ? "*" : ""));
}

// ---- boot ----------------------------------------------------------
async function fetchJson(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}
async function loadMarket(bust) {
  try {
    const j = await fetchJson("data/market.json" + (bust ? "?t=" + Date.now() : ""));
    if (j && j.tickers) MARKET = j;
  } catch (_) { /* not generated yet — the curated snapshot is used */ }
  return MARKET;
}
// ---- views: Themes (curated analysis) | Explorer (every listed ETF) --
let VIEW = "themes", LAST_THEME = null;
function setView(v) {
  VIEW = v;
  $("#themeView").hidden = v !== "themes";
  $("#explorer").hidden = v !== "explore";
  $(".theme-picker").classList.toggle("dim", v !== "themes");
  $("#tabThemes").classList.toggle("active", v === "themes");
  $("#tabExplore").classList.toggle("active", v === "explore");
  $("#tabThemes").setAttribute("aria-selected", v === "themes");
  $("#tabExplore").setAttribute("aria-selected", v === "explore");
  if (v === "explore" && !location.hash.startsWith("#explore")) history.replaceState(null, "", "#explore");
  closeMemo();
}
const exploreRoute = () => { const h = decodeURIComponent(location.hash.replace(/^#/, "")); return h === "explore" || h.startsWith("explore=") ? (h.split("=")[1] || "") : null; };

const THEME_ALIASES = { nuclear: "energy" };     // renamed themes keep old links working
const themeAlias = id => THEME_ALIASES[id] || id;
const themeFromUrl = () => themeAlias(decodeURIComponent(location.hash.replace(/^#/, "")));
function savedTheme() { try { return themeAlias(localStorage.getItem("etf.theme")); } catch (_) { return null; } }

async function init() {
  const sel = $("#themeSelect");
  const [themes] = await Promise.all([
    Promise.all(THEME_FILES.map(id => fetchJson(`data/${id}.json`).then(t => { t._id = id; return t; }).catch(() => null))),
    loadMarket(),
  ]);
  const loaded = themes.filter(Boolean);
  window._THEMES = {};
  loaded.forEach(t => { window._THEMES[t._id] = t; sel.append(el("option", { value: t._id }, `${t.name} (${(t.etfs || []).length})`)); });
  sel.addEventListener("change", () => selectTheme(sel.value));

  // Footer abbreviations legend, from the same GLOSSARY.
  const gl = $("#glossaryList");
  if (gl) Object.entries(GLOSSARY).forEach(([term, def]) => gl.append(el("dt", {}, term), el("dd", {}, def)));

  $("#filterBox").addEventListener("input", render);
  $("#themeOnly").addEventListener("change", render);
  $("#passOnly").addEventListener("change", render);
  $("#ratingDim").addEventListener("change", () => {
    const rv = $("#ratingVal");
    rv.disabled = !$("#ratingDim").value;
    if (!$("#ratingDim").value) rv.value = "";
    render();
  });
  $("#ratingVal").addEventListener("change", render);
  $("#segmentSel").addEventListener("change", render);
  $("#addBtn").addEventListener("click", onAddTicker);
  $("#addTicker").addEventListener("keydown", e => { if (e.key === "Enter") onAddTicker(); });
  $("#tabThemes").addEventListener("click", () => { if (VIEW !== "themes") selectTheme(LAST_THEME || $("#themeSelect").value); });
  $("#tabExplore").addEventListener("click", () => { if (VIEW !== "explore") showExplorer(); });
  $("#closeMemo").addEventListener("click", closeMemo);
  $("#overlay").addEventListener("click", closeMemo);
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeMemo(); });

  if (!loaded.length) {
    $("#themeIntro").append(el("p", { class: "livemsg err" }, "Couldn't load the theme data. Check your connection and reload the page."));
    return;
  }
  const want = [themeFromUrl(), savedTheme()].find(id => id && window._THEMES[id]);
  const first = want || loaded[0]._id;
  sel.value = first;
  const ex = exploreRoute();
  if (ex !== null) { LAST_THEME = first; showExplorer(window._THEMES[ex] ? ex : ""); }
  else selectTheme(first);
  window.addEventListener("hashchange", () => {
    const exr = exploreRoute();
    if (exr !== null) { if (VIEW !== "explore") showExplorer(window._THEMES[exr] ? exr : undefined); return; }
    const h = themeFromUrl();
    if (h && window._THEMES[h] && (VIEW !== "themes" || h !== CURRENT._id)) { sel.value = h; selectTheme(h); }
  });
}

function selectTheme(id) {
  CURRENT = window._THEMES[id];
  LAST_THEME = id;
  $("#themeSelect").value = id;
  setView("themes");
  if (!activeColumns().some(c => c.key === SORT.key)) SORT = { key: "ticker", dir: 1 };
  $("#controls").hidden = false;
  $("#liveMsg").hidden = true;
  const segs = [...new Set((CURRENT.etfs || []).map(e => e.segment).filter(Boolean))];
  const segSel = $("#segmentSel");
  segSel.innerHTML = "";
  segSel.append(el("option", { value: "" }, "All segments"), ...segs.map(x => el("option", { value: x }, x)));
  segSel.hidden = segs.length < 2;
  try { localStorage.setItem("etf.theme", id); } catch (_) { /* private mode */ }
  if (themeFromUrl() !== id) history.replaceState(null, "", "#" + id);
  closeMemo();
  renderIntro(); renderTensions(); render(); renderRoster();
}

// ---- intro / tensions ----------------------------------------------
function freshnessText() {
  if (!MARKET) return "Market data: hand-researched snapshot (automatic daily data not generated yet)";
  return `Prices, volume, returns & AUM: ${MARKET.as_of} close — updates automatically every weekday`;
}
function renderIntro() {
  const t = CURRENT, box = $("#themeIntro"); box.innerHTML = "";
  box.append(
    el("h2", {}, t.name + " ETFs"),
    el("div", { class: "asof" }, `Analysis as of ${t.as_of || "—"} · ${freshnessText()} `,
      el("button", { class: "refresh", title: "Re-load the latest daily market-data file", onclick: onCheckUpdate }, "↻ check for update")),
    el("div", { class: "tagline" }, t.tagline || ""),
    t.universe_note ? el("p", { class: "universe" }, "▸ " + t.universe_note) : null,
    t.benchmark_note ? el("p", { class: "bench" }, "▸ " + t.benchmark_note) : null
  );
}
function renderTensions() {
  const box = $("#tensions"); box.innerHTML = "";
  const list = CURRENT.key_tensions || []; if (!list.length) return;
  const ul = el("ul");
  list.forEach(x => {
    const i = x.indexOf(":");
    ul.append(el("li", { html: i > 0 ? `<b>${escapeHtml(x.slice(0, i))}</b>${escapeHtml(x.slice(i))}` : escapeHtml(x) }));
  });
  box.append(el("h3", {}, "Key tensions in this theme"), ul);
}

// ---- full-universe roster ------------------------------------------
// Tier 2: the complete list of funds tagged to the theme. Curated funds (those
// with a full card above) are marked ✓; the rest open a card built from the
// daily fund data.
function renderRoster() {
  const box = $("#roster"); if (!box) return;
  box.innerHTML = "";
  const roster = CURRENT.roster || [];
  if (!roster.length) { box.hidden = true; return; }
  box.hidden = false;
  const curated = new Set((CURRENT.etfs || []).filter(e => !e._adhoc).map(e => e.ticker));
  const det = el("details", { class: "rosterbox" });
  const nDetailed = roster.filter(x => curated.has(x.ticker)).length;
  det.append(el("summary", {},
    `Full universe — ${roster.length} ${CURRENT.name} ETFs (${nDetailed} analysed above · tap any to open)`));
  const note = el("p", { class: "rosternote" },
    "Every listed fund tagged to this theme, including leveraged/inverse and niche variants (clearly tagged). " +
    "✓ = full analysis card above. The others open a card with the latest daily fund data (price, returns, AUM, top holdings) — ask Claude to add a full analysis.");
  const item = x => {
    const isDet = curated.has(x.ticker);
    const d = daily(x.ticker);
    const y1 = d && d.performance && d.performance.y1;
    const n = num(y1);
    const hold = !d ? holdInfo(x.ticker) : null;
    return pressable(el("div", { class: "rosteritem" + (isDet ? " detailed" : ""),
      title: isDet ? "Full analysis card — click to open" : "Click to open this fund's daily data" },
      el("span", { class: "rtk" }, (isDet ? "✓ " : "") + x.ticker),
      x.tag ? el("span", { class: "rtag" }, x.tag) : null,
      el("span", { class: "rnm" }, x.name || ""),
      y1 ? el("span", { class: "rperf " + (n >= 0 ? "pos" : "neg"), title: "1-yr return (daily data)" }, y1) : null,
      hold ? el("span", { class: "rnodata", title: hold.text }, "⏸ on hold") : null),
      () => isDet ? openMemo(x.ticker) : lookupTicker(x.ticker, x));
  };
  const byTicker = (a, b) => a.ticker.localeCompare(b.ticker);
  const segments = [...new Set(roster.map(x => x.segment).filter(Boolean))];
  const grid = el("div", {});
  if (segments.length > 1) {           // grouped by segment, in the theme's own order
    segments.forEach(sg => {
      const g = el("div", { class: "rostergrid" });
      roster.filter(x => x.segment === sg).sort(byTicker).forEach(x => g.append(item(x)));
      grid.append(el("h4", { class: "rosterseg" }, sg), g);
    });
  } else {
    const g = el("div", { class: "rostergrid" });
    roster.slice().sort(byTicker).forEach(x => g.append(item(x)));
    grid.append(g);
  }
  det.append(note, grid, el("p", { class: "rosternote" },
    el("button", { class: "refresh", onclick: () => showExplorer(CURRENT._id) }, "Browse every listed ETF matching this theme in the Explorer →")));
  const gone = ((MARKET && MARKET.removed_recent) || []).filter(r => r.theme === CURRENT._id);
  if (gone.length) det.append(el("p", { class: "rosternote" }, "Recently removed (not found for " +
    (((MARKET.hold_policy || {}).days) || 30) + "+ days): " +
    gone.map(r => `${r.ticker} — ${r.name || ""} (${r.removed_on})`).join("; ") + "."));
  box.append(det);
}

// ---- table ---------------------------------------------------------
function visibleEtfs() {
  const q = $("#filterBox").value.trim().toLowerCase();
  const rdim = $("#ratingDim").value, rval = $("#ratingVal").value;
  let rows = (CURRENT.etfs || []).slice();
  if ($("#themeOnly").checked) rows = rows.filter(e => e.is_theme_fund);
  if ($("#passOnly").checked) rows = rows.filter(e => e.meets_criteria);
  if (q) rows = rows.filter(e => (e.ticker + " " + e.name + " " + (e.segment || "")).toLowerCase().includes(q));
  const seg = $("#segmentSel").value;
  if (seg) rows = rows.filter(e => e.segment === seg);
  if (rdim && rval) rows = rows.filter(e => {
    const r = (scoreOf(e, rdim) || {}).rating;
    if (rval === "green") return r === "green";
    if (rval === "greenyellow") return r === "green" || r === "yellow";
    if (rval === "red") return r === "red";
    return true;
  });
  rows.sort(cmp);
  return rows;
}
function sortVal(e, key) {
  switch (key) {
    case "ticker": return e.ticker;
    case "_er": return erOf(e);
    case "_aum": { const a = aumOf(e); return a ? a.musd : null; }
    case "_price": { const d = daily(e.ticker); return d && d.price != null ? d.price : (e.market && e.market.price); }
    case "_vol": { const d = daily(e.ticker); return d && d.volume_avg != null ? d.volume_avg : (e.market && e.market.volume_avg); }
    case "_yield": { const y = yieldOf(e); return y ? num(y.v) : null; }
    case "_perf1y": { const p = perfOf(e, "y1"); return p ? num(p.v) : null; }
    case "_perfytd": { const p = perfOf(e, "ytd"); return p ? num(p.v) : null; }
  }
  const sc = scoreOf(e, key.slice(1));
  return sc ? SCORE_RANK[sc.rating] : null;
}
function cmp(a, b) {
  const va = sortVal(a, SORT.key), vb = sortVal(b, SORT.key);
  const na = va == null, nb = vb == null;
  if (na || nb) return na === nb ? a.ticker.localeCompare(b.ticker) : (na ? 1 : -1);  // blanks always last
  if (typeof va === "string") return va.localeCompare(vb) * SORT.dir;
  return (va - vb) * SORT.dir || a.ticker.localeCompare(b.ticker);
}
function clearFilters() {
  $("#filterBox").value = ""; $("#themeOnly").checked = false; $("#passOnly").checked = false;
  $("#ratingDim").value = ""; $("#ratingVal").value = ""; $("#ratingVal").disabled = true;
  $("#segmentSel").value = "";
  render();
}
function render() {
  if (!CURRENT) return;
  const rows = visibleEtfs(), wrap = $("#tableWrap"); wrap.innerHTML = "";
  if (!rows.length) {
    wrap.append(el("div", { class: "empty" }, "No funds match these filters. ",
      el("button", { class: "refresh", onclick: clearFilters }, "Clear filters")));
    return;
  }
  const cols = activeColumns();
  const thead = el("tr");
  cols.forEach(c => {
    const active = SORT.key === c.key;
    const def = GLOSSARY[c.label];
    thead.append(el("th", { onclick: () => setSort(c.key), title: def || c.label, class: def ? "has-help" : "",
      "aria-sort": active ? (SORT.dir > 0 ? "ascending" : "descending") : null },
      c.label, def ? el("span", { class: "qmark" }, "ⓘ") : null,
      active ? el("span", { class: "arrow" }, SORT.dir > 0 ? " ▲" : " ▼") : null));
  });
  const tbody = el("tbody");
  rows.forEach(e => {
    const tr = el("tr", { class: e.is_theme_fund ? "" : "bench" });
    cols.forEach(c => {
      if (c.type === "score") {
        const sc = scoreOf(e, c.key.slice(1));
        tr.append(el("td", { class: "cellscore", "data-label": c.label, title: sc ? sc.note : "", onclick: () => openMemo(e.ticker) },
          sc ? el("span", { class: "score" }, el("span", { class: "dot " + sc.rating }), RATING_LABEL[sc.rating]) : "—"));
      } else if (c.key === "ticker") {
        tr.append(pressable(el("td", { class: "col-ticker", "aria-label": `Open the memo for ${e.ticker}` },
          el("span", { class: "tk" }, e.ticker),
          e.meets_criteria ? criteriaTag(e) : null,
          e._adhoc ? el("span", { class: "tag-adhoc", title: "Opened from the full-universe roster — no curated analysis yet" }, "not curated") : null,
          el("div", { class: "nm" }, e.name, e.segment ? el("span", { class: "seg" }, e.segment) : null)), () => openMemo(e.ticker)));
      } else {
        tr.append(el("td", { "data-label": c.label, onclick: () => openMemo(e.ticker) }, c.fmt(e)));
      }
    });
    tbody.append(tr);
  });
  const table = el("table"); table.append(el("thead", {}, thead), tbody); wrap.append(table);
}
function setSort(key) {
  if (SORT.key === key) SORT.dir *= -1; else SORT = { key, dir: key === "ticker" ? 1 : -1 };
  render();
}

function criteriaTag(e) {
  const warn = dataChecks(e).filter(c => c.screen);
  return warn.length
    ? el("span", { class: "tag-pass recheck", title: "Passed the screen (cost 🟢, concentration 🟢, purity 🟢/🟡) on the analysed numbers, but the latest fund data disagrees: " + warn.map(c => c.text).join(" ") }, "✓ criteria ⚠ re-check")
    : el("span", { class: "tag-pass", title: "Meets buy criteria: cost 🟢, concentration 🟢, purity 🟢/🟡" }, "✓ criteria");
}

// ---- messages / updates --------------------------------------------
function liveMsg(text, cls, action) {
  const box = $("#liveMsg"); box.hidden = false; box.className = "livemsg " + (cls || "");
  box.textContent = text;
  if (action) box.append(" ", el("button", { class: "refresh", onclick: action.fn }, action.label));
  box.append(el("button", { class: "msgclose", "aria-label": "Dismiss message", onclick: () => { box.hidden = true; } }, "×"));
}
async function onCheckUpdate() {
  const before = MARKET && MARKET.generated_at;
  liveMsg("Checking for newer market data…");
  await loadMarket(true);
  if (!MARKET) {
    liveMsg("Daily market data isn't available yet — it's generated automatically after the next US market close. The hand-researched snapshot is shown meanwhile.", "warn");
    return;
  }
  liveMsg(MARKET.generated_at !== before
    ? `Updated to the ${MARKET.as_of} close.`
    : `Already up to date — the latest data is the ${MARKET.as_of} close. It updates every weekday after the US market close (end-of-day, not intraday). For an intraday price, open a fund and tap “Live quote”.`);
  renderIntro(); render(); renderRoster();
}

// ---- look-up (box + roster) ------------------------------------------
// Theme (other than `except`) holding a curated card for this ticker.
function curatedHome(ticker, except) {
  return Object.values(window._THEMES || {}).find(t => t !== except &&
    (t.etfs || []).some(e => e.ticker === ticker && !e._adhoc)) || null;
}
function rosterEntry(ticker) {
  for (const t of [CURRENT, ...Object.values(window._THEMES || {})]) {
    const r = (t.roster || []).find(x => x.ticker === ticker);
    if (r) return r;
  }
  return null;
}
function goTo(theme, ticker) {
  $("#themeSelect").value = theme._id;
  selectTheme(theme._id);
  openMemo(ticker);
}
function onAddTicker() {
  const inp = $("#addTicker");
  const ticker = inp.value.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, "");
  if (!ticker) { liveMsg("Type a ticker symbol first (e.g. ARKQ).", "warn"); return; }
  $("#addBtn").disabled = true;
  try {
    const home = (CURRENT.etfs || []).some(e => e.ticker === ticker) ? null : curatedHome(ticker, CURRENT);
    if (home) {
      goTo(home, ticker);
      liveMsg(`${ticker} has a full analysis card in the ${home.name} theme — switched there.`);
    } else {
      lookupTicker(ticker, rosterEntry(ticker));
    }
  } finally {
    $("#addBtn").disabled = false;
    inp.value = "";
  }
}

// Open a card for any ticker. Curated → its memo. Otherwise build a card from
// the daily fund data, or an honest stub when we have no data for it.
function lookupTicker(ticker, entry) {
  ticker = String(ticker || "").trim().toUpperCase();
  if (!ticker) return;
  const existing = (CURRENT.etfs || []).find(e => e.ticker === ticker);
  if (existing) { openMemo(ticker); return; }
  const d = daily(ticker);                     // init() already loaded market.json
  CURRENT.etfs.push(d ? makeDailyEtf(ticker, d, entry) : makeStubEtf(ticker, entry));
  render();
  const home = curatedHome(ticker, CURRENT);
  const action = home ? { label: `Full analysis in ${home.name} →`, fn: () => goTo(home, ticker) } : null;
  if (d) {
    liveMsg(`${ticker}: added with the latest daily fund data (${d.price_asof} close). No curated analysis yet in this theme${home ? "" : " — ask Claude to add a full card"}.`, "", action);
  } else {
    const inRoster = (CURRENT.roster || []).some(r => r.ticker === ticker);
    liveMsg(inRoster
      ? `${ticker}: ${failReason(ticker)}`
      : `${ticker} isn't tracked yet, so there's no market data for it here. Ask Claude to add it to a theme and it gets daily data plus an analysis card. Meanwhile “Live quote” in the card opens an external quote page.`, "warn", action);
  }
  openMemo(ticker);
}
const LEVERAGED = /lever|inverse|\b-?\d(\.\d+)?x\b|ultra|bull|bear|daily/i;
function rosterFlags(tag) {
  return tag && LEVERAGED.test(tag)
    ? ["🔴 Leveraged/inverse daily-reset fund — suffers volatility decay; a trading tool, not a buy-and-hold theme investment."]
    : [];
}
// A card built purely from the daily fund data (no curated judgment).
function makeDailyEtf(ticker, d, entry) {
  const name = (entry && entry.name) || d.name || ticker;
  const tag = entry && entry.tag;
  const top = d.holdings && d.holdings[0];
  const stock = !!(d.instrument_type && d.instrument_type !== "ETF");
  return {
    ticker, name, is_theme_fund: true, _adhoc: true, _stock: stock, issuer: d.fund_family || null, holdings_url: null,
    expense_ratio: null, aum_musd: null, aum_display: null,             // erOf()/aumOf() read the daily data
    inception: d.first_trade_date || null, structure: tag || "—", index: "—",
    holdings_count: null, top10_weight_pct: null,
    top10_weight_display: d.top10_weight_pct != null ? `~${d.top10_weight_pct}% (fund data)` : "—",
    largest_position_display: top && top.weight != null ? `${top.weight}% (${top.symbol || top.name})` : "—",
    derivatives: "—", performance: {}, market: {},
    scores: {
      cost: scoreFromExpense(d.expense_ratio),
      purity: { rating: "yellow", note: "Not assessed — no curated analysis yet. Ask Claude to add a full card." },
      concentration: stock ? { rating: "red", note: "A single stock — 100% in one company." } : scoreFromTop10(d.top10_weight_pct),
      liquidity: scoreFromLiquidity(d),
      track_record: { rating: "yellow", note: "Not yet reviewed." },
    },
    overall: "From the full-universe roster — not yet curated.",
    memo: {
      thesis: stock
        ? `${name}${tag ? " — " + tag : ""}. Listed in the roster for reference: it's the single company the theme revolves around, not a fund. The numbers below are its daily market data; ratings are not meaningful for a single stock (it is 100% concentrated by definition).`
        : `${name}${tag ? " — " + tag : ""}. This fund is in the theme's full-universe roster but has no curated analysis yet: the numbers below come straight from the daily fund data, and the ratings are mechanical (cost from the expense ratio, concentration from the top-10 weight, liquidity from AUM and dollar volume). Theme purity needs a human read of the holdings.`,
      purity_verdict: { rating: "yellow", text: "Not assessed — check whether the top holdings below are genuine plays on the theme." },
      holdings_illustrative: [],
      red_flags: [...(d.instrument_type && d.instrument_type !== "ETF" ? ["🔴 This is a single company's stock, not an ETF — no diversification at all."] : []),
        ...rosterFlags(tag), "❓ Not curated — verify against the issuer's fact sheet before acting."],
      bull: [], bear: [],
    },
  };
}
// A minimal "no data" card so a click is never a dead end.
function makeStubEtf(ticker, entry) {
  const name = (entry && entry.name) || ticker;
  const tag = entry && entry.tag;
  const na = note => ({ rating: "yellow", note });
  return {
    ticker, name, is_theme_fund: true, _adhoc: true,
    expense_ratio: null, aum_musd: null, aum_display: null, structure: tag || "—", index: "—",
    holdings_count: null, top10_weight_pct: null, top10_weight_display: "—",
    largest_position_display: "—", derivatives: "—", performance: {}, market: {},
    scores: { cost: na("No data yet."), purity: na("Not assessed."), concentration: na("No data yet."),
      liquidity: na("No data yet."), track_record: na("Not assessed.") },
    overall: "Not tracked yet.",
    memo: {
      thesis: `${name}${tag ? " — " + tag : ""}. This ticker isn't in the daily data feed yet, so there are no figures to show. Ask Claude to add it to a theme: it then gets daily price, volume, returns, AUM and top holdings, plus a curated analysis card.`,
      red_flags: [...rosterFlags(tag), "❓ No data — check the ticker on the issuer's site or via “Live quote”."],
      bull: [], bear: [],
    },
  };
}
function scoreFromExpense(er) {
  if (er == null) return { rating: "yellow", note: "Expense ratio unavailable in the fund data." };
  if (er <= 0.50) return { rating: "green", note: `Expense ratio ${er.toFixed(2)}% (fund data) — reasonable.` };
  if (er <= 0.75) return { rating: "yellow", note: `Expense ratio ${er.toFixed(2)}% (fund data) — typical for thematic.` };
  return { rating: "red", note: `Expense ratio ${er.toFixed(2)}% (fund data) — high.` };
}
function scoreFromTop10(t) {          // thresholds per docs/METHODOLOGY.md (red flag > 50%)
  if (t == null) return { rating: "yellow", note: "Top-10 weight unavailable." };
  if (t <= 40) return { rating: "green", note: `Top-10 ~${t}% (fund data) — well spread.` };
  if (t <= 50) return { rating: "yellow", note: `Top-10 ~${t}% (fund data) — moderately concentrated.` };
  return { rating: "red", note: `Top-10 ~${t}% (fund data) — concentrated.` };
}
function scoreFromLiquidity(d) {
  const a = d.aum_musd, dv = d.dollar_volume_avg;
  if (a == null && dv == null) return { rating: "yellow", note: "AUM/volume unavailable." };
  const parts = [a != null ? `AUM ${fmtMusd(a)}` : null, dv != null ? `${d.dollar_volume_display} traded` : null].filter(Boolean).join(", ");
  if ((a != null && a < 50) || (dv != null && dv < 250e3)) return { rating: "red", note: `${parts} — small/thin: closure and spread risk.` };
  if ((a == null || a >= 500) && (dv == null || dv >= 5e6)) return { rating: "green", note: `${parts} — liquid.` };
  return { rating: "yellow", note: `${parts} — modest; use limit orders and check the bid/ask spread.` };
}

// ---- memo drawer ---------------------------------------------------
function openMemo(ticker) {
  const e = (CURRENT.etfs || []).find(x => x.ticker === ticker); if (!e) return;
  const m = e.memo || {}, d = daily(ticker);
  const body = $("#memoBody"); body.innerHTML = "";
  const wrap = el("div", { class: "memo" });
  const er = erOf(e), a = aumOf(e);
  const kind = e._stock ? "Single stock (not an ETF)" : e._explorer ? "Explorer fund (not curated)" : e._adhoc ? "Roster fund (not curated)" : e.is_theme_fund ? "Theme fund" : "Benchmark / reference";

  wrap.append(
    el("h2", { id: "memoTitle" }, `${e.ticker} — ${e.name}`),
    el("div", { class: "sub" }, `${kind} · Expense ${er == null ? "—" : er.toFixed(2) + "%"} · AUM ${a ? a.display : "—"} · Inception ${e.inception || "—"}`),
    el("div", { class: "liverow" },
      el("a", { class: "holdlink", href: quoteUrl(ticker), target: "_blank", rel: "noopener" }, "↗ Live quote"),
      e.holdings_url ? el("a", { class: "holdlink", href: e.holdings_url, target: "_blank", rel: "noopener" },
        "↗ Official holdings" + (e.issuer ? " (" + e.issuer + ")" : "")) : null),
    el("p", { class: "muted small" }, e._explorer
      ? `Explorer data: ${e.performance.as_of} · updates automatically every weekday.`
      : d
      ? `Market data: ${d.price_asof} close${staleNote(d)} · updates automatically every weekday.`
      : MARKET ? "No daily market data for this ticker yet — figures below are the hand-researched snapshot."
               : "Showing the hand-researched snapshot (daily data not generated yet)."),
    m.thesis ? el("div", { class: "thesis" }, m.thesis) : null
  );

  // Performance: fresh daily figures, falling back to the dated snapshot per tile.
  const Y = d ? +d.price_asof.slice(0, 4) : new Date().getFullYear();
  const tiles = [["YTD", "ytd"], ["1-yr", "y1"], ["3-yr ann.", "y3_annualized"], [String(Y - 1), "y" + (Y - 1)], [String(Y - 2), "y" + (Y - 2)]]
    .map(([lab, k]) => [lab, perfOf(e, k)]).filter(([, p]) => p);
  wrap.append(sectionTitle("Performance"));
  const pf = el("div", { class: "perf" });
  tiles.forEach(([lab, p]) => {
    const n = num(p.v);
    pf.append(el("div", { class: "p" + (p.fresh ? "" : " snap"), title: (GLOSSARY[lab] ? GLOSSARY[lab] + " " : "") + perfTitle(p) },
      el("span", { class: "lab" }, lab),
      el("span", { class: "val " + (n == null ? "muted" : n >= 0 ? "pos" : "neg") }, String(p.v) + (p.priceOnly ? "*" : ""))));
  });
  if (!tiles.length) pf.append(el("div", { class: "p" }, el("span", { class: "lab" }, "returns"), el("span", { class: "val muted" }, "—")));
  wrap.append(pf);
  const fresh = tiles.filter(([, p]) => p.fresh), snap = tiles.filter(([, p]) => !p.fresh);
  const basisTxt = [
    fresh.length ? `${fresh[0][1].priceOnly ? "Price return only (*excludes distributions)" : "Total return with distributions reinvested"}, as of ${fresh[0][1].asof}.` : null,
    snap.length ? `Faded tiles are an older snapshot (${snap[0][1].asof || CURRENT.as_of}).` : null,
    !tiles.length ? (tooNew(e, "y1") ? "The fund is too new for trailing returns." : "No return figures yet.") : null,
  ].filter(Boolean).join(" ");
  if (basisTxt) wrap.append(el("p", { class: "muted small" }, basisTxt));
  if (e.performance && e.performance.note) wrap.append(el("p", { class: "muted small" },
    `Analyst note (${isPlaceholder(e.performance.as_of) ? CURRENT.as_of : e.performance.as_of}): ${e.performance.note}`));

  // Key facts
  const mk = e.market || {};
  const facts = [];
  facts.push(["Price", d && d.price_display ? `${d.price_display} (${d.price_asof} close)` : mk.price_display ? `${mk.price_display} (snapshot ${mk.price_asof || ""})`.trim() : null]);
  facts.push(["Avg daily volume", d && d.volume_display ? `${d.volume_display}${d.dollar_volume_display ? " · " + d.dollar_volume_display : ""}` : mk.volume_display ? `${mk.volume_display} (snapshot)` : null]);
  if (d && d.high_52w != null) facts.push(["52-wk range", `$${d.low_52w} – $${d.high_52w}${d.pct_below_high ? ` (now ${d.pct_below_high === "0.0%" ? "at the high" : d.pct_below_high + " from the high"})` : ""}`]);
  if (d && d.max_drawdown_1y) facts.push(["Max drawdown (1 yr)", d.max_drawdown_1y]);
  facts.push(["AUM", a ? a.display + (a.fresh ? "" : " (snapshot)") : null]);
  let erTxt = e.expense_ratio != null ? e.expense_ratio.toFixed(2) + "%" : null;
  if (d && d.expense_ratio != null) {
    if (erTxt == null) erTxt = d.expense_ratio.toFixed(2) + "% (fund data)";
    else if (Math.abs(d.expense_ratio - e.expense_ratio) >= 0.01) erTxt += ` (fund data shows ${d.expense_ratio.toFixed(2)}% — check the issuer)`;
  }
  facts.push(["Expense ratio", erTxt]);
  if (e.distribution_yield) facts.push(["Distribution yield", e.distribution_yield + " (snapshot)"]);
  if (d && d.yield_ttm) facts.push(["Trailing 12-mo yield", d.yield_ttm]);
  if (e.sec_yield) facts.push(["30-day SEC yield", e.sec_yield]);
  facts.push(["Structure", e.structure], ["Index", e.index], ["# Holdings", e.holdings_count]);
  if (e.listing) facts.push(["Listing", e.listing]);
  if (e.domicile) facts.push(["Domicile", e.domicile]);
  facts.push(["Top-10 weight", [e.top10_weight_display && e.top10_weight_display !== "—" ? e.top10_weight_display : null,
    !e._adhoc && d && d.top10_weight_pct != null ? `latest ~${d.top10_weight_pct}%` : null].filter(Boolean).join(" · ") || null]);
  facts.push(["Largest position", e.largest_position_display], ["Derivatives", e.derivatives]);
  const kv = el("div", { class: "kv" });
  facts.filter(([, v]) => !isPlaceholder(v)).forEach(([k, v]) =>
    kv.append(el("div", { title: GLOSSARY[k] || "" }, el("span", {}, k + ": "), String(v))));
  wrap.append(sectionTitle("Key facts"), kv);

  wrap.append(sectionTitle(e._adhoc ? "Mechanical ratings (not curated)" : "Scored dimensions"));
  ["cost", "purity", "concentration", "liquidity", "track_record"].forEach(dim => {
    const sc = scoreOf(e, dim); if (!sc) return;
    wrap.append(el("p", {}, el("span", { class: "badge " + sc.rating }, RATING_LABEL[sc.rating]),
      " ", el("b", {}, dim.replace("_", " ")), " — ", sc.note));
  });

  const checks = dataChecks(e);
  if (checks.length) {
    const ul = el("ul", { class: "flags" });
    checks.forEach(c => ul.append(el("li", {}, `⚠ ${c.dim.replace("_", " ")}: ${c.text}`)));
    wrap.append(sectionTitle("Data check — latest fund data vs this analysis"), ul,
      el("p", { class: "muted small" }, (e.meets_criteria && checks.some(c => c.screen)
        ? "This fund passed your screen on the analysed numbers; the newer data may change that. "
        : "") + "Ratings are re-scored when the analysis is refreshed — ask Claude to re-check this fund."));
  }

  if (m.strategy) wrap.append(sectionTitle("Strategy"), el("p", {}, m.strategy));

  if (m.purity_verdict) {
    wrap.append(sectionTitle("Theme purity ⭐"));
    wrap.append(el("p", {}, el("span", { class: "badge " + m.purity_verdict.rating }, RATING_LABEL[m.purity_verdict.rating]), " ", m.purity_verdict.text));
  }
  const official = e.holdings_url
    ? el("a", { class: "holdlink", href: e.holdings_url, target: "_blank", rel: "noopener" },
        "Full official holdings list" + (e.issuer ? " from " + e.issuer : "") + " ↗")
    : null;
  if (d && d.holdings && d.holdings.length) {
    wrap.append(sectionTitle(`Top ${d.holdings.length} holdings — latest fund data`));
    const ht = el("table", { class: "hold" });
    d.holdings.forEach(h => {
      const pt = classify(e, h);
      ht.append(el("tr", {},
        el("td", {}, el("b", {}, h.name), h.symbol ? el("span", { class: "muted" }, ` (${h.symbol})`) : null),
        el("td", {}, h.weight != null ? h.weight + "%" : "—"),
        el("td", {}, pt ? el("span", { class: "tag " + pt }, pt) : null)));
    });
    wrap.append(ht, el("p", { class: "muted small" },
      `Via Yahoo Finance/Morningstar (${d.profile_asof || d.price_asof}); can lag the issuer by a few weeks. `, official));
  }
  if (Array.isArray(m.holdings_illustrative) && m.holdings_illustrative.length) {
    wrap.append(sectionTitle("Purity check — analyst classification"));
    const ht = el("table", { class: "hold" });
    m.holdings_illustrative.forEach(h => ht.append(el("tr", {},
      el("td", {}, el("b", {}, h.name)), el("td", {}, h.weight || ""),
      el("td", {}, el("span", { class: "tag " + (h.playtype || "partial") }, h.playtype || "")),
      el("td", { class: "nm" }, h.note || ""))));
    wrap.append(ht, el("p", { class: "muted small" },
      `Hand-classified snapshot (${(e.performance && e.performance.as_of) || CURRENT.as_of || "?"}): pure = direct theme play, partial = some exposure, unrelated = filler. `,
      d && d.holdings && d.holdings.length ? null : official));
  } else if (!(d && d.holdings && d.holdings.length) && official) {
    wrap.append(el("p", { class: "muted small" }, official));
  }

  if (m.concentration) wrap.append(sectionTitle("Concentration & risk"), el("p", {}, m.concentration));
  if (d && d.sectors && d.sectors.length) {
    wrap.append(sectionTitle("Sectors — latest fund data"), el("p", {}, d.sectors.map(s => `${s.sector} ${s.weight}%`).join(" · ")));
  }
  if (m.sector_geo) wrap.append(sectionTitle("Sector & geography (analyst)"), el("p", {}, m.sector_geo));
  if (m.cost_context) wrap.append(sectionTitle("Cost in context"), el("p", {}, m.cost_context));
  if (m.track_record_note) wrap.append(sectionTitle("Track record"), el("p", {}, m.track_record_note));

  if (Array.isArray(m.red_flags) && m.red_flags.length) {
    const ul = el("ul", { class: "flags" }); m.red_flags.forEach(f => ul.append(el("li", {}, f)));
    wrap.append(sectionTitle("Red flags"), ul);
  }
  if ((m.bull && m.bull.length) || (m.bear && m.bear.length)) {
    const bb = el("div", { class: "bb" });
    bb.append(colList("bull", "Bull case", m.bull), colList("bear", "Bear case", m.bear));
    wrap.append(sectionTitle("Bull vs Bear"), bb);
  }
  if (Array.isArray(m.decision_log) && m.decision_log.length) {
    wrap.append(sectionTitle("Decision log"));
    m.decision_log.forEach(x => wrap.append(el("div", { class: "dlog" },
      el("span", { class: "act" }, `${x.date} — ${x.action}: `), x.text)));
  }

  body.append(wrap);
  const drawer = $("#memoDrawer");
  $("#overlay").hidden = false; drawer.hidden = false;
  drawer.scrollTop = 0;
  document.body.classList.add("noscroll");
  $("#closeMemo").focus({ preventScroll: true });
}
// Match a fund-data holding to the analyst's classification, if we have one.
function classify(e, h) {
  const known = (e.memo && e.memo.holdings_illustrative) || [];
  const sym = String(h.symbol || "").toUpperCase().split(/[.\s]/)[0];
  const word = String(h.name || "").toLowerCase().match(/[a-z0-9]{4,}/);
  const hit = known.find(k => {
    const kn = String(k.name || "");
    if (sym.length >= 2 && new RegExp(`(^|[^A-Z0-9])${escapeRe(sym)}([^A-Z0-9]|$)`).test(kn.toUpperCase())) return true;
    return word && kn.toLowerCase().startsWith(word[0]);
  });
  return hit ? hit.playtype : null;
}
function colList(cls, title, items) {
  const col = el("div", { class: "col " + cls }); col.append(el("h4", {}, title));
  const ul = el("ul"); (items || []).forEach(x => ul.append(el("li", {}, x))); col.append(ul); return col;
}
const sectionTitle = t => el("h3", {}, t);
function closeMemo() {
  $("#overlay").hidden = true; $("#memoDrawer").hidden = true;
  document.body.classList.remove("noscroll");
}

init();
