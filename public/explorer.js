"use strict";

// ====================================================================
// All ETFs (the Explorer) — every listed ETF, searchable and sortable, with
// mechanical fee / size traffic lights. Data: data/universe-<market>.json,
// rebuilt every weekday by scripts/build_universe.py; loaded only when the
// Core tab or All ETFs opens.
// Shares helpers with app.js (el, $, daily, openMemo, curatedHome, …).
// ====================================================================

const UNIVERSE_FILES = [
  { market: "US", label: "US", file: "data/universe-us.json" },
  { market: "HK", label: "Hong Kong", file: "data/universe-hk.json" },
  { market: "LSE", label: "London", file: "data/universe-lse.json" },
];
// Domicile buckets for the filter. Hong Kong codes come from the ISIN; London UCITS funds are
// placed in Ireland or Luxembourg from the fund family ('IE/LU' = the family runs funds in both).
const DOMICILES = [["US", "US"], ["IE", "Ireland"], ["LU", "Luxembourg"], ["IE/LU", "Ireland or Luxembourg (not confirmed)"], ["NL", "Netherlands"], ["HK", "Hong Kong"], ["other", "Other / not known"]];
const domBucket = d => ["US", "HK", "IE", "LU", "IE/LU", "NL"].includes(d) ? d : "other";
const DOM_TEXT = { US: "US-domiciled", HK: "HK-domiciled", IE: "Irish UCITS", LU: "Luxembourg UCITS", NL: "Dutch UCITS (the fund withholds Dutch dividend tax on payouts)",
  "IE/LU": "UCITS — Ireland or Luxembourg (check the ISIN)", GB: "UK-domiciled", SG: "Singapore-domiciled" };
const DOM_SHORT = { IE: "Ireland", LU: "Luxembourg", NL: "Netherlands", "IE/LU": "IE or LU", US: "US", HK: "HK", SG: "Singapore" };
// Payout policy and site lane (scripts/build_universe.py derives both from the fund name).
const POL_SHORT = { A: "Acc", D: "Dist" };
const POL_TEXT = { A: "Accumulating — income is reinvested inside the fund; no cash is paid out",
  D: "Distributing — pays its income out to you as cash", "": "Not stated in the fund's name — check its fact sheet" };
// A US fund with no payout label is a trust, pool or note that pays nothing (scripts/build_universe.py).
const polText = r => !r.pol && r.dom === "US" ? "Pays nothing out — a trust, pool or note holding gold, crypto, futures or a bank's promise directly; check its fact sheet" : POL_TEXT[r.pol || ""];
const NOFEE_HELP = "“Not published” = our data source (Yahoo Finance) doesn't give the yearly fee for this line; the fund's fact sheet does.";
const NOSIZE_HELP = "“Not reported” = Yahoo Finance doesn't publish the fund size for this line — it says nothing about the fund.";
const LANE_TEXT = { world: "Core · All-world", dev: "Core · Developed world", us: "Core · US large-cap", income: "Income-focused" };
const CORE_LANES = ["world", "dev", "us"];
const nicheThemesOf = r => themesOf(r).filter(id => id !== "income");
const aumUsd = r => r.aumu != null ? r.aumu : (r.cur === "USD" || !r.cur ? r.aum : null);
const aumCur = r => r.acur || r.cur || "USD";        // AUM is in the fund's base currency
const EX_PAGE = 100;
let UNIVERSE = null, UNIVERSE_P = null;   // { rows: [...], meta: { US: {...} } } and the load in progress
// synced = the settings the filters were last set from (a visitor's own ticks survive unrelated changes)
const EX = { sort: { key: "aum", dir: -1 }, shown: EX_PAGE, synced: null };
// Pseudo-theme that holds the cards opened from All ETFs, so the shared
// memo drawer (which reads CURRENT) works unchanged.
const EXPLORE = { _id: "explore", name: "All ETFs", as_of: "", etfs: [], roster: [] };

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

