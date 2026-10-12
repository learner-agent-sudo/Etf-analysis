"use strict";

// ====================================================================
// Income Lab — every option-income ETF (US / Hong Kong / London) screened
// in three layers: tiered hard gates → quality components → strategy-family
// weights. Data: data/income-lab.json, rebuilt every weekday by
// scripts/build_income.py. Loaded only when the tab opens.
// Shares helpers with app.js (el, $, liveMsg, closeMemo, curatedHome, …).
// ====================================================================

let LAB = null;
const LAB_PAGE = 50;
const LS = { fam: "", pass: true, market: "", q: "", sort: { key: "score", dir: -1 }, shown: LAB_PAGE,
  tax: (() => { try { return localStorage.getItem("etf.labTax") || "us"; } catch (_) { return "us"; } })() };

const COMP_LABEL = {
  gap: "Total return vs benchmark", coverage: "Distribution coverage", nav: "NAV (price) trend",
  quality: "Underlying quality", tax: "Tax efficiency (US)", fees: "Fees",
  counterparty: "Counterparty risk", transparency: "ELN transparency", vix: "Volatility-spike sensitivity",
  stability: "Distribution stability",
};
const GATE_LABEL = { aum: "Fund size", age: "Track record", er: "Expense ratio", liquidity: "Trading volume", structure: "Structure" };
const pct = (x, d = 1) => x == null ? "—" : `${x > 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;
const pctPlain = (x, d = 1) => x == null ? "—" : `${(x * 100).toFixed(d)}%`;
const pp = x => x == null ? "—" : `${x > 0 ? "+" : ""}${(x * 100).toFixed(1)} pp/yr`;
const labScore = f => LS.tax === "us" ? f.score_us : f.score_intl;
const regYield = f => f.metrics.yield_regular != null ? f.metrics.yield_regular : f.metrics.yield_ttm;
const WEIGHT_LABEL = { active_premium_eln: "Active premium using ELNs", default: "All other families (incl. active funds without ELNs)" };
const labRank = f => LS.tax === "us" ? f.rank_us : f.rank_intl;
const labWeights = f => LS.tax === "us" ? f.weights_us : f.weights_intl;
const famName = k => (LAB && LAB.families[k]) || k;
const svgEl = (tag, attrs = {}) => { const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([k, v]) => v != null && n.setAttribute(k, v)); return n; };

async function loadLab() {
  if (LAB) return LAB;
  try { LAB = await fetchJson("data/income-lab.json"); } catch (_) { LAB = null; }
  return LAB;
}

async function showIncomeLab() {
  setView("income");
  const box = $("#incomeLab");
  if (!LAB) box.innerHTML = '<p class="muted">Loading the Income Lab…</p>';
  await loadLab();
  if (!LAB) {
    box.innerHTML = "";
    box.append(el("p", { class: "livemsg warn" }, "The Income Lab data hasn't been generated yet — it's built automatically by the daily update."));
    return;
  }
  if (!box.dataset.built) buildLab(box);
  renderLab();
}

function buildLab(box) {
  box.innerHTML = ""; box.dataset.built = "1";
  const n = LAB.funds.length, passing = LAB.funds.filter(f => f.passes).length;
  const famCounts = {};
  LAB.funds.forEach(f => { famCounts[f.family] = (famCounts[f.family] || 0) + 1; });
  box.append(
    el("div", { class: "intro" },
      el("h2", {}, "Income Lab"),
      el("div", { class: "asof" }, `${n} option-income ETFs screened (US, Hong Kong, London) · ${passing} pass every gate · data ${LAB.as_of} · updates every weekday`),
      el("p", { class: "universe" }, "▸ Every covered-call, premium-income, call-spread, 0DTE, single-stock, short-volatility and put-write ETF in one place. " +
        "Pick a strategy family, then compare funds inside it: each family is scored on what matters for that strategy, so scores are meant to be compared within a family."),
      methodBox()),
    el("section", { class: "controls" },
      el("select", { id: "labFam", "aria-label": "Strategy family" }, el("option", { value: "" }, `All strategy families (${n})`),
        ...Object.keys(LAB.families).filter(k => famCounts[k]).map(k => el("option", { value: k }, `${LAB.families[k]} (${famCounts[k]})`))),
      el("label", { class: "toggle pass-toggle", title: "Passes every tiered gate: fund size, track record, expense ratio, trading volume, structure" },
        el("input", { type: "checkbox", id: "labPass", checked: "checked" }), "✓ Recommended screen"),
      el("select", { id: "labTax", "aria-label": "Tax view" },
        el("option", { value: "us" }, "Tax view: US taxable investor"),
        el("option", { value: "intl" }, "Tax view: non-US / tax-sheltered (ignore US tax)")),
      el("select", { id: "labMkt", "aria-label": "Market" }, el("option", { value: "" }, "All markets"),
        el("option", { value: "US" }, "US"), el("option", { value: "HK" }, "Hong Kong"), el("option", { value: "LSE" }, "London")),
      el("input", { type: "search", id: "labQ", placeholder: "Search ticker or name…", "aria-label": "Search income ETFs" })),
    el("div", { class: "chartcard" },
      el("h3", { id: "labChartTitle" }),
      el("div", { class: "legend", "aria-hidden": "true" },
        el("span", {}, el("i", { class: "key pass" }), "passes every gate"),
        el("span", {}, el("i", { class: "key fail" }), "fails a gate or gate data missing")),
      el("div", { id: "labChart", class: "scatter" }),
      el("p", { class: "muted small", id: "labChartNote" })),
    el("div", { id: "labCount", class: "muted small" }),
    el("section", { id: "labTable", class: "table-wrap" }),
    el("div", { class: "exmore" }, el("button", { id: "labMore", class: "refresh" }, "Show more")),
    el("p", { class: "muted small" }, "Yield = distributions over the last 12 months ÷ price. Returns, NAV trend, coverage and risk use the last " +
      `${LAB.window_years} years (or since launch). Benchmark = the fund's own underlying. Price is used as a stand-in for NAV. ` +
      "Not investment or tax advice — verify with the issuer before acting."));
  $("#labTax").value = LS.tax;
  $("#labFam").addEventListener("change", e => { LS.fam = e.target.value; LS.shown = LAB_PAGE; renderLab(); });
  $("#labPass").addEventListener("change", e => { LS.pass = e.target.checked; LS.shown = LAB_PAGE; renderLab(); });
  $("#labTax").addEventListener("change", e => { LS.tax = e.target.value; try { localStorage.setItem("etf.labTax", LS.tax); } catch (_) { /* ignore */ } renderLab(); });
  $("#labMkt").addEventListener("change", e => { LS.market = e.target.value; LS.shown = LAB_PAGE; renderLab(); });
  let t = null;
  $("#labQ").addEventListener("input", e => { clearTimeout(t); t = setTimeout(() => { LS.q = e.target.value.trim().toLowerCase(); LS.shown = LAB_PAGE; renderLab(); }, 150); });
  $("#labMore").addEventListener("click", () => { LS.shown += LAB_PAGE; renderLab(); });
  let rt = null;
  window.addEventListener("resize", () => { if (VIEW === "income") { clearTimeout(rt); rt = setTimeout(renderChart, 150); } });
}

