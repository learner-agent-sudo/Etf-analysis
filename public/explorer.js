"use strict";

// ====================================================================
// Explorer — every listed ETF, searchable and sortable, with mechanical
// cost / size ratings. Data: data/universe-<market>.json, rebuilt every
// weekday by scripts/build_universe.py; loaded only when the Explorer opens.
// Shares helpers with app.js (el, $, daily, openMemo, curatedHome, …).
// ====================================================================

const UNIVERSE_FILES = [
  { market: "US", label: "US", file: "data/universe-us.json" },
  { market: "HK", label: "Hong Kong", file: "data/universe-hk.json" },
  { market: "LSE", label: "London", file: "data/universe-lse.json" },
];
// Domicile buckets for the filter (codes come from the ISIN, or the market).
const DOMICILES = [["US", "US-domiciled"], ["IE/LU", "Ireland / Luxembourg (UCITS)"], ["HK", "Hong Kong"], ["other", "Other"]];
const domBucket = d => !d ? "other" : d === "US" ? "US" : d === "HK" ? "HK" : /^(IE|LU|IE\/LU)$/.test(d) ? "IE/LU" : "other";
const DOM_TEXT = { US: "US-domiciled", HK: "HK-domiciled", IE: "Irish UCITS", LU: "Luxembourg UCITS", "IE/LU": "UCITS (Ireland/Lux)", GB: "UK-domiciled", SG: "Singapore-domiciled" };
const aumUsd = r => r.aumu != null ? r.aumu : (r.cur === "USD" || !r.cur ? r.aum : null);
const aumCur = r => r.acur || r.cur || "USD";        // AUM is in the fund's base currency
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
  const metas = UNIVERSE_FILES.map(f => UNIVERSE.meta[f.market]).filter(Boolean);   // fixed order
  if (!metas.length) {
    box.append(el("p", { class: "livemsg warn" }, "The Explorer data hasn't been generated yet — it's built automatically after the next daily update."));
    return;
  }
  const total = UNIVERSE.rows.length;
  box.append(
    el("div", { class: "intro" },
      el("h2", {}, "ETF Explorer"),
      el("div", { class: "asof" }, `${total.toLocaleString()} listed ETFs · ${metas.map(m => `${m.label} ${m.count.toLocaleString()} (data ${m.as_of})`).join(" · ")} · updates every weekday`),
      el("p", { class: "universe" }, "▸ Every listed ETF in one searchable list. Cost and Size are quick traffic lights worked out automatically from each fund's yearly fee and how much money it manages (tap ⓘ on any column for what it means). Whether a fund's holdings match its name, or rest on a few stocks, needs a human read — open any fund, or ask Claude to add it to a theme for the full analysis."),
      taxExplainer()),
    el("section", { class: "controls" },
      el("input", { type: "search", id: "exQ", placeholder: "Search ticker or name (e.g. uranium, covered call, QQQ)…", "aria-label": "Search ETFs" }),
      el("select", { id: "exMarket", "aria-label": "Market" }, el("option", { value: "" }, "All markets"),
        ...UNIVERSE_FILES.filter(f => UNIVERSE.meta[f.market]).map(f => el("option", { value: f.market }, f.label))),
      el("select", { id: "exTheme", "aria-label": "Theme" }, el("option", { value: "" }, "Any theme"),
        ...Object.values(window._THEMES || {}).map(t => el("option", { value: t._id }, t.name))),
      el("span", { class: "withhelp" }, el("select", { id: "exDom", "aria-label": "Domicile" }, el("option", { value: "" }, "Any domicile"),
        ...DOMICILES.map(([v, l]) => el("option", { value: v }, l))), helpBtn("Domicile", DOM_HELP)),
      el("select", { id: "exAum", "aria-label": "Minimum fund size" }, el("option", { value: "" }, "Any size"),
        ...[[50, "AUM ≥ US$50M"], [100, "AUM ≥ US$100M"], [1000, "AUM ≥ US$1B"], [10000, "AUM ≥ US$10B"]].map(([v, l]) => el("option", { value: v }, l))),
      el("select", { id: "exEr", "aria-label": "Maximum expense ratio" }, el("option", { value: "" }, "Any expense"),
        ...[[0.1, "Expense ≤ 0.10%"], [0.2, "≤ 0.20%"], [0.5, "≤ 0.50%"], [0.75, "≤ 0.75%"]].map(([v, l]) => el("option", { value: v }, l))),
      el("span", { class: "withhelp" }, el("label", { class: "toggle" },
        el("input", { type: "checkbox", id: "exPlain", checked: "checked" }), "Plain ETFs only"), helpBtn("Plain ETFs only", PLAIN_HELP)),
      el("span", { class: "withhelp" }, el("label", { class: "toggle pass-toggle" },
        el("input", { type: "checkbox", id: "exPre" }), "✓ Pre-screen"), helpBtn("Pre-screen", PRESCREEN_HELP))),
    el("p", { id: "exPreNote", class: "prenote", hidden: "hidden" }),
    el("div", { id: "exCount", class: "muted small" }),
    columnGuide([...exCols().map(c => [c.label, EX_HELP[c.key]]), ["✓ Pre-screen (filter)", PRESCREEN_HELP], ["Plain ETFs only (filter)", PLAIN_HELP]],
      "What do these columns and filters mean? (Cost, Size, Pre-screen …)"),
    el("section", { id: "exTable", class: "table-wrap" }),
    el("div", { class: "exmore" }, el("button", { id: "exMore", class: "refresh" }, "Show more")),
    el("p", { class: "muted small" }, "1-yr price = 52-week change in the share price only (excludes distributions — income and bond funds look worse than their real return). YTD = total return as reported by Yahoo Finance. " +
      "AUM is shown in the fund's reporting currency (≈ US$ on hover) and is approximate for London lines: several share classes of one fund report the same fund-wide total. Sources: " +
      metas.map(m => m.source).join(" ")));
  let t = null;
  $("#exQ").addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { EX.shown = EX_PAGE; renderExplorer(); }, 150); });
  ["exMarket", "exTheme", "exDom", "exAum", "exEr", "exPlain", "exPre"].forEach(id =>
    $("#" + id).addEventListener("change", () => { EX.shown = EX_PAGE; renderExplorer(); }));
  $("#exMore").addEventListener("click", () => { EX.shown += EX_PAGE; renderExplorer(); });
}

