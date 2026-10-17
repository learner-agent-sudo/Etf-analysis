"use strict";

// ====================================================================
// Income ranking — Themes → Income / Covered-Call → "Value ranking".
// Every option-income ETF (US / Hong Kong / London) gets one Value Score
// (0-100, the same formula for every strategy) so any two funds can be
// compared: earned income, paycheck trend, growth kept and smooth ride, 25
// points each, minus red flags. The brief's gates define "safety-checked";
// its strategy-family score sits in each fund card's expert details.
// Data: data/income-lab.json, rebuilt every weekday by
// scripts/build_income.py; loaded when the income theme opens.
// Shares helpers with app.js (el, $, liveMsg, openMemo, closeMemo, …).
// ====================================================================

let LAB = null;
let RANKS = new Map();                                 // ticker -> rank by Value Score within the current view
const LAB_PAGE = 50, CMP_MAX = 3;
const lsGet = k => { try { return localStorage.getItem(k); } catch (_) { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (_) { /* private mode */ } };
const LS = { scope: "safe", fam: "", market: lsGet("etf.labMkt") || "", minYield: 0, q: "",
  sort: { key: "value", dir: -1 }, shown: LAB_PAGE, cmp: [], tax: lsGet("etf.labTax") || "us" };

const FAM_PLAIN = {
  systematic_cc: "Covered call · rules-based", active_premium: "Covered call · managed", call_spread: "Call spread · tax-aware",
  daily_0dte: "Daily options (0DTE)", put_write: "Put-selling", dividend_options: "Dividend stocks + options",
  short_vol: "Short volatility", single_stock: "Single-stock options", crypto_income: "Crypto options",
  structured: "Autocallable notes", leveraged_income: "Leveraged income",
};
const BENCH_NAME = {                                   // read after "the": "vs the S&P 500"
  SPY: "S&P 500", QQQ: "Nasdaq-100", IWM: "Russell 2000", DIA: "Dow 30", EFA: "developed-markets index (EAFE)",
  ACWI: "world stock index", EEM: "emerging-markets index", FEZ: "Euro Stoxx 50", VGK: "European stock index",
  EWC: "Canadian stock index", AGG: "US bond market", TLT: "20+ year Treasury index", LQD: "investment-grade bond index",
  HYG: "high-yield bond index", XLK: "US tech sector", XLE: "US energy sector", XLF: "US financial sector",
  XLU: "US utilities sector", XLV: "US health-care sector", XLI: "US industrial sector", XLY: "US consumer sector",
  XLP: "US consumer-staples sector", XLB: "US materials sector", XLC: "US communication sector", XLRE: "US real-estate sector",
  SOXX: "semiconductor index", GLD: "gold price", SLV: "silver price", USO: "oil price", COPX: "copper-miner index",
  "BTC-USD": "bitcoin price", "ETH-USD": "ether price", MAGS: "Magnificent 7", ARKK: "ARK Innovation fund",
  AMLP: "MLP index", KWEB: "China internet index", FDN: "US internet index", GDX: "gold-miner index",
  "2800.HK": "Hang Seng Index", "2828.HK": "Hang Seng China Enterprises Index", "3067.HK": "Hang Seng Tech Index",
  "069500.KS": "KOSPI 200",
};
const FLAG_CHIP = { leveraged: "Leveraged", big_fall: "Fell over 50%", speculative: "One stock / crypto", note: "ETN/ETP note",
  own_money: "Pays from capital", cash_like: "≈ cash", young: "Short record", small: "Small / thin trading" };
const COMP_LABEL = {
  gap: "Total return vs benchmark", coverage: "Distribution coverage", nav: "NAV (price) trend",
  quality: "Underlying quality", tax: "Tax efficiency (US)", fees: "Fees",
  counterparty: "Counterparty risk", transparency: "ELN transparency", vix: "Volatility-spike sensitivity",
  stability: "Distribution stability",
};
const GATE_LABEL = { aum: "Fund size", age: "Track record", er: "Fee", liquidity: "Trading volume", structure: "Structure" };
const WEIGHT_LABEL = { active_premium_eln: "Active premium using ELNs", default: "All other families (incl. active funds without ELNs)" };

const pct = (x, d = 1) => x == null ? "—" : `${x > 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;
const pctPlain = (x, d = 1) => x == null ? "—" : `${(x * 100).toFixed(d)}%`;
const pp = x => x == null ? "—" : `${x > 0 ? "+" : ""}${(x * 100).toFixed(1)} pp/yr`;
const perYr = x => x == null ? "—" : pct(x) + "/yr";
const usd = x => x == null ? "—" : `${x < 0 ? "-" : ""}$${Math.round(Math.abs(x)).toLocaleString("en-US")}`;
const regYield = f => f.metrics.yield_regular != null ? f.metrics.yield_regular : f.metrics.yield_ttm;
const paidY = f => f.paid_yield != null ? f.paid_yield : regYield(f);
const famName = k => FAM_PLAIN[k] || (LAB && LAB.families[k]) || k;
const benchName = f => f.under || BENCH_NAME[f.bench] || f.bench || "its benchmark";
const benchThe = f => f.under || !BENCH_NAME[f.bench] ? benchName(f) : "the " + benchName(f);      // in sentences
const mktName = k => ({ US: "the US", HK: "Hong Kong", LSE: "London" }[k] || k);
const flagText = k => (((LAB && LAB.value && LAB.value.flags) || {})[k] || {}).text || FLAG_CHIP[k] || k;
const labScore = f => LS.tax === "us" ? f.score_us : f.score_intl;          // the brief's family score (expert)
const labRank = f => LS.tax === "us" ? f.rank_us : f.rank_intl;
const labWeights = f => LS.tax === "us" ? f.weights_us : f.weights_intl;
const labFund = t => (LAB && LAB.funds.find(f => f.t === t)) || null;
const byValue = (a, b) => a.value_rank - b.value_rank;
const svgEl = (tag, attrs = {}) => { const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([k, v]) => v != null && n.setAttribute(k, v)); return n; };

async function loadLab() {
  if (LAB) return LAB;
  try { LAB = await fetchJson("data/income-lab.json"); } catch (_) { LAB = null; }
  return LAB;
}

// Entry point from selectTheme() when the income theme's ranking is shown.
async function showIncomeRankings() {
  const box = $("#incomeLab");
  box.hidden = false;
  if (!LAB) box.innerHTML = '<p class="muted">Loading the income ranking…</p>';
  await loadLab();
  if (INCOME_SUB !== "rankings" || VIEW !== "themes") { box.hidden = true; return; }    // switched away meanwhile
  if (!LAB) {
    box.innerHTML = "";
    box.append(el("p", { class: "livemsg warn" }, "The income ranking hasn't been generated yet — it's built automatically by the daily update."));
    return;
  }
  if (!box.dataset.built) buildLab(box);
  renderLab();
  // deep links: #income/fund=GPIX, #income/compare=GPIX,SPYI
  const m = decodeURIComponent(location.hash).match(/^#income\/(fund|compare)=(.+)$/);
  if (m && m[1] === "fund") {
    if (labFund(m[2])) openLabCard(labFund(m[2]));
    else { history.replaceState(null, "", "#income"); liveMsg(`${m[2]} isn't in the income ranking — it may not be an option-income fund, or it isn't listed any more.`, "warn"); }
  }
  if (m && m[1] === "compare") {
    LS.cmp = [...new Set(m[2].split(","))].filter(labFund).slice(0, CMP_MAX);
    renderLab();
    if (LS.cmp.length >= 2) openCompare();
  }
}
// Older entry point (bookmarks, "Back" buttons): the ranking now lives in the income theme.
function showIncomeLab() { selectTheme("income", "rankings"); }

// ---- page skeleton --------------------------------------------------------
function buildLab(box) {
  box.innerHTML = ""; box.dataset.built = "1";
  const V = LAB.value || {}, n = LAB.funds.length;
  const famCounts = {};
  LAB.funds.forEach(f => { famCounts[f.family] = (famCounts[f.family] || 0) + 1; });
  box.append(
    el("p", { class: "lede" }, "Every option-income ETF we track (US, Hong Kong, London) gets one ", el("b", {}, "Value Score"),
      " out of 100: how much income and growth it actually delivered for the risk you took. ", el("b", {}, "Higher = better value"),
      ", and because every fund is scored the same way, any two can be compared."),
    el("div", { class: "asof" }, `${V.rated || 0} of ${n} funds rated · data to ${LAB.as_of} · updates every weekday · not investment advice`),
    standoutsBlock(),
    periodBanner(),
    undervaluedBox(),
    el("section", { class: "controls labcontrols" },
      el("div", { class: "segbtns", id: "labScope", role: "group", "aria-label": "Which funds" }),
      el("select", { id: "labFam", "aria-label": "Strategy type" }, el("option", { value: "" }, "All strategy types"),
        ...Object.keys(FAM_PLAIN).filter(k => famCounts[k]).map(k => el("option", { value: k }, `${famName(k)} (${famCounts[k]})`))),
      el("select", { id: "labMkt", "aria-label": "Where it is listed" }, el("option", { value: "" }, "Listed anywhere"),
        el("option", { value: "US" }, "Listed in the US"), el("option", { value: "HK" }, "Listed in Hong Kong"), el("option", { value: "LSE" }, "Listed in London")),
      el("select", { id: "labMin", "aria-label": "Minimum yield" }, el("option", { value: "0" }, "Pays any amount"),
        ...[0.04, 0.08, 0.12].map(v => el("option", { value: String(v) }, `Pays at least ${Math.round(v * 100)}%`))),
      el("input", { type: "search", id: "labQ", placeholder: "Search ticker or name…", "aria-label": "Search income ETFs" })),
    el("div", { id: "labCount", class: "muted small" }),
    el("section", { id: "labTable", class: "table-wrap" }),
    el("div", { class: "exmore" }, el("button", { id: "labMore", class: "refresh" }, "Show more")),
    howBox(),
    chartBox());
  $("#labMkt").value = LS.market;
  $("#labFam").addEventListener("change", e => { LS.fam = e.target.value; LS.shown = LAB_PAGE; renderLab(); });
  $("#labMkt").addEventListener("change", e => { LS.market = e.target.value; lsSet("etf.labMkt", LS.market); LS.shown = LAB_PAGE; renderLab(); });
  $("#labMin").addEventListener("change", e => { LS.minYield = +e.target.value; LS.shown = LAB_PAGE; renderLab(); });
  let t = null;
  $("#labQ").addEventListener("input", e => { clearTimeout(t); t = setTimeout(() => { LS.q = e.target.value.trim().toLowerCase(); LS.shown = LAB_PAGE; renderLab(); }, 150); });
  $("#labMore").addEventListener("click", () => { LS.shown += LAB_PAGE; renderLab(); });
  let rt = null;
  window.addEventListener("resize", () => { if (INCOME_SUB === "rankings") { clearTimeout(rt); rt = setTimeout(() => renderChart(), 150); } });
}

// The return-based pillars describe one stretch of market history — say which.
function periodBanner() {
  const spy = LAB.funds.filter(f => f.bench === "SPY" && !f.metrics.gap_window && f.metrics.window_years >= 2.9 && f.metrics.bench_tr_ann != null)
    .map(f => f.metrics.bench_tr_ann).sort((a, b) => a - b);
  const s = spy.length ? spy[Math.floor(spy.length / 2)] : null;
  const start = LAB.funds.map(f => f.metrics.window_start).filter(Boolean).sort()[0];
  const mood = s == null ? "" : s > 0.12 ? `, a strongly rising market (S&P 500 ${perYr(s)} with dividends)` : s < 0.03 ? `, a weak market (S&P 500 ${perYr(s)})` : ` (S&P 500 ${perYr(s)})`;
  return el("p", { class: "banner" }, `Measured over up to ${LAB.window_years} years, ${start || "—"} → ${LAB.as_of}${mood}. ` +
    "Option-income funds give up some upside for their payouts, so they tend to look better in flat or falling markets — the order can change. What happened, not a forecast.");
}

function undervaluedBox() {
  const d = el("details", { class: "callout" });
  d.append(el("summary", {}, "Looking for “undervalued”? Read this first"));
  const trap = labFund("TSLY"), good = labFund("GPIX");
  const g1 = trap && trap.growth_10k, g2 = good && good.growth_10k;
  const vix = LAB.market;
  d.append(
    el("p", {}, "An ETF's price follows the value of what it holds every day, so — unlike a single stock — there's no hidden discount to find. " +
      "What you ", el("i", {}, "can"), " find is better value: funds that pay income they actually earned, keep the share price (and your paycheck) from shrinking, " +
      "keep more of the market's growth and fall less. That is exactly what the Value Score ranks."),
    el("ul", {},
      el("li", {}, el("b", {}, "A high yield is not a bargain. "), g1 && g2
        ? `$10,000 in TSLY ${g1.years} years ago paid out about ${usd(g1.cash_paid)}, but the shares are now worth ${usd(g1.shares_now)} — the payouts were mostly your own money coming back. The same $10,000 in GPIX paid about ${usd(g2.cash_paid)} and the shares are worth ${usd(g2.shares_now)}.`
        : "If a fund pays more than it earns, the rest is your own money handed back and the price slides."),
      el("li", {}, el("b", {}, "A low share price is not cheap. "), "A $15 fund isn't cheaper than a $57 one; a price that keeps falling usually means the payouts are eating the capital."),
      vix ? el("li", {}, el("b", {}, "Timing: how rich are option premiums now? "),
        `The VIX (the market's “fear gauge”) is ${vix.vix} — higher than ${vix.pct_below}% of days in the last ${vix.years} years, so new option income is ` +
        `${vix.pct_below >= 70 ? "on the rich side" : vix.pct_below <= 30 ? "on the thin side" : "about normal"} right now. Covered-call funds collect more when the VIX is high (usually after markets fall). Market-wide context only — it isn't part of any fund's score.`) : null,
      el("li", {}, el("b", {}, "We never say “buy”. "), "The standouts are the best value for money over the period above. Check the issuer's documents before investing.")));
  return d;
}

