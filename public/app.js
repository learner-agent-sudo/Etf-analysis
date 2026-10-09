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

const THEME_FILES = ["quantum", "space", "income", "pharma", "ai-robotics", "nuclear", "cybersecurity", "water", "rare-earths", "glp1"];  // order in the picker

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
const fmtMusd = a => a >= 1000 ? `~$${(a / 1000).toFixed(1)}B` : `~$${a}M`;
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
// Why the daily feed has no data for a ticker (closed, non-US, wrong ticker…).
function failReason(t) {
  const f = MARKET && MARKET.failed;
  const r = f && !Array.isArray(f) ? f[t] : null;
  return "Not found in the daily market data" + (r && /not listed/i.test(r) ? " — the fund may have closed, be listed outside the US, or the ticker may be wrong." : ".") + " Verify on the issuer's site.";
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
  if (e.aum_display || e.aum_musd != null) return { musd: e.aum_musd, display: e.aum_display || fmtMusd(e.aum_musd), fresh: false };
  return null;
}
function aumCell(e) {
  const a = aumOf(e);
  if (!a) return nodata("AUM");
  return a.fresh ? el("span", { title: `Net assets per fund data (${a.asof || "latest"})` }, a.display)
                 : el("span", { class: "snap", title: snapTitle("AUM", CURRENT && CURRENT.as_of) }, a.display);
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
    if (m.price_display) return el("span", { class: "snap", title: snapTitle("Price", m.price_asof) }, m.price_display);
    return nodata("Price");
  }
  if (d && d.volume_display) return el("span", { title: `Average shares/day over 3 months (${d.dollar_volume_display || "?"} in dollars)${staleNote(d)}` }, d.volume_display);
  if (m.volume_display) return el("span", { class: "snap", title: snapTitle("Average volume", m.price_asof) }, m.volume_display);
  return nodata("Volume");
}
// A return figure: fresh daily data first, else the dated snapshot.
function perfOf(e, key) {
  const d = daily(e.ticker), dp = d && d.performance;
  if (dp && !isPlaceholder(dp[key])) return { v: dp[key], fresh: true, asof: dp.as_of, priceOnly: /^price/.test(dp.basis || "") };
  const sp = e.performance;
  if (sp && !isPlaceholder(sp[key])) return { v: sp[key], fresh: false, asof: sp.as_of };
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
const themeFromUrl = () => decodeURIComponent(location.hash.replace(/^#/, ""));
function savedTheme() { try { return localStorage.getItem("etf.theme"); } catch (_) { return null; } }

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
  $("#addBtn").addEventListener("click", onAddTicker);
  $("#addTicker").addEventListener("keydown", e => { if (e.key === "Enter") onAddTicker(); });
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
  selectTheme(first);
  window.addEventListener("hashchange", () => {
    const h = themeFromUrl();
    if (h && window._THEMES[h] && h !== CURRENT._id) { sel.value = h; selectTheme(h); }
  });
}

function selectTheme(id) {
  CURRENT = window._THEMES[id];
  if (!activeColumns().some(c => c.key === SORT.key)) SORT = { key: "ticker", dir: 1 };
  $("#controls").hidden = false;
  $("#liveMsg").hidden = true;
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
    "Every US-listed fund tagged to this theme, including leveraged/inverse and niche variants (clearly tagged). " +
    "✓ = full analysis card above. The others open a card with the latest daily fund data (price, returns, AUM, top holdings) — ask Claude to add a full analysis.");
  const grid = el("div", { class: "rostergrid" });
  roster.slice().sort((a, b) => a.ticker.localeCompare(b.ticker)).forEach(x => {
    const isDet = curated.has(x.ticker);
    const d = daily(x.ticker);
    const y1 = d && d.performance && d.performance.y1;
    const n = num(y1);
    const why = !d && MARKET ? failReason(x.ticker) : null;
    const row = pressable(el("div", { class: "rosteritem" + (isDet ? " detailed" : ""),
      title: isDet ? "Full analysis card — click to open" : "Click to open this fund's daily data" },
      el("span", { class: "rtk" }, (isDet ? "✓ " : "") + x.ticker),
      x.tag ? el("span", { class: "rtag" }, x.tag) : null,
      el("span", { class: "rnm" }, x.name || ""),
      y1 ? el("span", { class: "rperf " + (n >= 0 ? "pos" : "neg"), title: "1-yr return (daily data)" }, y1) : null,
      why ? el("span", { class: "rnodata", title: why }, "⚠ no data") : null),
      () => isDet ? openMemo(x.ticker) : lookupTicker(x.ticker, x));
    grid.append(row);
  });
  det.append(note, grid);
  box.append(det);
}

// ---- table ---------------------------------------------------------
function visibleEtfs() {
  const q = $("#filterBox").value.trim().toLowerCase();
  const rdim = $("#ratingDim").value, rval = $("#ratingVal").value;
  let rows = (CURRENT.etfs || []).slice();
  if ($("#themeOnly").checked) rows = rows.filter(e => e.is_theme_fund);
  if ($("#passOnly").checked) rows = rows.filter(e => e.meets_criteria);
  if (q) rows = rows.filter(e => (e.ticker + " " + e.name).toLowerCase().includes(q));
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
          sc ? el("span", { class: "dot " + sc.rating }) : "—", sc ? RATING_LABEL[sc.rating] : ""));
      } else if (c.key === "ticker") {
        tr.append(pressable(el("td", { class: "col-ticker", "aria-label": `Open the memo for ${e.ticker}` },
          el("span", { class: "tk" }, e.ticker),
          e.meets_criteria ? el("span", { class: "tag-pass", title: "Meets buy criteria: cost 🟢, concentration 🟢, purity 🟢/🟡" }, "✓ criteria") : null,
          e._adhoc ? el("span", { class: "tag-adhoc", title: "Opened from the full-universe roster — no curated analysis yet" }, "not curated") : null,
          el("div", { class: "nm" }, e.name)), () => openMemo(e.ticker)));
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
  return {
    ticker, name, is_theme_fund: true, _adhoc: true, issuer: d.fund_family || null, holdings_url: null,
    expense_ratio: null, aum_musd: null, aum_display: null,             // erOf()/aumOf() read the daily data
    inception: d.first_trade_date || null, structure: tag || "—", index: "—",
    holdings_count: null, top10_weight_pct: null,
    top10_weight_display: d.top10_weight_pct != null ? `~${d.top10_weight_pct}% (fund data)` : "—",
    largest_position_display: top && top.weight != null ? `${top.weight}% (${top.symbol || top.name})` : "—",
    derivatives: "—", performance: {}, market: {},
    scores: {
      cost: scoreFromExpense(d.expense_ratio),
      purity: { rating: "yellow", note: "Not assessed — no curated analysis yet. Ask Claude to add a full card." },
      concentration: scoreFromTop10(d.top10_weight_pct),
      liquidity: scoreFromLiquidity(d),
      track_record: { rating: "yellow", note: "Not yet reviewed." },
    },
    overall: "From the full-universe roster — not yet curated.",
    memo: {
      thesis: `${name}${tag ? " — " + tag : ""}. This fund is in the theme's full-universe roster but has no curated analysis yet: the numbers below come straight from the daily fund data, and the ratings are mechanical (cost from the expense ratio, concentration from the top-10 weight, liquidity from AUM and dollar volume). Theme purity needs a human read of the holdings.`,
      purity_verdict: { rating: "yellow", text: "Not assessed — check whether the top holdings below are genuine plays on the theme." },
      holdings_illustrative: [],
      red_flags: [...rosterFlags(tag), "❓ Not curated — verify against the issuer's fact sheet before acting."],
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
  const kind = e._adhoc ? "Roster fund (not curated)" : e.is_theme_fund ? "Theme fund" : "Benchmark / reference";

  wrap.append(
    el("h2", { id: "memoTitle" }, `${e.ticker} — ${e.name}`),
    el("div", { class: "sub" }, `${kind} · Expense ${er == null ? "—" : er.toFixed(2) + "%"} · AUM ${a ? a.display : "—"} · Inception ${e.inception || "—"}`),
    el("div", { class: "liverow" },
      el("a", { class: "holdlink", href: quoteUrl(ticker), target: "_blank", rel: "noopener" }, "↗ Live quote"),
      e.holdings_url ? el("a", { class: "holdlink", href: e.holdings_url, target: "_blank", rel: "noopener" },
        "↗ Official holdings" + (e.issuer ? " (" + e.issuer + ")" : "")) : null),
    el("p", { class: "muted small" }, d
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
  if (e.performance && e.performance.note) wrap.append(el("p", { class: "muted small" }, `Analyst note (${e.performance.as_of || "snapshot"}): ${e.performance.note}`));

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