const passesPrescreen = r => costRating(r.er) === "green" && (aumUsd(r) || 0) >= 50 && !r.f;
function exFiltered(pre = $("#exPre").checked) {
  const words = $("#exQ").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const mkt = $("#exMarket").value, th = $("#exTheme").value;
  const aumMin = +$("#exAum").value || 0, erMax = $("#exEr").value === "" ? null : +$("#exEr").value;
  const plain = $("#exPlain").checked, dom = $("#exDom").value;
  return UNIVERSE.rows.filter(r =>
    (!mkt || r.mkt === mkt) &&
    (!plain || !r.f) &&
    (!pre || passesPrescreen(r)) &&
    (!aumMin || (aumUsd(r) || 0) >= aumMin) &&
    (!dom || domBucket(r.dom) === dom) &&
    (erMax == null || (r.er != null && r.er <= erMax)) &&
    (!words.length || words.every(w => r.t.toLowerCase().includes(w) || r.n.toLowerCase().includes(w))) &&
    (!th || themesOf(r).includes(th)));
}
function exVal(r, key) {
  if (key === "_cost") { const c = costRating(r.er); return c ? SCORE_RANK[c] : null; }
  if (key === "_size") { const c = sizeRating(aumUsd(r)); return c ? SCORE_RANK[c] : null; }
  if (key === "aum") return aumUsd(r);
  return r[key];
}
function exCmp(a, b) {
  const { key, dir } = EX.sort;
  const va = exVal(a, key), vb = exVal(b, key);
  if (va == null || vb == null) return va == null && vb == null ? a.t.localeCompare(b.t) : (va == null ? 1 : -1);
  if (typeof va === "string") return va.localeCompare(vb) * dir;
  return (va - vb) * dir || a.t.localeCompare(b.t);
}

