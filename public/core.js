"use strict";

// ====================================================================
// Core tab — the main bucket: plain, low-cost funds tracking a broad
// market index, grouped by role (All-world · Developed world · US
// large-cap) and compared only within their role. Built from the Explorer
// universe (lane = world / dev / us, set by scripts/build_universe.py from
// fund names). Each share class appears once with its trading lines (a USD
// and a GBP line of the same class are one entry). A Core Score comes next;
// this view compares fee, size, payout and domicile.
// Shares helpers with app.js / explorer.js (el, $, loadUniverse, …).
// ====================================================================

const CORE_ROLE_INFO = [
  { id: "world", title: "All-world", blurb: "Developed and emerging markets in one fund — thousands of companies in about 47–50 countries. The simplest one-fund core." },
  { id: "dev", title: "Developed world", blurb: "About 1,400–2,200 large and mid-size companies in roughly two dozen developed countries. No emerging markets — add those separately if you want them." },
  { id: "us", title: "US large-cap", blurb: "The biggest US companies: the S&P 500, or 1,000–3,500 stocks for “total market” funds. One country — roughly 60% or more of the world market — so less spread out than a world fund." },
];
const CORE_PAGE = 8;
const CS = { pol: "", mkt: "", size: 500, q: "", sort: "size", more: {} };
const CORE_SORTS = { size: "Biggest first", fee: "Cheapest first", name: "A → Z" };
const CORE_HELP = {
  fund: "The fund and its trading lines: the same share class can trade in more than one currency (e.g. a USD and a GBP line) — same fund, same holdings. Tap a row for the fund's card.",
  fee: "The yearly fee (expense ratio). For core funds tracking the same index, a lower fee is the clearest edge — 0.10% vs 0.20% is $10 a year on $10,000, every year.",
  size: "How much money the whole fund manages, in US$. Bigger funds are cheaper to trade and very unlikely to close. “Not reported” = Yahoo doesn't publish it for this line — it says nothing about the fund.",
  payout: "Accumulating reinvests dividends inside the fund (no cash to you); distributing pays them out. Same fund, different share class. Reinvested income can still be taxable in some countries.",
  domicile: "Where the fund is legally based. It changes how much tax is lost on dividends and, for non-US investors, US estate-tax exposure. With your tax residence set in ⚙ Settings, a general note for your country is shown. Not tax advice.",
};

// One entry per share class: lines that differ only by trading currency are grouped.
const classKey = n => String(n || "").toLowerCase()
  .replace(/\b(usd|gbp|eur|chf|jpy)\s*(hedged|hdg|h)\b/g, "hedged-$1")        // hedged classes stay apart
  .replace(/\bh(gbp|eur|usd|chf)\b/g, "hedged-$1")                           // UBS writes 'hGBP'
  .replace(/\bunhedged\b|\b(usd|gbp|eur|chf|jpy|hkd)\b/g, " ")
  .replace(/\b(acc|accumulating|accumulation|dist|distributing|distribution|dis|inc|capitalisation|capi)\b|[(),]|\s-\s/g, " ")
  .replace(/\s+/g, " ").trim();
const CUR_ORDER = { USD: 0, GBP: 1, EUR: 2, HKD: 3 };
function coreEntries() {
  const groups = new Map();
  UNIVERSE.rows.filter(r => CORE_LANES.includes(r.lane)).forEach(r => {
    const k = [r.lane, r.mkt, r.pol || "", classKey(r.n)].join("|");
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(r);
  });
  return [...groups.values()].map(lines => {
    lines.sort((a, b) => (CUR_ORDER[a.cur] ?? 9) - (CUR_ORDER[b.cur] ?? 9) || a.t.localeCompare(b.t));
    const fees = lines.map(r => r.er).filter(v => v != null), sizes = lines.map(aumUsd).filter(v => v != null);
    const first = lines[0];
    return { lane: first.lane, mkt: first.mkt, pol: first.pol || "", dom: lines.map(r => r.dom).find(Boolean) || "",
      name: first.n, lines, er: fees.length ? Math.min(...fees) : null, size: sizes.length ? Math.max(...sizes) : null };
  });
}
function coreVisible(role) {
  const words = CS.q.toLowerCase().split(/\s+/).filter(Boolean);
  const list = (CORE_ENTRIES || []).filter(x => x.lane === role &&
    (!CS.pol || x.pol === CS.pol) && (!CS.mkt || x.mkt === CS.mkt) &&
    (!CS.size || x.size == null || x.size >= CS.size) &&
    (!words.length || words.every(w => x.name.toLowerCase().includes(w) || x.lines.some(r => r.t.toLowerCase().includes(w)))));
  const blanksLast = (a, b, f) => (a == null) - (b == null) || (a == null ? 0 : f(a, b));
  const by = {
    size: (a, b) => blanksLast(a.size, b.size, (x, y) => y - x),
    fee: (a, b) => blanksLast(a.er, b.er, (x, y) => x - y) || blanksLast(a.size, b.size, (x, y) => y - x),
    name: (a, b) => a.name.localeCompare(b.name),
  }[CS.sort];
  return list.sort((a, b) => by(a, b) || a.lines[0].t.localeCompare(b.lines[0].t));
}