// One download, shared by the Core tab and All ETFs (also while it is still on its way).
function loadUniverse() {
  if (!UNIVERSE_P) UNIVERSE_P = fetchUniverse();
  return UNIVERSE_P;
}
async function fetchUniverse() {
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
    // a theme's benchmarks (QQQ, XLK, SOXX …) sit in its table and roster only as yardsticks: not members
    const bench = new Set((t.etfs || []).filter(e => !e._adhoc && !e.is_theme_fund).map(e => e.ticker));
    const own = new Set([...(t.etfs || []).filter(e => !e._adhoc && e.is_theme_fund).map(e => e.ticker),
      ...(t.roster || []).filter(r => !bench.has(r.ticker) && !/^benchmark/i.test(r.tag || "")).map(r => r.ticker)]);
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
  if (VIEW !== "explore") return;                          // switched away meanwhile
  if (!box.dataset.built) buildExplorer(box);
  if (!$("#exTable")) return;                              // no data yet
  exSync();
  if (themeId !== undefined) {                          // the income theme is a role here, not a theme
    $("#exTheme").value = themeId === "income" ? "" : themeId || "";
    $("#exLane").value = themeId === "income" ? "income" : "";
    $("#exQ").value = "";
  }
  EX.shown = EX_PAGE;
  CURRENT = EXPLORE;
  renderExplorer();
}

