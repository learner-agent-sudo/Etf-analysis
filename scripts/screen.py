#!/usr/bin/env python3
"""
Backend ETF screener — the "green light" gate.

Screens every curated fund against the buy-interest criteria BEFORE a fund is
worth featuring:

    cost           must be GREEN
    concentration  must be GREEN   (the "concern" dimension)
    purity         GREEN or YELLOW (not red)

Benchmarks/reference funds (is_theme_fund == false) are excluded — they exist
only for comparison, not as buy candidates.

Usage:
    python3 scripts/screen.py            # human-readable report
    python3 scripts/screen.py --json     # machine-readable (list of passing tickers)
    python3 scripts/screen.py --stamp    # write meets_criteria=true/false back into the data
    python3 scripts/screen.py --check    # compare ratings with the latest market.json data

The --stamp mode tags each fund so the website can show a "Meets my criteria"
badge/filter. Run it after adding or re-scoring any fund.
"""
import json, glob, os, sys

DATA = os.path.join(os.path.dirname(__file__), "..", "public", "data")

# The rule. Change here and re-run --stamp to update the whole site.
def rating(etf, dim):
    return (etf.get("scores", {}).get(dim) or {}).get("rating")

def passes(etf):
    return (rating(etf, "cost") == "green"
            and rating(etf, "concentration") == "green"
            and rating(etf, "purity") in ("green", "yellow"))

CRITERIA_TEXT = "cost=green, concentration=green, purity in {green,yellow}"


def load():
    out = []
    for f in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        if "etfs" in d:              # skip non-theme files such as market.json
            out.append((f, d))
    return out


def report():
    print(f"ETF green-light screen — {CRITERIA_TEXT}\n")
    total_pass = total_funds = 0
    for _f, d in load():
        funds = [e for e in d["etfs"] if e.get("is_theme_fund")]
        winners = [e for e in funds if passes(e)]
        total_pass += len(winners); total_funds += len(funds)
        print(f"## {d['name']} — {len(winners)}/{len(funds)} pass")
        for e in funds:
            mark = "PASS" if passes(e) else "  · "
            print(f"   {mark} {e['ticker']:6} cost={rating(e,'cost'):6} conc={rating(e,'concentration'):6} "
                  f"purity={rating(e,'purity'):6}")
        print()
    print(f"TOTAL: {total_pass}/{total_funds} theme funds pass the green-light screen.")


def as_json():
    res = {}
    for _f, d in load():
        res[d["id"]] = [e["ticker"] for e in d["etfs"]
                        if e.get("is_theme_fund") and passes(e)]
    print(json.dumps(res, indent=2))


def stamp():
    n = 0
    for f, d in load():
        for e in d["etfs"]:
            e["meets_criteria"] = bool(e.get("is_theme_fund") and passes(e))
            n += 1
        json.dump(d, open(f, "w", encoding="utf-8"), indent=2)
    print(f"Stamped meets_criteria on {n} funds across {len(load())} themes.")


def check():
    """Flag curated funds whose latest fund data (public/data/market.json)
    contradicts the numbers their ratings were based on. Mirrors the site's
    'Data check' section; screen-relevant drifts on passing funds come first."""
    mpath = os.path.join(DATA, "market.json")
    if not os.path.exists(mpath):
        print("No market.json yet — nothing to compare.")
        return
    market = json.load(open(mpath, encoding="utf-8")).get("tickers", {})
    rows = []
    for _f, d in load():
        for e in d["etfs"]:
            m = market.get(e["ticker"])
            if not m:
                continue
            notes, hits_screen = [], False
            t_new, t_old = m.get("top10_weight_pct"), e.get("top10_weight_pct")
            if t_new is not None and t_old is not None and abs(t_new - t_old) >= 8:
                notes.append(f"top-10 {t_old}% -> {t_new}%")
                hits_screen |= t_new > t_old + 8 or (t_new > 50 >= t_old)
            er_new, er_old = m.get("expense_ratio"), e.get("expense_ratio")
            if er_new is not None and er_old is not None and abs(er_new - er_old) >= 0.05:
                notes.append(f"expense {er_old:.2f}% -> {er_new:.2f}%")
                hits_screen |= er_new > er_old
            a_new, a_old = m.get("aum_musd"), e.get("aum_musd")
            if a_new and a_old and not 0.5 <= a_new / a_old <= 2:
                notes.append(f"AUM ${a_old}M -> ${a_new}M")
            if notes:
                rows.append((not (e.get("meets_criteria") and hits_screen), d["id"], e["ticker"],
                             e.get("meets_criteria"), hits_screen, "; ".join(notes)))
    print(f"Data check vs market.json — {len(rows)} fund(s) with drift\n")
    for _k, theme, tk, passes_now, hits, note in sorted(rows):
        flag = "RE-CHECK (passes screen)" if passes_now and hits else ""
        print(f"  {theme:14} {tk:6} {note}  {flag}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--json":
        as_json()
    elif arg == "--stamp":
        stamp()
    elif arg == "--check":
        check()
    else:
        report()