// Three standouts from safety-checked funds with a full record and no red flags.
function standoutsBlock() {
  const pool = LAB.funds.filter(f => f.safety_checked && f.metrics.window_years >= 2.5 && !(f.value_flags || []).length).sort(byValue);
  const used = new Set();
  const pick = fn => { const f = pool.find(x => !used.has(x.t) && fn(x)); if (f) used.add(f.t); return f; };
  const picks = [
    ["Best overall value", pick(() => true)],
    ["Best for high income", pick(f => paidY(f) >= 0.10)],
    ["Smallest falls", pick(f => f.metrics.max_drawdown >= -0.15 && paidY(f) >= 0.05)],
  ].filter(([, f]) => f);
  const box = el("section", { class: "standouts", "aria-label": "Standouts" });
  picks.forEach(([label, f]) => {
    const all = f.earned_yield >= paidY(f) - 0.0005;
    box.append(el("div", { class: "stand" },
      el("div", { class: "slab" }, label),
      el("div", { class: "stop" }, el("span", {}, el("span", { class: "tk" }, f.t), el("div", { class: "nm" }, f.n)),
        el("span", { class: "sscore" }, el("span", { class: "big" }, String(f.value_display)), gradeChip(f, true))),
      el("div", { class: "small" }, `Pays ${pctPlain(paidY(f))}`, el("span", { class: all ? "pos" : "warn" }, all ? " · all earned" : ` · ${pctPlain(f.earned_yield)} earned`),
        ` · price ${perYr(f.metrics.price_cagr)} · worst fall ${pct(f.metrics.max_drawdown)}`),
      el("div", { class: "small" }, `On $10,000: about ${usd(10000 * paidY(f))} a year in cash`),
      f.age_grace_until ? el("div", { class: "small muted" }, `Turns ${LAB.gates[f.style].age} years old on ${f.age_grace_until}`) : null,
      el("div", { class: "sacts" },
        el("button", { class: "refresh", onclick: () => openLabCard(f) }, "Details"), cmpButton(f.t))));
  });
  return el("div", {}, box, el("p", { class: "muted small" }, "Picked from safety-checked funds with at least 2½ years of history and no red flags — the best value for money over the last 3 years, not buy recommendations."));
}