function buildExplorer(box) {
  box.innerHTML = "";
  box.dataset.built = "1";
  const metas = UNIVERSE_FILES.map(f => UNIVERSE.meta[f.market]).filter(Boolean);   // fixed order
  if (!metas.length) {
    box.append(el("p", { class: "livemsg warn" }, "The full ETF list hasn't been generated yet — it's built automatically after the next daily update."));
    return;
  }
  const total = UNIVERSE.rows.length, asof = metas.map(m => m.as_of).sort().pop();
  const more = el("details", { class: "morefilters", id: "exMoreBox" });
  if (matchMedia("(min-width: 701px)").matches) more.open = true;          // phones start folded: the list comes first
  more.append(el("summary", { id: "exMoreSum" }, "More filters"),
    el("div", { class: "controls" },
      el("select", { id: "exTheme", "aria-label": "Theme" }, el("option", { value: "" }, "Any theme"),
        ...nicheIds().map(id => el("option", { value: id }, window._THEMES[id].name))),
      el("span", { class: "withhelp" }, el("select", { id: "exPol", "aria-label": "Payout" }, el("option", { value: "" }, "Any payout"),
        el("option", { value: "A" }, "Accumulating (reinvests)"), el("option", { value: "D" }, "Distributing (pays out)"),
        el("option", { value: "?" }, "Not stated / pays nothing")), helpBtn("Payout", POL_HELP)),
      el("span", { class: "withhelp" }, el("select", { id: "exDom", "aria-label": "Domicile" }, el("option", { value: "" }, "Any domicile"),
        ...DOMICILES.map(([v, l]) => el("option", { value: v }, l))), helpBtn("Domicile", DOM_HELP)),
      el("select", { id: "exAum", "aria-label": "Minimum fund size" }, el("option", { value: "" }, "Any fund size"),
        ...[[50, "Size ≥ US$50M"], [100, "Size ≥ US$100M"], [1000, "Size ≥ US$1B"], [10000, "Size ≥ US$10B"]].map(([v, l]) => el("option", { value: v }, l))),
      el("select", { id: "exEr", "aria-label": "Maximum yearly fee" }, el("option", { value: "" }, "Any yearly fee"),
        ...[[0.1, "Fee ≤ 0.10%"], [0.2, "Fee ≤ 0.20%"], [0.5, "Fee ≤ 0.50%"], [0.75, "Fee ≤ 0.75%"]].map(([v, l]) => el("option", { value: v }, l))),
      el("span", { class: "withhelp" }, el("label", { class: "toggle" },
        el("input", { type: "checkbox", id: "exPlain", checked: "checked" }), "Plain ETFs only"), helpBtn("Plain ETFs only", PLAIN_HELP)),
      el("span", { class: "withhelp" }, el("label", { class: "toggle" },
        el("input", { type: "checkbox", id: "exNoInc", ...(needsIncome() ? {} : { checked: "checked" }) }), "Hide income-focused"), helpBtn("Hide income-focused", NOINC_HELP)),
      el("span", { class: "withhelp" }, el("label", { class: "toggle pass-toggle" },
        el("input", { type: "checkbox", id: "exPre" }), "✓ Pre-screen"), helpBtn("Pre-screen", PRESCREEN_HELP)),
      el("button", { type: "button", class: "refresh", id: "exReset" }, "Reset filters")));
  box.append(
    el("div", { class: "intro" },
      el("h2", {}, "All ETFs"),
      el("p", { class: "lede" }, `Search all ${total.toLocaleString()} ETFs listed in the US, London and Hong Kong. Tap any fund for its card.`),
      el("div", { class: "asof", title: metas.map(m => `${m.label}: ${m.count.toLocaleString()} ETFs (data ${m.as_of})`).join(" · ") },
        `${metas.map(m => `${m.label} ${m.count.toLocaleString()}`).join(" · ")} · data ${asof} · updates every weekday`)),
    el("section", { class: "controls" },
      el("input", { type: "search", id: "exQ", placeholder: "Search ticker or name (e.g. uranium, S&P 500, QQQ)…", "aria-label": "Search ETFs" }),
      el("select", { id: "exMarket", "aria-label": "Market" }, el("option", { value: "" }, "All markets"),
        ...UNIVERSE_FILES.filter(f => UNIVERSE.meta[f.market]).map(f => el("option", { value: f.market }, f.label))),
      el("span", { class: "withhelp" }, el("select", { id: "exLane", "aria-label": "Role" }, el("option", { value: "" }, "Any role"),
        el("option", { value: "core" }, "Core — broad index (any)"), el("option", { value: "world" }, "Core — All-world"),
        el("option", { value: "dev" }, "Core — Developed world"), el("option", { value: "us" }, "Core — US large-cap"),
        el("option", { value: "theme" }, "Themes (any theme)"), el("option", { value: "income" }, "Income-focused"),
        el("option", { value: "other" }, "Other (sector, bond, factor …)")), helpBtn("Role", LANE_HELP)),
      el("select", { id: "exSort", "aria-label": "Sort" }, el("option", { value: "", hidden: "hidden" }, "Sorted by a column"),
        ...EX_SORTS.map(([v, l]) => el("option", { value: v }, l)))),
    el("div", { id: "exTax" }, taxExplainer()),
    more,
    el("p", { id: "exPreNote", class: "prenote", hidden: "hidden" }),
    el("div", { id: "exCount", class: "muted small" }),
    columnGuide([...exCols().map(c => [c.label, EX_HELP[c.key]]), ["Role (filter)", LANE_HELP], ["Payout (filter) · Acc / Dist tags", POL_HELP],
      ["Domicile (filter)", DOM_HELP], ["Hide income-focused (filter)", NOINC_HELP], ["✓ Pre-screen (filter)", PRESCREEN_HELP], ["Plain ETFs only (filter)", PLAIN_HELP]],
      "What do these columns and filters mean? (Yearly fee, Fund size, Payout …)"),
    el("section", { id: "exTable", class: "table-wrap" }),
    el("div", { class: "exmore" }, el("button", { id: "exMore", class: "refresh" }, "Show more")),
    el("p", { class: "muted small" }, "1-yr price = 52-week change in the share price only (excludes distributions — income and bond funds look worse than their real return). YTD = total return as reported by Yahoo Finance. " +
      "Fund size is shown in the fund's reporting currency (≈ US$ on hover) and is approximate for London lines: several share classes of one fund report the same fund-wide total. Sources: " +
      metas.map(m => m.source).join(" ")));
  EX.synced = { income: SETTINGS.income, tax: SETTINGS.tax };
  let t = null;
  $("#exQ").addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { EX.shown = EX_PAGE; renderExplorer(); }, 150); });
  ["exMarket", "exLane", "exTheme", "exPol", "exDom", "exAum", "exEr", "exPlain", "exNoInc", "exPre"].forEach(id =>
    $("#" + id).addEventListener("change", () => { EX.shown = EX_PAGE; renderExplorer(); }));
  $("#exMore").addEventListener("click", () => { EX.shown += EX_PAGE; renderExplorer(); });
  $("#exSort").addEventListener("change", e => { const [key, dir] = e.target.value.split(":"); EX.sort = { key, dir: +dir }; EX.shown = EX_PAGE; renderExplorer(); });
  $("#exReset").addEventListener("click", () => {
    ["exTheme", "exPol", "exDom", "exAum", "exEr"].forEach(id => { $("#" + id).value = ""; });
    $("#exPlain").checked = true; $("#exNoInc").checked = !needsIncome(); $("#exPre").checked = false;
    EX.shown = EX_PAGE; renderExplorer();
  });
}
// Filters in "More filters" that differ from their defaults, in words (for its label and the count line).
function exActiveExtras() {
  const pick = id => { const s = $("#" + id); return s.value ? s.options[s.selectedIndex].text : null; };
  return [pick("exTheme"), pick("exPol"), pick("exDom"), pick("exAum"), pick("exEr"),
    !$("#exPlain").checked ? "incl. leveraged/ETN/futures" : null,
    $("#exNoInc").checked !== !needsIncome() ? ($("#exNoInc").checked ? "income hidden" : "income shown") : null,
    $("#exPre").checked ? "pre-screen" : null].filter(Boolean);
}
// Re-apply the settings the filters depend on, but only the parts that changed since
// they were last applied — a visitor's own ticks survive an unrelated settings change.
function exSync() {
  const s = { income: SETTINGS.income, tax: SETTINGS.tax };
  if (!EX.synced) EX.synced = s;
  if (s.income !== EX.synced.income) { $("#exNoInc").checked = !needsIncome(); EX.shown = EX_PAGE; }
  if (s.tax !== EX.synced.tax) { const box = $("#exTax"); box.innerHTML = ""; box.append(taxExplainer()); }
  EX.synced = s;
}

