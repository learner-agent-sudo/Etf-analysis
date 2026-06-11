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
        out.append((f, json.load(open(f, encoding="utf-8"))))
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


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--json":
        as_json()
    elif arg == "--stamp":
        stamp()
    else:
        report()
