#!/usr/bin/env python3
"""
Prepare a capital call (drawdown) under a fund's governing agreement.

Reads the call terms (call_terms.json from call_terms.py), the investor
register (xlsx) and the manager's drawdown instruction (pdf), then:
  - allocates each purpose on the key the agreement requires:
      portfolio investments   -> Remaining Commitment Percentage (eligible members)
      management / admin fees -> Invested Capital Percentage
      fund & org expenses     -> Capital Commitment Percentage
  - rounds to the cent with largest-remainder so every purpose ties exactly
  - tests the notice period in Business Days and proposes the earliest compliant due date
  - caps every member at its Remaining Capital Commitment
  - flags register conditions that change the answer (defaulting members,
    outstanding subsequent-closing equalisation, undefined allocation bases)
  - compares with a naive single-key (commitment %) allocation
  - drafts one Funding Notice per member, all marked DRAFT — NOT RELEASED

Usage:
  python3 capital_call.py --terms <call_terms.json> --register <register.xlsx>
      --instruction <instruction.pdf> --out-dir <dir>
"""
import argparse, datetime as dt, json, os, re
from decimal import Decimal, ROUND_DOWN
import pdfplumber
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
CAL = os.path.join(os.path.dirname(HERE), "references", "business_days_2026.json")
C = Decimal("0.01")


# ------------------------------------------------------------ business days
def load_calendar(path=CAL):
    c = json.load(open(path))
    return {dt.date.fromisoformat(d) for d in c["nyse_closed"] + c["fed_closed"]}, c.get("notes", {})


def is_bd(d, closed):
    return d.weekday() < 5 and d not in closed


def add_bd(d, n, closed):
    while n > 0:
        d += dt.timedelta(days=1)
        if is_bd(d, closed):
            n -= 1
    return d


def bd_between(a, b, closed):  # business days after a up to and including b
    n, d = 0, a
    while d < b:
        d += dt.timedelta(days=1)
        n += is_bd(d, closed)
    return n


# ------------------------------------------------------------ inputs
def read_register(path):
    wb = load_workbook(path, data_only=True)
    ws = wb["Register"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h).strip() for h in rows[0]]
    members = [dict(zip(hdr, r)) for r in rows[1:] if r[0]]
    fund = {str(r[0]).strip(): r[1] for r in wb["Fund"].iter_rows(values_only=True) if r[0]}
    return members, fund


def read_instruction(path):
    with pdfplumber.open(path) as pdf:
        t = "\n".join(p.extract_text() or "" for p in pdf.pages)
    g = lambda rx, f=str: f(re.search(rx, t).group(1).strip())
    money = lambda s: Decimal(s.replace(",", ""))
    date = lambda s: dt.datetime.strptime(s, "%d %B %Y").date()
    return {"call_no": g(r"Drawdown\s+No\.\s*(\d+)", int),
            "notice_date": g(r"Funding Notice date:\s*(\d{1,2} \w+ \d{4})", date),
            "requested_due": g(r"Requested Drawdown Due Date:\s*(\d{1,2} \w+ \d{4})", date),
            "pi": money(g(r"Portfolio Investment[^\n$]*\$\s*([\d,]+\.\d{2})")),
            "pi_name": g(r"Portfolio Investment\s*[—-]\s*([^\n$]+?)\s+\$"),
            "fees": money(g(r"Management fees[^\n$]*\$\s*([\d,]+\.\d{2})")),
            "expenses": money(g(r"Fund Expenses[^\n$]*\$\s*([\d,]+\.\d{2})")),
            "total": money(g(r"Total Drawdown\s*\$\s*([\d,]+\.\d{2})")),
            "account": g(r"Fund account:\s*([^\n]+)"),
            "nav_per_unit": money(g(r"NAV per Unit[^\n$]*\$\s*([\d.]+)")),
            "prime_rate": Decimal(g(r"Prime Rate[^\n]*?([\d.]+)%")) / 100}


