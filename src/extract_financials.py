#!/usr/bin/env python3
"""
Extract fund financial statements and NAV reports from a data room into one
structured JSON: every line item with its values and the page it came from.

Reads (by filename pattern in --dataroom):
  *Annual_Financial_Report*.pdf    -> fy   (current and prior year columns)
  *Half_Year_Financial_Report*.pdf -> hy
  *Monthly_Report_YYYY-MM*.pdf     -> monthly[YYYY-MM]

Usage:
  python3 extract_financials.py --dataroom <dir> --out <extracted.json>
"""
import argparse, glob, json, os, re
import pdfplumber

NUM = r"\(?-?[\d,]+(?:\.\d+)?\)?|-"
LINE = re.compile(rf"^(?P<label>.*?[A-Za-z').])\s+(?P<vals>(?:{NUM})(?:\s+(?:{NUM}))*)$")

SECTIONS = [  # (heading text, key)
    ("Statement of profit or loss", "pl"),
    ("Statement of financial position", "fp"),
    ("Statement of changes in equity", "ce"),
    ("Statement of cash flows", "cf"),
    ("Note 7", "receivables"),
    ("Note 9", "payables"),
    ("Note 10", "units_count"),
    ("Value of units", "units_value"),
    ("Note 11", "distributions"),
    ("Note 14", "fees_note"),
    ("Note 4", "fees_note"),
]
SKIP = re.compile(r"(\$\s*$|\bunits\s*$|Anonymised · page)")


def num(tok):
    if tok == "-":
        return 0.0
    neg = tok.startswith("(") or tok.startswith("-")
    v = float(tok.strip("()-").replace(",", ""))
    return -v if neg else v


def parse_statements(path):
    out, cur = {}, None
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            for raw in (page.extract_text() or "").splitlines():
                line = raw.strip()
                for head, key in SECTIONS:
                    if line.startswith(head):
                        cur = key
                        out.setdefault(key, {"page": pno, "lines": {}})
                if cur is None or SKIP.search(line):
                    continue
                m = LINE.match(line)
                if m and not line.startswith(("Note ", "Statement ")):
                    vals = [num(t) for t in re.findall(NUM, m.group("vals"))]
                    out[cur]["lines"][m.group("label").strip()] = vals if len(vals) > 1 else vals[0]
            text = page.extract_text() or ""
            if (e := re.search(r"earnings per unit \(cents\):\s*([\d.]+)\s*\(2025:\s*([\d.]+)\)", text)):
                out["eps_cents"] = [float(e.group(1)), float(e.group(2))]
            if (e := re.search(r"Distributions for the year:\s*([\d.]+)\s*cents per unit\s*\(2025:\s*([\d.]+)\)", text)):
                out["cents_per_unit_year"] = [float(e.group(1)), float(e.group(2))]
            if (e := re.search(r"ended 30 June 2026:\s*([\d.]+)\s*cents per unit", text.replace("\n", " "))):
                out["cents_per_unit_final"] = float(e.group(1))
            if (e := re.search(r"NAV per unit of \$([\d.]+) as at ([\w ]+\d{4})", text.replace("\n", " "))):
                out["subsequent_nav"] = {"nav_per_unit": float(e.group(1)), "date": e.group(2).strip()}
    return out


def parse_monthly(path):
    with pdfplumber.open(path) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    r = {"source": os.path.basename(path), "audited": "unaudited" not in text.lower()}
    for label, key in [("NAV per unit (cum)", "nav_cum"), ("NAV per unit (ex-distribution)", "nav_ex"), ("NAV per unit ", "nav")]:
        m = re.search(re.escape(label) + r"\s*\$([\d.]+)", text)
        if m and key not in r:
            r[key] = float(m.group(1))
    if "nav" not in r and "nav_ex" in r:
        r.pop("nav", None)
    if (m := re.search(r"1-month performance\s*([+-][\d.]+)%", text)):
        r["return_1m"] = float(m.group(1)) / 100
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataroom", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    res = {"dataroom": os.path.abspath(a.dataroom), "monthly": {}}
    for f in sorted(glob.glob(os.path.join(a.dataroom, "*.pdf"))):
        b = os.path.basename(f)
        if "Annual_Financial_Report" in b:
            res["fy"] = dict(parse_statements(f), source=b)
        elif "Half_Year_Financial_Report" in b:
            res["hy"] = dict(parse_statements(f), source=b)
        elif (m := re.search(r"Monthly_Report_(\d{4}-\d{2})", b)):
            res["monthly"][m.group(1)] = parse_monthly(f)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=2)
    n = sum(len(s["lines"]) for d in (res.get("fy", {}), res.get("hy", {})) for s in d.values() if isinstance(s, dict) and "lines" in s)
    print(f"Extracted {n} line items from {len([k for k in ('fy', 'hy') if k in res])} financial reports "
          f"and {len(res['monthly'])} monthly NAV reports -> {a.out}")


if __name__ == "__main__":
    main()