function methodBox() {
  const d = el("details", { class: "glossary taxbox" });
  d.append(el("summary", {}, "How the screen and score work"));
  const g = LAB.gates, liq = LAB.liquidity;
  const dl = el("dl");
  const add = (k, v) => dl.append(el("dt", {}, k), el("dd", {}, v));
  add("Layer 1 — tiered gates", `Systematic strategies: AUM ≥ $${g.systematic.aum}M, ≥ ${g.systematic.age} years old, expense ≤ ${g.systematic.er}%. ` +
    `Actively managed: AUM ≥ $${g.active.aum}M, ≥ ${g.active.age} years, expense ≤ ${g.active.er}%. Everyone: ≥ ${(liq.shares / 1000)}K shares/day ` +
    `or ≥ $${liq.dollars / 1e6}M/day traded, and no leveraged funds or ETNs. Untick “Recommended screen” to see every fund.`);
  add("Layer 2 — quality components (0–100)", "Total return vs the fund's own benchmark (−4 pp/yr scores 50 on a smooth curve; level with it ≈ 83); distribution coverage — how much of the payout came from total return rather than from a falling NAV (<70% is flagged); NAV trend; underlying quality (broad index > sector > single stock > leveraged, extreme-yield penalty, payout track record); US tax efficiency; fees; plus ELN counterparty/transparency, volatility-spike sensitivity and payout stability where relevant.");
  add("Layer 3 — family weights", Object.entries(LAB.weights).map(([k, w]) =>
    `${WEIGHT_LABEL[k] || famName(k)}: ` + Object.entries(w).map(([c, v]) => `${COMP_LABEL[c] || c} ${v}%`).join(", ")).join(" · "));
  add("Tax view", "US taxable investor: as in the brief. Non-US / tax-sheltered: the US-tax component is dropped and the other weights scaled up — §1256 60/40 treatment doesn't help non-US investors (US withholding on distributions matters instead — see the Explorer's Tax & domicile panel). Hong Kong and London funds never get the US-tax component.");
  add("Young funds", "Funds need about a year of history to be scored. With less than three years, the history-based components are pulled toward what seasoned funds of the same strategy typically score — a short record is judged against the strategy's norm.");
  add("Changes from the original brief", "Coverage is measured from prices and distributions rather than the tax 'return of capital' label (not available in free data, and misleading for funds like SPYI whose ROC is a tax effect while NAV holds up). Benchmarks are each fund's own underlying, not always SPY. Liquidity accepts $2M/day as an alternative to 100K shares. Holdings-quality (ROE, leverage of the stocks) is approximated by the underlying exposure, since holdings fundamentals for 400+ funds aren't available.");
  d.append(dl);
  return d;
}