function howBox() {
  const d = el("details", { class: "glossary taxbox", id: "labHow" });
  d.append(el("summary", {}, "How the Value Score works"));
  const V = LAB.value || {}, g = LAB.gates, liq = LAB.liquidity;
  const dl = el("dl");
  const add = (k, v) => dl.append(el("dt", {}, k), el("dd", {}, v));
  add("Earned income · 25 pts", "What the fund paid over the last 12 months (regular payouts), counted only up to its total return — money handed back out of your own capital doesn't count. 4% a year ≈ 14 pts, 8% ≈ 20, 12% ≈ 23.");
  add("Paycheck trend · 25 pts", "Whether the share price held up. If it falls, every future payout is smaller in dollars. Flat ≈ 18 pts, −3%/yr ≈ 12½, −10%/yr ≈ 2.");
  add("Growth kept · 25 pts", "How much of its own market's return (S&P 500, Nasdaq-100 …) the fund kept while paying you. Level with it ≈ 21 pts; 4%/yr behind ≈ 12½.");
  add("Smooth ride · 25 pts", "How far it fell at its worst, and how much return above cash it gave for its ups and downs (the Sharpe ratio).");
  add("Red flags", Object.values(V.flags || {}).map(x => x.text + (x.kind === "cap" ? ` (score capped at ${x.amount})` : x.text.startsWith("Short") ? " (up to −10)" : ` (−${x.amount})`)).join(" · "));
  add("Grades", (V.grades || []).map(([lo, gr, label]) => `${gr} ${lo ? lo + "+" : "under 45"} ${label.toLowerCase()}`).join(" · ") + ". Scores within about 2 points are effectively tied.");
  add("Young funds", "Funds need about a year of prices to be rated. With less than three years, each pillar blends the fund's own numbers with the typical seasoned fund of the same strategy, in proportion to its history.");
  add("Safety-checked", `The gates from your brief: rules-based funds need AUM ≥ $${g.systematic.aum}M, ≥ ${g.systematic.age} years, fee ≤ ${g.systematic.er}%; actively managed ones AUM ≥ $${g.active.aum}M, ≥ ${g.active.age} years, fee ≤ ${g.active.er}%; all need ≥ ${liq.shares / 1000}K shares or $${liq.dollars / 1e6}M a day of trading and no leverage or ETN structure. Funds whose only miss is being up to ${(V.age_grace_years || 0.5) * 12} months too young are included and show the date they qualify. Missing data never counts as a pass.`);
  add("Not in the score", "Tax (it's personal — each card has general notes), fees (already taken out of every return shown) and the brief's strategy-family weights (in each card under “Details for experts”).");
  d.append(dl);
  return d;
}

function chartBox() {
  const d = el("details", { class: "glossary taxbox", id: "labChartBox" });
  d.append(el("summary", {}, "Chart: payout vs Value Score"),
    el("div", { class: "chartcard" },
      el("h3", { id: "labChartTitle" }),
      el("div", { class: "legend", "aria-hidden": "true" },
        el("span", {}, el("i", { class: "key pass" }), "safety-checked"),
        el("span", {}, el("i", { class: "key fail" }), "not safety-checked")),
      el("div", { id: "labChart", class: "scatter" }),
      el("p", { class: "muted small", id: "labChartNote" })));
  d.addEventListener("toggle", () => { if (d.open) renderChart(); });
  return d;
}

// ---- filtering, ranking, table -------------------------------------------------
// Scope + type + market + yield (not the search box): ranks are within this set.
function labBase(scope = LS.scope) {
  return LAB.funds.filter(f =>
    (scope === "unrated" ? f.value_score == null : f.value_score != null && (scope === "all" || f.safety_checked)) &&
    (!LS.fam || f.family === LS.fam) && (!LS.market || f.market === LS.market) &&
    (!LS.minYield || (paidY(f) || 0) >= LS.minYield));
}
function labSearch(list) {
  const words = LS.q.split(/\s+/).filter(Boolean);
  return words.length ? list.filter(f => words.every(w => f.t.toLowerCase().includes(w) || f.n.toLowerCase().includes(w))) : list;
}

const VCOLS = [
  { key: "t", label: "# · Fund", v: f => RANKS.get(f.t) || 9e9, help: "Rank by Value Score among the funds in this view (sorting by another column keeps each fund's rank). Tick the box to compare up to 3 funds side by side." },
  { key: "value", label: "Value Score", v: f => f.value_score, fmt: f => valueCell(f), help: "One number out of 100, the same formula for every fund: earned income, paycheck trend, growth kept and smooth ride (25 points each), minus red flags. Higher = better value. A 80+, B 70–79, C 60–69, D 45–59, F under 45." },
  { key: "income", label: "Income", v: f => paidY(f), fmt: f => incomeCell(f), help: "Regular payouts over the last 12 months ÷ price (year-end specials excluded), what that is on $10,000 a year, and how much of it the fund actually earned (the rest came out of your capital)." },
  { key: "nav", label: "Price trend", v: f => f.metrics.price_cagr, fmt: f => signedSpan(f.metrics.price_cagr, perYr), help: "How the share price (≈ the fund's value per share) changed per year, payouts not counted. Falling = each future payout is smaller." },
  { key: "gap", label: "vs its market", v: f => f.metrics.gap, fmt: f => gapCell(f), help: "Total return per year compared with the market the fund sells options on (S&P 500, Nasdaq-100 …). The cost of the income: below −4%/yr is a lot." },
  { key: "dd", label: "Worst fall", v: f => f.metrics.max_drawdown, fmt: f => ddCell(f), help: "The biggest drop from a high to a later low over the period (payouts reinvested), and what that meant on $10,000." },
  { key: "er", label: "Fee", v: f => f.er, fmt: f => f.er == null ? el("span", { class: "muted" }, "—") : el("span", {}, f.er.toFixed(2) + "%"), help: "Annual fee. It's already taken out of every return shown, so it isn't scored separately." },
];
const UCOLS = [
  { key: "t", label: "Fund", v: f => f.t },
  { key: "income", label: "Pays", v: f => paidY(f), fmt: f => el("span", {}, pctPlain(paidY(f))), help: "Regular payouts over the last 12 months ÷ price." },
  { key: "why", label: "Why it isn't rated", v: f => f.value_unrated || "", fmt: f => el("span", { class: "muted" }, f.value_unrated || "—") },
  { key: "age", label: "Age", v: f => f.age_years, fmt: f => el("span", {}, f.age_years == null ? "—" : f.age_years.toFixed(1) + " yrs") },
];

function syncControls() {
  const scopes = [["safe", "Safety-checked"], ["all", "All rated"], ["unrated", "Not rated"]];
  const box = $("#labScope"); box.innerHTML = "";
  scopes.forEach(([k, label]) => box.append(el("button", { class: "segbtn" + (LS.scope === k ? " active" : ""), "aria-pressed": String(LS.scope === k),
    title: k === "safe" ? "Funds that pass the size, age, fee, trading and structure checks" : k === "all" ? "Every fund with a Value Score, including ones that fail a safety check" : "Funds too new (or without a benchmark) to score",
    onclick: () => setScope(k) }, `${label} (${labBase(k).length})`)));
  $("#labFam").value = LS.fam; $("#labMkt").value = LS.market; $("#labMin").value = String(LS.minYield);
}
function setScope(k) {
  LS.scope = k; LS.shown = LAB_PAGE;
  const cols = k === "unrated" ? UCOLS : VCOLS;
  if (!cols.some(c => c.key === LS.sort.key)) LS.sort = k === "unrated" ? { key: "income", dir: -1 } : { key: "value", dir: -1 };
  renderLab();
}

