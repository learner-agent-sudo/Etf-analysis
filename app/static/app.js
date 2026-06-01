"use strict";

// ---- state ---------------------------------------------------------------
let CURRENT = null;            // current theme object
let SORT = { key: "ticker", dir: 1 };

const RATING_LABEL = { green: "Good", yellow: "Caution", red: "Concern" };

const COLUMNS = [
  { key: "ticker", label: "Ticker", type: "str" },
  { key: "expense_ratio", label: "Expense", type: "num", fmt: v => v == null ? "—" : v.toFixed(2) + "%" },
  { key: "aum_musd", label: "AUM", type: "num", fmt: (_v, e) => e.aum_display || "—" },
  { key: "structure", label: "Structure", type: "str" },
  { key: "holdings_count", label: "# Hold", type: "num", fmt: v => v == null ? "—" : v },
  { key: "top10_weight_pct", label: "Top-10", type: "num", fmt: (_v, e) => e.top10_weight_display || "—" },
  { key: "_cost", label: "Cost", type: "score" },
  { key: "_purity", label: "Purity", type: "score" },
  { key: "_concentration", label: "Concen.", type: "score" },
  { key: "_liquidity", label: "Liquidity", type: "score" },
];

const SCORE_RANK = { green: 0, yellow: 1, red: 2 };

// ---- helpers -------------------------------------------------------------
const $ = sel => document.querySelector(sel);
function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids) if (kid != null) n.append(kid.nodeType ? kid : document.createTextNode(kid));
  return n;
}
function scoreOf(etf, dim) { return (etf.scores && etf.scores[dim]) || null; }

// ---- data load -----------------------------------------------------------
async function init() {
  const res = await fetch("/api/themes");
  const { themes } = await res.json();
  const sel = $("#themeSelect");
  sel.innerHTML = "";
  themes.forEach(t => sel.append(el("option", { value: t.id }, `${t.name} (${t.etf_count})`)));
  sel.addEventListener("change", () => loadTheme(sel.value));
  if (themes.length) loadTheme(themes[0].id);

  $("#filterBox").addEventListener("input", render);
  $("#themeOnly").addEventListener("change", render);
  $("#closeMemo").addEventListener("click", closeMemo);
  $("#overlay").addEventListener("click", closeMemo);
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeMemo(); });
}

async function loadTheme(id) {
  const res = await fetch("/api/theme/" + encodeURIComponent(id));
  CURRENT = await res.json();
  $("#controls").hidden = false;
  renderIntro();
  renderTensions();
  render();
}

// ---- rendering -----------------------------------------------------------
function renderIntro() {
  const t = CURRENT;
  const box = $("#themeIntro");
  box.innerHTML = "";
  box.append(
    el("h2", {}, t.name + " ETFs"),
    el("div", { class: "asof" }, "Data as of " + (t.as_of || "—")),
    el("div", { class: "tagline" }, t.tagline || ""),
    t.benchmark_note ? el("p", { class: "bench" }, "▸ " + t.benchmark_note) : null
  );
}