def split(total, weights):
    """Largest-remainder allocation to the cent. weights: {id: Decimal >= 0}."""
    tw = sum(weights.values())
    if tw == 0:
        return {k: Decimal("0.00") for k in weights}
    raw = {k: total * w / tw for k, w in weights.items()}
    floor = {k: v.quantize(C, ROUND_DOWN) for k, v in raw.items()}
    left = int(((total - sum(floor.values())) / C).to_integral_value())
    for k in sorted(raw, key=lambda k: raw[k] - floor[k], reverse=True)[:left]:
        floor[k] += C
    return floor


# ------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--terms", required=True)
    ap.add_argument("--register", required=True)
    ap.add_argument("--instruction", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    T = json.load(open(a.terms))["terms"]
    members, fund = read_register(a.register)
    ins = read_instruction(a.instruction)
    closed, cal_notes = load_calendar()
    res = run(T, members, fund, ins, closed, cal_notes)
    out = os.path.join(a.out_dir, "capital_call")
    os.makedirs(os.path.join(out, "notices"), exist_ok=True)
    json.dump(res, open(os.path.join(out, "call.json"), "w"), indent=2, default=str)
    write_xlsx(res, os.path.join(out, f"Capital_Call_{ins['call_no']}_Workpaper.xlsx"))
    write_notices(res, os.path.join(out, "notices"))
    report(res)


def run(T, members, fund, ins, closed, cal_notes):
    D = lambda v: Decimal(str(v or 0))
    exc, checks = [], []
    ids = [m["ID"] for m in members]
    M = {m["ID"]: m for m in members}
    commit = {i: D(M[i]["Commitment"]) for i in ids}
    contrib = {i: D(M[i]["Contributed PI"]) + D(M[i]["Contributed Fees"]) + D(M[i]["Contributed Expenses"]) for i in ids}
    eq_due = {i: D(M[i].get("Equalisation Due")) for i in ids}
    status = {i: str(M[i].get("Status") or "Active") for i in ids}

    # --- register conditions
    defaulting = [i for i in ids if status[i].lower().startswith("defaulting")]
    for i in defaulting:
        exc.append({"id": "E3", "severity": "High", "member": i,
                    "issue": f"{i} status: {status[i]}. Under s.5.2(e) it may have no further right to "
                             "contribute to Portfolio Investments.",
                    "treatment": "Excluded from the Portfolio Investment allocation; still allocated fees and expenses. "
                                 "Confirm the Managing Members' election under s.5.2(e) before release."})
    subsequent = [i for i in ids if eq_due[i] > 0]
    for i in subsequent:
        exc.append({"id": "E2", "severity": "High", "member": i,
                    "issue": f"{i} was admitted at a Subsequent Closing and its equalisation payment under s.5.3(c) of "
                             f"{eq_due[i]:,.2f} is outstanding (due {M[i].get('Equalisation Due Date')}). Counting it as unfunded "
                             "overstates its Remaining Commitment Percentage.",
                    "treatment": "Remaining Capital Commitment reduced by the equalisation already demanded. Impact of "
                                 "not doing so is shown on the 'Equalisation impact' sheet. Release after equalisation is received."})
    exc.append({"id": "E4", "severity": "Medium", "member": "All",
                "issue": "Invested Capital Percentage includes each member's 'pro rata share' of subscription facility "
                         "drawings; the agreement does not define the basis of that share.",
                "treatment": "Capital Commitment Percentage used. Confirm with the Investment Manager."})

    def remaining(adjust_eq=True):
        return {i: commit[i] - contrib[i] - (eq_due[i] if adjust_eq else 0) for i in ids}

    def allocate(adjust_eq=True):
        rem = remaining(adjust_eq)
        eligible = {i: rem[i] for i in ids if i not in defaulting}
        pi = split(ins["pi"], eligible)
        pi.update({i: Decimal("0.00") for i in defaulting})
        fac = D(fund.get("Subscription facility drawn"))
        tc = sum(commit.values())
        # equalisation, once received, funds PI in the fund's historical mix
        pi_hist = sum(D(M[i]["Contributed PI"]) for i in ids)
        mix = pi_hist / sum(contrib.values())
        ic = {i: D(M[i]["Contributed PI"]) + (eq_due[i] * mix if adjust_eq else 0) + fac * commit[i] / tc for i in ids}
        fees = split(ins["fees"], ic)
        exp = split(ins["expenses"], commit)
        tot = {i: pi[i] + fees[i] + exp[i] for i in ids}
        return rem, ic, pi, fees, exp, tot

    rem, ic, pi, fees, exp, tot = allocate(True)
    rem_a, _, pi_a, fees_a, exp_a, tot_a = allocate(False)
    naive = split(ins["total"], commit)

    # --- notice period
    need = T["notice_business_days"]["value"]
    have = bd_between(ins["notice_date"], ins["requested_due"], closed)
    earliest = add_bd(ins["notice_date"], need, closed)
    skipped = [f"{d}: {n}" for d, n in cal_notes.items()
               if ins["notice_date"] < dt.date.fromisoformat(d) <= earliest]
    due = ins["requested_due"] if have >= need else earliest
    if have < need:
        exc.insert(0, {"id": "E1", "severity": "High", "member": "All",
                       "issue": f"Requested Drawdown Due Date {ins['requested_due']:%d %b %Y} gives {have} Business Days' notice; "
                                f"the agreement requires at least {need} (s.5.1(b)(i)).",
                       "treatment": f"Earliest compliant due date {earliest:%d %b %Y}. " +
                                    ("Non-business days in the window: " + "; ".join(skipped) if skipped else "")})

    # --- checks
    def ck(desc, ok, detail=""):
        checks.append({"check": desc, "status": "PASS" if ok else "FAIL", "detail": detail})
    ck("Portfolio Investment allocations sum to instruction", sum(pi.values()) == ins["pi"], f"{sum(pi.values()):,.2f}")
    ck("Management fee allocations sum to instruction", sum(fees.values()) == ins["fees"], f"{sum(fees.values()):,.2f}")
    ck("Fund expense allocations sum to instruction", sum(exp.values()) == ins["expenses"], f"{sum(exp.values()):,.2f}")
    ck("Purposes sum to Total Drawdown", ins["pi"] + ins["fees"] + ins["expenses"] == ins["total"], f"{ins['total']:,.2f}")
    over = [i for i in ids if tot[i] > rem[i]]
    ck("No member called above its Remaining Capital Commitment (s.5.1(a))", not over, ", ".join(over))
    ck(f"Notice period as instructed >= {need} Business Days", have >= need, f"{have} Business Days as instructed")
    ck(f"Notices drafted with a compliant due date", bd_between(ins["notice_date"], due, closed) >= need, f"{due:%d %b %Y}")
    ck("Each notice states date, account, purpose and amount (s.5.1(b)(ii) A-D)", True, "enforced by notice template")

    rows = []
    for i in ids:
        rows.append({"id": i, "investor": M[i]["Investor"], "type": M[i]["Type"], "status": status[i],
                     "commitment": commit[i], "contributed": contrib[i], "equalisation_due": eq_due[i],
                     "remaining_before": rem[i], "commitment_pct": commit[i] / sum(commit.values()),
                     "remaining_pct": (rem[i] / sum(rem[j] for j in ids if j not in defaulting)) if i not in defaulting else Decimal(0),
                     "invested_capital_pct": ic[i] / sum(ic.values()),
                     "pi": pi[i], "fees": fees[i], "expenses": exp[i], "total": tot[i],
                     "remaining_after": rem[i] - tot[i], "units": (tot[i] / ins["nav_per_unit"]).quantize(Decimal("0.001")),
                     "naive": naive[i], "naive_diff": naive[i] - tot[i],
                     "total_if_eq_ignored": tot_a[i], "eq_impact": tot_a[i] - tot[i]})
    return {"call_no": ins["call_no"], "instruction": ins, "due_date_used": due, "earliest_compliant": earliest,
            "notice_bd_given": have, "notice_bd_required": need, "rows": rows, "checks": checks, "exceptions": exc,
            "status": "DRAFT — NOT RELEASED", "terms_source": T.get("_source", "")}


# ------------------------------------------------------------ outputs
def write_xlsx(res, path):
    wb = Workbook()
    H = PatternFill("solid", fgColor="1B2430")
    money = '#,##0.00;(#,##0.00);"-"'

    def sheet(ws, hdr, data, widths, fmts):
        ws.append(hdr)
        for c in ws[ws.max_row]:
            c.font = Font(bold=True, color="FFFFFF"); c.fill = H
        for r in data:
            ws.append(r)
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for col, f in fmts.items():
            for row in ws.iter_rows(min_row=2, min_col=col, max_col=col):
                for c in row:
                    c.number_format = f

    ins = res["instruction"]
    ws = wb.active; ws.title = "Summary"
    for r in [[f"Capital Call {res['call_no']} — allocation workpaper"], [res["status"]], [],
              ["Funding Notice date", str(ins["notice_date"])], ["Requested due date", str(ins["requested_due"])],
              ["Due date used in notices", str(res["due_date_used"])],
              ["Business Days' notice (given / required)", f"{res['notice_bd_given']} / {res['notice_bd_required']}"],
              ["Portfolio Investment", float(ins["pi"])], ["Management fees", float(ins["fees"])],
              ["Fund Expenses", float(ins["expenses"])], ["Total Drawdown", float(ins["total"])],
              ["NAV per Unit for issuance", float(ins["nav_per_unit"])], [],
              ["Prepared by", "Agent pipeline"], ["Reviewed and approved by", "________________  Senior Fund Accountant"]]:
        ws.append(r)
    ws["A1"].font = Font(bold=True, size=13); ws.column_dimensions["A"].width = 42; ws.column_dimensions["B"].width = 30
    R = res["rows"]
    sheet(wb.create_sheet("Allocation"),
          ["ID", "Investor", "Status", "Commitment", "Remaining before", "Commitment %", "Remaining %", "Invested capital %",
           "Portfolio Investment", "Management fees", "Fund Expenses", "Total call", "Remaining after", "Units to issue"],
          [[r["id"], r["investor"], r["status"], float(r["commitment"]), float(r["remaining_before"]), float(r["commitment_pct"]),
            float(r["remaining_pct"]), float(r["invested_capital_pct"]), float(r["pi"]), float(r["fees"]), float(r["expenses"]),
            float(r["total"]), float(r["remaining_after"]), float(r["units"])] for r in R] +
          [["TOTAL", "", "", sum(float(r["commitment"]) for r in R), sum(float(r["remaining_before"]) for r in R), 1, 1, 1,
            sum(float(r["pi"]) for r in R), sum(float(r["fees"]) for r in R), sum(float(r["expenses"]) for r in R),
            sum(float(r["total"]) for r in R), sum(float(r["remaining_after"]) for r in R), sum(float(r["units"]) for r in R)]],
          [6, 34, 30, 15, 16, 12, 12, 14, 16, 15, 14, 15, 15, 14],
          {4: money, 5: money, 6: "0.000%", 7: "0.000%", 8: "0.000%", 9: money, 10: money, 11: money, 12: money, 13: money, 14: "#,##0.000"})
    sheet(wb.create_sheet("Naive vs agreement"),
          ["ID", "Investor", "Agreement allocation", "Single-key (commitment %)", "Difference"],
          [[r["id"], r["investor"], float(r["total"]), float(r["naive"]), float(r["naive_diff"])] for r in R],
          [6, 34, 20, 24, 16], {3: money, 4: money, 5: money})
    sheet(wb.create_sheet("Equalisation impact"),
          ["ID", "Investor", "Equalisation treated as demanded", "Equalisation ignored", "Difference"],
          [[r["id"], r["investor"], float(r["total"]), float(r["total_if_eq_ignored"]), float(r["eq_impact"])] for r in R],
          [6, 34, 28, 22, 16], {3: money, 4: money, 5: money})
    sheet(wb.create_sheet("Checks"), ["Check", "Status", "Detail"],
          [[c["check"], c["status"], c["detail"]] for c in res["checks"]], [70, 10, 40], {})
    sheet(wb.create_sheet("Exceptions"), ["ID", "Severity", "Member", "Issue", "Treatment"],
          [[e["id"], e["severity"], e["member"], e["issue"], e["treatment"]] for e in res["exceptions"]], [5, 10, 8, 90, 90], {})
    wb.save(path)


def write_notices(res, folder):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    ink = colors.HexColor("#1B2430")
    h1 = ParagraphStyle("h1", fontName="Times-Bold", fontSize=16, leading=20, textColor=ink)
    b = ParagraphStyle("b", fontName="Helvetica", fontSize=9, leading=12.5, textColor=ink, spaceAfter=6)
    s = ParagraphStyle("s", fontName="Helvetica", fontSize=7.5, leading=10, textColor=colors.HexColor("#5B6573"))
    red = ParagraphStyle("r", fontName="Helvetica-Bold", fontSize=9, textColor=colors.HexColor("#B42318"))
    ins = res["instruction"]
    for r in res["rows"]:
        if r["total"] == 0:
            continue
        path = os.path.join(folder, f"Funding_Notice_Call{res['call_no']}_{r['id']}.pdf")
        doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                                title=f"Funding Notice — Drawdown {res['call_no']} — {r['id']}")
        t = Table([["Purpose", "Allocation basis", "Amount (USD)"],
                   [f"Portfolio Investment — {ins['pi_name']}", "Remaining Commitment Percentage", f"{r['pi']:,.2f}"],
                   ["Management fees", "Invested Capital Percentage", f"{r['fees']:,.2f}"],
                   ["Fund Expenses (not attributable to a Portfolio Investment)", "Capital Commitment Percentage", f"{r['expenses']:,.2f}"],
                   ["Total Capital Contribution due", "", f"{r['total']:,.2f}"]], colWidths=(80 * mm, 55 * mm, 35 * mm))
        t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
                               ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8.5), ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.6, ink), ("LINEABOVE", (0, -1), (-1, -1), 0.6, ink)]))
        st = [Paragraph(f"{res['status']}", red), Spacer(1, 4), Paragraph(f"Funding Notice — Drawdown No. {res['call_no']}", h1),
              Paragraph(f"To: {r['investor']} ({r['id']})", b),
              Paragraph(f"Notice date: {ins['notice_date']:%d %B %Y} &nbsp;&nbsp; <b>Drawdown Due Date: {res['due_date_used']:%d %B %Y}</b>", b),
              Paragraph("Pursuant to Section 5.1(b) of the Limited Liability Company Agreement, you are required to make the Capital "
                        "Contribution below by wire transfer of immediately available funds, in U.S. dollars, on or before the "
                        "Drawdown Due Date.", b), t, Spacer(1, 8),
              Paragraph(f"<b>Pay to:</b> {ins['account']} &nbsp; <b>Reference:</b> CALL{res['call_no']}-{r['id']}", b),
              Paragraph(f"Commitment {r['commitment']:,.2f} · Remaining Capital Commitment before this Drawdown {r['remaining_before']:,.2f} · "
                        f"after {r['remaining_after']:,.2f}", b),
              Paragraph(f"Units will be issued on the Drawdown Due Date at the NAV per Unit as of the close of the last quarter "
                        f"(${ins['nav_per_unit']}), subject to adjustment: approximately {r['units']:,.3f} Units.", b),
              Spacer(1, 10), Paragraph("Failure to fund when due may result in the remedies set out in Section 5.2, including interest "
                                       "at the Default Rate.", s)]
        doc.build(st)


