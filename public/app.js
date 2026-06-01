"use strict";

// ====================================================================
// ETF Analysis — static frontend.
// Content comes from /data/<theme>.json (committed, always available).
// Live HARD FACTS come from /api/etf?ticker=XXX (Vercel function), layered
// on top when the user taps ↻ or looks up a new ticker.
// ====================================================================

let CURRENT = null;                 // current theme object
let LIVE = {};                      // ticker -> live data overlay
let SORT = { key: "ticker", dir: 1 };

const RATING_LABEL = { green: "Good", yellow: "Caution", red: "Concern" };
const SCORE_RANK = { green: 0, yellow: 1, red: 2 };

const THEME_FILES = ["quantum", "space"];  // order in the picker

const COLUMNS = [
  { key: "ticker", label: "Ticker" },
  { key: "expense_ratio", label: "Expense", fmt: (v, e) => liveOr(e, "expense_ratio", v == null ? "—" : v.toFixed(2) + "%") },
  { key: "aum_musd", label: "AUM", fmt: (_v, e) => liveOr(e, "aum_display", e.aum_display || "—") },
  { key: "_perf1y", label: "1-yr", fmt: (_v, e) => perfCell(e, "y1") },
  { key: "_perfytd", label: "YTD", fmt: (_v, e) => perfCell(e, "ytd") },
  { key: "structure", label: "Structure" },
  { key: "holdings_count", label: "# Hold", fmt: v => v == null ? "—" : v },
  { key: "top10_weight_pct", label: "Top-10", fmt: (_v, e) => e.top10_weight_display || "—" },
  { key: "_cost", label: "Cost", type: "score" },
  { key: "_purity", label: "Purity", type: "score" },
  { key: "_concentration", label: "Concen.", type: "score" },
  { key: "_refresh", label: "Live" },
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
const scoreOf = (etf, dim) => (etf.scores && etf.scores[dim]) || null;

// ---- live-data helpers ---------------------------------------------
function liveOr(etf, field, fallback) {
  const lv = LIVE[etf.ticker];
  if (lv && lv[field] != null) {
    if (field === "expense_ratio") return lv[field].toFixed(2) + "% ●";
    return lv[field] + " ●";
  }
  return fallback;
}
function perfCell(etf, key) {
  const lv = LIVE[etf.ticker];
  let v = lv && lv.performance && lv.performance[key];
  let live = !!v;
  if (!v) v = etf.performance && etf.performance[key];
  if (v == null || v === "" ) return el("span", { class: "muted" }, "—");
  const num = parseFloat(String(v).replace(/[^0-9.\-]/g, ""));
  const cls = isFinite(num) ? (num >= 0 ? "pos" : "neg") : "muted";
  return el("span", { class: cls, title: live ? "live" : "snapshot" }, String(v) + (live ? " ●" : ""));
}

// ---- boot ----------------------------------------------------------
async function init() {
  const sel = $("#themeSelect");
  const loaded = [];
  for (const id of THEME_FILES) {
    try {
      const r = await fetch(`/data/${id}.json`, { cache: "no-store" });
      if (r.ok) { const t = await r.json(); t._id = id; loaded.push(t); }
    } catch (_) { /* skip */ }
  }
  window._THEMES = {};
  loaded.forEach(t => { window._THEMES[t._id] = t; sel.append(el("option", { value: t._id }, `${t.name} (${(t.etfs||[]).length})`)); });
  sel.addEventListener("change", () => selectTheme(sel.value));
  if (loaded.length) selectTheme(loaded[0]._id);

  $("#filterBox").addEventListener("input", render);
  $("#themeOnly").addEventListener("change", render);
  $("#addBtn").addEventListener("click", onAddTicker);
  $("#addTicker").addEventListener("keydown", e => { if (e.key === "Enter") onAddTicker(); });
  $("#closeMemo").addEventListener("click", closeMemo);
  $("#overlay").addEventListener("click", closeMemo);
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeMemo(); });
}

function selectTheme(id) {
  CURRENT = window._THEMES[id];
  LIVE = {};
  $("#controls").hidden = false;
  $("#liveMsg").hidden = true;
  renderIntro(); renderTensions(); render();
}