function renderTensions() {
  const box = $("#tensions");
  box.innerHTML = "";
  const list = CURRENT.key_tensions || [];
  if (!list.length) return;
  const ul = el("ul");
  list.forEach(x => ul.append(el("li", { html: boldFirst(x) })));
  box.append(el("h3", {}, "Key tensions in this theme"), ul);
}
function boldFirst(s) {
  const i = s.indexOf(":");
  return i > 0 ? `<b>${escapeHtml(s.slice(0, i))}</b>${escapeHtml(s.slice(i))}` : escapeHtml(s);
}
function escapeHtml(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function visibleEtfs() {
  const q = $("#filterBox").value.trim().toLowerCase();
  const themeOnly = $("#themeOnly").checked;
  let rows = (CURRENT.etfs || []).slice();
  if (themeOnly) rows = rows.filter(e => e.is_theme_fund);
  if (q) rows = rows.filter(e => (e.ticker + " " + e.name).toLowerCase().includes(q));
  rows.sort(cmp);
  return rows;
}

function cmp(a, b) {
  const k = SORT.key, dir = SORT.dir;
  let va, vb;
  if (k.startsWith("_")) {           // score columns
    const dim = k.slice(1);
    va = SCORE_RANK[(scoreOf(a, dim) || {}).rating] ?? 9;
    vb = SCORE_RANK[(scoreOf(b, dim) || {}).rating] ?? 9;
  } else {
    va = a[k]; vb = b[k];
  }
  if (va == null) return 1;          // nulls sink
  if (vb == null) return -1;
  if (typeof va === "string") return va.localeCompare(vb) * dir;
  return (va - vb) * dir;
}

function render() {
  if (!CURRENT) return;
  const rows = visibleEtfs();
  const wrap = $("#tableWrap");
  wrap.innerHTML = "";

  const thead = el("tr");
  COLUMNS.forEach(c => {
    const active = SORT.key === c.key;
    const arrow = active ? el("span", { class: "arrow" }, SORT.dir > 0 ? " ▲" : " ▼") : null;
    thead.append(el("th", { onclick: () => setSort(c.key) }, c.label, arrow));
  });

  const tbody = el("tbody");
  rows.forEach(e => {
    const tr = el("tr", { class: e.is_theme_fund ? "" : "bench", onclick: () => openMemo(e.ticker) });
    COLUMNS.forEach(c => {
      if (c.type === "score") {
        const sc = scoreOf(e, c.key.slice(1));
        tr.append(el("td", { class: "cellscore", title: sc ? sc.note : "" },
          sc ? el("span", { class: "dot " + sc.rating }) : "—",
          sc ? RATING_LABEL[sc.rating] : ""));
      } else if (c.key === "ticker") {
        tr.append(el("td", {}, el("span", { class: "tk" }, e.ticker),
          el("div", { class: "nm" }, e.name)));
      } else {
        const raw = e[c.key];
        tr.append(el("td", {}, c.fmt ? c.fmt(raw, e) : (raw == null ? "—" : String(raw))));
      }
    });
    tbody.append(tr);
  });

  const table = el("table");
  table.append(el("thead", {}, thead), tbody);
  wrap.append(table);
}

function setSort(key) {
  if (SORT.key === key) SORT.dir *= -1;
  else SORT = { key, dir: 1 };
  render();
}

// ---- memo drawer ---------------------------------------------------------
function openMemo(ticker) {
  const e = (CURRENT.etfs || []).find(x => x.ticker === ticker);
  if (!e) return;
  const m = e.memo || {};
  const body = $("#memoBody");
  body.innerHTML = "";
  const wrap = el("div", { class: "memo" });

  wrap.append(
    el("h2", {}, `${e.ticker} — ${e.name}`),
    el("div", { class: "sub" },
      `${e.is_theme_fund ? "Theme fund" : "Benchmark / reference"} · Expense ${e.expense_ratio?.toFixed(2)}% · AUM ${e.aum_display || "—"} · Inception ${e.inception || "—"}`),
    m.thesis ? el("div", { class: "thesis" }, m.thesis) : null
  );

  // snapshot grid
  const kv = el("div", { class: "kv" });
  const facts = [
    ["Structure", e.structure], ["Index", e.index],
    ["# Holdings", e.holdings_count], ["Top-10 weight", e.top10_weight_display],
    ["Largest position", e.largest_position_display], ["Derivatives", e.derivatives],
  ];
  facts.forEach(([k, v]) => kv.append(el("div", { html: `<span>${k}:</span> ${escapeHtml(String(v ?? "—"))}` })));
  wrap.append(sectionTitle("Snapshot"), kv);

  // scored dimensions
  wrap.append(sectionTitle("Scored dimensions"));
  ["cost", "purity", "concentration", "liquidity", "track_record"].forEach(dim => {
    const sc = scoreOf(e, dim);
    if (!sc) return;
    wrap.append(el("p", {},
      el("span", { class: "badge " + sc.rating }, RATING_LABEL[sc.rating]),
      " ", el("b", {}, dim.replace("_", " ")), " — ", sc.note));
  });

  if (m.strategy) wrap.append(sectionTitle("Strategy"), el("p", {}, m.strategy));

  if (m.purity_verdict) {
    wrap.append(sectionTitle("Theme purity ⭐"));
    wrap.append(el("p", {}, el("span", { class: "badge " + m.purity_verdict.rating },
      RATING_LABEL[m.purity_verdict.rating]), " ", m.purity_verdict.text));
    if (Array.isArray(m.holdings_illustrative)) {
      const ht = el("table", { class: "hold" });
      m.holdings_illustrative.forEach(h => ht.append(el("tr", {},
        el("td", {}, el("b", {}, h.name)),
        el("td", {}, h.weight || ""),
        el("td", {}, el("span", { class: "tag " + (h.playtype || "partial") }, h.playtype || "")),
        el("td", { class: "nm" }, h.note || ""))));
      wrap.append(ht);
    }
  }

  if (m.concentration) wrap.append(sectionTitle("Concentration & risk"), el("p", {}, m.concentration));
  if (m.sector_geo) wrap.append(sectionTitle("Sector & geography"), el("p", {}, m.sector_geo));
  if (m.cost_context) wrap.append(sectionTitle("Cost in context"), el("p", {}, m.cost_context));
  if (m.track_record_note) wrap.append(sectionTitle("Track record"), el("p", {}, m.track_record_note));

  if (Array.isArray(m.red_flags) && m.red_flags.length) {
    const ul = el("ul", { class: "flags" });
    m.red_flags.forEach(f => ul.append(el("li", {}, f)));
    wrap.append(sectionTitle("Red flags"), ul);
  }

  if (m.bull || m.bear) {
    const bb = el("div", { class: "bb" });
    bb.append(colList("bull", "Bull case", m.bull), colList("bear", "Bear case", m.bear));
    wrap.append(sectionTitle("Bull vs Bear"), bb);
  }

  if (Array.isArray(m.decision_log)) {
    wrap.append(sectionTitle("Decision log"));
    m.decision_log.forEach(d => wrap.append(el("div", { class: "dlog" },
      el("span", { class: "act" }, `${d.date} — ${d.action}: `), d.text)));
  }

  body.append(wrap);
  $("#overlay").hidden = false;
  $("#memoDrawer").hidden = false;
}

function colList(cls, title, items) {
  const col = el("div", { class: "col " + cls });
  col.append(el("h4", {}, title));
  const ul = el("ul");
  (items || []).forEach(x => ul.append(el("li", {}, x)));
  col.append(ul);
  return col;
}
function sectionTitle(t) { return el("h3", {}, t); }
function closeMemo() { $("#overlay").hidden = true; $("#memoDrawer").hidden = true; }

init();
