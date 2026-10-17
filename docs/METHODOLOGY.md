# Methodology — the dimensions we score and why

This is the analytical core. Every ETF gets looked at through the same lens so
that funds are **comparable**. Each dimension below lists: what it is, why it
matters (especially for high-risk themes), where to find it, and the red-flag
threshold.

Score each dimension 🟢 / 🟡 / 🔴 and write one sentence of evidence. The point is
not a single magic number — it is a structured, honest summary of trade-offs.

---

## 1. Cost

What you pay, every year, regardless of performance. The one thing you fully
control by choosing one fund over another.

| Metric | What it is | Where | 🔴 Red flag |
|---|---|---|---|
| **Expense ratio (TER)** | Annual % of assets taken as fees | Fact sheet, prospectus | Thematic > 0.75%; broad > 0.50% |
| **Bid/ask spread** | Cost to trade in/out | Broker, etf.com | Wide / illiquid (> 0.30%) |
| **Premium / discount to NAV** | Price vs. true asset value | Issuer daily NAV page | Persistent > ±0.50% |

> Why it matters: cost compounds. 0.75% vs 0.35% is ~0.40%/yr — over a decade
> that is a meaningful chunk of return, paid whether the fund wins or loses.
> Thematic funds are systematically more expensive; decide if the theme is worth
> the premium.

---

## 2. Strategy / structure

*How* the fund tries to deliver its result. This defines the real risk engine.

- **Passive vs active.** Passive tracks a published index (rules-based,
  transparent). Active = manager discretion (theme drift, key-person risk, but
  also adaptability).
- **Index methodology** (if passive). Cap-weighted? Equal-weighted? Tiered?
  Equal-weight spreads risk; cap-weight concentrates it in the biggest names.
- **Derivatives / options.** Covered calls, protective puts, etc. These **cap
  upside** and/or change the return shape — critical to understand for any
  "income" or "buffered" ETF.
- **Leverage / inverse.** Daily-reset leveraged funds (2x, 3x) suffer **volatility
  decay** and are *not* buy-and-hold instruments. Treat as 🔴 for long-term theme
  investing unless you know exactly what you're doing.
- **Securities lending.** Adds small income but a sliver of counterparty risk.

> Where: prospectus "Principal Investment Strategies" section; fact sheet.

### Reading an options-income strategy (since you flagged this)
For covered-call / option ETFs, capture: (a) what they write options *on*
(the index vs. individual holdings), (b) how much of the portfolio is covered,
(c) whether it's systematic or discretionary, and (d) the **upside cap** —
the price you pay for the income is giving up rallies. High headline "yield" is
often return-of-capital, not free money.

---

## 3. Holdings concentration

How many eggs, how many baskets.

| Metric | Where | 🔴 Red flag |
|---|---|---|
| **# of holdings** | Fact sheet | < 30 (very concentrated) |
| **Top-10 weight %** | Fact sheet / holdings file | > 50% |
| **Largest single position %** | Holdings file | > 10% |

> Why it matters: a 35-stock fund with 60% in the top 10 is, functionally, a
> bet on a handful of companies wearing a diversification costume. For volatile
> themes (space, biotech) concentration multiplies the swings.

---

## 4. Theme purity ⭐ (the most important one for your use case)

**Does the fund actually do what its name says?** Thematic ETFs routinely pad
holdings with loosely-related large caps to hit liquidity/diversification rules.

How to assess:
1. Pull the **full holdings list** (issuer publishes daily for most ETFs).
2. For each top holding ask: *is this a pure-play on the theme, a partial
   exposure, or basically unrelated?*
3. Estimate **% of assets in genuine pure-plays** vs. "filler."

> Worked example: a space ETF holding a furniture retailer, a water-utility, and
> several broad industrials is selling "space" but delivering "diversified
> industrials with a space label." Not wrong — but know what you own. Also watch
> for **theme drift**: e.g. several "space" funds quietly broadened mandates to
> "space *and defense*" in 2025, changing the risk profile.