function labFiltered() {
  const words = LS.q.split(/\s+/).filter(Boolean);
  return LAB.funds.filter(f =>
    (!LS.fam || f.family === LS.fam) &&
    (!LS.pass || f.passes) &&
    (!LS.market || f.market === LS.market) &&
    (!words.length || words.every(w => f.t.toLowerCase().includes(w) || f.n.toLowerCase().includes(w))));
}

const LAB_COLS = [
  { key: "rank", label: "#", v: f => labRank(f), fmt: f => labRank(f) ? String(labRank(f)) : "—", help: "Rank within its strategy family (all funds, current tax view)." },
  { key: "t", label: "Fund", v: f => f.t },
  { key: "score", label: "Score", v: f => labScore(f), fmt: f => scoreCell(labScore(f)), help: "0–100 quality score with the family's weights. Compare within a family." },
  { key: "yld", label: "Yield", v: f => regYield(f), fmt: f => pctPlain(regYield(f)), help: "Regular distributions over the last 12 months ÷ price (one-off year-end capital-gain specials excluded)." },
  { key: "tr", label: "Total return", v: f => f.metrics.tr_ann, fmt: f => signedSpan(f.metrics.tr_ann, pct), help: "Annualised total return (distributions reinvested) over the window." },
  { key: "gap", label: "vs benchmark", v: f => f.metrics.gap, fmt: f => signedSpan(f.metrics.gap, pp), help: "Annualised total return minus the fund's own benchmark. Below −4 pp/yr = the income is costing too much." },
  { key: "nav", label: "NAV trend", v: f => f.metrics.price_cagr, fmt: f => signedSpan(f.metrics.price_cagr, pct), help: "Annualised change in price (≈ NAV), excluding distributions." },
  { key: "cov", label: "Covered", v: f => f.metrics.coverage, fmt: f => coverageCell(f.metrics.coverage), help: "Share of distributions paid out of total return rather than out of a falling NAV." },
  { key: "mdd", label: "Max DD", v: f => f.metrics.max_drawdown, fmt: f => signedSpan(f.metrics.max_drawdown, pct), help: "Worst peak-to-trough fall over the window." },
  { key: "er", label: "Expense", v: f => f.er, fmt: f => f.er == null ? "—" : f.er.toFixed(2) + "%" },
  { key: "aum", label: "AUM", v: f => f.aum_usd, fmt: f => f.aum_usd == null ? "—" : fmtMoneyM(f.aum_usd, "USD") },
];
function gateStatus(f) {
  if (f.passes) return "passes every gate";
  const failed = Object.entries(f.gates).filter(([, v]) => v === false).map(([k]) => GATE_LABEL[k].toLowerCase());
  const unknown = (f.gates_unknown || []).map(k => GATE_LABEL[k].toLowerCase());
  return [failed.length ? "fails: " + failed.join(", ") : null, unknown.length ? "no data: " + unknown.join(", ") : null].filter(Boolean).join(" · ");
}
function scoreCell(s) {
  if (s == null) return el("span", { class: "muted", title: "Not enough history to score (needs about a year)" }, "n/a");
  return el("span", { class: "scorechip" }, el("span", { class: "scorebar", style: `--w:${s}%` }), String(Math.round(s)));
}
function signedSpan(x, f) { return x == null ? el("span", { class: "muted" }, "—") : el("span", { class: x >= 0 ? "pos" : "neg" }, f(x)); }
function coverageCell(c) {
  if (c == null) return el("span", { class: "muted" }, "—");
  return el("span", { class: c >= 0.7 ? "" : "neg", title: c < 0.7 ? "More than 30% of distributions came out of NAV" : "" }, `${Math.round(c * 100)}%${c < 0.7 ? " ⚠" : ""}`);
}