function renderLab() {
  if (!LAB || !$("#labTable")) return;
  syncControls();
  const base = labBase(), cols = LS.scope === "unrated" ? UCOLS : VCOLS;
  RANKS = new Map(base.filter(f => f.value_rank).sort(byValue).map((f, i) => [f.t, i + 1]));
  const all = labSearch(base);
  const col = cols.find(c => c.key === LS.sort.key) || cols[0], dir = LS.sort.dir;
  all.sort((a, b) => {
    const va = col.v(a), vb = col.v(b);
    if (va == null || vb == null) return va == null && vb == null ? a.t.localeCompare(b.t) : (va == null ? 1 : -1);
    return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * dir || (a.value_rank || 9e9) - (b.value_rank || 9e9) || a.t.localeCompare(b.t);
  });
  const rows = all.slice(0, LS.shown);
  const filt = [LS.fam ? famName(LS.fam).toLowerCase() : null, LS.market ? "listed in " + mktName(LS.market) : null,
    LS.minYield ? `paying ≥ ${Math.round(LS.minYield * 100)}%` : null].filter(Boolean).join(", ");
  $("#labCount").textContent = (LS.scope === "unrated"
    ? `${all.length} fund${all.length === 1 ? "" : "s"} not rated yet${filt ? " (" + filt + ")" : ""} — mostly under a year old.`
    : `${all.length} ${LS.scope === "safe" ? "safety-checked" : "rated"} fund${all.length === 1 ? "" : "s"}${filt ? " (" + filt + ")" : ""}, ranked by Value Score — the same formula for every strategy, so any two can be compared. Scores within about 2 points are effectively tied.`) +
    (rows.length < all.length ? ` Showing ${rows.length}.` : "");
  $("#labMore").hidden = rows.length >= all.length;
  const wrap = $("#labTable"); wrap.innerHTML = "";
  if (!rows.length) wrap.append(emptyState());
  else {
    const head = el("tr");
    cols.forEach(c => {
      const active = col.key === c.key;
      head.append(el("th", { title: c.help || c.label, class: c.help ? "has-help" : "", "aria-sort": active ? (dir > 0 ? "ascending" : "descending") : null,
        onclick: () => {
          LS.sort = LS.sort.key === c.key ? { key: c.key, dir: -LS.sort.dir } : { key: c.key, dir: ["t", "er", "why"].includes(c.key) ? 1 : -1 };
          renderLab(); } }, c.label, c.help ? el("span", { class: "qmark" }, "ⓘ") : null,
        active ? el("span", { class: "arrow" }, dir > 0 ? " ▲" : " ▼") : null));
    });
    const body = el("tbody");
    rows.forEach(f => {
      const tr = el("tr", {});
      cols.forEach(c => tr.append(c.key === "t" ? fundCell(f)
        : el("td", { "data-label": c.label, onclick: () => openLabCard(f) }, c.fmt(f))));
      body.append(tr);
    });
    const table = el("table"); table.append(el("thead", {}, head), body); wrap.append(table);
  }
  if ($("#labChartBox") && $("#labChartBox").open) renderChart(all);
  renderTray();
}

function emptyState() {
  const box = el("div", { class: "empty" });
  if (LS.scope === "safe" && LS.market && !LS.q) {
    const closest = LAB.funds.filter(f => f.market === LS.market && f.value_score != null).sort(byValue)[0];
    box.append(`No ${mktName(LS.market).replace("the ", "")}-listed income ETF passes every safety check yet${closest ? ` — the best rated is ${closest.t} (${closest.value_display}, ${closest.value_grade})` : ""}. `,
      el("button", { class: "refresh", onclick: () => setScope("all") }, `Show all rated ${mktName(LS.market).replace("the ", "")} funds`));
    return box;
  }
  box.append("No funds match. ", el("button", { class: "refresh", onclick: () => {
    LS.q = ""; $("#labQ").value = ""; LS.fam = ""; LS.minYield = 0; renderLab(); } }, "Clear filters"),
    LS.scope === "safe" ? el("button", { class: "refresh", onclick: () => setScope("all") }, "Include funds that fail a safety check") : null);
  return box;
}

function gradeChip(f, withLabel) {
  return el("span", { class: "grade g" + f.value_grade, title: `${f.value_label} — ahead of ${f.value_pct}% of the other rated income ETFs` },
    withLabel ? `${f.value_grade} · ${f.value_label}` : f.value_grade);
}
function valueCell(f) {
  if (f.value_score == null) return el("span", { class: "muted", title: f.value_unrated || "" }, "not rated");
  return el("span", { class: "scorechip", title: `${f.value_score.toFixed(1)} / 100 · ${f.value_label}${f.value_ceiling ? ` · capped at ${f.value_ceiling} by a red flag` : ""}` },
    el("span", { class: "scorebar g" + f.value_grade, style: `--w:${f.value_score}%` }), String(f.value_display), gradeChip(f));
}
function incomeCell(f) {
  const paid = paidY(f);
  if (paid == null) return el("span", { class: "muted" }, "—");
  const all = f.earned_yield == null || f.earned_yield >= paid - 0.0005;
  return el("div", {}, el("b", {}, pctPlain(paid)),
    el("div", { class: "sub2" }, `${usd(10000 * paid)}/yr on $10k`, f.earned_yield == null ? null
      : el("span", { class: all ? "pos" : "warn" }, all ? " · all earned" : ` · only ${pctPlain(f.earned_yield)} earned`)));
}
function gapCell(f) {
  const g = f.metrics.gap;
  if (g == null) return el("span", { class: "muted" }, "—");
  return el("div", {}, el("span", { class: g >= 0 ? "pos" : g < -0.04 ? "neg" : "" }, perYr(g)),
    el("div", { class: "sub2", title: f.bench_assumed ? "* Assumed — the fund's name doesn't say which market it sells options on" : null },
      `vs ${benchName(f)}${f.bench_assumed ? "*" : ""}`));
}
function ddCell(f) {
  const d = f.metrics.max_drawdown;
  if (d == null) return el("span", { class: "muted" }, "—");
  return el("div", {}, el("span", { class: "neg" }, pct(d)), el("div", { class: "sub2" }, `${usd(10000 * d)} on $10k`));
}
function signedSpan(x, f) { return x == null ? el("span", { class: "muted" }, "—") : el("span", { class: x >= 0 ? "pos" : "neg" }, f(x)); }

function fundChips(f) {
  const chips = [];
  if (f.age_grace_until) chips.push(el("span", { class: "chip info", title: `Passes every other safety check; turns ${LAB.gates[f.style].age} years old on ${f.age_grace_until}.` }, `${LAB.gates[f.style].age} yrs on ${f.age_grace_until}`));
  if (curatedHome(f.t, null)) chips.push(el("span", { class: "chip info", title: "Has a hand-written analyst memo" }, "Analyst notes"));
  (f.value_flags || []).forEach(k => {
    const cap = ((LAB.value.flags || {})[k] || {}).kind === "cap";
    chips.push(el("span", { class: "chip " + (cap ? "bad" : "warn"), title: flagText(k) }, FLAG_CHIP[k] || k));
  });
  if (f.value_score != null && !f.safety_checked) chips.push(el("span", { class: "chip", title: "Not safety-checked — " + gateStatus(f) }, "✗ safety check"));
  if (f.eln) chips.push(el("span", { class: "chip", title: "Earns its option income through equity-linked notes from banks (counterparty risk)" }, "ELN"));
  return chips;
}
function fundCell(f) {
  const cb = el("input", { type: "checkbox", class: "cmpbox", "data-t": f.t, "aria-label": `Compare ${f.t}`, title: "Tick up to 3 funds to compare them side by side" });
  cb.checked = LS.cmp.includes(f.t);
  cb.addEventListener("click", ev => { ev.stopPropagation(); toggleCmp(f.t); });
  cb.addEventListener("keydown", ev => ev.stopPropagation());
  const rank = RANKS.get(f.t);
  return pressable(el("td", { class: "col-ticker", "aria-label": `Open ${f.t}` },
    rank ? el("span", { class: "rk", title: "Rank by Value Score in this view" }, String(rank)) : null,
    cb, el("span", { class: "tk" }, f.t), ...fundChips(f),
    el("div", { class: "nm" }, f.n, el("span", { class: "seg" }, famName(f.family)),
      f.market !== "US" ? el("span", { class: "seg mkt" }, f.market === "LSE" ? "London" : "Hong Kong") : null)),
    () => openLabCard(f));
}
function gateStatus(f) {
  if (f.passes) return "passes every check";
  const failed = Object.entries(f.gates).filter(([, v]) => v === false).map(([k]) => GATE_LABEL[k].toLowerCase());
  const unknown = (f.gates_unknown || []).map(k => GATE_LABEL[k].toLowerCase());
  return [failed.length ? "fails: " + failed.join(", ") : null, unknown.length ? "no data: " + unknown.join(", ") : null].filter(Boolean).join(" · ");
}