const passesPrescreen = r => costRating(r.er) === "green" && (aumUsd(r) || 0) >= 50 && !r.f;
function laneMatch(r, lane) {
  if (lane === "core") return CORE_LANES.includes(r.lane);
  if (lane === "theme") return nicheThemesOf(r).length > 0;
  if (lane === "other") return !r.lane && !nicheThemesOf(r).length;
  return r.lane === lane;
}
function exFiltered(pre = $("#exPre").checked, showHidden = false) {
  const words = $("#exQ").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const mkt = $("#exMarket").value, th = $("#exTheme").value, lane = $("#exLane").value, pol = $("#exPol").value;
  const aumMin = +$("#exAum").value || 0, erMax = $("#exEr").value === "" ? null : +$("#exEr").value;
  const plain = $("#exPlain").checked && !showHidden, dom = $("#exDom").value;
  const noInc = $("#exNoInc").checked && lane !== "income" && !showHidden;   // asking for income funds overrides the hide
  return UNIVERSE.rows.filter(r =>
    (!mkt || r.mkt === mkt) &&
    (!plain || !r.f) &&
    (!pre || passesPrescreen(r)) &&
    (!noInc || r.lane !== "income") &&
    (!lane || laneMatch(r, lane)) &&
    (!pol || (pol === "?" ? !r.pol : r.pol === pol)) &&
    (!aumMin || (aumUsd(r) || 0) >= aumMin) &&
    (!dom || domBucket(r.dom) === dom) &&
    (erMax == null || (r.er != null && r.er <= erMax)) &&
    (!words.length || words.every(w => r.t.toLowerCase().includes(w) || r.n.toLowerCase().includes(w))) &&
    (!th || themesOf(r).includes(th)));
}
// Settings changed while All ETFs is open: new income default, new tax notes.
function explorerSettingsChanged() {
  if (!$("#exTable")) return;
  exSync();
  renderExplorer();
}
function exVal(r, key) {
  if (key === "aum") return aumUsd(r);
  if (key === "ytd") return ytdOf(r);
  return r[key];
}
// YTD from the theme data's own total-return series when the fund has one (the same figure its
// card and theme table show), else the list's Yahoo figure.
function ytdOf(r) {
  const d = daily(r.t), v = d && d.performance && !isPlaceholder(d.performance.ytd) ? num(d.performance.ytd) : null;
  return v != null ? v : r.ytd;
}
const EX_SORTS = [["aum:-1", "Biggest first"], ["er:1", "Cheapest first"], ["ytd:-1", "Best this year"], ["c1y:-1", "Best 1-yr price change"],
  ["vol:-1", "Most traded"], ["t:1", "A → Z"]];
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
  er: "The yearly fee (expense ratio): the share of your money the fund takes every year to run itself, whether it goes up or down. 0.50% = $50 a year on $10,000. Lower is better. " +
    "The dot is a quick traffic light: 🟢 0.50% or less, 🟡 up to 0.75%, 🔴 more than 0.75%.",
  aum: "Fund size (assets under management): how much money is invested in the fund in total. Bigger funds are easier to buy and sell and less likely to be closed down. Shown in the fund's own currency. " +
    "The dot: 🟢 at least US$500M, 🟡 US$50M–500M, 🔴 under US$50M — very small funds are more often closed down, which forces you to sell.",
  p: "The price of one share at the last close. It says nothing about value — a $20 fund isn't cheaper than a $500 one; you just get fewer shares of the second.",
  c1y: "How much the share price changed over the last 12 months. Payouts are NOT included, so funds that pay big dividends look worse here than they really did.",
  ytd: "Year-to-date: the return since 1 January, payouts included (as reported by Yahoo Finance).",
  yld: "Payouts over the last 12 months as a % of the price. A high yield isn't automatically good — part of it can be your own money handed back.",
  vol: "Average number of shares traded per day. More trading usually means a smaller gap between the buying and selling price, so it's cheaper to trade.",
};
const PRESCREEN_HELP = "A quick first filter that keeps only funds that are cheap, established and plain: yearly fee 0.50% or less (🟢), at least US$50M invested, and no leverage, ETN or futures. " +
  "It removes the obvious no's — it does NOT judge what the fund holds, its theme or its returns, so it isn't a buy list. Open a fund to look closer.";