def report(res):
    ins = res["instruction"]
    print(f"Capital Call {res['call_no']}: total {ins['total']:,.2f} = PI {ins['pi']:,.2f} + fees {ins['fees']:,.2f} + expenses {ins['expenses']:,.2f}")
    print(f"Notice: {res['notice_bd_given']} Business Days given, {res['notice_bd_required']} required -> due date used {res['due_date_used']:%d %b %Y}")
    print(f"{'ID':<4} {'Investor':<34} {'PI':>14} {'Fees':>12} {'Expenses':>11} {'Total':>14} {'Naive diff':>12}")
    for r in res["rows"]:
        print(f"{r['id']:<4} {r['investor'][:34]:<34} {r['pi']:>14,.2f} {r['fees']:>12,.2f} {r['expenses']:>11,.2f} {r['total']:>14,.2f} {r['naive_diff']:>12,.2f}")
    for c in res["checks"]:
        print(f"  CHECK {c['status']:<4} {c['check']} {('— ' + c['detail']) if c['detail'] else ''}")
    for e in res["exceptions"]:
        print(f"  {e['id']} [{e['severity']}] {e['member']}: {e['issue']}")
    print(f"Notices drafted: {sum(1 for r in res['rows'] if r['total'] > 0)} — {res['status']}")


if __name__ == "__main__":
    main()