| Rating | Meaning |
|---|---|
| 🟢 | Most of top holdings are clear pure-plays on the theme |
| 🟡 | Mixed; meaningful filler or adjacent exposure |
| 🔴 | Name and holdings substantially disagree |

---

## 5. Sector & geographic exposure

Where the money actually sits — and, crucially, **overlap across your funds**.
Two different thematic ETFs can hold the same mega-caps, so buying both gives
less diversification than it looks. Record top 3 sectors and US-vs-international
split for every fund.

---

## 6. Size & liquidity

Can you get in and out at a fair price, and will the fund survive?

| Metric | Where | 🔴 Red flag |
|---|---|---|
| **AUM (net assets)** | Fact sheet | < $50M (closure risk) |
| **Avg daily volume** | Broker / etf.com | Thin → wide spreads |
| **Inception date / age** | Fact sheet | < 1–2 yrs (no track record) |
| **Fund closures** | News | Issuer history of shuttering funds |

> Small, young thematic ETFs get **liquidated** when assets don't show up —
> forcing a sale at a bad time and a taxable event.

---

## 7. Track record & risk (context, not prophecy)

Past performance does not predict the future, but it characterizes behavior.
Capture, with dates: trailing returns (1/3/5yr) **vs. a fair benchmark**,
max drawdown, volatility, and **tracking difference** (for passive: how far it
strays from its index). For active funds, compare to a relevant index to see if
the manager is adding or subtracting value net of fees.

---

## The green-light screen (backend gate)

A fund only earns buy-interest if it clears a hard screen on the dimensions that
are non-negotiable. Default rule (see `scripts/screen.py`):

- **Cost — must be 🟢 green** (the one thing fully in your control)
- **Concentration — must be 🟢 green** (the "concern" — no hidden single-stock bet)
- **Theme purity — 🟢 green or 🟡 yellow** (you'll accept some dilution, but not a
  fund whose label and holdings flatly disagree)

Benchmarks/reference funds are excluded (they exist for comparison, not to buy).
Run `python3 scripts/screen.py` for the report, `--stamp` to tag every fund with
`meets_criteria` so the website shows a **✓ criteria** badge and a "Meets my
criteria" filter. Re-run after adding or re-scoring any fund.

> Finding: across six themes only a handful of funds pass — niche themes are
> structurally small (→ concentrated) and low-scale (→ pricey), so "cheap AND
> diversified AND on-theme" is rare. That scarcity is the point: the screen
> surfaces the few funds actually worth a deep look.

## Income ranking — every option-income ETF on one Value Score

Themes → *Income / Covered-Call* → **Value ranking** (`scripts/build_income.py`,
rebuilt daily) covers every covered-call, premium-income, call-spread, 0DTE,
single-stock, short-volatility, put-write and dividend+options ETF on US, Hong
Kong and London listings (~400 funds), grouped into strategy families.

### The headline: Value Score (0–100, compare any two funds)

One number, computed the same way for every fund, so a higher score is better
value across strategies: *how much an income investor got for what it cost
them over the last 3 years*. Four pillars, 25 points each:

| Pillar | Measures | Curve (pillar 0–100) |
|---|---|---|
| Earned income | regular yield, counted only up to the fund's total return (the rest came out of your capital) | 4% → 55, 8% → 80, 12% → 91 |
| Paycheck trend | price (≈ NAV) change per year — a falling price shrinks every payout | 0%/yr → 73, −3% → 50, −10% → 9 |
| Growth kept | total return vs the fund's own benchmark (the brief's gap) | 0 pp → 83, −4 pp → 50, −8 pp → 17 |
| Smooth ride | half worst fall, half Sharpe vs T-bills | −10% → 92, −25% → 50; Sharpe 1.0 → 88 |