// ---- intro / tensions ----------------------------------------------
function renderIntro() {
  const t = CURRENT, box = $("#themeIntro"); box.innerHTML = "";
  box.append(
    el("h2", {}, t.name + " ETFs"),
    el("div", { class: "asof" }, "Curated snapshot as of " + (t.as_of || "—") + (t.live_refresh ? " · ↻ for live data" : "")),
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
    ul.append(el("li", { html: i > 0 ? `<b>${escapeHtml(x.slice(0,i))}</b>${escapeHtml(x.slice(i))}` : escapeHtml(x) }));
  });
  box.append(el("h3", {}, "Key tensions in this theme"), ul);
}

// ---- table ---------------------------------------------------------
function visibleEtfs() {
  const q = $("#filterBox").value.trim().toLowerCase();
  const themeOnly = $("#themeOnly").checked;
  let rows = (CURRENT.etfs || []).slice();
  if (themeOnly) rows = rows.filter(e => e.is_theme_fund);
  if (q) rows = rows.filter(e => (e.ticker + " " + e.name).toLowerCase().includes(q));
  rows.sort(cmp);
  return rows;
}
function sortVal(e, key) {
  if (key === "_perf1y") return perfNum(e, "y1");
  if (key === "_perfytd") return perfNum(e, "ytd");
  if (key.startsWith("_")) { const d = key.slice(1); return SCORE_RANK[(scoreOf(e, d)||{}).rating] ?? 9; }
  if (key === "expense_ratio") { const lv = LIVE[e.ticker]; return (lv && lv.expense_ratio != null) ? lv.expense_ratio : e.expense_ratio; }
  if (key === "aum_musd") { const lv = LIVE[e.ticker]; return (lv && lv.aum_musd != null) ? lv.aum_musd : e.aum_musd; }
  return e[key];
}
function perfNum(e, k) {
  const lv = LIVE[e.ticker];
  let v = (lv && lv.performance && lv.performance[k]) || (e.performance && e.performance[k]);
  const n = parseFloat(String(v).replace(/[^0-9.\-]/g, ""));
  return isFinite(n) ? n : null;
}
function cmp(a, b) {
  let va = sortVal(a, SORT.key), vb = sortVal(b, SORT.key);
  if (va == null) return 1; if (vb == null) return -1;
  if (typeof va === "string") return va.localeCompare(vb) * SORT.dir;
  return (va - vb) * SORT.dir;
}
function render() {
  if (!CURRENT) return;
  const rows = visibleEtfs(), wrap = $("#tableWrap"); wrap.innerHTML = "";
  const thead = el("tr");
  COLUMNS.forEach(c => {
    const active = SORT.key === c.key;
    thead.append(el("th", { onclick: () => setSort(c.key) }, c.label,
      active ? el("span", { class: "arrow" }, SORT.dir > 0 ? " ▲" : " ▼") : null));
  });
  const tbody = el("tbody");
  rows.forEach(e => {
    const isLive = !!LIVE[e.ticker];
    const tr = el("tr", { class: (e.is_theme_fund ? "" : "bench ") + (isLive ? "live" : "") });
    COLUMNS.forEach(c => {
      if (c.key === "_refresh") {
        tr.append(el("td", {}, el("button", { class: "refresh",
          onclick: ev => { ev.stopPropagation(); refreshTicker(e.ticker); } }, "↻")));
      } else if (c.type === "score") {
        const sc = scoreOf(e, c.key.slice(1));
        const td = el("td", { class: "cellscore", title: sc ? sc.note : "", onclick: () => openMemo(e.ticker) },
          sc ? el("span", { class: "dot " + sc.rating }) : "—", sc ? RATING_LABEL[sc.rating] : "");
        tr.append(td);
      } else if (c.key === "ticker") {
        tr.append(el("td", { onclick: () => openMemo(e.ticker) },
          el("span", { class: "tk" }, e.ticker),
          isLive ? el("span", { class: "tag-live" }, "live") : null,
          el("div", { class: "nm" }, e.name)));
      } else {
        const out = c.fmt ? c.fmt(e[c.key], e) : (e[c.key] == null ? "—" : String(e[c.key]));
        tr.append(el("td", { onclick: () => openMemo(e.ticker) }, out));
      }
    });
    tbody.append(tr);
  });
  const table = el("table"); table.append(el("thead", {}, thead), tbody); wrap.append(table);
}
function setSort(key) {
  if (key === "_refresh") return;
  if (SORT.key === key) SORT.dir *= -1; else SORT = { key, dir: key === "ticker" ? 1 : -1 };
  render();
}