function renderLab() {
  if (!LAB || !$("#labTable")) return;
  const all = labFiltered();
  const { key, dir } = LS.sort;
  const col = LAB_COLS.find(c => c.key === key);
  all.sort((a, b) => {
    const va = col.v(a), vb = col.v(b);
    if (va == null || vb == null) return va == null && vb == null ? a.t.localeCompare(b.t) : (va == null ? 1 : -1);
    return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * dir || a.t.localeCompare(b.t);
  });
  const rows = all.slice(0, LS.shown);
  $("#labCount").textContent = `${all.length} fund${all.length === 1 ? "" : "s"}${LS.pass ? " passing every gate" : ""}` +
    `${LS.fam ? " in " + famName(LS.fam) : ""} · showing ${rows.length} · ${LS.fam ? "ranked within this family" : "pick a family to rank like-for-like"}`;
  $("#labMore").hidden = rows.length >= all.length;
  const wrap = $("#labTable"); wrap.innerHTML = "";
  if (!rows.length) {
    wrap.append(el("div", { class: "empty" }, "No funds match. ", el("button", { class: "refresh", onclick: () => {
      LS.pass = false; $("#labPass").checked = false; LS.q = ""; $("#labQ").value = ""; renderLab(); } }, "Show funds that fail a gate too")));
  } else {
    const head = el("tr");
    LAB_COLS.forEach(c => {
      const active = LS.sort.key === c.key;
      head.append(el("th", { title: c.help || c.label, class: c.help ? "has-help" : "", onclick: () => {
        LS.sort = LS.sort.key === c.key ? { key: c.key, dir: -LS.sort.dir } : { key: c.key, dir: ["t", "rank", "er"].includes(c.key) ? 1 : -1 };
        renderLab(); } }, c.label, c.help ? el("span", { class: "qmark" }, "ⓘ") : null,
        active ? el("span", { class: "arrow" }, LS.sort.dir > 0 ? " ▲" : " ▼") : null));
    });
    const body = el("tbody");
    rows.forEach(f => {
      const tr = el("tr", {});
      LAB_COLS.forEach(c => {
        if (c.key === "t") {
          tr.append(pressable(el("td", { class: "col-ticker", "aria-label": `Open ${f.t}` },
            el("span", { class: "tk" }, f.t),
            f.passes ? el("span", { class: "tag-pass", title: "Passes every gate" }, "✓ screen") : null,
            el("div", { class: "nm" }, f.n, el("span", { class: "seg" }, famName(f.family)),
              f.market !== "US" ? el("span", { class: "seg mkt" }, f.market === "LSE" ? "London" : "Hong Kong") : null)),
            () => openLabCard(f)));
        } else {
          tr.append(el("td", { "data-label": c.label, onclick: () => openLabCard(f) }, c.fmt(f)));
        }
      });
      body.append(tr);
    });
    const table = el("table"); table.append(el("thead", {}, head), body); wrap.append(table);
  }
  renderChart(all);
}