// ---- compare ------------------------------------------------------------------
function toggleCmp(t) {
  if (LS.cmp.includes(t)) LS.cmp = LS.cmp.filter(x => x !== t);
  else if (LS.cmp.length >= CMP_MAX) liveMsg(`You can compare up to ${CMP_MAX} funds — remove one from the compare bar first.`, "warn");
  else LS.cmp = [...LS.cmp, t];
  syncCmp();
}
// Checkboxes, "+ Compare" buttons and the tray all mirror LS.cmp.
function syncCmp() {
  document.querySelectorAll(".cmpbox[data-t]").forEach(cb => { cb.checked = LS.cmp.includes(cb.dataset.t); });
  document.querySelectorAll("button[data-cmp]").forEach(b => { b.textContent = LS.cmp.includes(b.dataset.cmp) ? "✓ Comparing" : "+ Compare"; });
  renderTray();
}
const cmpButton = t => el("button", { class: "refresh", "data-cmp": t, onclick: () => toggleCmp(t) }, LS.cmp.includes(t) ? "✓ Comparing" : "+ Compare");
function renderTray() {
  let tray = $("#cmpTray");
  if (!tray) { tray = el("div", { id: "cmpTray", class: "cmptray", role: "region", "aria-label": "Compare funds" }); document.body.append(tray); }
  tray.innerHTML = "";
  const show = LS.cmp.length > 0 && INCOME_SUB === "rankings" && VIEW === "themes";
  tray.hidden = !show;
  document.body.classList.toggle("has-tray", show);
  if (!show) return;
  tray.append(el("span", { class: "muted small" }, "Compare:"),
    ...LS.cmp.map(t => el("span", { class: "cmpchip" }, t, el("button", { class: "x", "aria-label": `Remove ${t} from compare`, onclick: () => toggleCmp(t) }, "×"))),
    el("button", { onclick: openCompare, disabled: LS.cmp.length < 2 ? "disabled" : null }, LS.cmp.length < 2 ? "Tick one more fund" : `Compare ${LS.cmp.length} ▸`),
    el("button", { class: "refresh", onclick: () => { LS.cmp = []; syncCmp(); } }, "Clear"));
}
function openDrawer(wide) {
  const d = $("#memoDrawer");
  d.classList.toggle("wide", !!wide);
  $("#overlay").hidden = false; d.hidden = false; d.scrollTop = 0;
  document.body.classList.add("noscroll");
  $("#closeMemo").focus({ preventScroll: true });
}
function openCompare() {
  const fs = LS.cmp.map(labFund).filter(Boolean);
  if (fs.length < 2) return;
  history.replaceState(null, "", "#income/compare=" + fs.map(f => f.t).join(","));
  const yrs = f => f.growth_10k && f.growth_10k.years;
  const sameWindow = fs.every(f => f.growth_10k && Math.abs(yrs(f) - yrs(fs[0])) < 0.05 && f.metrics.as_of === fs[0].metrics.as_of);
  const P = (k, f) => f.value_pillars ? f.value_pillars[k] / 4 : null;
  const rows = [
    ["Value Score", f => f.value_score, "high", f => f.value_score == null ? "not rated" : `${f.value_display} / 100 · ${f.value_grade} ${f.value_label}`],
    ["Rank (all rated)", f => f.value_rank, "low", f => f.value_rank ? `#${f.value_rank} of ${LAB.value.rated}` : "—"],
    ["Pays (12 months)", f => paidY(f), null, f => `${pctPlain(paidY(f))} · ${usd(10000 * paidY(f))} a year on $10k`],
    ["Earned income", f => f.earned_yield, "high", f => pctPlain(f.earned_yield)],
    ["Price trend", f => f.metrics.price_cagr, "high", f => perYr(f.metrics.price_cagr)],
    ["vs its market", f => f.metrics.gap, "high", f => f.metrics.gap == null ? "—" : `${perYr(f.metrics.gap)} vs ${benchName(f)}`],
    ["Worst fall", f => f.metrics.max_drawdown, "high", f => `${pct(f.metrics.max_drawdown)} (${usd(10000 * f.metrics.max_drawdown)} on $10k)`],
    ["Sharpe ratio", f => f.metrics.sharpe, "high", f => f.metrics.sharpe == null ? "—" : f.metrics.sharpe.toFixed(2)],
    ["Fee", f => f.er, "low", f => f.er == null ? "—" : f.er.toFixed(2) + "%"],
    ["Earned-income points", f => P("income", f), "high", f => P("income", f) == null ? "—" : `${P("income", f).toFixed(1)} / 25`],
    ["Paycheck-trend points", f => P("nav", f), "high", f => P("nav", f) == null ? "—" : `${P("nav", f).toFixed(1)} / 25`],
    ["Growth-kept points", f => P("kept", f), "high", f => P("kept", f) == null ? "—" : `${P("kept", f).toFixed(1)} / 25`],
    ["Smooth-ride points", f => P("ride", f), "high", f => P("ride", f) == null ? "—" : `${P("ride", f).toFixed(1)} / 25`],
    ["$10,000, payouts reinvested", f => f.growth_10k && f.growth_10k.reinvested, sameWindow ? "high" : null,
      f => f.growth_10k ? `${usd(f.growth_10k.reinvested)} after ${f.growth_10k.years} yrs` : "—"],
    ["Track record", null, null, f => f.age_years == null ? "—" : `${f.age_years.toFixed(1)} years`],
    ["Safety check", null, null, f => f.safety_checked ? (f.age_grace_until ? `✓ (old enough on ${f.age_grace_until})` : "✓ passes") : `✗ ${gateStatus(f)}`],
    ["Red flags", null, null, f => (f.value_flags || []).length ? f.value_flags.map(k => FLAG_CHIP[k] || k).join(", ") : "none"],
  ];
  const table = el("table", { class: "cmptable" });
  table.append(el("thead", {}, el("tr", {}, el("th", {}, ""), ...fs.map(f => el("th", { scope: "col" }, el("span", { class: "tk" }, f.t), el("div", { class: "nm" }, famName(f.family)))))));
  const tb = el("tbody");
  rows.forEach(([label, v, better, fmt]) => {
    const txt = fs.map(fmt);
    let win = new Set();
    if (better && v) {
      const vals = fs.map(v);
      const ok = vals.filter(x => x != null);
      if (ok.length >= 2) {
        const best = better === "high" ? Math.max(...ok) : Math.min(...ok);
        const bestTxt = txt[vals.indexOf(best)];
        if (new Set(ok.map(x => txt[vals.indexOf(x)])).size > 1) fs.forEach((f, i) => { if (txt[i] === bestTxt) win.add(i); });
      }
    }
    tb.append(el("tr", {}, el("th", { scope: "row" }, label), ...txt.map((t, i) => el("td", { class: win.has(i) ? "win" : null }, t))));
  });
  table.append(tb);
  const rated = fs.filter(f => f.value_score != null);
  const top = (fn, hi = true) => rated.filter(f => fn(f) != null).sort((a, b) => (fn(b) - fn(a)) * (hi ? 1 : -1))[0];
  const bv = top(f => f.value_score), bi = top(f => f.earned_yield), bd = top(f => f.metrics.max_drawdown);
  const notes = [];
  if (new Set(fs.map(benchName)).size > 1) notes.push(`These funds sell options on different markets (${[...new Set(fs.map(benchName))].join(", ")}), so “vs its market” compares each with its own.`);
  fs.filter(f => (f.value_flags || []).includes("young")).forEach(f => notes.push(`${f.t} has under 2 years of history — its score leans on similar funds.`));
  fs.filter(f => f.value_score == null).forEach(f => notes.push(`${f.t} isn't rated: ${f.value_unrated}.`));
  if (!sameWindow) notes.push("The funds' histories cover different periods, so the $10,000 row isn't marked.");
  const body = $("#memoBody"); body.innerHTML = "";
  const wrap = el("div", { class: "memo" });
  wrap.append(el("h2", { id: "memoTitle" }, "Side by side: " + fs.map(f => f.t).join(" vs ")),
    rated.length ? el("p", { class: "verdict" }, [bv && `Highest Value Score: ${bv.t} (${bv.value_display})`, bi && `most income actually earned: ${bi.t} (${pctPlain(bi.earned_yield)})`,
      bd && `smallest worst fall: ${bd.t} (${pct(bd.metrics.max_drawdown)})`].filter(Boolean).join(" · ") + ".") : null,
    el("div", { class: "cmpwrap" }, table),
    el("p", { class: "muted small" }, "● marks the best figure in each row. " + notes.join(" ")),
    el("p", { class: "muted small" }, `Over each fund's last ${LAB.window_years} years (or since launch) to ${LAB.as_of}. Not investment advice.`));
  body.append(wrap);
  openDrawer(true);
}

