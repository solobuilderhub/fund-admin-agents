#!/usr/bin/env python3
"""
Tie out a fund's financial statements: casts, cross-casts, statement-to-note
ties, equity / units / retained earnings / cash rollforwards, and NAV per unit.

Arithmetic only — no judgement. Each check records expected, actual,
difference, tolerance and the pages it touches. Tolerance is zero unless a
figure was published rounded (source in $'000), in which case the bound is
half a rounding unit per rounded input.

Usage:
  python3 tieout.py --extracted <extracted.json> --out-dir <dir> [--rounding 125]
"""
import argparse, json, os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

checks = []


def chk(area, desc, expected, actual, refs, rounded_inputs=0, half_unit=0.0):
    diff = round(actual - expected, 2)
    tol = round(rounded_inputs * half_unit, 2)
    status = "TIES" if abs(diff) < 0.005 else ("TIES (rounding)" if abs(diff) <= tol else "BREAK")
    checks.append({"id": f"T{len(checks) + 1:02d}", "area": area, "check": desc, "expected": round(expected, 2),
                   "actual": round(actual, 2), "difference": diff, "tolerance": tol, "status": status, "refs": refs})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extracted", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--rounding", type=float, default=125.0,
                    help="value of one published rounding unit in reporting currency (default: $'000 x 0.125 = 125)")
    a = ap.parse_args()
    H = a.rounding / 2
    e = json.load(open(a.extracted))
    F, Y = e["fy"], e.get("hy")
    src = F["source"]

    def L(sec, key, col=0, d=F):
        v = d[sec]["lines"][key]
        return v[col] if isinstance(v, list) else v

    def pg(sec, d=F):
        return f"{d['source']} p.{d[sec]['page']}"

    for col, yr in [(0, "FY26"), (1, "FY25")]:
        # --- profit or loss
        inc = ["Interest income/(expense)", "Dividends and distributions received",
               "Net gains on financial instruments at FVTPL", "Net foreign exchange gains/(losses)", "Other operating income"]
        exp = ["Responsible entity fee and management fee", "Withholding tax",
               "Secondaries management fee and carried interest fee", "Transaction costs",
               "Legal and professional fees", "Other operating expenses"]
        chk("Profit or loss", f"{yr} income lines cast to total net investment income",
            L("pl", "Total net investment income", col), sum(L("pl", k, col) for k in inc), [pg("pl")])
        chk("Profit or loss", f"{yr} expense lines cast to total operating expenses",
            L("pl", "Total operating expenses", col), sum(L("pl", k, col) for k in exp), [pg("pl")])
        chk("Profit or loss", f"{yr} income less expenses = profit",
            L("pl", "Profit for the year", col),
            L("pl", "Total net investment income", col) + L("pl", "Total operating expenses", col), [pg("pl")])
        # --- financial position
        chk("Financial position", f"{yr} assets cast",
            L("fp", "Total assets", col),
            sum(L("fp", k, col) for k in ["Cash and cash equivalents", "Receivables", "Financial assets at FVTPL"]), [pg("fp")])
        chk("Financial position", f"{yr} liabilities cast",
            L("fp", "Total liabilities", col),
            sum(L("fp", k, col) for k in ["Bank borrowing", "Distribution payable", "Payables"]), [pg("fp")])
        chk("Financial position", f"{yr} assets less liabilities = unitholders' equity (NAV)",
            L("fp", "Total unitholders' equity", col), L("fp", "Total assets", col) - L("fp", "Total liabilities", col), [pg("fp")])
        chk("Financial position", f"{yr} issued units + retained earnings = equity",
            L("fp", "Total unitholders' equity", col), L("fp", "Issued units", col) + L("fp", "Retained earnings", col), [pg("fp")])
        # --- changes in equity
        chk("Changes in equity", f"{yr} equity rollforward",
            L("ce", "Closing equity", col),
            sum(L("ce", k, col) for k in ["Opening equity", "Distributions reinvested", "Units buyback",
                                           "Distributions paid/payable", "Profit for the year"]), [pg("ce")])
        chk("Changes in equity", f"{yr} closing equity agrees to statement of financial position",
            L("fp", "Total unitholders' equity", col), L("ce", "Closing equity", col), [pg("ce"), pg("fp")])
        chk("Changes in equity", f"{yr} profit agrees to statement of profit or loss",
            L("pl", "Profit for the year", col), L("ce", "Profit for the year", col), [pg("ce"), pg("pl")])
        # --- cash flows
        op = ["Proceeds from sale of investments", "Payments for purchase of investments", "Transaction costs paid",
              "Dividends and distributions received", "Interest received/(paid)", "GST received/(paid)",
              "Other income received", "Management fees paid",
              "Secondaries management fee and carried interest fee paid", "Payments to suppliers"]
        fin = ["Change in bank borrowing", "Distributions paid", "Units buyback"]
        chk("Cash flows", f"{yr} operating cash flows cast",
            L("cf", "Net cash from operating activities", col), sum(L("cf", k, col) for k in op), [pg("cf")])
        chk("Cash flows", f"{yr} financing cash flows cast",
            L("cf", "Net cash from financing activities", col), sum(L("cf", k, col) for k in fin), [pg("cf")])
        chk("Cash flows", f"{yr} operating + financing = net change in cash",
            L("cf", "Net change in cash", col),
            L("cf", "Net cash from operating activities", col) + L("cf", "Net cash from financing activities", col), [pg("cf")])
        chk("Cash flows", f"{yr} opening cash + net change + FX = closing cash",
            L("cf", "Closing cash", col),
            L("cf", "Opening cash", col) + L("cf", "Net change in cash", col) + L("cf", "FX translation of foreign cash", col), [pg("cf")])
        chk("Cash flows", f"{yr} closing cash agrees to statement of financial position",
            L("fp", "Cash and cash equivalents", col), L("cf", "Closing cash", col), [pg("cf"), pg("fp")])
        # --- notes
        chk("Notes", f"{yr} receivables note agrees to statement of financial position",
            L("fp", "Receivables", col), L("receivables", "Total", col), [pg("receivables"), pg("fp")])
        chk("Notes", f"{yr} payables note agrees to statement of financial position",
            L("fp", "Payables", col), L("payables", "Total", col), [pg("payables"), pg("fp")])
        chk("Units", f"{yr} units on issue rollforward (count)",
            L("units_count", "Closing", col),
            sum(L("units_count", k, col) for k in ["Opening", "Issued", "DRP", "Buyback"]), [pg("units_count")])
        chk("Units", f"{yr} issued units rollforward (value)",
            L("units_value", "Closing", col),
            sum(L("units_value", k, col) for k in ["Opening", "Issued", "DRP", "Buyback"]), [pg("units_value")])
        chk("Units", f"{yr} issued units (value) agree to statement of financial position",
            L("fp", "Issued units", col), L("units_value", "Closing", col), [pg("units_value"), pg("fp")])
        chk("Units", f"{yr} DRP in equity statement agrees to units note",
            L("ce", "Distributions reinvested", col), L("units_value", "DRP", col), [pg("ce"), pg("units_value")])
        chk("Units", f"{yr} buyback: equity statement = cash flow statement",
            L("ce", "Units buyback", col), L("cf", "Units buyback", col), [pg("ce"), pg("cf")])
        chk("Distributions", f"{yr} distributions note agrees to equity statement",
            -L("ce", "Distributions paid/payable", col), L("distributions", "Total", col), [pg("distributions"), pg("ce")])
        chk("Distributions", f"{yr} distribution payable = June distribution less June DRP",
            L("fp", "Distribution payable", col),
            L("distributions", "Distribution payable - June", col) + L("distributions", "DRP - June", col),
            [pg("distributions"), pg("fp")])
        chk("Distributions", f"{yr} DRP (equity) = DRP December + DRP June",
            L("ce", "Distributions reinvested", col),
            -(L("distributions", "DRP - December", col) + L("distributions", "DRP - June", col)), [pg("distributions"), pg("ce")])
        # fee note (whole dollars) vs statements (rounded)
        chk("Fees", f"{yr} fee note expense agrees to profit or loss",
            -L("pl", "Responsible entity fee and management fee", col),
            L("fees_note", "RE and management fee expense", col), [pg("fees_note"), pg("pl")], 1, H)
        chk("Fees", f"{yr} fee note payable agrees to payables note",
            L("payables", "Responsible entity and management fees payable", col),
            L("fees_note", "RE and management fee payable", col), [pg("fees_note"), pg("payables")], 1, H)
        chk("Fees", f"{yr} carried interest fee payable agrees to other expenses payable",
            L("payables", "Other expenses payable", col),
            L("fees_note", "Carried interest fee payable", col), [pg("fees_note"), pg("payables")], 1, H)

    # --- cross-year
    chk("Changes in equity", "FY26 opening equity = FY25 closing equity",
        L("fp", "Total unitholders' equity", 1), L("ce", "Opening equity", 0), [pg("ce"), pg("fp")])
    chk("Retained earnings", "FY25 retained earnings + FY26 profit - distributions = FY26 retained earnings",
        L("fp", "Retained earnings", 0),
        L("fp", "Retained earnings", 1) + L("pl", "Profit for the year", 0) + L("ce", "Distributions paid/payable", 0),
        [pg("fp"), pg("pl"), pg("ce")])
    chk("Cash flows", "FY26 distributions paid in cash = opening payable + (December distribution - December DRP)",
        -L("cf", "Distributions paid", 0),
        L("fp", "Distribution payable", 1) + L("distributions", "Distribution paid - December", 0)
        + L("distributions", "DRP - December", 0), [pg("cf"), pg("distributions"), pg("fp")])
    if Y:
        chk("Half-year", "HY: assets less liabilities = equity",
            L("fp", "Total unitholders' equity", d=Y), L("fp", "Total assets", d=Y) - L("fp", "Total liabilities", d=Y), [pg("fp", Y)])
        chk("Half-year", "HY: retained earnings = FY25 RE + H1 profit - December distribution",
            L("fp", "Retained earnings", d=Y),
            L("fp", "Retained earnings", 1) + L("pl", "Profit for the half-year", d=Y)
            - L("distributions", "Distribution paid - December", 0), [pg("fp", Y), pg("pl", Y), pg("distributions")])
        chk("Half-year", "HY: distribution payable = December distribution less December DRP",
            L("fp", "Distribution payable", d=Y),
            L("distributions", "Distribution paid - December", 0) + L("distributions", "DRP - December", 0),
            [pg("fp", Y), pg("distributions")], 2, H)
        chk("Half-year", "HY fee note expense agrees to half-year profit or loss",
            -L("pl", "Responsible entity fee and management fee", d=Y),
            L("fees_note", "RE and management fee expense", d=Y), [pg("fees_note", Y), pg("pl", Y)], 1, H)

    # --- NAV per unit (audited)
    nav = {yr: L("fp", "Total unitholders' equity", c) / L("units_count", "Closing", c) for c, yr in [(0, "FY26"), (1, "FY25")]}
    result = {"source": src, "checks": checks,
              "summary": {s: sum(1 for c in checks if c["status"] == s) for s in ["TIES", "TIES (rounding)", "BREAK"]},
              "audited_nav_per_unit": {k: round(v, 6) for k, v in nav.items()}}
    os.makedirs(a.out_dir, exist_ok=True)
    json.dump(result, open(os.path.join(a.out_dir, "tieout.json"), "w"), indent=2)

    wb = Workbook(); ws = wb.active; ws.title = "Tie-out"
    hdr = ["ID", "Area", "Check", "Expected", "Actual", "Difference", "Tolerance", "Status", "Source pages"]
    ws.append(["The Fund — financial statement tie-out workpaper (FY26 audited, FY25 comparative, HY26)"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append(["Prepared by agent pipeline · arithmetic only · requires senior fund accountant review"])
    ws.append([]); ws.append(hdr)
    for c in ws[4]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1B2430")
    for c in checks:
        ws.append([c["id"], c["area"], c["check"], c["expected"], c["actual"], c["difference"], c["tolerance"],
                   c["status"], "; ".join(c["refs"])])
        cell = ws.cell(row=ws.max_row, column=8)
        cell.font = Font(bold=True, color="0B6E4F" if c["status"].startswith("TIES") else "B42318")
    for i, w in enumerate([6, 18, 70, 16, 16, 12, 11, 16, 70], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for r in ws.iter_rows(min_row=5, min_col=4, max_col=7):
        for c in r:
            c.number_format = '#,##0.00;(#,##0.00);"-"'
    wb.save(os.path.join(a.out_dir, "Tieout_Workpaper.xlsx"))

    s = result["summary"]
    print(f"{len(checks)} checks · {s['TIES']} tie exactly · {s['TIES (rounding)']} tie within published rounding · "
          f"{s['BREAK']} breaks")
    for c in checks:
        if c["status"] != "TIES":
            print(f"  {c['id']} {c['status']:<16} {c['check']}  (diff {c['difference']:,.2f}, tol {c['tolerance']:,.2f})")
    print(f"Audited NAV per unit: FY26 {nav['FY26']:.4f} · FY25 {nav['FY25']:.4f}")


if __name__ == "__main__":
    main()