let CORE_ENTRIES = null;
async function showCore() {
  setView("core");
  const box = $("#coreView");
  if (!UNIVERSE) box.innerHTML = '<p class="muted">Loading the core fund list…</p>';
  await loadUniverse();
  if (VIEW !== "core") return;                             // switched away meanwhile
  if (!UNIVERSE.rows.length) {
    box.innerHTML = "";
    box.append(el("p", { class: "livemsg warn" }, "The fund list hasn't been generated yet — it's built automatically after the next daily update."));
    return;
  }
  if (!CORE_ENTRIES) CORE_ENTRIES = coreEntries();
  if (!box.dataset.built) buildCore(box);
  renderCore();
}

function buildCore(box) {
  box.innerHTML = ""; box.dataset.built = "1";
  const seg = (id, label, opts) => el("div", { class: "segbtns", id, role: "group", "aria-label": label },
    ...opts.map(([v, l]) => el("button", { type: "button", class: "segbtn", "data-v": v }, l)));
  box.append(
    el("div", { class: "intro" },
      el("h2", {}, "Core ETFs — your main bucket"),
      el("div", { id: "corePlan" }),
      el("p", { class: "lede" }, "Core funds are plain, low-cost funds that track a broad market index, so one fund owns hundreds or thousands of companies. Most of your money goes here. ",
        el("b", {}, "Choose the role first, then the fund within it"), " — funds are compared only with others in the same role."),
      el("p", { class: "bench" }, "▸ Within a role, look for: a lower yearly fee · a bigger fund · the payout type you want (accumulating reinvests for you) · a domicile that suits where you pay tax · a trading line in a currency and market you can use."),
      el("p", { class: "refnote small" }, el("b", {}, "Coming next: "), "a Core Score out of 100 for every fund here — cost & tracking, diversification, size & trading, falls & risk, and tax & domicile. Until then, compare the columns below.")),
    el("section", { class: "controls" },
      el("span", { class: "withhelp" }, seg("corePol", "Payout", [["", "Any payout"], ["A", "Accumulating"], ["D", "Distributing"]]), helpBtn("Payout", CORE_HELP.payout)),
      el("select", { id: "coreMkt", "aria-label": "Where it is listed" }, el("option", { value: "" }, "Listed anywhere"),
        el("option", { value: "US" }, "Listed in the US"), el("option", { value: "LSE" }, "Listed in London"), el("option", { value: "HK" }, "Listed in Hong Kong")),
      el("select", { id: "coreSize", "aria-label": "Minimum fund size" },
        el("option", { value: "500" }, "Size ≥ US$500M (or not reported)"), el("option", { value: "5000" }, "Size ≥ US$5B (or not reported)"), el("option", { value: "0" }, "Any size")),
      el("select", { id: "coreSort", "aria-label": "Sort" }, ...Object.entries(CORE_SORTS).map(([v, l]) => el("option", { value: v }, l))),
      el("input", { type: "search", id: "coreQ", placeholder: "Search ticker or name (e.g. Vanguard, CSPX)…", "aria-label": "Search core funds" })),
    columnGuide([["Fund · trading lines", CORE_HELP.fund], ["Yearly fee", CORE_HELP.fee], ["Size", CORE_HELP.size], ["Payout", CORE_HELP.payout], ["Domicile", CORE_HELP.domicile],
      ["Why these funds?", "Funds whose name says they track a plain broad index (all-world, developed world, S&P 500 / total US market …) with a yearly fee of 0.50% or less. Screened (ESG, Islamic), factor, sector, regional, options and leveraged funds are left out on purpose — they're tilts, not the core. Find them in the Explorer."]],
      "What do these columns mean? (Fee, Size, Payout, Domicile …)"),
    el("div", { id: "coreLists" }),
    el("p", { class: "muted small" }, "Source: the Explorer's daily list of every ETF listed in the US, London and Hong Kong (Yahoo Finance numbers). Roles are read from fund names. Sizes and fees for some London lines aren't published by Yahoo. Not investment advice."));
  const setSeg = () => document.querySelectorAll("#corePol button").forEach(b => b.classList.toggle("active", b.dataset.v === CS.pol));
  document.querySelectorAll("#corePol button").forEach(b => b.addEventListener("click", () => { CS.pol = b.dataset.v; CS.more = {}; setSeg(); renderCoreLists(); }));
  setSeg();
  $("#coreMkt").addEventListener("change", e => { CS.mkt = e.target.value; CS.more = {}; renderCoreLists(); });
  $("#coreSize").addEventListener("change", e => { CS.size = +e.target.value; CS.more = {}; renderCoreLists(); });
  $("#coreSort").addEventListener("change", e => { CS.sort = e.target.value; renderCoreLists(); });
  let t = null;
  $("#coreQ").addEventListener("input", e => { clearTimeout(t); t = setTimeout(() => { CS.q = e.target.value.trim(); CS.more = {}; renderCoreLists(); }, 150); });
}

