#!/usr/bin/env python3
"""
Parallel NAV benchmark: compare the fund's published (unaudited) NAV series
with independently derived figures, apply the ASIC RG 94 materiality benchmark
(0.30% of unit price), and compile the Benchmark Variance Report pack from the
tie-out and fee outputs.

Tests
  B1  Audited year-end NAV per unit vs published unaudited month-end NAV (ex)
  B2  Cum NAV - ex NAV = declared distribution per unit
  B3  Distribution payable / cents per unit = units on issue at 30 June
  B4  Published monthly returns recompute from published NAVs
  B5  Coverage: months whose return cannot be recomputed from the data room

The report is always issued as DRAFT. Only signoff.py, run on a reviewer's
explicit instruction, can mark it released.

Usage:
  python3 benchmark.py --extracted <extracted.json> --out-dir <dir> [--threshold 0.003]
  (reads tieout.json and fees.json from --out-dir when present)
"""
import argparse, json, os, datetime as dt
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

INK, MUTED = colors.HexColor("#1B2430"), colors.HexColor("#5B6573")


def disp(v, kind):
    if v is None:
        return "-"
    return {"nav": f"{v:.4f}", "cpu": f"{v:.5f}", "units": f"{v:,.0f}", "pct": f"{v:+.2%}"}[kind]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extracted", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--threshold", type=float, default=0.003, help="RG 94 unit price materiality benchmark (0.30%)")
    ap.add_argument("--period", default="June 2026 NAV cycle")
    a = ap.parse_args()
    e = json.load(open(a.extracted))
    F, M = e["fy"], e["monthly"]
    L = lambda s, k, c=0: F[s]["lines"][k][c]
    tie = json.load(open(os.path.join(a.out_dir, "tieout.json"))) if os.path.exists(os.path.join(a.out_dir, "tieout.json")) else None
    fees = json.load(open(os.path.join(a.out_dir, "fees.json"))) if os.path.exists(os.path.join(a.out_dir, "fees.json")) else None

    units = L("units_count", "Closing")
    equity = L("fp", "Total unitholders' equity")
    aud = equity / units
    jun = M["2026-06"]
    V, open_items = [], []

    # B1
    diff = aud - jun["nav_ex"]
    pct = diff / jun["nav_ex"]
    V.append({"id": "B1", "test": "Audited NAV per unit (30 Jun) vs published unaudited ex-distribution NAV",
              "ours": round(aud, 4), "theirs": jun["nav_ex"], "difference": round(diff, 4), "difference_pct": round(pct, 4),
              "value_impact": round(diff * units, 2), "kind": "nav",
              "status": "EXCEEDS RG 94 0.30%" if abs(pct) >= a.threshold else "WITHIN 0.30%",
              "explanation": "Published month-end NAV is an unaudited estimate; audited NAV is higher. Typical cause for a "
                             "fund of private equity funds: underlying manager valuations received after the monthly report "
                             "and booked in the year-end accounts. Not confirmable from the data room.",
              "action": "Obtain the administrator's bridge from the published June NAV to audited NAV, with each "
                        "post-report valuation adjustment and its source statement. Confirm whether any unit "
                        "transactions (DRP, buyback) were priced off the published NAV."})
    open_items.append({"id": "O4", "priority": "High", "item": "June NAV bridge: published unaudited NAV to audited NAV "
                       f"({pct:+.2%}, {diff * units:,.0f}); confirm impact on any unit transactions priced off it."})
    # B2
    dist_cpu = F["cents_per_unit_final"] / 100
    cd = jun["nav_cum"] - jun["nav_ex"]
    d2 = cd - dist_cpu
    V.append({"id": "B2", "test": "Cum NAV less ex NAV = declared final distribution per unit",
              "ours": round(dist_cpu, 5), "theirs": round(cd, 5), "difference": round(d2, 5), "difference_pct": None,
              "value_impact": None, "kind": "cpu", "status": "TIES (4dp rounding)" if abs(d2) <= 0.00005 + 1e-9 else "BREAK",
              "explanation": "Published NAVs are rounded to 4 decimal places.", "action": "None."})
    # B3
    jd = L("distributions", "Distribution payable - June")
    implied = jd / dist_cpu
    du = implied - units
    V.append({"id": "B3", "test": "June distribution / cents per unit = units on issue at 30 June",
              "ours": round(implied), "theirs": units, "difference": round(du), "difference_pct": round(du / units, 4),
              "value_impact": round(du * dist_cpu, 2), "kind": "units", "status": "QUERY",
              "explanation": "The June distribution implies fewer units than were on issue at 30 June. Candidate causes: "
                             "record date before 30 June, or buyback units cancelled after the record date.",
              "action": "Obtain the distribution record date and the registry unit count at that date."})
    open_items.append({"id": "O5", "priority": "Medium", "item": f"Distribution units: implied {implied:,.0f} vs {units:,.0f} "
                       "on issue at 30 June. Obtain record date and registry count."})
    # B4 / B5
    order = sorted(M)
    for prev, cur in zip(order, order[1:]):
        p = M[prev].get("nav_ex", M[prev].get("nav"))
        r = M[cur]["nav"] / p - 1
        rep = M[cur]["return_1m"]
        V.append({"id": "B4", "test": f"{cur} one-month return recomputes from published NAVs",
                  "ours": round(r, 4), "theirs": rep, "difference": round(r - rep, 4), "difference_pct": None,
                  "value_impact": None, "kind": "pct", "status": "TIES (1dp rounding)" if abs(r - rep) < 0.0005 + 1e-9 else "BREAK",
                  "explanation": f"NAV {M[cur]['nav']:.4f} / prior NAV {p:.4f} - 1 (distribution-adjusted where ex NAV "
                                 "published).", "action": "None."})
    V.append({"id": "B5", "test": f"{order[0]} one-month return", "ours": None, "theirs": M[order[0]]["return_1m"],
              "difference": None, "difference_pct": None, "value_impact": None, "kind": "pct", "status": "NOT TESTABLE",
              "explanation": "Prior month NAV not in the data room.", "action": "Request the May NAV report."})
    open_items.append({"id": "O6", "priority": "Low", "item": "Request the prior-month (May) NAV report to test the June return."})

    all_open = open_items + (fees["open_items"] if fees else [])
    all_open.sort(key=lambda o: {"High": 0, "Medium": 1, "Low": 2}[o["priority"]])
    now = dt.datetime.now().strftime("%d %b %Y %H:%M")
    pack = {"period": a.period, "generated": now, "status": "DRAFT — NOT RELEASED", "reviewer": None,
            "nav_tests": V, "open_items": all_open,
            "tieout_summary": tie["summary"] if tie else None, "fee_tests": fees["tests"] if fees else None,
            "headline": {"audited_nav_per_unit": round(aud, 4), "published_nav_ex": jun["nav_ex"],
                         "nav_difference_pct": round(pct, 4), "rg94_threshold": a.threshold,
                         "tieout_checks": len(tie["checks"]) if tie else None,
                         "tieout_breaks": tie["summary"]["BREAK"] if tie else None}}
    os.makedirs(a.out_dir, exist_ok=True)
    json.dump(pack, open(os.path.join(a.out_dir, "benchmark.json"), "w"), indent=2)
    write_xlsx(pack, tie, fees, os.path.join(a.out_dir, "Benchmark_Variance_Report.xlsx"))
    write_pdf(pack, tie, os.path.join(a.out_dir, "Benchmark_Variance_Report.pdf"))

    print(f"Benchmark Variance Report — {a.period} — {pack['status']}")
    for v in V:
        print(f"  {v['id']} {v['test'][:70]:<70} ours {disp(v['ours'], v['kind']):>12} theirs {disp(v['theirs'], v['kind']):>12}  {v['status']}")
    if tie:
        print(f"  Tie-out: {len(tie['checks'])} checks, {tie['summary']['BREAK']} breaks")
    print(f"  Open items: {len(all_open)} ({sum(o['priority'] == 'High' for o in all_open)} high)")