const PLAIN_HELP = "Hides products built for short-term trading or with extra risks: leveraged / inverse funds (2×, 3×, −1× — they reset daily and drift away from the market over time), " +
  "exchange-traded notes (ETNs — a bank's promise to pay, not a fund that owns anything) and futures-based funds (oil, VIX … — returns can lag the real price badly). On by default.";
const DOM_HELP = "Domicile = the country where the fund is legally based (not where it's listed). It changes the tax taken off dividends and, for non-US investors, US estate-tax exposure — see “Tax & domicile” below the list. " +
  "For London funds, Ireland or Luxembourg is worked out from the fund family (iShares, Vanguard, SPDR, Invesco, HSBC … run Irish funds); “not confirmed” means the family runs funds in both — the ISIN on the fact sheet settles it (IE… = Ireland, LU… = Luxembourg). General information, not tax advice.";
const LANE_HELP = "Which job a fund does. Core = a plain, low-cost fund tracking a broad market index (the whole world, the developed world, or the big US companies) — the main bucket. " +
  "Themes = funds matching one of the site's themes (space, quantum …) — small satellite bets. Income-focused = funds built to pay out cash by selling options (the Income tab). " +
  "Other = everything else (sectors, bonds, factor or regional funds …). Roles are worked out from fund names, so check the card.";
const POL_HELP = "What the fund does with the dividends it receives. Accumulating (Acc) reinvests them inside the fund, so the price grows instead of paying you cash. " +
  "Distributing (Dist) pays them out. Most US-listed ETFs distribute; US trusts and pools that hold gold, crypto or futures directly (GLD, IBIT, USO …) pay nothing and show no tag. " +
  "London funds often come in both versions — same fund, different share class. Reinvested income can still be taxable in some countries. “Not stated” = the name doesn't say; check the fact sheet.";
const NOINC_HELP = "Hides option-income funds (covered-call and similar — the ones ranked in the Income tab). Ticked by default when your settings say you don't need income; untick to include them, or pick Role → Income-focused.";

// A figure with its traffic-light dot in front (fee and size).
const dotted = (rating, what, text) => rating
  ? el("span", { class: "dotted", title: `${what}: ${RATING_LABEL[rating]}` }, el("span", { class: "dot " + rating }), text) : text;