function renderCore() {
  if (!$("#coreLists")) return;
  const plan = $("#corePlan"); plan.innerHTML = ""; plan.append(planStrip());
  renderCoreLists();
}

function renderCoreLists() {
  const box = $("#coreLists"); box.innerHTML = "";
  const r = taxHome();
  CORE_ROLE_INFO.forEach(role => {
    const all = coreVisible(role.id), n = CS.more[role.id] ? all.length : Math.min(all.length, CORE_PAGE);
    const sec = el("section", { class: "corerole", id: "core-" + role.id });
    sec.append(el("h3", {}, `${role.title} `, el("span", { class: "muted" }, `· ${all.length} share class${all.length === 1 ? "" : "es"}`)),
      el("p", { class: "small" }, role.blurb));
    if (!all.length) {
      sec.append(el("p", { class: "empty" }, "No funds match these filters."));
      box.append(sec);
      return;
    }
    const head = el("tr", {}, ...[["Fund", CORE_HELP.fund], ["Yearly fee", CORE_HELP.fee], ["Size", CORE_HELP.size], ["Payout", CORE_HELP.payout],
      ["Domicile" + (r && r.id !== "other" ? ` (for ${r.label})` : ""), CORE_HELP.domicile]].map(([l, h]) => withHelp(el("th", { class: "has-help" }, l), l, h)));
    const body = el("tbody");
    all.slice(0, n).forEach(x => {
      const open = () => coreOpen(x.lines[0]);
      body.append(el("tr", {},
        pressable(el("td", { class: "col-ticker", "aria-label": `Open ${x.lines[0].t}` },
          ...x.lines.map(l => el("span", { class: "tk line", title: `${l.t} trades in ${l.cur}` }, l.t, el("small", {}, " " + l.cur))),
          el("div", { class: "nm" }, x.name, x.mkt !== "US" ? el("span", { class: "seg mkt" }, (UNIVERSE.meta[x.mkt] || {}).label || x.mkt) : null)), open),
        el("td", { "data-label": "Yearly fee", onclick: open }, x.er == null ? nodata("Expense ratio") : x.er.toFixed(2) + "%"),
        el("td", { "data-label": "Size", onclick: open }, x.size == null ? el("span", { class: "muted", title: CORE_HELP.size }, "not reported") : fmtMoneyM(x.size, "USD")),
        el("td", { "data-label": "Payout", onclick: open }, x.pol ? el("span", { class: "tag-pol pol" + x.pol, title: POL_TEXT[x.pol] }, x.pol === "A" ? "Accumulating" : "Distributing")
          : el("span", { class: "muted", title: POL_TEXT[""] }, "not stated")),
        el("td", { "data-label": "Domicile", onclick: open }, DOM_SHORT[x.dom] || x.dom || "—", " ", verdictChip(x.dom))));
    });
    const table = el("table"); table.append(el("thead", {}, head), body);
    sec.append(el("div", { class: "table-wrap" }, table));
    if (all.length > n || CS.more[role.id]) sec.append(el("div", { class: "exmore" }, el("button", { type: "button", class: "refresh",
      onclick: () => { CS.more[role.id] = !CS.more[role.id]; renderCoreLists(); } }, CS.more[role.id] ? "Show fewer" : `Show all ${all.length}`)));
    box.append(sec);
  });
}

// A core fund's card: the Explorer card (no jump to a theme where it is only a benchmark).
function coreOpen(r) {
  EXPLORE.etfs = EXPLORE.etfs.filter(e => e.ticker !== r.t);
  EXPLORE.etfs.push(universeCard(r));
  CURRENT = EXPLORE;
  openMemo(r.t);
}