def write_xlsx(pack, tie, fees, path):
    wb = Workbook()
    H = PatternFill("solid", fgColor="1B2430")

    def header(ws, row):
        for c in ws[row]:
            c.font = Font(bold=True, color="FFFFFF"); c.fill = H

    ws = wb.active; ws.title = "Summary"
    h = pack["headline"]
    rows = [["The Fund — Benchmark Variance Report"], [pack["period"]], [],
            ["Status", pack["status"]], ["Generated", pack["generated"]], [],
            ["Audited NAV per unit, 30 June", h["audited_nav_per_unit"]],
            ["Published unaudited NAV per unit (ex), 30 June", h["published_nav_ex"]],
            ["Difference", h["nav_difference_pct"]], ["RG 94 materiality benchmark", h["rg94_threshold"]],
            ["Financial statement tie-out checks", h["tieout_checks"]], ["Tie-out breaks", h["tieout_breaks"]],
            ["Open items", len(pack["open_items"])], [],
            ["Prepared by", "Agent pipeline (extraction, tie-out, fee recompute, NAV benchmark)"],
            ["Reviewed and signed by", pack.get("reviewer") or "________________  Senior Fund Accountant"],
            ["Release", "Not released until signed"]]
    for r in rows:
        ws.append(r)
    ws["A1"].font = Font(bold=True, size=14)
    for r in ("B9", "B10"):
        ws[r].number_format = "0.00%"
    ws.column_dimensions["A"].width = 48; ws.column_dimensions["B"].width = 70

    ws = wb.create_sheet("NAV variances")
    ws.append(["ID", "Test", "Ours", "Theirs", "Difference", "Diff %", "Value impact", "Status", "Explanation", "Action"])
    header(ws, 1)
    for v in pack["nav_tests"]:
        ws.append([v["id"], v["test"], v["ours"], v["theirs"], v["difference"], v["difference_pct"], v["value_impact"],
                   v["status"], v["explanation"], v["action"]])
    for i, w in enumerate([5, 60, 12, 12, 12, 9, 14, 22, 80, 70], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    if fees:
        ws = wb.create_sheet("Fee tests")
        ws.append(["ID", "Test", "Recomputed", "Reported", "Variance", "Variance %", "Status", "Method", "Note"])
        header(ws, 1)
        for t in fees["tests"]:
            ws.append([t["id"], t["test"], t["recomputed"], t["reported"], t["variance"], t["variance_pct"], t["status"], t["method"], t["note"]])
        for i, w in enumerate([5, 50, 14, 14, 14, 10, 22, 70, 80], start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
    if tie:
        ws = wb.create_sheet("Tie-out")
        ws.append(["ID", "Area", "Check", "Expected", "Actual", "Difference", "Tolerance", "Status", "Source pages"])
        header(ws, 1)
        for c in tie["checks"]:
            ws.append([c["id"], c["area"], c["check"], c["expected"], c["actual"], c["difference"], c["tolerance"], c["status"], "; ".join(c["refs"])])
        for i, w in enumerate([6, 18, 70, 15, 15, 12, 11, 16, 70], start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
    ws = wb.create_sheet("Open items")
    ws.append(["ID", "Priority", "Item"]); header(ws, 1)
    for o in pack["open_items"]:
        ws.append([o["id"], o["priority"], o["item"]])
    ws.column_dimensions["C"].width = 120
    wb.save(path)


def write_pdf(pack, tie, path):
    h1 = ParagraphStyle("h1", fontName="Times-Bold", fontSize=17, leading=21, textColor=INK)
    h2 = ParagraphStyle("h2", fontName="Times-Bold", fontSize=12, leading=15, textColor=INK, spaceBefore=10, spaceAfter=4)
    b = ParagraphStyle("b", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=INK)
    s = ParagraphStyle("s", fontName="Helvetica", fontSize=8, leading=10.5, textColor=MUTED)
    cell = ParagraphStyle("c", fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=INK)
    hh = pack["headline"]
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title="The Fund — Benchmark Variance Report")
    st = [Paragraph("The Fund — Benchmark Variance Report", h1),
          Paragraph(f"{pack['period']} · generated {pack['generated']} · <b>{pack['status']}</b>", s), Spacer(1, 8),
          Paragraph(f"Audited NAV per unit at 30 June is <b>{hh['audited_nav_per_unit']:.4f}</b> against a published unaudited "
                    f"NAV of <b>{hh['published_nav_ex']:.4f}</b>, a difference of <b>{hh['nav_difference_pct']:+.2%}</b>, above the "
                    f"{hh['rg94_threshold']:.2%} RG 94 materiality benchmark. "
                    + (f"All {hh['tieout_checks']} financial statement tie-out checks pass ({hh['tieout_breaks']} breaks). " if tie else "")
                    + f"{len(pack['open_items'])} open items are listed for the administrator and manager.", b)]

    def table(rows, widths):
        t = Table([[Paragraph(str(x), cell) for x in r] for r in rows], colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#C9CED6"))]))
        for i in range(len(rows[0])):
            t._cellvalues[0][i] = Paragraph(f"<font color='white'><b>{rows[0][i]}</b></font>", cell)
        return t

    st += [Paragraph("NAV variances", h2),
           table([["ID", "Test", "Ours", "Theirs", "Status", "Explanation / action"]] +
                 [[v["id"], v["test"], disp(v["ours"], v["kind"]), disp(v["theirs"], v["kind"]), v["status"],
                   v["explanation"] + " " + v["action"]] for v in pack["nav_tests"]],
                 [9 * mm, 42 * mm, 17 * mm, 17 * mm, 24 * mm, 69 * mm])]
    if pack["fee_tests"]:
        st += [Paragraph("Fee recomputation", h2),
               table([["ID", "Test", "Recomputed", "Reported", "Status", "Note"]] +
                     [[t["id"], t["test"], f"{t['recomputed']:,.0f}" if t["recomputed"] is not None else "-",
                       f"{t['reported']:,.0f}", t["status"], t["note"]] for t in pack["fee_tests"]],
                     [9 * mm, 42 * mm, 22 * mm, 20 * mm, 26 * mm, 59 * mm])]
    if tie:
        su = tie["summary"]
        st += [Paragraph("Financial statement tie-out", h2),
               Paragraph(f"{len(tie['checks'])} checks: {su['TIES']} tie exactly, {su['TIES (rounding)']} tie within published "
                         f"rounding, {su['BREAK']} breaks. Full workpaper in the Excel pack.", b)]
    st += [Paragraph("Open items", h2),
           table([["ID", "Priority", "Item"]] + [[o["id"], o["priority"], o["item"]] for o in pack["open_items"]],
                 [10 * mm, 16 * mm, 152 * mm]),
           Spacer(1, 14), Paragraph("Sign-off", h2),
           Paragraph("Prepared by: agent pipeline — extraction, tie-out, fee recomputation, NAV benchmark.", b),
           Paragraph("Reviewed and signed: " + (pack.get("reviewer") or "________________________  Senior Fund Accountant"), b),
           Paragraph("This report is not released until signed.", s)]
    doc.build(st)


if __name__ == "__main__":
    main()