// ---- live refresh --------------------------------------------------
function liveMsg(text, cls) {
  const box = $("#liveMsg"); box.hidden = false; box.className = "livemsg " + (cls || "");
  box.textContent = text;
}
async function refreshTicker(ticker) {
  liveMsg(`Fetching live data for ${ticker}…`);
  try {
    const r = await fetch(`/api/etf?ticker=${encodeURIComponent(ticker)}`);
    const j = await r.json();
    if (!j.ok) {
      liveMsg(j.message || `Couldn't fetch ${ticker} (${j.error}). Static data still shown.`, "warn");
      return null;
    }
    LIVE[ticker] = j.data;
    liveMsg(`Live data for ${ticker} updated (${j.source}, ${j.as_of}). ● marks live values.`);
    render();
    return j.data;
  } catch (e) {
    liveMsg(`Live refresh failed (${e.message}). This works once deployed to Vercel with an API key.`, "err");
    return null;
  }
}
async function onAddTicker() {
  const inp = $("#addTicker");
  const ticker = inp.value.trim().toUpperCase();
  if (!ticker) return;
  $("#addBtn").disabled = true;
  // If it already exists in the theme, just refresh + open it.
  let existing = (CURRENT.etfs || []).find(e => e.ticker === ticker);
  const data = await refreshTicker(ticker);
  if (!existing && data) {
    // Inject a lightweight, clearly-marked "live only" row (no curated memo yet).
    CURRENT.etfs.push(makeLiveEtf(ticker, data));
    liveMsg(`Added ${ticker} from live data. No curated analysis yet — ask to add a full memo. ● = live.`);
    render();
  }
  if (existing) openMemo(ticker);
  $("#addBtn").disabled = false;
  inp.value = "";
}
function makeLiveEtf(ticker, d) {
  return {
    ticker, name: ticker + " (live lookup)", is_theme_fund: true, _adhoc: true,
    expense_ratio: d.expense_ratio ?? null, aum_musd: d.aum_musd ?? null,
    aum_display: d.aum_display || null, structure: "—", index: "—",
    holdings_count: (d.holdings && d.holdings.length) || null,
    top10_weight_pct: d.top10_weight_pct ?? null,
    top10_weight_display: d.top10_weight_pct != null ? "~" + d.top10_weight_pct + "%" : "—",
    largest_position_display: (d.holdings && d.holdings[0]) ? `${d.holdings[0].weight ?? "?"}% (${d.holdings[0].symbol})` : "—",
    derivatives: "—", performance: d.performance || {},
    scores: {
      cost: scoreFromExpense(d.expense_ratio),
      purity: { rating: "yellow", note: "Ad-hoc live lookup — theme purity not yet assessed. Ask to add a curated memo." },
      concentration: scoreFromTop10(d.top10_weight_pct),
      liquidity: scoreFromAum(d.aum_musd),
      track_record: { rating: "yellow", note: "Not yet reviewed." },
    },
    overall: "Ad-hoc live lookup — not yet curated.",
    memo: adhocMemo(ticker, d),
  };
}
function scoreFromExpense(er) {
  if (er == null) return { rating: "yellow", note: "Expense ratio unavailable from live feed." };
  if (er <= 0.50) return { rating: "green", note: `Live expense ratio ${er.toFixed(2)}% — reasonable.` };
  if (er <= 0.75) return { rating: "yellow", note: `Live expense ratio ${er.toFixed(2)}% — typical for thematic.` };
  return { rating: "red", note: `Live expense ratio ${er.toFixed(2)}% — high.` };
}
function scoreFromTop10(t) {
  if (t == null) return { rating: "yellow", note: "Top-10 weight unavailable." };
  if (t < 40) return { rating: "green", note: `Top-10 ~${t}% — well spread.` };
  if (t <= 55) return { rating: "yellow", note: `Top-10 ~${t}% — moderately concentrated.` };
  return { rating: "red", note: `Top-10 ~${t}% — concentrated.` };
}
function scoreFromAum(a) {
  if (a == null) return { rating: "yellow", note: "AUM unavailable." };
  if (a >= 500) return { rating: "green", note: `AUM ${a >= 1000 ? "~$"+(a/1000).toFixed(1)+"B" : "~$"+a+"M"} — liquid.` };
  if (a >= 50) return { rating: "yellow", note: `AUM ~$${a}M — modest; check spreads.` };
  return { rating: "red", note: `AUM ~$${a}M — small; closure risk.` };
}
function adhocMemo(ticker, d) {
  const holds = (d.holdings || []).map(h => ({
    name: `${h.name} (${h.symbol})`, weight: h.weight != null ? h.weight + "%" : "—",
    playtype: "partial", note: "" }));
  return {
    thesis: `Live lookup for ${ticker}. This row was pulled from the market-data provider and is NOT yet curated — no theme-purity judgment, bull/bear, or red-flag review. Ask to add a full memo and it'll be researched and committed.`,
    strategy: "—  (not yet curated)",
    purity_verdict: { rating: "yellow", text: "Holdings shown below are live; classification (pure/partial/unrelated) needs human review." },
    holdings_illustrative: holds.length ? holds : [{ name: "(no holdings returned by feed)", weight: "—", playtype: "partial", note: "" }],
    concentration: d.top10_weight_pct != null ? `Live top-10 ≈ ${d.top10_weight_pct}%.` : "Concentration unavailable from feed.",
    sector_geo: (d.sectors && d.sectors.length) ? d.sectors.map(s => `${s.sector} ${s.weight}%`).join(" · ") : "Sectors unavailable.",
    cost_context: d.expense_ratio != null ? `Live expense ratio ${d.expense_ratio.toFixed(2)}%.` : "Expense ratio unavailable.",
    track_record_note: d.performance ? `Live: YTD ${d.performance.ytd||"—"}, 1-yr ${d.performance.y1||"—"}, 3-yr ann. ${d.performance.y3_annualized||"—"} (as of ${d.performance.as_of||"?"}).` : "Performance unavailable.",
    red_flags: ["❓ Not yet curated — verify everything against the issuer fact sheet & SEC filing."],
    bull: [], bear: [],
    decision_log: [{ date: new Date().toISOString().slice(0,10), action: "LIVE LOOKUP", text: "Ad-hoc fetch; request a curated memo to analyze properly." }],
  };
}