// ---- scatter: payout (x) vs Value Score (y) -----------------------------------
// Payout axis on a square-root scale: most funds pay 5-20%, single-stock funds 100%+.
const X_CAP = 2.5;
function renderChart(list) {
  const host = $("#labChart"); if (!host || !LAB || !$("#labChartBox").open) return;
  const pts = (list || labSearch(labBase())).filter(f => f.value_score != null && paidY(f) != null);
  $("#labChartTitle").textContent = `Payout vs Value Score — ${LS.fam ? famName(LS.fam) : "all strategy types"}${LS.scope === "safe" ? " (safety-checked)" : ""}`;
  host.innerHTML = "";
  const W = Math.max(300, host.clientWidth || 600), H = Math.min(360, Math.max(240, Math.round(W * 0.5)));
  const m = { l: 40, r: 14, t: 10, b: 34 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const maxY = Math.min(X_CAP, Math.max(0.1, ...pts.map(paidY)) * 1.05);
  const x = v => m.l + Math.sqrt(Math.max(0, Math.min(v, maxY)) / maxY) * iw;
  const y = v => m.t + (1 - v / 100) * ih;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
    "aria-label": `Scatter of ${pts.length} funds: payout yield against Value Score` });
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
  const xl = svgEl("text", { x: m.l + iw / 2, y: H - 4, "text-anchor": "middle", class: "axlabel" }); xl.textContent = "Payout yield, last 12 months (square-root scale)";
  const yl = svgEl("text", { x: 12, y: m.t + ih / 2, "text-anchor": "middle", class: "axlabel", transform: `rotate(-90 12 ${m.t + ih / 2})` }); yl.textContent = "Value Score";
  g.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), class: "base" }), xl, yl);
  svg.append(g);
  const tip = el("div", { class: "viztip", hidden: "hidden" });
  const show = (f, cx, cy) => {
    tip.innerHTML = "";
    tip.append(el("strong", {}, `${f.value_display} ${f.value_grade} · pays ${pctPlain(paidY(f))}`),
      el("div", {}, `${f.t} — ${f.n}`), el("div", { class: "muted" }, `${famName(f.family)} · ${f.safety_checked ? "safety-checked" : gateStatus(f)}`));
    tip.hidden = false;
    tip.style.left = Math.min(cx + 12, W - 220) + "px"; tip.style.top = Math.max(0, cy - 10) + "px";
  };
  const top5 = new Set(pts.slice().sort(byValue).slice(0, 5).map(f => f.t));
  const placed = [];
  pts.slice().sort((a, b) => (a.safety_checked === b.safety_checked ? 0 : a.safety_checked ? 1 : -1)).forEach(f => {
    const cx = x(paidY(f)), cy = y(f.value_score);
    const grp = svgEl("g", { class: "pt" + (f.safety_checked ? " pass" : " fail"), tabindex: "0", role: "button",
      "aria-label": `${f.t}: Value Score ${f.value_display}, pays ${pctPlain(paidY(f))}` });
    grp.append(svgEl("circle", { cx, cy, r: 12, class: "hit" }), svgEl("circle", { cx, cy, r: f.safety_checked ? 5 : 4, class: "dot" }));
    if (paidY(f) > maxY) grp.append(svgEl("path", { d: `M${cx + 6},${cy - 4} l5,4 l-5,4 z`, class: "pin" }));
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
  const pinned = pts.filter(f => paidY(f) > maxY).length;
  $("#labChartNote").textContent = `${pts.length} funds. Top 5 by Value Score are labelled; hover or tap a dot for details, click to open it.` +
    (pinned ? ` ${pinned} fund${pinned === 1 ? "" : "s"} paying over ${Math.round(maxY * 100)}% ${pinned === 1 ? "is" : "are"} pinned at the right edge (▸).` : "") +
    " A big payout doesn't mean good value — many of the highest payers score lowest.";
}

// ---- fund card ----------------------------------------------------------------
function openLabCard(f) {
  history.replaceState(null, "", "#income/fund=" + encodeURIComponent(f.t));
  const m = f.metrics;
  const body = $("#memoBody"); body.innerHTML = "";
  const wrap = el("div", { class: "memo" });
  const home = curatedHome(f.t, null);
  wrap.append(
    el("h2", { id: "memoTitle" }, `${f.t} — ${f.n}`),
    el("div", { class: "sub" }, `${famName(f.family)} · ${f.style === "systematic" ? "rules-based" : "actively managed"} · listed in ${mktName(f.market)} · ` +
      (f.bench ? `compared with ${benchThe(f)}${f.bench_assumed ? " (assumed — the name doesn't say)" : ""}` : "no comparable benchmark") +
      (f.eln ? " · uses equity-linked notes" : "")),
    el("div", { class: "liverow" },
      el("a", { class: "holdlink", href: quoteUrl(f.t), target: "_blank", rel: "noopener" }, "↗ Live quote"),
      home ? el("button", { class: "refresh", onclick: () => openAnalystMemo(f, home) }, "Read the analyst memo →") : null,
      f.value_score != null || f.growth_10k ? cmpButton(f.t) : null),
    heroBlock(f));
  if (f.value_score != null) wrap.append(...pillarBlock(f));
  wrap.append(...tenKBlock(f));

  // safety checks (the brief's gates)
  wrap.append(sectionTitle(f.safety_checked ? "Safety checks ✓" : "Safety checks"));
  const lim = LAB.gates[f.style];
  const gateText = {
    aum: `${f.aum_usd == null ? "size unknown" : fmtMoneyM(f.aum_usd, "USD")} (needs ≥ $${lim.aum}M)`,
    age: `${f.age_years == null ? "age unknown" : f.age_years.toFixed(1) + " years old"} (needs ≥ ${lim.age})`,
    er: `${f.er == null ? "unknown" : f.er.toFixed(2) + "% a year"} (needs ≤ ${lim.er}%)`,
    liquidity: `${f.vol == null ? "volume unknown" : shares(f.vol)} (needs ≥ ${LAB.liquidity.shares / 1000}K shares or $${LAB.liquidity.dollars / 1e6}M a day)`,
    structure: f.family === "leveraged_income" ? "leveraged — never passes" : f.note || /N/.test(f.flags || "") ? "an ETN/ETP note — never passes" : "a regular fund, not leveraged",
  };
  const gl = el("ul", { class: "gates" });
  Object.entries(f.gates).forEach(([k, ok]) => gl.append(el("li", { class: ok === true ? "ok" : ok === false ? "no" : "unk" },
    el("span", { class: "gicon", "aria-hidden": "true" }, ok === true ? "✓" : ok === false ? "✗" : "?"),
    el("b", {}, GATE_LABEL[k] + ": "), ok === true ? "pass — " : ok === false ? "fail — " : "no data — ", gateText[k])));
  wrap.append(gl, el("p", { class: "muted small" }, f.age_grace_until
    ? `Counted as safety-checked: it passes everything else and turns ${lim.age} on ${f.age_grace_until}.`
    : `${f.style === "systematic" ? "Rules-based" : "Actively managed"} funds have ${f.style === "systematic" ? "lighter" : "stricter"} limits (from your brief). Missing data never counts as a pass.`));

  // payouts
  wrap.append(sectionTitle("Payouts"));
  if (m.dist_hist && m.dist_hist.length) {
    wrap.append(distChart(m.dist_hist, f.cur),
      el("p", { class: "muted small" }, `Monthly payouts per share, last 24 months · ${m.payments_12m} payments in the last 12 months · paid ${m.streak_months} months in a row` +
        (m.specials_ttm ? ` · plus a year-end special of ${pctPlain(m.specials_ttm)} (not counted in the yield)` : "") +
        (f.extreme_yield ? " · ⚠ yield far above its strategy's norm" : "")));
  }
  if (m.coverage != null) {
    const cov = m.coverage, cap = 1 - cov;
    wrap.append(el("div", { class: "covbar", role: "img", "aria-label": `${Math.round(cov * 100)}% from total return, ${Math.round(cap * 100)}% from capital` },
      cov > 0 ? el("span", { class: "seg1", style: `flex:${cov}` }) : null, cap > 0.005 ? el("span", { class: "seg2", style: `flex:${cap}` }) : null),
      el("div", { class: "covlegend" },
        el("span", {}, el("i", { class: "key k1" }), `Earned by the fund ${Math.round(cov * 100)}%`),
        cap > 0.005 ? el("span", {}, el("i", { class: "key k2" }), `Out of your capital (price fell) ${Math.round(cap * 100)}%`) : null),
      el("p", { class: "muted small" }, `Where the payouts came from over ${m.window_years} years: payouts averaged ${pctPlain(m.dist_yield_ann)} a year while the price changed ${perYr(m.price_cagr)}. ` +
        (cap > 0.3 ? "Much of the payout effectively came out of your own capital." : cap > 0.005 ? "Some of the payout came out of capital." : "The price held up, so the fund earned its payouts.")));
  } else if (m.short_history) wrap.append(el("p", { class: "muted" }, "Too little history yet (under a year) to split where the payouts came from."));

  wrap.append(expertBlock(f));
  wrap.append(el("details", { class: "expert" }, el("summary", {}, "Tax — general information"),
    el("p", {}, f.market === "US" ? (f.tax_note || "—") : "Not a US fund — the US tax notes don't apply; see the Explorer's Tax & domicile panel for withholding by domicile."),
    el("p", { class: "muted small" }, "General information, not tax advice — tax depends on where you live and the account you hold it in. For non-US investors, US withholding on distributions usually matters more than §1256 treatment.")));
  body.append(wrap);
  openDrawer(false);
}

function openAnalystMemo(f, home) {
  if (CURRENT && home._id === CURRENT._id) { openMemo(f.t); return; }
  goTo(home, f.t);
  liveMsg(`${f.t}: analyst memo in the ${home.name} theme.`, "", { label: "← Back to the income ranking", fn: () => selectTheme("income", "rankings") });
}

function heroBlock(f) {
  if (f.value_score == null) {
    return el("div", { class: "hero" }, el("div", { class: "heroline" }, el("span", { class: "heroval muted" }, "Not rated")),
      el("p", {}, (f.value_unrated || "Not enough data") + "."),
      el("p", { class: "muted small" }, "A fund needs about a year of prices and a usable benchmark to get a Value Score."));
  }
  const safe = LAB.funds.filter(x => x.safety_checked).sort(byValue);
  const si = safe.indexOf(f);
  const flags = (f.value_flags || []).map(k => el("li", {}, `${((LAB.value.flags || {})[k] || {}).kind === "cap" ? "🔴" : "⚠️"} ${flagText(k)}`));
  return el("div", { class: "hero" },
    el("div", { class: "heroline" }, el("span", { class: "heroval" }, String(f.value_display), el("span", { class: "muted" }, " / 100")), gradeChip(f, true)),
    el("div", { class: "muted small" }, [si >= 0 ? `#${si + 1} of ${safe.length} safety-checked` : "not safety-checked", `#${f.value_rank} of ${LAB.value.rated} rated`,
      `ahead of ${f.value_pct}% of the other rated income ETFs`].join(" · ")),
    el("p", { class: "verdict" }, verdictText(f)),
    flags.length ? el("ul", { class: "flags" }, ...flags) : null);
}

// "Strong: … Weak: …" from the fund's own numbers (raw pillars, before any young-fund blending).
function verdictText(f) {
  const R = f.value_raw || f.value_pillars, m = f.metrics, bn = benchThe(f);
  const strong = {
    income: () => `earned ${pctPlain(f.earned_yield)} a year in income`,
    nav: () => `price up ${pctPlain(m.price_cagr)} a year`,
    kept: () => m.gap >= 0 ? `beat ${bn} by ${pctPlain(m.gap)} a year` : `kept nearly all of ${bn}'s return`,
    ride: () => `worst fall only ${pctPlain(-m.max_drawdown)}`,
  };
  const weak = {
    income: () => f.earned_yield < paidY(f) - 0.005 ? `pays ${pctPlain(paidY(f))} but earned only ${pctPlain(f.earned_yield)}` : `pays only ${pctPlain(paidY(f))}`,
    nav: () => `price falling ${pctPlain(-m.price_cagr)} a year, so each payout buys less`,
    kept: () => `${pctPlain(-m.gap)} a year behind ${bn}`,
    ride: () => `fell ${pctPlain(-m.max_drawdown)} at its worst`,
  };
  const ks = Object.keys(R);
  const s = ks.filter(k => R[k] >= 75).sort((a, b) => R[b] - R[a]).slice(0, 2).map(k => strong[k]());
  const w = ks.filter(k => R[k] < 50).sort((a, b) => R[a] - R[b]).slice(0, 2).map(k => weak[k]());
  return [s.length ? `Strong: ${s.join("; ")}.` : null, w.length ? `Weak: ${w.join("; ")}.` : "No weak spots."].filter(Boolean).join(" ");
}

function pillarBlock(f) {
  const P = f.value_pillars, m = f.metrics;
  const rows = [
    ["income", "Earned income", `${pctPlain(f.earned_yield)} a year${f.earned_yield < paidY(f) - 0.0005 ? ` (pays ${pctPlain(paidY(f))})` : ""}`],
    ["nav", "Paycheck trend", `price ${perYr(m.price_cagr)}`],
    ["kept", "Growth kept", `${perYr(m.gap)} vs ${benchName(f)}`],
    ["ride", "Smooth ride", `worst fall ${pct(m.max_drawdown)}${m.sharpe != null ? `, Sharpe ${m.sharpe.toFixed(2)}` : ""}`],
  ];
  const list = el("div", { class: "bars pts" });
  rows.forEach(([k, label, detail]) => list.append(el("div", { class: "barrow", title: `${label}: ${P[k]} / 100 → ${(P[k] / 4).toFixed(1)} of 25 points` },
    el("span", { class: "blabel" }, label, el("span", { class: "bdet" }, " " + detail)),
    el("span", { class: "btrack" }, el("span", { class: "bfill", style: `--w:${P[k]}%` })),
    el("span", { class: "bval" }, `${(P[k] / 4).toFixed(1)}/25`))));
  const lines = [];
  const F = (LAB.value && LAB.value.flags) || {};
  (f.value_flags || []).filter(k => (F[k] || {}).kind === "deduct").forEach(k => {
    const amt = k === "young" ? Math.max(0, F[k].amount * (2 - m.window_years)) : F[k].amount;
    lines.push(`− ${amt.toFixed(1)} · ${flagText(k)}`);
  });
  if (f.value_ceiling) lines.push(`capped at ${f.value_ceiling} · ${(f.value_flags || []).filter(k => (F[k] || {}).kind === "cap" && F[k].amount === f.value_ceiling).map(flagText).join("; ")}`);
  const out = [sectionTitle(`Where the ${f.value_display} comes from`), list];
  out.push(el("div", { class: "ptsum" }, ...lines.map(x => el("div", {}, x)),
    el("div", {}, el("b", {}, `= ${f.value_score.toFixed(1)} → ${f.value_display} / 100`), ` (${f.value_grade} · ${f.value_label.toLowerCase()})`)));
  if (m.window_years < 0.95 * LAB.window_years) out.push(el("p", { class: "muted small" },
    `Only ${m.window_years} years of prices, so each bar blends this fund's own numbers (${Math.round(m.window_years / LAB.window_years * 100)}%) ` +
    `with what seasoned ${(LAB.families[f.family] || famName(f.family)).toLowerCase()} funds typically score.`));
  out.push(el("p", { class: "muted small" }, "Each bar is worth up to 25 points. Earned income: what it paid, counted only up to its total return. Paycheck trend: whether the share price held up. " +
    `Growth kept: how much of ${benchThe(f)}'s return it kept. Smooth ride: its worst fall and its return above cash per unit of ups and downs.`));
  return out;
}

function tenKBlock(f) {
  const m = f.metrics, g = f.growth_10k, paid = paidY(f);
  if (paid == null && !g) return [];
  const tiles = el("div", { class: "tiles" });
  const tile = (lab, val, note) => tiles.append(el("div", { class: "tile" }, el("span", { class: "tlab" }, lab), el("span", { class: "tval" }, val), note ? el("span", { class: "tnote" }, note) : null));
  if (paid != null) {
    const short = f.earned_yield != null && f.earned_yield < paid - 0.0005;
    tile("Cash a year, at today's payout", usd(10000 * paid), short
      ? `but only ${usd(10000 * f.earned_yield)} of it was earned — the rest came out of your capital`
      : `about ${usd(10000 * paid / 12)} a month`);
  }
  if (g) {
    tile("Payouts reinvested", `${usd(10000)} → ${usd(g.reinvested)}`, `over ${g.years} years` + (g.bench_reinvested ? ` · ${benchThe(f)} turned $10,000 into ${usd(g.bench_reinvested)}` : ""));
    tile("Took the cash instead", `${usd(g.shares_now)} + ${g.cash_paid_exact ? "" : "≈"}${usd(g.cash_paid)}`, "shares now + payouts received");
  }
  if (m.max_drawdown != null) tile("Worst fall", usd(10000 * m.max_drawdown), "at the low point (payouts reinvested)");
  return [sectionTitle("What $10,000 did"), tiles,
    el("p", { class: "muted small" }, g ? `${m.window_start} → ${m.as_of}. What happened, not a forecast.` : "Too new for a track record.")];
}

function expertBlock(f) {
  const m = f.metrics;
  const d = el("details", { class: "expert" });
  d.append(el("summary", {}, "Details for experts"));
  // the brief's strategy-family score, with its tax view
  const famBox = el("div");
  const drawFam = () => {
    famBox.innerHTML = "";
    const s = labScore(f), w = labWeights(f) || {};
    const famFunds = LAB.funds.filter(x => x.family === f.family && labScore(x) != null).length;
    const sel = el("select", { "aria-label": "Tax view" },
      el("option", { value: "us" }, "US taxable investor"), el("option", { value: "intl" }, "Non-US / tax-sheltered"));
    sel.value = LS.tax;
    sel.addEventListener("change", () => { LS.tax = sel.value; lsSet("etf.labTax", LS.tax); drawFam(); });
    famBox.append(el("h3", {}, "Strategy-family score (from your brief)"),
      el("p", {}, s == null ? "Not scored." : el("b", {}, `${Math.round(s)} / 100`), s == null ? null : ` · #${labRank(f) || "—"} of ${famFunds} ${famName(f.family).toLowerCase()} funds · tax view: `, s == null ? null : sel),
      el("p", { class: "muted small" }, "Ranks a fund only against its own strategy, with the family weights from your brief (e.g. rules-based covered calls: NAV 40 / gap 30 / tax 30). The Value Score above uses one formula for every strategy instead, so it can compare across them."));
    if (s != null) {
      const list = el("div", { class: "bars" });
      Object.entries(w).sort((a, b) => b[1] - a[1]).forEach(([k, wt]) => {
        const v = f.components[k];
        list.append(el("div", { class: "barrow", title: `${COMP_LABEL[k]}: ${v} / 100, weight ${wt}%` },
          el("span", { class: "blabel" }, COMP_LABEL[k] || k, el("span", { class: "muted" }, ` · ${wt}%`)),
          el("span", { class: "btrack" }, el("span", { class: "bfill", style: `--w:${v}%` })),
          el("span", { class: "bval" }, String(Math.round(v)))));
      });
      famBox.append(list);
    }
  };
  drawFam();
  const facts = [
    ["Yield (12 months, regular)", pctPlain(regYield(f))],
    ["Incl. year-end specials", m.specials_ttm ? `${pctPlain(m.yield_ttm)} (specials ${pctPlain(m.specials_ttm)})` : "none"],
    ["Total return / yr", pct(m.tr_ann)], [`${f.bench || "Benchmark"} total return / yr${m.gap_window ? " (since " + m.gap_window[0] + ")" : ""}`, pct(m.bench_tr_ann)],
    [m.gap_window ? `vs benchmark (since ${m.gap_window[0]})` : "vs benchmark", pp(m.gap)],
    ["Distribution coverage", m.coverage == null ? "—" : `${Math.round(m.coverage * 100)}%`],
    ["NAV (price) trend / yr", pct(m.price_cagr)], ["Max drawdown", pct(m.max_drawdown)],
    ["Volatility / yr", pctPlain(m.vol_ann)], ["Sharpe ratio", m.sharpe == null ? "—" : m.sharpe.toFixed(2)],
    ["Upside capture", m.up_capture == null ? "—" : `${Math.round(m.up_capture * 100)}%`],
    ["Downside capture", m.down_capture == null ? "—" : `${Math.round(m.down_capture * 100)}%`],
    ["VIX sensitivity (beta)", m.vix_beta == null ? "—" : m.vix_beta.toFixed(3)],
    ["Worst VIX-spike day", m.vix_spike_day ? `${pct(m.vix_spike_day.fund_return)} (VIX ${pct(m.vix_spike_day.vix_change, 0)})` : "—"],
    ["Window", m.window_start ? `${m.window_start} → ${m.as_of} (${m.window_years} yrs)` : "—"],
    ["Expense ratio", f.er == null ? "—" : f.er.toFixed(2) + "%"], ["AUM", f.aum_usd == null ? "—" : fmtMoneyM(f.aum_usd, "USD")],
    ["Value Score pillars (0–100)", f.value_pillars ? Object.entries(f.value_pillars).map(([k, v]) => `${k} ${Math.round(v)}`).join(" · ") : "—"],
  ];
  const kv = el("div", { class: "kv" });
  facts.forEach(([k, v]) => kv.append(el("div", {}, el("span", {}, k + ": "), v)));
  const notes = [];
  if (f.exposure === "single stock") notes.push(`🔴 Single-stock strategy on ${f.under || f.bench || "one stock"} — the payout depends on one company's volatility; NAV erosion is common.`);
  if (f.inverse) notes.push("🔴 Inverse strategy (profits when the underlying falls) — not comparable to a long benchmark.");
  if (f.bench_missing) notes.push(`❓ Benchmark ${f.bench} couldn't be loaded.`);
  if (f.currency_mismatch) notes.push("❓ This line trades in a different currency from its benchmark, so the comparison would mostly measure the exchange rate.");
  if (m.gap_window) notes.push(`ℹ️ ${f.bench} data only starts ${m.gap_window[0]}, so the benchmark comparison covers ${m.gap_window[0]} → ${m.gap_window[1]} rather than the fund's full window.`);
  if (m.bench_span) notes.push(`❓ Benchmark ${f.bench} data (${m.bench_span[0]} → ${m.bench_span[1]}) doesn't line up with the fund's window.`);
  if (f.bench_assumed) notes.push("ℹ️ No index named in the fund's name — compared with the S&P 500 as an assumption.");
  if (m.bad_ticks_removed) notes.push(`ℹ️ ${m.bad_ticks_removed} bad price print${m.bad_ticks_removed === 1 ? "" : "s"} removed from the price history.`);
  if ((f.gates_unknown || []).length) notes.push("❓ Missing data for: " + f.gates_unknown.map(k => GATE_LABEL[k].toLowerCase()).join(", ") + " — it can't be safety-checked until it's known.");
  if (f.eln) notes.push("⚠️ Uses equity-linked notes: bank counterparty risk and less transparent option exposure.");
  d.append(famBox, el("h3", {}, "Returns & holding experience"), kv,
    el("p", { class: "muted small" }, "Upside/downside capture: how much of the benchmark's up and down months the fund kept. Sharpe uses T-bill returns as the risk-free rate. Price is a stand-in for NAV."),
    notes.length ? el("ul", { class: "flags" }, ...notes.map(x => el("li", {}, x))) : null);
  return d;
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