// Definitions shown by each header's ⓘ and in the column guide.
const EX_HELP = {
  t: "The fund's trading symbol — what you type into your broker to buy it. London listings end in .L, Hong Kong ones in .HK. Tap a row for the fund's card.",
  er: "The yearly fee (expense ratio): the share of your money the fund takes every year to run itself, whether it goes up or down. 0.50% = $50 a year on $10,000. Lower is better.",
  aum: "Assets under management: how much money is invested in the fund in total. Bigger funds are easier to buy and sell and less likely to be closed down. Shown in the fund's own currency.",
  p: "The price of one share at the last close. It says nothing about value — a $20 fund isn't cheaper than a $500 one; you just get fewer shares of the second.",
  c1y: "How much the share price changed over the last 12 months. Payouts are NOT included, so funds that pay big dividends look worse here than they really did.",
  ytd: "Year-to-date: the return since 1 January, payouts included (as reported by Yahoo Finance).",
  yld: "Payouts over the last 12 months as a % of the price. A high yield isn't automatically good — part of it can be your own money handed back.",
  vol: "Average number of shares traded per day. More trading usually means a smaller gap between the buying and selling price, so it's cheaper to trade.",
  _cost: "A traffic light for the yearly fee (expense ratio): 🟢 Good = 0.50% a year or less, 🟡 Caution = up to 0.75%, 🔴 Concern = more than 0.75%. It rates the fee you pay every year — not the share price.",
  _size: "A traffic light for fund size (AUM): 🟢 Good = at least US$500M invested, 🟡 Caution = US$50M–500M, 🔴 Concern = under US$50M — very small funds are more often closed down, which forces you to sell.",
};
const PRESCREEN_HELP = "A quick first filter that keeps only funds that are cheap, established and plain: yearly fee 0.50% or less (Cost 🟢), at least US$50M invested, and no leverage, ETN or futures. " +
  "It removes the obvious no's — it does NOT judge what the fund holds, its theme or its returns, so it isn't a buy list. Open a fund to look closer.";
const PLAIN_HELP = "Hides products built for short-term trading or with extra risks: leveraged / inverse funds (2×, 3×, −1× — they reset daily and drift away from the market over time), " +
  "exchange-traded notes (ETNs — a bank's promise to pay, not a fund that owns anything) and futures-based funds (oil, VIX … — returns can lag the real price badly). On by default.";
const DOM_HELP = "Domicile = the country where the fund is legally based (not where it's listed). It changes the tax taken off dividends and, for non-US investors, US estate-tax exposure — see “Tax & domicile” above. General information, not tax advice.";

const EX_COLS = [
  { key: "t", label: "Ticker" },
  { key: "er", label: "Expense", fmt: r => r.er == null ? nodata("Expense ratio") : r.er.toFixed(2) + "%" },
  { key: "aum", label: "AUM", fmt: r => r.aum == null ? nodata("AUM")
      : aumCur(r) !== "USD" && aumUsd(r) != null
        ? el("span", { title: `≈ ${fmtMoneyM(aumUsd(r), "USD")} at today's FX rate` }, fmtMoneyM(r.aum, aumCur(r)))
        : fmtMoneyM(r.aum, aumCur(r)) },
  { key: "p", label: "Price", fmt: r => money(r.p, r.cur) || nodata("Price") },
  { key: "c1y", label: "1-yr price", fmt: r => pctSpan(r.c1y) },
  { key: "ytd", label: "YTD", fmt: r => pctSpan(r.ytd) },
  { key: "yld", label: "Yield", when: () => UNIVERSE.rows.filter(r => r.yld != null).length > UNIVERSE.rows.length * 0.3,
    fmt: r => r.yld == null ? el("span", { class: "muted" }, "—") : r.yld.toFixed(2) + "%" },
  { key: "vol", label: "Avg Vol", fmt: r => shares(r.vol) || nodata("Volume") },
  { key: "_cost", label: "Cost", score: r => costRating(r.er) },
  { key: "_size", label: "Size", score: r => sizeRating(aumUsd(r)) },
];
const exCols = () => EX_COLS.filter(c => !c.when || c.when());
function pctSpan(v) {
  if (v == null) return el("span", { class: "muted" }, "—");
  return el("span", { class: v >= 0 ? "pos" : "neg" }, signed(v));
}