const EX_COLS = [
  { key: "t", label: "Ticker" },
  { key: "er", label: "Yearly fee", fmt: r => r.er == null ? el("span", { class: "muted", title: NOFEE_HELP }, "not published") : dotted(costRating(r.er), "Fee", r.er.toFixed(2) + "%") },
  { key: "aum", label: "Fund size", fmt: r => r.aum == null ? el("span", { class: "muted", title: NOSIZE_HELP }, "not reported")
      : dotted(sizeRating(aumUsd(r)), "Size", aumCur(r) !== "USD" && aumUsd(r) != null
        ? el("span", { title: `≈ ${fmtMoneyM(aumUsd(r), "USD")} at today's FX rate` }, fmtMoneyM(r.aum, aumCur(r)))
        : fmtMoneyM(r.aum, aumCur(r))) },
  { key: "p", label: "Price", fmt: r => money(r.p, r.cur) || nodata("Price") },
  { key: "c1y", label: "1-yr price", fmt: r => pctSpan(r.c1y) },
  { key: "ytd", label: "YTD", fmt: r => pctSpan(ytdOf(r)) },
  { key: "yld", label: "Yield", when: () => UNIVERSE.rows.filter(r => r.yld != null).length > UNIVERSE.rows.length * 0.3,
    fmt: r => r.yld == null ? el("span", { class: "muted" }, "—") : r.yld.toFixed(2) + "%" },
  { key: "vol", label: "Daily volume", fmt: r => shares(r.vol) || nodata("Daily volume") },
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
  const order = sk === "t" ? (sd > 0 ? "A→Z" : "Z→A") : (sd > 0 ? "lowest first" : "highest first");
  const extras = exActiveExtras(), hidden = [$("#exPlain").checked ? "leveraged, ETN & futures funds" : null,
    $("#exNoInc").checked && $("#exLane").value !== "income" ? "income-focused funds" : null].filter(Boolean);
  $("#exMoreSum").textContent = extras.length ? `More filters · ${extras.length} on` : "More filters";
  $("#exCount").textContent = `${all.length.toLocaleString()} match${all.length === 1 ? "" : "es"}` +
    (extras.length ? ` (${extras.join(", ")})` : "") +
    (hidden.length ? ` · hiding ${hidden.join(" and ")} (More filters)` : "") +
    (rows.length < all.length ? ` · first ${rows.length.toLocaleString()} shown, by ${sortCol.label.toLowerCase()} (${order})` : "") +
    " · tap a row for its card";
  const sv = `${sk}:${sd}`;                                         // phones have no headers: the box is how they sort
  $("#exSort").value = EX_SORTS.some(([v]) => v === sv) ? sv : "";
  const pre = $("#exPre").checked, note = $("#exPreNote");
  note.hidden = !pre;
  if (pre) {
    const before = exFiltered(false).length;
    const noFee = exFiltered(false).filter(r => r.er == null && !r.f && (aumUsd(r) || 0) >= 50).length;
    note.textContent = `✓ Pre-screen on: ${all.length.toLocaleString()} of ${before.toLocaleString()} funds pass — cheap (yearly fee 0.50% or less), established (at least US$50M invested) and plain (no leverage, ETN or futures). ` +
      (noFee ? `${noFee.toLocaleString()} otherwise-passing fund${noFee === 1 ? " has" : "s have"} no fee in our data and ${noFee === 1 ? "is" : "are"} left out (several big Vanguard London lines among them). ` : "") +
      "It's a first filter, not a buy list: it doesn't look at what a fund holds or how it has performed.";
  }
  $("#exMore").hidden = rows.length >= all.length;
  const wrap = $("#exTable"); wrap.innerHTML = "";
  if (!rows.length) {
    const more = hidden.length ? exFiltered(undefined, true).length : 0;
    wrap.append(more
      ? el("div", { class: "empty" }, `${more.toLocaleString()} fund${more === 1 ? " matches" : "s match"} among the ${hidden.join(" and ")} hidden by default. `,
          el("button", { type: "button", class: "refresh", onclick: () => { $("#exNoInc").checked = false; $("#exPlain").checked = false; EX.shown = EX_PAGE; renderExplorer(); } }, "Show them"))
      : el("div", { class: "empty" }, "No ETFs match. Try a broader search or fewer filters."));
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
        const chips = (r.lane === "income" ? [] : nicheThemesOf(r)).map(id => (window._THEMES[id] || {}).name).filter(Boolean).slice(0, 2);
        tr.append(pressable(el("td", { class: "col-ticker", "aria-label": `Open ${r.t}` },
          el("span", { class: "tk" }, r.t),
          r.pol ? el("span", { class: "tag-pol pol" + r.pol, title: POL_TEXT[r.pol] }, POL_SHORT[r.pol]) : null,
          verdictChip(r.dom),
          homes.has(r.t) ? el("span", { class: "tag-pass", title: "Has a full analysis card in a theme" }, "✓ analysed") : null,
          r.f ? el("span", { class: "tag-adhoc", title: [...r.f].map(x => FLAG_TEXT[x]).join(", ") }, [...r.f].map(x => FLAG_TEXT[x]).join(" · ")) : null,
          el("div", { class: "nm" }, r.n, LANE_TEXT[r.lane] ? el("span", { class: "seg lane-" + r.lane }, LANE_TEXT[r.lane]) : null,
            ...chips.map(n => el("span", { class: "seg" }, n)),
            r.mkt !== "US" ? el("span", { class: "seg mkt", title: DOM_TEXT[r.dom] || "" }, `${(UNIVERSE.meta[r.mkt] || {}).label || r.mkt}${r.dom ? " · " + (DOM_SHORT[r.dom] || r.dom) : ""}`) : null)),
          () => exOpen(r)));
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
    .flatMap(t => (t.etfs || []).filter(e => isHomeCard(t, e)).map(e => e.ticker)));
  return CURATED_INDEX;
}

