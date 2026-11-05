#!/usr/bin/env python3
"""
Extract capital call mechanics from a fund's governing agreement (LPA / LLC
agreement extract): notice periods, allocation key per purpose, Business Day
definition, default cure period, amended-notice funding period, Default Rate,
unit issue price, and subsequent-closing equalisation. Each term carries the
agreement section and original page.

Usage:
  python3 call_terms.py --pdf <agreement_extract.pdf> --out <call_terms.json>
"""
import argparse, json, os, re
import pdfplumber

W = {"five": 5, "ten": 10, "fifteen": 15, "twenty": 20}

RULES = [
    ("notice_business_days", "Funding Notice period (Business Days before Drawdown Due Date)",
     r"no later than (\w+) \(\d+\) Business Days prior to the date of such Drawdown", "num"),
    ("initial_notice_business_days", "Initial Drawdown notice period (Business Days)",
     r"initial Drawdown[^.]*?at least (\w+) \(\d+\) Business Days prior", "num"),
    ("key_portfolio_investment", "Allocation key — Portfolio Investments",
     r"in respect of any Portfolio Investment, such Capital Contribution shall be equal to such Member’s (Remaining Commitment Percentage)", "txt"),
    ("key_management_fees", "Allocation key — Management Fees",
     r"in respect of [\w\- ]*Management Fees[^;]*?such Capital Contribution shall be equal to such Member’s (Invested Capital Percentage)", "txt"),
    ("key_fund_expenses", "Allocation key — Fund Expenses not attributable to a Portfolio Investment",
     r"not attributable to a particular Portfolio Investment[^;]*?such Capital Contribution shall be equal to such Member’s (Capital Commitment Percentage)", "txt"),
    ("cap_remaining_commitment", "Cap — no Member funds above its Remaining Capital Commitment",
     r"(up to but not exceeding the amount of its Remaining Capital Commitment)", "txt"),
    ("business_day", "Business Day definition",
     r"Business Day shall mean (any day on which both \(a\) the New York Stock\s+Exchange is open and \(b\) the U\.S\. Federal Reserve Banks are open)", "txt"),
    ("default_cure_business_days", "Default — cure period after written notice (Business Days)",
     r"such failure continues for (\w+) Business Days after receipt of written notice", "num"),
    ("amended_notice_business_days", "Defaulted Amount — amended notice funding period (Business Days)",
     r"Payment of such additional Capital Contributions shall be made within (\w+) Business Days", "num"),
    ("default_rate", "Default Rate",
     r"Default Rate shall mean (the lesser of \(a\) the Prime Rate plus 4% per annum and\s*\(b\) the maximum annual interest rate permitted by law)", "txt"),
    ("unit_issue_price", "Unit issue price on Drawdown",
     r"(Units will be issued at a per-Unit price equal to the net asset value \(“ ?NAV ?” ?\) per Unit as of the close of the last quarter preceding the funding date)", "txt"),
    ("equalisation", "Subsequent Closing equalisation",
     r"(required to pay to the Fund in connection with such closing an amount equal to their proportionate share of all funded Commitments made prior to their admission)", "txt"),
    ("notice_contents", "Funding Notice must state",
     r"Each Funding Notice shall specify:\s*\(A\) (the date of the Drawdown)", "txt"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    with pdfplumber.open(a.pdf) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    flat = re.sub(r"\s+", " ", text)
    # section and original-page markers written into the extract: "[Section 5.1 · p.28]"
    marks = [(m.start(), m.group(1), m.group(2)) for m in re.finditer(r"\[(Section [\d.()a-z]+|Definitions) · p\.(\d+)\]", flat)]

    def where(pos):
        prev = [m for m in marks if m[0] <= pos]
        return (prev[-1][1], int(prev[-1][2])) if prev else (None, None)

    terms, missing = {}, []
    for key, label, rx, kind in RULES:
        m = re.search(rx, flat, re.I)
        if not m:
            missing.append(key)
            continue
        v = m.group(1)
        val = W.get(v.lower(), int(v) if v.isdigit() else v) if kind == "num" else v
        sec, page = where(m.start())
        terms[key] = {"label": label, "value": val, "section": sec, "page": page,
                      "evidence": flat[max(0, m.start() - 60): m.end() + 60].strip()}
    res = {"_source": os.path.basename(a.pdf), "terms": terms, "missing": missing,
           "status": "COMPLETE" if not missing else "NEEDS REVIEW"}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=2)
    print(f"Captured {len(terms)} capital call terms · missing: {missing or 'none'}")
    for k, t in terms.items():
        v = t["value"] if isinstance(t["value"], int) else (t["value"][:60] + ("…" if len(str(t["value"])) > 60 else ""))
        print(f"  {t['label']:<66} {v!s:<62} {t['section']} p.{t['page']}")


if __name__ == "__main__":
    main()
