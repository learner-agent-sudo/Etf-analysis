"use strict";

// ====================================================================
// Explorer — every listed ETF, searchable and sortable, with mechanical
// cost / size ratings. Data: data/universe-<market>.json, rebuilt every
// weekday by scripts/build_universe.py; loaded only when the Explorer opens.
// Shares helpers with app.js (el, $, daily, openMemo, curatedHome, …).
// ====================================================================

const UNIVERSE_FILES = [{ market: "US", label: "US", file: "data/universe-us.json" }];
const EX_PAGE = 100;
let UNIVERSE = null;                      // { rows: [...], meta: { US: {...} } }
const EX = { sort: { key: "aum", dir: -1 }, shown: EX_PAGE };
// Pseudo-theme that holds the cards opened from the Explorer, so the shared
// memo drawer (which reads CURRENT) works unchanged.
const EXPLORE = { _id: "explore", name: "Explorer", as_of: "", etfs: [], roster: [] };

const CUR_SYM = { USD: "$", GBP: "£", EUR: "€", HKD: "HK$" };
const money = (v, cur) => v == null ? null : `${CUR_SYM[cur] || (cur ? cur + " " : "$")}${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmtMoneyM = (m, cur) => { const s = CUR_SYM[cur] || "$";
  return m >= 1e6 ? `~${s}${(m / 1e6).toFixed(1)}T` : m >= 1000 ? `~${s}${(m / 1000).toFixed(1)}B` : `~${s}${Math.round(m)}M`; };
const fmtDollarVol = (v, cur) => v == null ? null
  : v >= 1e6 ? fmtMoneyM(v / 1e6, cur) + "/day" : `~${CUR_SYM[cur] || "$"}${Math.round(v / 1e3)}K/day`;
const signed = v => v == null ? null : `${v > 0 ? "+" : ""}${v}%`;
const shares = v => v == null ? null : v >= 1e6 ? `~${(v / 1e6).toFixed(1)}M/day` : v >= 1e3 ? `~${Math.round(v / 1e3)}K/day` : `~${v}/day`;
const costRating = er => er == null ? null : er <= 0.50 ? "green" : er <= 0.75 ? "yellow" : "red";
const sizeRating = aum => aum == null ? null : aum >= 500 ? "green" : aum >= 50 ? "yellow" : "red";
const FLAG_TEXT = { L: "leveraged/inverse", N: "ETN", F: "futures-based" };

async function loadUniverse() {
  if (UNIVERSE) return UNIVERSE;
  const rows = [], meta = {};
  await Promise.all(UNIVERSE_FILES.map(async f => {
    try {
      const j = await fetchJson(f.file);
      meta[f.market] = { as_of: j.as_of, count: j.count, currency: j.currency, domicile: j.domicile, source: j.source, label: f.label };
      j.rows.forEach(r => {
        const o = { mkt: f.market, cur: j.currency, dom: j.domicile };
        j.cols.forEach((c, i) => { o[c] = r[i]; });
        rows.push(o);
      });
    } catch (_) { /* market not built yet */ }
  }));
  UNIVERSE = { rows, meta };
  EXPLORE.as_of = Object.values(meta).map(m => m.as_of).sort().pop() || "";
  return UNIVERSE;
}

// Theme membership: the theme's own tickers + its keyword list (theme JSON).
let THEME_TESTS = null;
function themeTests() {
  if (THEME_TESTS) return THEME_TESTS;
  THEME_TESTS = Object.values(window._THEMES || {}).map(t => {
    const own = new Set([...(t.etfs || []).filter(e => !e._adhoc).map(e => e.ticker), ...(t.roster || []).map(r => r.ticker)]);
    const kws = t.keywords || [];
    const re = kws.length ? new RegExp("(^|[^a-z0-9])(" + kws.map(escapeRe).join("|") + ")", "i") : null;
    return { id: t._id, name: t.name, own, re };
  });
  return THEME_TESTS;
}
function themesOf(r) {
  if (!r._th) r._th = themeTests().filter(x => x.own.has(r.t) || (x.re && x.re.test(r.n))).map(x => x.id);
  return r._th;
}

// ---- view ------------------------------------------------------------
async function showExplorer(themeId) {
  setView("explore");
  const box = $("#explorer");
  if (!UNIVERSE) box.innerHTML = '<p class="muted">Loading every listed ETF…</p>';
  await loadUniverse();
  if (!box.dataset.built) buildExplorer(box);
  if (themeId !== undefined) { $("#exTheme").value = themeId || ""; $("#exQ").value = ""; }
  EX.shown = EX_PAGE;
  CURRENT = EXPLORE;
  renderExplorer();
}

function buildExplorer(box) {
  box.innerHTML = "";
  box.dataset.built = "1";
  const metas = Object.values(UNIVERSE.meta);
  if (!metas.length) {
    box.append(el("p", { class: "livemsg warn" }, "The Explorer data hasn't been generated yet — it's built automatically after the next daily update."));
    return;
  }
  const total = UNIVERSE.rows.length;
  box.append(
    el("div", { class: "intro" },
      el("h2", {}, "ETF Explorer"),
      el("div", { class: "asof" }, `${total.toLocaleString()} listed ETFs · ${metas.map(m => `${m.label} ${m.count.toLocaleString()} (data ${m.as_of})`).join(" · ")} · updates every weekday`),
      el("p", { class: "universe" }, "▸ Every listed ETF in one searchable list. Cost and Size are mechanical (from the expense ratio and fund size); purity and concentration need a human read of the holdings — open any fund, or ask Claude to add it to a theme for the full analysis. Hong Kong and London listings are being added next.")),
    el("section", { class: "controls" },
      el("input", { type: "search", id: "exQ", placeholder: "Search ticker or name (e.g. uranium, covered call, QQQ)…", "aria-label": "Search ETFs" }),
      el("select", { id: "exMarket", "aria-label": "Market" }, el("option", { value: "" }, "All markets"),
        ...UNIVERSE_FILES.filter(f => UNIVERSE.meta[f.market]).map(f => el("option", { value: f.market }, f.label))),
      el("select", { id: "exTheme", "aria-label": "Theme" }, el("option", { value: "" }, "Any theme"),
        ...Object.values(window._THEMES || {}).map(t => el("option", { value: t._id }, t.name))),
      el("select", { id: "exAum", "aria-label": "Minimum fund size" }, el("option", { value: "" }, "Any size"),
        ...[[50, "AUM ≥ $50M"], [100, "AUM ≥ $100M"], [1000, "AUM ≥ $1B"], [10000, "AUM ≥ $10B"]].map(([v, l]) => el("option", { value: v }, l))),
      el("select", { id: "exEr", "aria-label": "Maximum expense ratio" }, el("option", { value: "" }, "Any expense"),
        ...[[0.1, "Expense ≤ 0.10%"], [0.2, "≤ 0.20%"], [0.5, "≤ 0.50%"], [0.75, "≤ 0.75%"]].map(([v, l]) => el("option", { value: v }, l))),
      el("label", { class: "toggle", title: "Hide leveraged/inverse funds, exchange-traded notes and futures-based products" },
        el("input", { type: "checkbox", id: "exPlain", checked: "checked" }), "Plain ETFs only"),
      el("label", { class: "toggle pass-toggle", title: "Cost 🟢 (expense ≤ 0.50%), AUM ≥ $50M, not leveraged / ETN / futures" },
        el("input", { type: "checkbox", id: "exPre" }), "✓ Pre-screen")),
    el("div", { id: "exCount", class: "muted small" }),
    el("section", { id: "exTable", class: "table-wrap" }),
    el("div", { class: "exmore" }, el("button", { id: "exMore", class: "refresh" }, "Show more")),
    el("p", { class: "muted small" }, "1-yr price = 52-week change in the share price only (excludes distributions — income and bond funds look worse than their real return). YTD = total return as reported by Yahoo Finance. Sources: " +
      metas.map(m => m.source).join(" ")));
  let t = null;
  $("#exQ").addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { EX.shown = EX_PAGE; renderExplorer(); }, 150); });
  ["exMarket", "exTheme", "exAum", "exEr", "exPlain", "exPre"].forEach(id =>
    $("#" + id).addEventListener("change", () => { EX.shown = EX_PAGE; renderExplorer(); }));
  $("#exMore").addEventListener("click", () => { EX.shown += EX_PAGE; renderExplorer(); });
}

function exFiltered() {
  const words = $("#exQ").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const mkt = $("#exMarket").value, th = $("#exTheme").value;
  const aumMin = +$("#exAum").value || 0, erMax = $("#exEr").value === "" ? null : +$("#exEr").value;
  const plain = $("#exPlain").checked, pre = $("#exPre").checked;
  return UNIVERSE.rows.filter(r =>
    (!mkt || r.mkt === mkt) &&
    (!plain || !r.f) &&
    (!pre || (costRating(r.er) === "green" && (r.aum || 0) >= 50 && !r.f)) &&
    (!aumMin || (r.aum || 0) >= aumMin) &&
    (erMax == null || (r.er != null && r.er <= erMax)) &&
    (!words.length || words.every(w => r.t.toLowerCase().includes(w) || r.n.toLowerCase().includes(w))) &&
    (!th || themesOf(r).includes(th)));
}
function exVal(r, key) {
  if (key === "_cost") { const c = costRating(r.er); return c ? SCORE_RANK[c] : null; }
  if (key === "_size") { const c = sizeRating(r.aum); return c ? SCORE_RANK[c] : null; }
  return r[key];
}
function exCmp(a, b) {
  const { key, dir } = EX.sort;
  const va = exVal(a, key), vb = exVal(b, key);
  if (va == null || vb == null) return va == null && vb == null ? a.t.localeCompare(b.t) : (va == null ? 1 : -1);
  if (typeof va === "string") return va.localeCompare(vb) * dir;
  return (va - vb) * dir || a.t.localeCompare(b.t);
}

const EX_COLS = [
  { key: "t", label: "Ticker" },
  { key: "er", label: "Expense", fmt: r => r.er == null ? nodata("Expense ratio") : r.er.toFixed(2) + "%" },
  { key: "aum", label: "AUM", fmt: r => r.aum == null ? nodata("AUM") : fmtMoneyM(r.aum, r.cur) },
  { key: "p", label: "Price", fmt: r => money(r.p, r.cur) || nodata("Price") },
  { key: "c1y", label: "1-yr price", fmt: r => pctSpan(r.c1y) },
  { key: "ytd", label: "YTD", fmt: r => pctSpan(r.ytd) },
  { key: "yld", label: "Yield", when: () => UNIVERSE.rows.filter(r => r.yld != null).length > UNIVERSE.rows.length * 0.3,
    fmt: r => r.yld == null ? el("span", { class: "muted" }, "—") : r.yld.toFixed(2) + "%" },
  { key: "vol", label: "Avg Vol", fmt: r => shares(r.vol) || nodata("Volume") },
  { key: "_cost", label: "Cost", score: r => costRating(r.er), help: "Mechanical: expense ≤ 0.50% 🟢, ≤ 0.75% 🟡, higher 🔴." },
  { key: "_size", label: "Size", score: r => sizeRating(r.aum), help: "Mechanical: AUM ≥ $500M 🟢, ≥ $50M 🟡, smaller 🔴 (closure risk)." },
];
function pctSpan(v) {
  if (v == null) return el("span", { class: "muted" }, "—");
  return el("span", { class: v >= 0 ? "pos" : "neg" }, signed(v));
}

function renderExplorer() {
  if (!UNIVERSE || !$("#exTable")) return;
  const all = exFiltered().sort(exCmp);
  const rows = all.slice(0, EX.shown);
  $("#exCount").textContent = `${all.length.toLocaleString()} match${all.length === 1 ? "" : "es"} · showing ${rows.length.toLocaleString()} · click a header to sort, a row for details`;
  $("#exMore").hidden = rows.length >= all.length;
  const wrap = $("#exTable"); wrap.innerHTML = "";
  if (!rows.length) {
    wrap.append(el("div", { class: "empty" }, "No ETFs match. Try a broader search or fewer filters."));
    return;
  }
  const cols = EX_COLS.filter(c => !c.when || c.when());
  const head = el("tr");
  cols.forEach(c => {
    const active = EX.sort.key === c.key, def = c.help || GLOSSARY[c.label];
    head.append(el("th", { title: def || c.label, class: def ? "has-help" : "", onclick: () => {
      EX.sort = EX.sort.key === c.key ? { key: c.key, dir: -EX.sort.dir } : { key: c.key, dir: c.key === "t" || c.key === "er" ? 1 : -1 };
      renderExplorer();
    } }, c.label, def ? el("span", { class: "qmark" }, "ⓘ") : null,
      active ? el("span", { class: "arrow" }, EX.sort.dir > 0 ? " ▲" : " ▼") : null));
  });
  const body = el("tbody");
  const homes = curatedIndex();
  rows.forEach(r => {
    const tr = el("tr", {});
    cols.forEach(c => {
      if (c.key === "t") {
        const chips = themesOf(r).map(id => (window._THEMES[id] || {}).name).filter(Boolean).slice(0, 2);
        tr.append(pressable(el("td", { class: "col-ticker", "aria-label": `Open ${r.t}` },
          el("span", { class: "tk" }, r.t),
          homes.has(r.t) ? el("span", { class: "tag-pass", title: "Has a full analysis card in a theme" }, "✓ analysed") : null,
          r.f ? el("span", { class: "tag-adhoc", title: [...r.f].map(x => FLAG_TEXT[x]).join(", ") }, [...r.f].map(x => FLAG_TEXT[x]).join(" · ")) : null,
          el("div", { class: "nm" }, r.n, ...chips.map(n => el("span", { class: "seg" }, n)), r.mkt !== "US" ? el("span", { class: "seg" }, r.mkt) : null)),
          () => exOpen(r)));
      } else if (c.score) {
        const rt = c.score(r);
        tr.append(el("td", { class: "cellscore", "data-label": c.label, onclick: () => exOpen(r) },
          rt ? el("span", { class: "score" }, el("span", { class: "dot " + rt }), RATING_LABEL[rt]) : "—"));
      } else {
        tr.append(el("td", { "data-label": c.label, onclick: () => exOpen(r) }, c.fmt(r)));
      }
    });
    body.append(tr);
  });
  const table = el("table"); table.append(el("thead", {}, head), body); wrap.append(table);
}

let CURATED_INDEX = null;
function curatedIndex() {
  if (!CURATED_INDEX) CURATED_INDEX = new Set(Object.values(window._THEMES || {})
    .flatMap(t => (t.etfs || []).filter(e => !e._adhoc).map(e => e.ticker)));
  return CURATED_INDEX;
}

// Open a fund from the Explorer: curated card if one exists, else a card from
// the daily data (when the fund is in a theme roster) or the universe row.
function exOpen(r) {
  const home = curatedHome(r.t, null);
  if (home) {
    goTo(home, r.t);
    liveMsg(`${r.t} has a full analysis card in the ${home.name} theme — opened it there.`, "", { label: "← Back to Explorer", fn: () => showExplorer() });
    return;
  }
  if (!EXPLORE.etfs.some(e => e.ticker === r.t)) {
    const d = daily(r.t);
    EXPLORE.etfs.push(d ? makeDailyEtf(r.t, d, { name: r.n }) : makeUniverseEtf(r));
  }
  openMemo(r.t);
}

function makeUniverseEtf(r) {
  const flagged = [...(r.f || "")].map(x => FLAG_TEXT[x]);
  const dv = r.p != null && r.vol != null ? r.p * r.vol : null;
  const asof = (UNIVERSE.meta[r.mkt] || {}).as_of;
  return {
    ticker: r.t, name: r.n, is_theme_fund: true, _adhoc: true, _fresh: true, _explorer: true,
    issuer: null, holdings_url: null,
    expense_ratio: r.er, aum_musd: r.aum != null ? Math.round(r.aum) : null,
    aum_display: r.aum != null ? fmtMoneyM(r.aum, r.cur) : null, inception: r.inc,
    structure: flagged.length ? flagged.join(" · ") : "—", index: "—", holdings_count: null,
    top10_weight_pct: null, top10_weight_display: "—", largest_position_display: "—",
    derivatives: /L|F/.test(r.f || "") ? "Yes — swaps / futures" : "—",
    performance: { ytd: signed(r.ytd), as_of: asof,
      note: r.c1y != null ? `52-week share-price change: ${signed(r.c1y)} (excludes distributions).` : null },
    market: { price: r.p, price_display: money(r.p, r.cur), price_asof: asof, volume_avg: r.vol, volume_display: shares(r.vol) },
    scores: {
      cost: scoreFromExpense(r.er),
      purity: { rating: "yellow", note: "Not assessed — Explorer funds have mechanical data only." },
      concentration: { rating: "yellow", note: "Holdings aren't loaded for Explorer funds — add the fund to a theme to get its top-10 breakdown." },
      liquidity: scoreFromLiquidity({ aum_musd: r.aum != null ? Math.round(r.aum) : null, dollar_volume_avg: dv,
        dollar_volume_display: fmtDollarVol(dv, r.cur) }),
      track_record: { rating: "yellow", note: r.inc ? `Listed since ${r.inc}.` : "Inception unknown." },
    },
    overall: "Explorer fund — mechanical data only.",
    memo: {
      thesis: `${r.n} — listed on ${r.x || r.mkt}${r.dom ? " (" + r.dom + "-domiciled)" : ""}. This card comes from the Explorer (every listed ETF), so it shows the daily basics only: no holdings, purity or risk analysis yet. Ask Claude to add it to a theme for the full treatment.`,
      red_flags: [
        ...(/L/.test(r.f || "") ? ["🔴 Leveraged/inverse daily-reset fund — suffers volatility decay; a trading tool, not a buy-and-hold investment."] : []),
        ...(/N/.test(r.f || "") ? ["⚠️ ETN: an unsecured note — you carry the issuer's credit risk, and it holds no basket of assets."] : []),
        ...(/F/.test(r.f || "") ? ["⚠️ Futures-based: returns can lag the spot price badly (roll costs / contango)."] : []),
        "❓ Not curated — verify against the issuer's fact sheet before acting."],
      bull: [], bear: [],
    },
  };
}