// Open a fund from All ETFs: its analyst card if one exists (curatedHome skips cards where
// it is only a benchmark), else a card from the daily data or the universe row.
function exOpen(r) {
  const home = curatedHome(r.t, null);
  if (home) {
    goTo(home, r.t);
    liveMsg(`${r.t} has a full analysis card in ${home._id === "income" ? "the Income tab" : "the " + home.name + " theme"} — opened it there.`, "", { label: "← Back to All ETFs", fn: () => showExplorer() });
    return;
  }
  if (!EXPLORE.etfs.some(e => e.ticker === r.t)) EXPLORE.etfs.push(universeCard(r));
  openMemo(r.t);
}
// A universe row's card. When the fund is also in the daily theme data, that adds holdings,
// returns and a top-10 concentration rating; the wording and the other checks stay the list's.
function universeCard(r) {
  const u = makeUniverseEtf(r), d = daily(r.t);
  if (!d) return u;
  const k = makeDailyEtf(r.t, d, { name: r.n });
  return { ...k, _explorer: true, overall: u.overall, memo: u.memo, structure: u.structure, derivatives: u.derivatives,
    domicile: u.domicile, _dom: u._dom, payout: u.payout, role: u.role, listing: u.listing,
    scores: { ...u.scores, liquidity: k.scores.liquidity,
      cost: u.scores.cost || (d.expense_ratio != null ? k.scores.cost : undefined),
      concentration: d.top10_weight_pct != null ? k.scores.concentration : undefined } };
}
// How long the fund has traded: a few years of history is the minimum to judge it on.
function scoreFromAge(inc) {
  const y = inc ? (Date.parse(EXPLORE.as_of || inc) - Date.parse(inc)) / 3.156e10 : NaN;
  if (!isFinite(y)) return undefined;
  if (y >= 5) return { rating: "green", note: `Listed since ${inc} — over 5 years of history.` };
  if (y >= 1) return { rating: "yellow", note: `Listed since ${inc} — under 5 years of history.` };
  return { rating: "red", note: `Listed since ${inc} — under a year: very little history, and young funds close more often.` };
}

function makeUniverseEtf(r) {
  const flagged = [...(r.f || "")].map(x => FLAG_TEXT[x]);
  const dv = r.p != null && r.vol != null ? r.p * r.vol : null;
  const asof = (UNIVERSE.meta[r.mkt] || {}).as_of, mktLabel = (UNIVERSE.meta[r.mkt] || {}).label || r.mkt;
  const core = CORE_LANES.includes(r.lane);
  return {
    ticker: r.t, name: r.n, is_theme_fund: true, _adhoc: true, _fresh: true, _explorer: true,
    issuer: null, holdings_url: null,
    expense_ratio: r.er, aum_musd: r.aum != null ? Math.round(r.aum) : null,
    aum_display: r.aum != null ? fmtMoneyM(r.aum, aumCur(r)) + (aumCur(r) !== "USD" && aumUsd(r) != null ? ` (≈ ${fmtMoneyM(aumUsd(r), "USD")})` : "") : null,
    inception: r.inc, domicile: r.dom ? (DOM_TEXT[r.dom] || r.dom) : null, _dom: r.dom || null,
    payout: r.pol != null ? polText(r) : null, role: LANE_TEXT[r.lane] || null, listing: `${mktLabel}${r.x && r.x !== mktLabel ? " (" + r.x + ")" : ""} · trades in ${r.cur || "USD"}`,
    structure: flagged.length ? flagged.join(" · ") : "—", index: "—", holdings_count: null,
    top10_weight_pct: null, top10_weight_display: "—", largest_position_display: "—",
    derivatives: /L|F/.test(r.f || "") ? "Yes — swaps / futures" : "—",
    performance: { ytd: signed(r.ytd), as_of: asof,
      note: r.c1y != null ? `52-week share-price change: ${signed(r.c1y)} (excludes distributions).` : null },
    market: { price: r.p, price_display: money(r.p, r.cur), price_asof: asof, volume_avg: r.vol, volume_display: shares(r.vol) },
    // Only checks the data can answer: no rating at all beats a yellow 'Caution' that only means 'unknown'.
    scores: {
      cost: r.er != null ? scoreFromExpense(r.er) : undefined,
      liquidity: scoreFromLiquidity({ aum_musd: aumUsd(r) != null ? Math.round(aumUsd(r)) : null, dollar_volume_avg: dv && r.cur && r.cur !== "USD" ? null : dv,
        dollar_volume_display: fmtDollarVol(dv, r.cur) }),
      track_record: scoreFromAge(r.inc),
    },
    overall: "From the full ETF list — daily data, no analyst review.",
    memo: {
      thesis: `${r.n} — listed in ${mktLabel}${r.dom ? " (" + (DOM_TEXT[r.dom] || r.dom) + ")" : ""}. ` +
        (core ? "A plain broad-index core fund: it holds hundreds or thousands of companies, so theme purity and concentration don't apply. " : "") +
        "The figures are the daily data from the full ETF list (via Yahoo Finance); there is no analyst review of this fund — check its fact sheet before buying.",
      red_flags: [
        ...(/L/.test(r.f || "") ? ["🔴 Leveraged/inverse daily-reset fund — suffers volatility decay; a trading tool, not a buy-and-hold investment."] : []),
        ...(/N/.test(r.f || "") ? ["⚠️ ETN: an unsecured note — you carry the issuer's credit risk, and it holds no basket of assets."] : []),
        ...(/F/.test(r.f || "") ? ["⚠️ Futures-based: returns can lag the spot price badly (roll costs / contango)."] : [])],
      bull: [], bear: [],
    },
  };
}