// ---- memo drawer ---------------------------------------------------
function openMemo(ticker) {
  const e = (CURRENT.etfs || []).find(x => x.ticker === ticker); if (!e) return;
  const m = e.memo || {}, lv = LIVE[ticker];
  const body = $("#memoBody"); body.innerHTML = "";
  const wrap = el("div", { class: "memo" });
  const erShown = (lv && lv.expense_ratio != null) ? lv.expense_ratio.toFixed(2) + "%●" : (e.expense_ratio != null ? e.expense_ratio.toFixed(2) + "%" : "—");
  const aumShown = (lv && lv.aum_display) ? lv.aum_display + "●" : (e.aum_display || "—");

  wrap.append(
    el("h2", {}, `${e.ticker} — ${e.name}`),
    el("div", { class: "sub" }, `${e.is_theme_fund ? "Theme fund" : "Benchmark / reference"} · Expense ${erShown} · AUM ${aumShown} · Inception ${e.inception || "—"}`),
    el("div", { class: "liverow" },
      el("button", { class: "refresh", onclick: () => refreshTicker(ticker).then(() => openMemo(ticker)) }, "↻ Refresh live"),
      el("span", { class: "muted", style: "font-size:12px" }, lv ? "● = live values shown" : "showing curated snapshot")),
    m.thesis ? el("div", { class: "thesis" }, m.thesis) : null
  );

  // performance block (live overlaid on snapshot)
  const perf = (lv && lv.performance) || e.performance;
  if (perf) {
    wrap.append(sectionTitle("Performance" + (lv && lv.performance ? " (live)" : " (snapshot)")));
    const pf = el("div", { class: "perf" });
    [["YTD","ytd"],["1-yr","y1"],["3-yr ann.","y3_annualized"],["2025","y2025"],["2024","y2024"]].forEach(([lab,k]) => {
      if (perf[k] == null) return;
      const num = parseFloat(String(perf[k]).replace(/[^0-9.\-]/g,""));
      pf.append(el("div", { class: "p" }, el("span", { class: "lab" }, lab),
        el("span", { class: "val " + (isFinite(num) ? (num>=0?"pos":"neg") : "muted") }, String(perf[k]))));
    });
    wrap.append(pf);
    if (perf.note) wrap.append(el("p", { class: "muted", style:"font-size:13px" }, perf.note));
  }

  const kv = el("div", { class: "kv" });
  [["Structure", e.structure], ["Index", e.index], ["# Holdings", e.holdings_count],
   ["Top-10 weight", e.top10_weight_display], ["Largest position", e.largest_position_display],
   ["Derivatives", e.derivatives]].forEach(([k,v]) =>
    kv.append(el("div", { html: `<span>${k}:</span> ${escapeHtml(String(v ?? "—"))}` })));
  wrap.append(sectionTitle("Snapshot"), kv);

  wrap.append(sectionTitle("Scored dimensions"));
  ["cost","purity","concentration","liquidity","track_record"].forEach(dim => {
    const sc = scoreOf(e, dim); if (!sc) return;
    wrap.append(el("p", {}, el("span", { class: "badge " + sc.rating }, RATING_LABEL[sc.rating]),
      " ", el("b", {}, dim.replace("_"," ")), " — ", sc.note));
  });

  if (m.strategy) wrap.append(sectionTitle("Strategy"), el("p", {}, m.strategy));

  if (m.purity_verdict) {
    wrap.append(sectionTitle("Theme purity ⭐"));
    wrap.append(el("p", {}, el("span", { class: "badge " + m.purity_verdict.rating }, RATING_LABEL[m.purity_verdict.rating]), " ", m.purity_verdict.text));
    // prefer LIVE holdings if present
    const liveHolds = lv && lv.holdings && lv.holdings.length
      ? lv.holdings.map(h => ({ name: `${h.name} (${h.symbol})`, weight: h.weight!=null?h.weight+"%":"—", playtype: classifyLive(e, h), note: "live" }))
      : null;
    const holds = liveHolds || m.holdings_illustrative;
    if (Array.isArray(holds)) {
      if (liveHolds) wrap.append(el("p", { class: "muted", style:"font-size:12px" }, "● live holdings from provider"));
      const ht = el("table", { class: "hold" });
      holds.forEach(h => ht.append(el("tr", {},
        el("td", {}, el("b", {}, h.name)), el("td", {}, h.weight || ""),
        el("td", {}, el("span", { class: "tag " + (h.playtype||"partial") }, h.playtype||"")),
        el("td", { class: "nm" }, h.note || ""))));
      wrap.append(ht);
    }
  }

  if (m.concentration) wrap.append(sectionTitle("Concentration & risk"), el("p", {}, m.concentration));
  if (lv && lv.sectors && lv.sectors.length) {
    wrap.append(sectionTitle("Sectors (live)"), el("p", {}, lv.sectors.map(s => `${s.sector} ${s.weight}%`).join(" · ")));
  } else if (m.sector_geo) wrap.append(sectionTitle("Sector & geography"), el("p", {}, m.sector_geo));
  if (m.cost_context) wrap.append(sectionTitle("Cost in context"), el("p", {}, m.cost_context));
  if (m.track_record_note) wrap.append(sectionTitle("Track record"), el("p", {}, m.track_record_note));

  if (Array.isArray(m.red_flags) && m.red_flags.length) {
    const ul = el("ul", { class: "flags" }); m.red_flags.forEach(f => ul.append(el("li", {}, f)));
    wrap.append(sectionTitle("Red flags"), ul);
  }
  if ((m.bull && m.bull.length) || (m.bear && m.bear.length)) {
    const bb = el("div", { class: "bb" });
    bb.append(colList("bull","Bull case",m.bull), colList("bear","Bear case",m.bear));
    wrap.append(sectionTitle("Bull vs Bear"), bb);
  }
  if (Array.isArray(m.decision_log)) {
    wrap.append(sectionTitle("Decision log"));
    m.decision_log.forEach(d => wrap.append(el("div", { class: "dlog" },
      el("span", { class: "act" }, `${d.date} — ${d.action}: `), d.text)));
  }

  body.append(wrap);
  $("#overlay").hidden = false; $("#memoDrawer").hidden = false;
}
// best-effort: keep curated classification for known holdings, else 'partial'
function classifyLive(etf, h) {
  const known = (etf.memo && etf.memo.holdings_illustrative) || [];
  const sym = (h.symbol || "").toUpperCase();
  const match = known.find(k => (k.name||"").toUpperCase().includes(sym) && sym.length);
  return match ? match.playtype : "partial";
}
function colList(cls, title, items) {
  const col = el("div", { class: "col " + cls }); col.append(el("h4", {}, title));
  const ul = el("ul"); (items||[]).forEach(x => ul.append(el("li", {}, x))); col.append(ul); return col;
}
const sectionTitle = t => el("h3", {}, t);
function closeMemo() { $("#overlay").hidden = true; $("#memoDrawer").hidden = true; }

init();
