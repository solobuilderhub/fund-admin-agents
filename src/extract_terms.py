#!/usr/bin/env python3
"""
Extract fund fee and pricing terms from an offer document (PDS / constitution
extract), including scanned or redacted image-only PDFs.

Pipeline: rasterise (pdftoppm) -> OCR (tesseract) -> rule-based term capture.
Every captured term carries its evidence sentence and the printed page number,
so a reviewer can check it against the source in seconds.

Usage:
  python3 extract_terms.py --pdf <offer_doc.pdf> --out <terms.json>
"""
import argparse, json, os, re, subprocess, tempfile

TERMS = [
    # key, label, regex (on normalised text), value group handling
    ("combined_fee_pa", "Responsible entity + management fee (aggregate)",
     r"(?:totalling|management\s+fee)\s+(\d\.\d{2})%\s*p\.a\."),
    ("re_fee_pa", "Responsible entity fee",
     r"responsible\s+entity\s+fee\s+of\s+(\d\.\d{2})%\s*p\.a"),
    ("mgmt_fee_pa", "Management fee",
     r"management\s+fee\s+of\s+(\d\.\d{2})%\s*p\.a"),
    ("perf_fee_rate", "Performance fee rate",
     r"performance\s+fee\s+of\s+(\d{1,2})%\s+of\s+the\s+trust"),
    ("hurdle_pa", "Hurdle return",
     r"hurdle\s+return\s*\(being\s+(\d{1,2})%\s*p\.a"),
]
FLAGS = [
    ("hwm", "High water mark applies", r"high\s+water\s*mark|\bHWM\b"),
    ("perf_fee_accrued_monthly", "Performance fee accrued monthly", r"calculated\s+and\s+accrued\s+monthly"),
    ("fees_paid_monthly_in_arrears", "Management costs paid monthly in arrears", r"payable\s+monthly\s+in\s+arrears"),
    ("gst_net_of_ritc", "Fees quoted inclusive of GST net of RITC", r"net\s+of\s+any\s+reduced\s+input\s+tax\s+credits"),
]


def ocr_pages(pdf):
    out = []
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftoppm", "-r", "200", "-png", pdf, os.path.join(td, "p")], check=True)
        for i, f in enumerate(sorted(os.listdir(td)), start=1):
            txt = subprocess.run(["tesseract", os.path.join(td, f), "stdout"], capture_output=True, text=True).stdout
            m = re.search(r"^\s*(\d{1,3})\s*[|I]\s", txt, re.M) or re.search(r"[|I]\s*(\d{1,3})\s*$", txt, re.M)
            out.append({"extract_page": i, "printed_page": int(m.group(1)) if m else None, "text": txt})
    return out


def norm(s):
    return re.sub(r"\s+", " ", s.replace("’", "'"))


def sentence(text, span):
    a = text.rfind(".", 0, span[0]) + 1
    b = text.find(".", span[1])
    return text[a:b + 1 if b > 0 else None].strip()[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    pages = ocr_pages(a.pdf)
    found = {}
    for p in pages:
        t = norm(p["text"])
        for key, label, rx in TERMS:
            if key in found:
                continue
            m = re.search(rx, t, re.I)
            if m:
                v = float(m.group(1)) / 100
                found[key] = {"label": label, "value": v, "page": p["printed_page"],
                              "extract_page": p["extract_page"], "evidence": sentence(t, m.span())}
        for key, label, rx in FLAGS:
            if key in found:
                continue
            m = re.search(rx, t, re.I)
            if m:
                found[key] = {"label": label, "value": True, "page": p["printed_page"],
                              "extract_page": p["extract_page"], "evidence": sentence(t, m.span())}
    checks = []
    if {"re_fee_pa", "mgmt_fee_pa", "combined_fee_pa"} <= found.keys():
        s = round(found["re_fee_pa"]["value"] + found["mgmt_fee_pa"]["value"], 6)
        checks.append({"check": "RE fee + management fee = aggregate fee", "expected": found["combined_fee_pa"]["value"],
                       "actual": s, "status": "PASS" if abs(s - found["combined_fee_pa"]["value"]) < 1e-9 else "FAIL"})
    missing = [k for k, *_ in TERMS + FLAGS if k not in found]
    res = {"source": os.path.basename(a.pdf), "pages_read": len(pages), "terms": found,
           "internal_checks": checks, "missing": missing,
           "status": "COMPLETE" if not missing else "NEEDS REVIEW"}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=2)
    print(f"Read {len(pages)} pages · captured {len(found)} terms · missing: {missing or 'none'}")
    for k, v in found.items():
        val = f"{v['value']:.2%}" if isinstance(v["value"], float) else "yes"
        print(f"  {v['label']:<52} {val:>8}   p.{v['page']}")
    for c in checks:
        print(f"  CHECK {c['check']}: {c['status']}")


if __name__ == "__main__":
    main()