Funds with under 3 years of prices are pulled toward the typical seasoned
fund of their strategy (or risk bucket). Red flags then cap or deduct:
leveraged or a fall of more than half → at most 44 (F); single stock /
crypto, ETN/ETP notes, or paying out of capital (earned < half of paid, or
price falling > 10%/yr) → at most 59 (D); no better than T-bills −10; under
2 years −10 × (2 − years); under $100M or thinly traded −5. Grades: A 80+,
B 70–79, C 60–69, D 45–59, F under 45. The score is pre-tax (tax is
personal) and fee-neutral (fees are already inside every return). It
describes the past window, not the future — and an ETF trades at about the
value of what it holds, so the page never calls a fund "undervalued" or
"cheap"; it ranks value for money.

The default view is **safety-checked** funds: those passing every gate
below, plus funds whose only failed gate is age and that are within six
months of it (shown with the date they turn old enough). Today's VIX
against its 3-year range is shown as market-wide context for how rich
option premiums are; it isn't part of any score.

### The brief's three-layer screen (expert detail in each fund card)

The gates and the strategy-family score from the user's brief are kept: the
gates define "safety-checked", and the family-weighted score (with its US /
non-US tax view) appears in each fund card's expert details.

1. **Tiered gates** (the "Recommended screen"): systematic strategies need AUM
   ≥ $100M, ≥ 2 years, expense ≤ 0.60%; actively managed ones AUM ≥ $500M,
   ≥ 3 years, expense ≤ 0.85%. All need ≥ 100K shares or ≥ $2M a day of
   trading, and leveraged funds, ETNs and ETPs never pass.
2. **Quality components (0–100):** total return vs the fund's *own*
   underlying (−4 pp/yr scores 50); distribution coverage — the share of the
   payout funded by total return rather than by a falling NAV (< 70% flagged);
   NAV trend; underlying quality (broad index > sector > single stock >
   leveraged, extreme-yield penalty within the family, payout track record);
   US tax efficiency; fees; ELN counterparty/transparency; volatility-spike
   sensitivity; payout stability. Return and NAV components use smooth
   curves (−4 pp/yr vs benchmark = 50, level ≈ 83) so funds don't tie at a
   cap. Funds need ~1 year of history to be scored; with less than three
   years, history-based components are pulled toward the median of seasoned
   funds in the same family. Yields exclude one-off year-end capital-gain
   specials; coverage uses log returns (a fund with negative total return
   covered none of its payout).
3. **Family weights:** systematic covered calls NAV 40 / gap 30 / tax 30;
   active funds that use ELNs counterparty 30 / gap 30 / fees 20 /
   transparency 20 (other active funds use the default weights); call
   spreads tax 40 / gap 30 / NAV 30; short volatility VIX sensitivity 40 /
   gap 30 / stability 30; all other families gap 30 / coverage 25 / NAV 20 /
   quality 15 / tax 10. A non-US tax view drops the US-tax component.

Benchmarks are always total-return series (ETFs rather than price-only
indices, e.g. 2800.HK for the Hang Seng); inverse funds, lines trading in a
different currency from their benchmark, and funds whose benchmark can't be
loaded are listed but not scored. Benchmark prices are matched to the
fund's window dates within 10 days (markets keep different holidays). If the
benchmark's history starts late but still shares at least a year and 60% of
the window, both are compared over that shared stretch and the card says
so; otherwise the card shows the benchmark's date range and the fund isn't
scored. Leveraged "daily target" funds and
bond/closed-end funds without an option overlay are excluded.

Scores rank funds *within* a family. Holding-experience metrics (max
drawdown, volatility, Sharpe vs T-bills, up/down capture) are shown for every
fund. Coverage is measured from prices and payouts because the tax
"return of capital" label isn't in free data and misleads for funds whose ROC
is a tax effect while their NAV holds up.

## Putting it together

There is **no universal weighting** — it depends on your goal. A reasonable
default for a long-term thematic bet:

1. Theme purity (are you buying the bet you think you are?)
2. Concentration & risk (can you stomach the swings?)
3. Cost (is the premium justified?)
4. Liquidity/size (will it survive and trade well?)
5. Track record (sanity check on execution)

Fill the [scorecard](../templates/comparison-scorecard-template.md), then the
deep [memo](../templates/etf-memo-template.md) for finalists, then the
[red-flags checklist](../templates/red-flags-checklist.md). Decide. Write down
*why*.