// General information on fund domicile and tax — deliberately not personal advice.
// With a tax residence chosen in Settings, the notes for that country (data/tax-domicile.json).
const DOM_ORDER = [["US", "US-domiciled (most US-listed ETFs)"], ["IE", "Ireland-domiciled UCITS (most London ETFs)"],
  ["LU", "Luxembourg-domiciled UCITS"], ["HK", "Hong Kong-domiciled"]];
const capFirst = s => s ? s[0].toUpperCase() + s.slice(1) : s;
function taxExplainer() {
  const d = el("details", { class: "glossary taxbox" }), r = taxHome(), home = r && r.id !== "other" ? r : null;
  d.append(el("summary", {}, home ? `Tax & domicile — general notes for ${home.label} residents (not tax advice)` : "Tax & domicile — general information (not tax advice)"));
  const dl = el("dl");
  const add = (k, v) => { if (v) dl.append(el("dt", {}, k), el("dd", {}, v)); };
  add("Why domicile matters", "Where a fund is legally based (its domicile) — not where it trades — largely decides the tax lost on its dividends and, for non-US investors, US estate-tax exposure. The same index can be held through a US, Irish or Hong Kong fund with different after-tax results.");
  if (home) {
    if (home.summary) add("In short", home.summary);
    DOM_ORDER.forEach(([k, label]) => {
      const v = (home.domiciles || {})[k];
      if (v) add(label, `${(VERDICT[v.verdict] || ["•"])[0]} ${capFirst(v.verdict)} — ${v.note}`);
    });
    add("US tax on US-fund dividends", home.us_wht);
    add("US estate tax", home.estate);
    add("Accumulating share classes", home.accumulating);
    add("Your home country's tax on fund income", home.home_tax);
    add("Can you buy them?", home.access);
    if ((home.caveats || []).length) add("Watch out", home.caveats.join(" "));
  } else {
    const fl = (TAX && TAX.fund_level) || [];
    const label = Object.fromEntries(DOM_ORDER);
    if (fl.length) fl.forEach(f => add(label[f.domicile] || f.domicile, [f.inside_fund, f.on_distributions, f.us_situs, f.note].filter(Boolean).join(" ")));
    else {
      add(label.US, "For investors who are not US persons, US withholding tax on dividends is generally 30% unless a tax treaty lowers it. US-listed ETFs are US-situs assets: for non-US persons, US estate tax can apply above US$60,000.");
      add(label.IE, "The fund itself generally suffers 15% on US dividends under the US–Ireland treaty; Ireland normally doesn't withhold on distributions to non-Irish investors; and the fund is not a US-situs asset for US estate tax.");
      add(label.LU, "Usually suffers 30% on US dividends at fund level.");
    }
    add("Your own rules", "Your home country's tax and reporting rules decide the rest — for example, reinvested income in an accumulating fund is still taxed every year in some countries. Choose where you pay tax in ⚙ Settings to see general notes for that country, and confirm with a tax adviser before acting.");
  }
  const src = (home && home.sources) || [];
  if (src.length) {
    const links = el("span", {});
    src.slice(0, 6).forEach((x, i) => links.append(i ? " · " : "", el("a", { href: x.url, target: "_blank", rel: "noopener", title: x.supports || "" }, (() => { try { return new URL(x.url).hostname.replace(/^www\./, ""); } catch (_) { return "source"; } })())));
    dl.append(el("dt", {}, "Sources" + (TAX.as_of ? ` (checked ${TAX.as_of})` : "")), el("dd", {}, links));
  }
  d.append(dl);
  return d;
}
