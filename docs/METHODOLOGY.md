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