function renderExplorer() {
  if (!UNIVERSE || !$("#exTable")) return;
  const all = exFiltered().sort(exCmp);
  const rows = all.slice(0, EX.shown);
  const sortCol = EX_COLS.find(c => c.key === EX.sort.key) || EX_COLS[0];
  const { key: sk, dir: sd } = EX.sort;
  const order = sk === "t" ? (sd > 0 ? "A→Z" : "Z→A") : ["_cost", "_size"].includes(sk) ? (sd > 0 ? "best first" : "worst first") : (sd > 0 ? "lowest first" : "highest first");
  $("#exCount").textContent = `${all.length.toLocaleString()} match${all.length === 1 ? "" : "es"}` +
    (rows.length < all.length ? ` · showing the first ${rows.length.toLocaleString()}, sorted by ${sortCol.label} (${order}) — “Show more” is at the bottom, or narrow the search` : "") +
    " · click a header to sort, a row for details, ⓘ for what a column means";
  const pre = $("#exPre").checked, note = $("#exPreNote");
  note.hidden = !pre;
  if (pre) {
    const before = exFiltered(false).length;
    note.textContent = `✓ Pre-screen on: ${all.length.toLocaleString()} of ${before.toLocaleString()} funds pass — cheap (yearly fee 0.50% or less), established (at least US$50M invested) and plain (no leverage, ETN or futures). ` +
      "It's a first filter, not a buy list: it doesn't look at what a fund holds or how it has performed.";
  }
  $("#exMore").hidden = rows.length >= all.length;
  const wrap = $("#exTable"); wrap.innerHTML = "";
  if (!rows.length) {
    wrap.append(el("div", { class: "empty" }, "No ETFs match. Try a broader search or fewer filters."));
    return;
  }
  const cols = exCols();
  const head = el("tr");
  cols.forEach(c => {
    const active = EX.sort.key === c.key, def = EX_HELP[c.key] || GLOSSARY[c.label];
    head.append(withHelp(el("th", { class: def ? "has-help" : "", "aria-sort": active ? (EX.sort.dir > 0 ? "ascending" : "descending") : null, onclick: () => {
      EX.sort = EX.sort.key === c.key ? { key: c.key, dir: -EX.sort.dir } : { key: c.key, dir: c.key === "t" || c.key === "er" ? 1 : -1 };
      renderExplorer();
    } }, c.label, active ? el("span", { class: "arrow" }, EX.sort.dir > 0 ? " ▲" : " ▼") : null), c.label, def));
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
          el("div", { class: "nm" }, r.n, ...chips.map(n => el("span", { class: "seg" }, n)),
            r.mkt !== "US" ? el("span", { class: "seg mkt", title: DOM_TEXT[r.dom] || "" }, `${(UNIVERSE.meta[r.mkt] || {}).label || r.mkt}${r.dom ? " · " + r.dom : ""}`) : null)),
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
    aum_display: r.aum != null ? fmtMoneyM(r.aum, aumCur(r)) + (aumCur(r) !== "USD" && aumUsd(r) != null ? ` (≈ ${fmtMoneyM(aumUsd(r), "USD")})` : "") : null,
    inception: r.inc, domicile: r.dom ? (DOM_TEXT[r.dom] || r.dom) : null, listing: `${(UNIVERSE.meta[r.mkt] || {}).label || r.mkt}${r.x ? " (" + r.x + ")" : ""} · trades in ${r.cur || "USD"}`,
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
      liquidity: scoreFromLiquidity({ aum_musd: aumUsd(r) != null ? Math.round(aumUsd(r)) : null, dollar_volume_avg: dv && r.cur && r.cur !== "USD" ? null : dv,
        dollar_volume_display: fmtDollarVol(dv, r.cur) }),
      track_record: { rating: "yellow", note: r.inc ? `Listed since ${r.inc}.` : "Inception unknown." },
    },
    overall: "Explorer fund — mechanical data only.",
    memo: {
      thesis: `${r.n} — listed in ${(UNIVERSE.meta[r.mkt] || {}).label || r.mkt}${r.dom ? " (" + (DOM_TEXT[r.dom] || r.dom) + ")" : ""}. This card comes from the Explorer (every listed ETF), so it shows the daily basics only: no holdings, purity or risk analysis yet. Ask Claude to add it to a theme for the full treatment.`,
      red_flags: [
        ...(/L/.test(r.f || "") ? ["🔴 Leveraged/inverse daily-reset fund — suffers volatility decay; a trading tool, not a buy-and-hold investment."] : []),
        ...(/N/.test(r.f || "") ? ["⚠️ ETN: an unsecured note — you carry the issuer's credit risk, and it holds no basket of assets."] : []),
        ...(/F/.test(r.f || "") ? ["⚠️ Futures-based: returns can lag the spot price badly (roll costs / contango)."] : []),
        "❓ Not curated — verify against the issuer's fact sheet before acting."],
      bull: [], bear: [],
    },
  };
}