// ---- scatter: yield (x) vs quality score (y) -------------------------
// Yield axis on a square-root scale: most funds yield 5-20%, but single-stock
// funds reach 100%+ — a linear axis either crushes the crowd or pins outliers.
const X_CAP = 2.5;                                     // only yields above 250% are pinned at the edge
function renderChart(list) {
  const host = $("#labChart"); if (!host || !LAB) return;
  const pts = (list || labFiltered()).filter(f => labScore(f) != null && regYield(f) != null);
  $("#labChartTitle").textContent = `Yield vs quality score — ${LS.fam ? famName(LS.fam) : "all strategy families"}${LS.pass ? " (recommended screen)" : ""}`;
  host.innerHTML = "";
  const W = Math.max(300, host.clientWidth || 600), H = Math.min(360, Math.max(240, Math.round(W * 0.5)));
  const m = { l: 40, r: 14, t: 10, b: 34 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const maxY = Math.min(X_CAP, Math.max(0.1, ...pts.map(f => regYield(f))) * 1.05);
  const x = v => m.l + Math.sqrt(Math.max(0, Math.min(v, maxY)) / maxY) * iw;
  const y = v => m.t + (1 - v / 100) * ih;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
    "aria-label": `Scatter of ${pts.length} funds: distribution yield against quality score` });
  const g = svgEl("g", { class: "axis" });
  [0, 25, 50, 75, 100].forEach(v => {
    g.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: "grid" }));
    const t = svgEl("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }); t.textContent = v; g.append(t);
  });
  let lastX = -99;
  [0, 0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 1.6].filter(v => v <= maxY).forEach(v => {
    if (x(v) - lastX < 34) return;                     // keep tick labels apart
    lastX = x(v);
    g.append(svgEl("line", { x1: x(v), x2: x(v), y1: m.t, y2: m.t + ih, class: "grid" }));
    const t = svgEl("text", { x: x(v), y: H - m.b + 16, "text-anchor": "middle" }); t.textContent = `${Math.round(v * 100)}%`; g.append(t);
  });
  const xl = svgEl("text", { x: m.l + iw / 2, y: H - 4, "text-anchor": "middle", class: "axlabel" }); xl.textContent = "Distribution yield, last 12 months (square-root scale)";
  const yl = svgEl("text", { x: 12, y: m.t + ih / 2, "text-anchor": "middle", class: "axlabel", transform: `rotate(-90 12 ${m.t + ih / 2})` }); yl.textContent = "Quality score";
  g.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), class: "base" }), xl, yl);
  svg.append(g);
  const tip = el("div", { class: "viztip", hidden: "hidden" });
  const show = (f, cx, cy) => {
    tip.innerHTML = "";
    tip.append(el("strong", {}, `${Math.round(labScore(f))} · ${pctPlain(regYield(f))}`),
      el("div", {}, `${f.t} — ${f.n}`), el("div", { class: "muted" }, `${famName(f.family)} · ${gateStatus(f)}`));
    tip.hidden = false;
    const left = Math.min(cx + 12, W - 220), top = Math.max(0, cy - 10);
    tip.style.left = left + "px"; tip.style.top = top + "px";
  };
  const top5 = new Set(pts.slice().sort((a, b) => labScore(b) - labScore(a)).slice(0, 5).map(f => f.t));
  const placed = [];
  // failing funds first so passing ones sit on top
  pts.slice().sort((a, b) => (a.passes === b.passes ? 0 : a.passes ? 1 : -1)).forEach(f => {
    const cx = x(regYield(f)), cy = y(labScore(f));
    const grp = svgEl("g", { class: "pt" + (f.passes ? " pass" : " fail"), tabindex: "0", role: "button",
      "aria-label": `${f.t}: score ${Math.round(labScore(f))}, yield ${pctPlain(regYield(f))}` });
    grp.append(svgEl("circle", { cx, cy, r: 12, class: "hit" }), svgEl("circle", { cx, cy, r: f.passes ? 5 : 4, class: "dot" }));
    if (regYield(f) > maxY) grp.append(svgEl("path", { d: `M${cx + 6},${cy - 4} l5,4 l-5,4 z`, class: "pin" }));
    if (top5.has(f.t)) {                               // direct label unless it would collide with one already placed
      const w = f.t.length * 7 + 4, box = [cx + 8, cy - 18, cx + 8 + w, cy - 4];
      if (!placed.some(b => box[0] < b[2] && b[0] < box[2] && box[1] < b[3] && b[1] < box[3])) {
        placed.push(box);
        const lab = svgEl("text", { x: cx + 8, y: cy - 7, class: "dlabel" }); lab.textContent = f.t; grp.append(lab);
      }
    }
    grp.addEventListener("pointerenter", () => show(f, cx, cy));
    grp.addEventListener("focus", () => show(f, cx, cy));
    grp.addEventListener("pointerleave", () => { tip.hidden = true; });
    grp.addEventListener("blur", () => { tip.hidden = true; });
    grp.addEventListener("click", () => openLabCard(f));
    grp.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openLabCard(f); } });
    svg.append(grp);
  });
  host.append(svg, tip);
  const pinned = pts.filter(f => regYield(f) > maxY).length;
  $("#labChartNote").textContent = `${pts.length} funds with a score. Top 5 by score are labelled; hover or tap a dot for details, click to open it.` +
    (pinned ? ` ${pinned} fund${pinned === 1 ? "" : "s"} yielding over ${Math.round(maxY * 100)}% ${pinned === 1 ? "is" : "are"} pinned at the right edge (▸).` : "") +
    " Upper-right = high yield with high quality.";
}

