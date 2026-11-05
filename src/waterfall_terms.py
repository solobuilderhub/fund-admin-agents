#!/usr/bin/env python3
"""
Extract distribution waterfall terms from a fund agreement extract: tier order,
preferred return rate and compounding, catch-up and split percentages, the
incentive-fee caps, apportionment rule, and the proceeds definitions. Each term
carries its section and original page.

Usage:
  python3 waterfall_terms.py --pdf <agreement_extract.pdf> --out <waterfall_terms.json>
"""
import argparse, json, os, re
import pdfplumber

RULES = [
    ("apportionment", "Apportionment of proceeds among Members",
     r"(apportioned among the Members pro rata in accordance with their respective Capital Contributions in respect of such Portfolio Investment)", "txt"),
    ("tier_a", "Tier A — return of Capital Contributions (incl. fee and expense contributions)",
     r"(Return of Capital Contributions \. First, 100% to such Member)", "txt"),
    ("pref_rate", "Tier B — Preferred Return rate", r"equal to (\d+)% per annum, compounded\s+annually", "pct"),
    ("pref_compounding", "Tier B — compounding", r"per annum, (compounded\s+annually)", "txt"),
    ("pref_start", "Tier B — accrual start",
     r"(computed from the dates that such Capital Contributions were due \(or, if actually made later, the date on which such Capital Contributions were actually made\))", "txt"),
    ("catch_up_pct", "Tier C — Investment Manager catch-up to", r"Investment Manager Catch Up to (\d+)%", "pct"),
    ("split_member_pct", "Tier D — split to Members", r"\(D\) (\d+)%/\d+%", "pct"),
    ("split_im_pct", "Tier D — split to Investment Manager", r"\(D\) \d+%/(\d+)%", "pct"),
    ("gains_cap_pct", "Cap — incentive on Disposition Proceeds, % of net cumulative gains",
     r"exceeds (\d+)% of cumulative realized capital gains net of all cumulative realized capital losses and unrealized capital depreciation", "pct"),
    ("gains_cap_basis", "Cap — basis",
     r"(cumulative realized capital gains net of all cumulative realized capital losses and unrealized capital depreciation)", "txt"),
    ("proportion_cap", "Cap — relative to proceeds distributed to Members (wording)",
     r"(In no event will the\s+Investment Manager receive amounts of [\w\- ]*Incentive Fees under clause \(i\)\(C\) and \(i\)\(D\) above in excess of the percentage of the Disposition Proceeds actually distributed to Members)", "txt"),
    ("current_waterfall", "Current Proceeds — separate waterfall (no return of capital tier)",
     r"(Current Proceeds apportioned to Members shall be divided)", "txt"),
    ("def_current", "Definition — Current Proceeds", r"(Current Proceeds shall mean all proceeds from current returns on investments[^.]*)", "txt"),
    ("def_disposition", "Definition — Disposition Proceeds", r"(Disposition Proceeds shall mean all amounts received by the Fund upon the disposition of\s*an investment[^.]*)", "txt"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    with pdfplumber.open(a.pdf) as pdf:
        flat = re.sub(r"\s+", " ", "\n".join(p.extract_text() or "" for p in pdf.pages))
    marks = [(m.start(), m.group(1), m.group(2)) for m in re.finditer(r"\[(Section [\d.()a-z]+|Definitions) · p\.(\d+)\]", flat)]
    where = lambda pos: next(((s, int(p)) for q, s, p in reversed(marks) if q <= pos), (None, None))
    terms, missing = {}, []
    for key, label, rx, kind in RULES:
        m = re.search(rx, flat, re.I)
        if not m:
            missing.append(key); continue
        v = int(m.group(1)) / 100 if kind == "pct" else m.group(1)
        sec, page = where(m.start())
        terms[key] = {"label": label, "value": v, "section": sec, "page": page,
                      "evidence": flat[max(0, m.start() - 50): m.end() + 50].strip()}
    checks = []
    if {"split_member_pct", "split_im_pct"} <= terms.keys():
        s = terms["split_member_pct"]["value"] + terms["split_im_pct"]["value"]
        checks.append({"check": "Tier D split sums to 100%", "status": "PASS" if abs(s - 1) < 1e-9 else "FAIL"})
    if {"catch_up_pct", "split_im_pct"} <= terms.keys():
        ok = terms["catch_up_pct"]["value"] == terms["split_im_pct"]["value"]
        checks.append({"check": "Catch-up target equals Investment Manager split (full catch-up)", "status": "PASS" if ok else "REVIEW"})
    res = {"_source": os.path.basename(a.pdf), "terms": terms, "checks": checks, "missing": missing,
           "interpretation_flags": ["The 'percentage of the Disposition Proceeds actually distributed to Members' limit does not state "
                                    "the percentage; not modelled — confirm with the Investment Manager."] if "proportion_cap" in terms else [],
           "status": "COMPLETE" if not missing else "NEEDS REVIEW"}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=2)
    print(f"Captured {len(terms)} waterfall terms · missing: {missing or 'none'}")
    for k, t in terms.items():
        v = f"{t['value']:.0%}" if isinstance(t["value"], float) else (t["value"][:70] + ("…" if len(t["value"]) > 70 else ""))
        print(f"  {t['label']:<72} {v:<72} {t['section']} p.{t['page']}")
    for c in checks:
        print(f"  CHECK {c['status']}: {c['check']}")
    for f in res["interpretation_flags"]:
        print(f"  FLAG: {f}")


if __name__ == "__main__":
    main()