// General information on fund domicile and tax — deliberately not personal advice.
function taxExplainer() {
  const d = el("details", { class: "glossary taxbox" });
  d.append(el("summary", {}, "Tax & domicile — general information (not tax advice)"));
  const items = [
    ["Why domicile matters", "Where a fund is legally based (its domicile) — not where it trades — largely decides the tax drag on its dividends and, for non-US investors, US estate-tax exposure. The same index can be held through a US, Irish or Hong Kong fund with different after-tax results."],
    ["US-domiciled (most US-listed ETFs)", "For investors who are not US citizens or residents, US withholding tax on dividends is generally 30% unless a tax treaty lowers it (Hong Kong has no comprehensive income-tax treaty with the US). US-listed ETFs are US-situs assets: for non-US persons, US estate tax can apply above US$60,000."],
    ["Ireland-domiciled UCITS (most UCITS ETFs in London)", "The fund itself generally suffers 15% on US dividends under the US–Ireland treaty; Ireland normally doesn't withhold on distributions to non-Irish investors; and the fund is not a US-situs asset for US estate tax. Often offered as accumulating share classes (dividends reinvested inside the fund)."],
    ["Luxembourg-domiciled UCITS", "Usually suffers 30% on US dividends at fund level. Funds marked 'IE/LU' are UCITS funds whose exact domicile (Ireland vs Luxembourg) should be checked on the fund's fact sheet (ISIN starting IE or LU)."],
    ["Hong Kong-domiciled ETFs", "Hong Kong doesn't tax individuals on dividends or capital gains; withholding on the fund's own foreign holdings (e.g. on US shares) still happens inside the fund."],
    ["Your own rules", "Your home country's tax and reporting rules also apply — e.g. UK investors look for 'reporting fund' status, and US persons face PFIC rules on non-US funds. Tax depends on your residence and situation; confirm with a tax adviser before acting."],
  ];
  const dl = el("dl");
  items.forEach(([k, v]) => dl.append(el("dt", {}, k), el("dd", {}, v)));
  d.append(dl);
  return d;
}