// ---- fund card ----------------------------------------------------------
function openLabCard(f) {
  const m = f.metrics, s = labScore(f), w = labWeights(f) || {};
  const body = $("#memoBody"); body.innerHTML = "";
  const wrap = el("div", { class: "memo" });
  const home = curatedHome(f.t, null);
  const famFunds = LAB.funds.filter(x => x.family === f.family && labScore(x) != null).length;
  wrap.append(
    el("h2", { id: "memoTitle" }, `${f.t} — ${f.n}`),
    el("div", { class: "sub" }, `${famName(f.family)} · ${f.style === "systematic" ? "systematic" : "actively managed"} · ${f.market === "LSE" ? "London" : f.market === "HK" ? "Hong Kong" : "US"}-listed · ` +
      (f.bench ? `benchmark ${f.bench}${f.bench_assumed ? " (assumed: no index named)" : ""}` : "no comparable benchmark") +
      (f.eln ? " · uses equity-linked notes" : "")),
    el("div", { class: "liverow" },
      el("a", { class: "holdlink", href: quoteUrl(f.t), target: "_blank", rel: "noopener" }, "↗ Live quote"),
      home ? el("button", { class: "refresh", onclick: () => { goTo(home, f.t); liveMsg(`${f.t}: full analysis card in the ${home.name} theme.`, "", { label: "← Back to Income Lab", fn: () => showIncomeLab() }); } }, `Full analysis in ${home.name} →`) : null),
    el("div", { class: "hero" },
      el("div", { class: "heroval" }, s == null ? "n/a" : String(Math.round(s)), el("span", { class: "muted" }, " / 100")),
      el("div", { class: "muted small" }, s == null ? (f.inverse ? "Inverse strategy — not scored against a long benchmark." :
      f.currency_mismatch ? "Different currency from its benchmark — not scored." : f.bench_missing || !f.bench ? "No benchmark available — not scored." :
      "Not enough history to score (needs about a year).") :
        `Rank ${labRank(f) || "—"} of ${famFunds} in ${famName(f.family)} · ${LS.tax === "us" ? "US taxable view" : "non-US view"}`)));

  // score breakdown
  if (s != null) {
    wrap.append(sectionTitle("Why this score"));
    const list = el("div", { class: "bars" });
    Object.entries(w).sort((a, b) => b[1] - a[1]).forEach(([k, wt]) => {
      const v = f.components[k];
      list.append(el("div", { class: "barrow", title: `${COMP_LABEL[k]}: ${v} / 100, weight ${wt}%` },
        el("span", { class: "blabel" }, `${COMP_LABEL[k] || k}`, el("span", { class: "muted" }, ` · ${wt}%`)),
        el("span", { class: "btrack" }, el("span", { class: "bfill", style: `--w:${v}%` })),
        el("span", { class: "bval" }, String(Math.round(v)))));
    });
    wrap.append(list, el("p", { class: "muted small" }, "Each bar is a 0–100 component score; the percentage is its weight for this strategy family." +
      (m.window_years < LAB.window_years ? ` Only ${m.window_years} years of history, so the return-based scores are pulled toward what seasoned ${famName(f.family).toLowerCase()} funds typically score.` : "")));
  }

  // gates
  wrap.append(sectionTitle("Recommended-screen gates"));
  const lim = LAB.gates[f.style];
  const gateText = {
    aum: `AUM ${f.aum_usd == null ? "unknown" : fmtMoneyM(f.aum_usd, "USD")} (needs ≥ $${lim.aum}M)`,
    age: `${f.age_years == null ? "unknown age" : f.age_years.toFixed(1) + " years old"} (needs ≥ ${lim.age})`,
    er: `Expense ${f.er == null ? "unknown" : f.er.toFixed(2) + "%"} (needs ≤ ${lim.er}%)`,
    liquidity: `${f.vol == null ? "volume unknown" : shares(f.vol)} (needs ≥ ${LAB.liquidity.shares / 1000}K shares or $${LAB.liquidity.dollars / 1e6}M/day)`,
    structure: f.family === "leveraged_income" ? "Leveraged — excluded" : "Not leveraged, not an ETN",
  };
  const gl = el("ul", { class: "gates" });
  Object.entries(f.gates).forEach(([k, ok]) => gl.append(el("li", { class: ok === true ? "ok" : ok === false ? "no" : "unk" },
    el("span", { class: "gicon", "aria-hidden": "true" }, ok === true ? "✓" : ok === false ? "✗" : "?"),
    el("b", {}, GATE_LABEL[k] + ": "), ok === true ? "pass — " : ok === false ? "fail — " : "no data — ", gateText[k])));
  wrap.append(gl);

  // distribution coverage
  wrap.append(sectionTitle("Where the distributions came from"));
  if (m.coverage == null) {
    wrap.append(el("p", { class: "muted" }, m.short_history ? "Too little history yet (under a year)." : "Not enough data to split the distributions."));
  } else {
    const cov = m.coverage, cap = 1 - cov;
    const bar = el("div", { class: "covbar", role: "img", "aria-label": `${Math.round(cov * 100)}% from total return, ${Math.round(cap * 100)}% from capital` },
      cov > 0 ? el("span", { class: "seg1", style: `flex:${cov}` }) : null, cap > 0.005 ? el("span", { class: "seg2", style: `flex:${cap}` }) : null);
    wrap.append(bar, el("div", { class: "covlegend" },
      el("span", {}, el("i", { class: "key k1" }), `From total return ${Math.round(cov * 100)}%`),
      cap > 0.005 ? el("span", {}, el("i", { class: "key k2" }), `From capital (NAV fell) ${Math.round(cap * 100)}%`) : null),
      el("p", { class: "muted small" }, `Distributions averaged ${pctPlain(m.dist_yield_ann)} a year while the price (≈ NAV) changed ${pct(m.price_cagr)} a year, ` +
        `${m.window_years} years to ${m.as_of}. ` + (cap > 0.3 ? "More than 30% of the payout effectively came out of your capital — the destructive kind of return of capital." :
          cap > 0.005 ? "Some of the payout came out of capital." : "NAV held up, so the payout was covered by the fund's returns.") +
        " This is measured from prices and payouts — the issuer's tax 'return of capital' label can differ (it's a tax classification, not a measure of NAV erosion)."));
  }

  // distribution history
  if (m.dist_hist && m.dist_hist.length) {
    wrap.append(sectionTitle("Distribution history (last 24 months)"));
    wrap.append(distChart(m.dist_hist, f.cur),
      el("p", { class: "muted small" }, `${m.payments_12m} payments in the last 12 months · paid ${m.streak_months} months in a row` +
        (m.stability_cv != null ? ` · payment variability ${Math.round(m.stability_cv * 100)}% (lower = steadier)` : "") +
        (f.extreme_yield ? " · ⚠ yield far above its strategy family's norm" : "")));
  }

  // returns & holding experience
  const facts = [
    ["Yield (12 months, regular)", pctPlain(regYield(f))],
    ["Incl. year-end specials", m.specials_ttm ? `${pctPlain(m.yield_ttm)} (specials ${pctPlain(m.specials_ttm)})` : "none"],
    ["Total return / yr", pct(m.tr_ann)], [`${f.bench} total return / yr`, pct(m.bench_tr_ann)], ["vs benchmark", pp(m.gap)],
    ["NAV (price) trend / yr", pct(m.price_cagr)], ["Max drawdown", pct(m.max_drawdown)],
    ["Volatility / yr", pctPlain(m.vol_ann)], ["Sharpe ratio", m.sharpe == null ? "—" : m.sharpe.toFixed(2)],
    ["Upside capture", m.up_capture == null ? "—" : `${Math.round(m.up_capture * 100)}%`],
    ["Downside capture", m.down_capture == null ? "—" : `${Math.round(m.down_capture * 100)}%`],
    ["VIX sensitivity (beta)", m.vix_beta == null ? "—" : m.vix_beta.toFixed(3)],
    ["Worst VIX-spike day", m.vix_spike_day ? `${pct(m.vix_spike_day.fund_return)} (VIX ${pct(m.vix_spike_day.vix_change, 0)})` : "—"],
    ["Window", m.window_start ? `${m.window_start} → ${m.as_of} (${m.window_years} yrs)` : "—"],
    ["Expense ratio", f.er == null ? "—" : f.er.toFixed(2) + "%"], ["AUM", f.aum_usd == null ? "—" : fmtMoneyM(f.aum_usd, "USD")],
  ];
  const kv = el("div", { class: "kv" });
  facts.forEach(([k, v]) => kv.append(el("div", {}, el("span", {}, k + ": "), v)));
  wrap.append(sectionTitle("Returns & holding experience"), kv,
    el("p", { class: "muted small" }, "Upside/downside capture: how much of the benchmark's up and down months the fund kept — covered calls typically keep far less of the upside than of the downside. Sharpe uses T-bill returns as the risk-free rate."));

  // flags + tax
  const flags = [];
  if (f.family === "leveraged_income") flags.push("🔴 Leveraged underlying — volatility decay; not a buy-and-hold income fund.");
  if (f.exposure === "single stock") flags.push(`🔴 Single-stock strategy on ${f.bench} — the payout depends on one company's volatility; NAV erosion is common.`);
  if (m.coverage != null && m.coverage < 0.7) flags.push("⚠️ Over 30% of distributions came out of NAV.");
  if (m.gap != null && m.gap < -0.04) flags.push("⚠️ Trails its benchmark by more than 4 pp a year — the income is costing a lot of return.");
  if (f.extreme_yield) flags.push("⚠️ Yield far above what its strategy family normally pays — usually unsustainable.");
  if (f.inverse) flags.push("🔴 Inverse strategy (profits when the underlying falls) — not comparable to a long benchmark, so it isn't scored.");
  if (f.bench_missing) flags.push(`❓ Benchmark ${f.bench} couldn't be loaded — total return vs benchmark not available.`);
  if (f.currency_mismatch) flags.push("❓ This line trades in a different currency from its benchmark, so the comparison would mostly measure the exchange rate — not scored.");
  if (f.bench_assumed) flags.push("ℹ️ No index named in the fund's name — compared with the S&P 500 as an assumption.");
  if (m.bad_ticks_removed) flags.push(`ℹ️ ${m.bad_ticks_removed} bad price print${m.bad_ticks_removed === 1 ? "" : "s"} removed from the price history.`);
  if ((f.gates_unknown || []).length) flags.push("❓ Missing data for: " + f.gates_unknown.map(k => GATE_LABEL[k].toLowerCase()).join(", ") + " — the fund can't pass the recommended screen until it's known.");
  if (f.eln) flags.push("⚠️ Uses equity-linked notes: bank counterparty risk and less transparent option exposure.");
  if (m.short_history) flags.push("❓ Less than a year of history — not scored.");
  if (flags.length) { const ul = el("ul", { class: "flags" }); flags.forEach(x => ul.append(el("li", {}, x))); wrap.append(sectionTitle("Flags"), ul); }
  wrap.append(sectionTitle("Tax character (general, US investor view)"),
    el("p", {}, f.market === "US" ? (f.tax_note || "—") : "Not a US fund — the US tax characterisation doesn't apply; see the Explorer's Tax & domicile panel for withholding by domicile."),
    el("p", { class: "muted small" }, "General information, not tax advice. For non-US investors, US withholding on distributions usually matters more than §1256 treatment."));

  body.append(wrap);
  $("#overlay").hidden = false; $("#memoDrawer").hidden = false;
  $("#memoDrawer").scrollTop = 0;
  document.body.classList.add("noscroll");
  $("#closeMemo").focus({ preventScroll: true });
}

function distChart(hist, cur) {
  const W = 560, H = 120, m = { l: 6, r: 6, t: 8, b: 20 };
  const max = Math.max(...hist.map(([, v]) => v)) || 1;   // months without a payment show as gaps
  const n = hist.length, gap = 2, bw = Math.max(3, (W - m.l - m.r) / n - gap);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "distchart", role: "img",
    "aria-label": `Monthly distributions over ${n} months, highest ${max.toFixed(3)}` });
  const host = el("div", { class: "scatter" });
  const tip = el("div", { class: "viztip", hidden: "hidden" });
  svg.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, class: "base" }));
  hist.forEach(([mo, v], i) => {
    const h = v > 0 ? Math.max(2, v / max * (H - m.t - m.b)) : 0, x0 = m.l + i * (bw + gap), y0 = H - m.b - h;
    const r = Math.min(4, bw / 2);
    const d = `M${x0},${H - m.b} V${y0 + r} Q${x0},${y0} ${x0 + r},${y0} H${x0 + bw - r} Q${x0 + bw},${y0} ${x0 + bw},${y0 + r} V${H - m.b} Z`;
    const g = svgEl("g", { class: "pt", tabindex: "0", "aria-label": `${mo}: ${v}` });
    g.append(svgEl("rect", { x: x0 - 1, y: m.t, width: bw + 2, height: H - m.t - m.b, class: "hit" }));
    if (v > 0) g.append(svgEl("path", { d, class: "bar" }));
    const showTip = () => { tip.innerHTML = ""; tip.append(el("strong", {}, v > 0 ? `${CUR_SYM[cur] || ""}${v.toFixed(4)}` : "no payment"), el("div", { class: "muted" }, mo)); tip.hidden = false;
      tip.style.left = Math.min(x0 / W * 100, 70) + "%"; tip.style.top = "0px"; };
    g.addEventListener("pointerenter", showTip); g.addEventListener("focus", showTip);
    g.addEventListener("pointerleave", () => { tip.hidden = true; }); g.addEventListener("blur", () => { tip.hidden = true; });
    svg.append(g);
    if (i === 0 || i === n - 1) { const t = svgEl("text", { x: x0 + bw / 2, y: H - 5, "text-anchor": i === 0 ? "start" : "end", class: "axtext" }); t.textContent = mo; svg.append(t); }
  });
  host.append(svg, tip);
  return host;
}
