#!/usr/bin/env python3
"""
Run a distribution through the fund agreement's waterfall, member by member.

Disposition Proceeds (s.6.2(b)(i)):  A return of capital -> B preferred return
  (IRR-style: rate compounded annually from each contribution's date, all prior
  distributions counted) -> C manager catch-up to X% of profit -> D split.
Current Proceeds (s.6.2(b)(ii)): preferred return -> catch-up -> split.
Then the fund-level cap: incentive attributable to Disposition Proceeds may not
exceed Y% of cumulative realized gains net of realized losses AND unrealized
depreciation (appreciation is ignored). Excess is withheld, not redirected.
Defaulting Members: amounts they owe may be offset against their distribution
(s.5.2(e)(i)) — shown gross and net, election required.

Every tier is rounded to the cent and the whole distribution ties exactly.

Usage:
  python3 waterfall.py --terms <waterfall_terms.json> --history <capital_account_history.xlsx>
      --instruction <distribution_instruction.pdf> --out-dir <dir>
      [--disposition <amount>]            what-if: override the exit proceeds
      [--sensitivity 20000000,30000000,45000000]
"""
import argparse, datetime as dt, json, os, re
from decimal import Decimal, ROUND_DOWN, getcontext
import pdfplumber
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

getcontext().prec = 34
C = Decimal("0.01")
q = lambda v: v.quantize(C)
Z = Decimal(0)


def split(total, w):
    tw = sum(w.values())
    raw = {k: total * v / tw for k, v in w.items()}
    fl = {k: v.quantize(C, ROUND_DOWN) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - fl[k], reverse=True)[:int((total - sum(fl.values())) / C)]:
        fl[k] += C
    return fl


def read_history(path):
    wb = load_workbook(path, data_only=True)
    rows = lambda s: [dict(zip([str(h) for h in r[0]], x)) for r in [list(wb[s].iter_rows(values_only=True))] for x in r[1:] if x[0]]
    flows = rows("Flows")
    for f in flows:
        f["Date"] = f["Date"].date() if isinstance(f["Date"], dt.datetime) else dt.date.fromisoformat(str(f["Date"]))
        f["Amount"] = Decimal(str(f["Amount"]))
    return flows, rows("Members"), rows("Apportionment")


def read_instruction(path):
    with pdfplumber.open(path) as pdf:
        t = "\n".join(p.extract_text() or "" for p in pdf.pages)
    money = lambda rx: Decimal(re.search(rx + r"[^$\n]*\$\s*([\d,]+\.\d{2})", t).group(1).replace(",", ""))
    d = re.search(r"Distribution designation date:\s*(\d{1,2} \w+ \d{4})", t).group(1)
    owed = {m.group(1): Decimal(m.group(2).replace(",", "")) for m in re.finditer(r"(I\d+)\s*\$\s*([\d,]+\.\d{2})\s*\(Drawdown", t)}
    owed_due = re.search(r"\(Drawdown \d+, due (\d{1,2} \w+ \d{4})\)", t)
    return {"date": dt.datetime.strptime(d, "%d %B %Y").date(),
            "investment": re.search(r"Disposition Proceeds\s*[—-]\s*([^\n$]+?)\s+\$", t).group(1).strip(),
            "disposition": money(r"Disposition Proceeds"), "cost": money(r"Cost basis"),
            "current": money(r"Current Proceeds"), "realized_gains": money(r"Cumulative realized capital gains"),
            "realized_losses": money(r"Cumulative realized capital losses"), "unreal_dep": money(r"Unrealized capital depreciation"),
            "unreal_app": money(r"Unrealized capital appreciation"), "prior_incentive": money(r"Incentive fees previously paid"),
            "owed": owed, "owed_due": dt.datetime.strptime(owed_due.group(1), "%d %B %Y").date() if owed_due else None,
            "prime": Decimal(re.search(r"Prime Rate[^\n]*?([\d.]+)%", t).group(1)) / 100}


def fv(a, d0, d1, r):
    return a * Decimal(str((1 + float(r)) ** ((d1 - d0).days / 365)))


def run(T, flows, members, appo, ins, disposition=None):
    P = disposition if disposition is not None else ins["disposition"]
    Q = ins["current"]
    r = Decimal(str(T["pref_rate"]["value"])); cu = Decimal(str(T["catch_up_pct"]["value"]))
    sm = Decimal(str(T["split_member_pct"]["value"])); si = Decimal(str(T["split_im_pct"]["value"]))
    cap_pct = Decimal(str(T["gains_cap_pct"]["value"])); D = ins["date"]
    ids = [m["ID"] for m in members]
    share = {a["Member"]: Decimal(str(a["Share"])) for a in appo if a["Investment"] == ins["investment"]}
    Pm, Qm = split(P, share), split(Q, share)
    out, exc = [], []
    for i in ids:
        fl = [f for f in flows if f["Member"] == i]
        contrib = sum(f["Amount"] for f in fl if f["Kind"] == "Contribution")
        prior_a = sum(f["Amount"] for f in fl if f["Kind"] == "Distribution" and f["Tier"] == "A")
        prior_b = sum(f["Amount"] for f in fl if f["Kind"] == "Distribution" and f["Tier"] in ("B", "ii(A)"))
        prior_c = Z
        required = sum(fv(f["Amount"], f["Date"], D, r) for f in fl if f["Kind"] == "Contribution") \
            - sum(fv(f["Amount"], f["Date"], D, r) for f in fl if f["Kind"] == "Distribution")
        p = Pm.get(i, Z)
        A = q(min(p, max(Z, contrib - prior_a)))
        B = q(min(p - A, max(Z, required - A)))
        rem = p - A - B
        Cc = q(min(rem, max(Z, (prior_b + B) * cu / (1 - cu) - prior_c)))
        rem2 = rem - Cc
        Dm = q(rem2 * sm); Di = rem2 - Dm
        # current proceeds (ii)
        qv = Qm.get(i, Z)
        pref_left = max(Z, required - A - B - Dm)
        iA = q(min(qv, pref_left)); remq = qv - iA
        iB = q(min(remq, max(Z, (prior_b + B + iA) * cu / (1 - cu) - prior_c - Cc)))
        remq2 = remq - iB; iCm = q(remq2 * sm); iCi = remq2 - iCm
        out.append({"id": i, "investor": next(m["Investor"] for m in members if m["ID"] == i),
                    "status": next(m["Status"] for m in members if m["ID"] == i), "share": share.get(i, Z),
                    "contributed": contrib, "capital_returned_before": prior_a, "prior_b": prior_b, "pref_required_at_date": q(max(Z, required)),
                    "disposition": p, "A": A, "B": B, "C_im": Cc, "D_member": Dm, "D_im": Di,
                    "current": qv, "iiA": iA, "iiB_im": iB, "iiC_member": iCm, "iiC_im": iCi,
                    "member_total": A + B + Dm + iA + iCm, "im_disposition": Cc + Di, "im_current": iB + iCi})
    # fund-level cap on incentive attributable to Disposition Proceeds
    net_gains = ins["realized_gains"] - ins["realized_losses"] - ins["unreal_dep"]
    cap = max(Z, q(cap_pct * net_gains - ins["prior_incentive"]))
    im_disp = sum(o["im_disposition"] for o in out)
    withheld = max(Z, im_disp - cap)
    if withheld > 0:
        cut = split(withheld, {o["id"]: o["im_disposition"] for o in out if o["im_disposition"] > 0})
        for o in out:
            o["im_withheld"] = cut.get(o["id"], Z); o["im_disposition_paid"] = o["im_disposition"] - o["im_withheld"]
        exc.append({"id": "W1", "severity": "High",
                    "issue": f"Incentive on Disposition Proceeds per tiers C and D is {im_disp:,.2f}; the cap is {cap_pct:.0%} of cumulative "
                             f"realized gains net of realized losses and unrealized depreciation = {cap_pct:.0%} x {net_gains:,.2f} = {cap:,.2f}. "
                             f"Unrealized appreciation ({ins['unreal_app']:,.2f}) does not count.",
                    "treatment": f"{withheld:,.2f} withheld from the Investment Manager. The agreement does not say where it goes: "
                                 "held pending Investment Manager / Board confirmation, not redistributed to Members."})
    else:
        for o in out:
            o["im_withheld"] = Z; o["im_disposition_paid"] = o["im_disposition"]
    for o in out:
        owed = ins["owed"].get(o["id"])
        if owed:
            interest = q(owed * (ins["prime"] + Decimal("0.04")) * (D - ins["owed_due"]).days / 365)
            o["offset"] = min(o["member_total"], owed + interest); o["offset_interest"] = interest
            exc.append({"id": "W3", "severity": "High",
                        "issue": f"{o['id']} is a Defaulting Member owing {owed:,.2f} plus Default Rate interest {interest:,.2f}.",
                        "treatment": f"s.5.2(e)(i) permits applying its distribution to amounts it owes: net {o['member_total'] - o['offset']:,.2f} "
                                     f"instead of {o['member_total']:,.2f}. Managing Members' election required; both shown."})
        else:
            o["offset"] = Z; o["offset_interest"] = Z
        o["member_net"] = o["member_total"] - o["offset"]
    exc.append({"id": "W2", "severity": "Medium",
                "issue": "The limit tying incentive to 'the percentage of the Disposition Proceeds actually distributed to Members' "
                         "does not state the percentage.", "treatment": "Not modelled. Confirm the intended test with the Investment Manager."})
    exc.append({"id": "W4", "severity": "Low", "issue": "Disposition and Current Proceeds are distributed on the same date; the order "
                "affects how the preferred return is counted 'without duplication'.",
                "treatment": "Disposition waterfall applied first, then Current Proceeds. Confirm the convention."})
    tot = lambda k: sum(o[k] for o in out)
    checks = [("Apportionment ties to Disposition Proceeds", sum(Pm.values()) == P),
              ("Apportionment ties to Current Proceeds", sum(Qm.values()) == Q),
              ("Members + Investment Manager + withheld = total proceeds",
               tot("member_total") + tot("im_disposition_paid") + tot("im_current") + tot("im_withheld") == P + Q),
              ("No member returned more capital than contributed", all(o["capital_returned_before"] + o["A"] <= o["contributed"] for o in out)),
              ("Incentive on Disposition Proceeds within the net-gains cap", tot("im_disposition_paid") <= cap),
              ("Catch-up never exceeds its share of cumulative profit",
               all(o["C_im"] <= (o["prior_b"] + o["B"]) * cu / (1 - cu) + C for o in out))]
    return {"date": D, "investment": ins["investment"], "disposition": P, "current": Q, "rows": out, "exceptions": exc,
            "cap": {"net_gains": net_gains, "cap": cap, "im_before_cap": im_disp, "withheld": withheld,
                    "realized_gains": ins["realized_gains"], "realized_losses": ins["realized_losses"],
                    "unrealized_depreciation": ins["unreal_dep"], "unrealized_appreciation_ignored": ins["unreal_app"]},
            "checks": [{"check": c, "status": "PASS" if ok else "FAIL"} for c, ok in checks],
            "totals": {k: tot(k) for k in ["A", "B", "C_im", "D_member", "D_im", "iiA", "iiB_im", "iiC_member", "iiC_im",
                                           "member_total", "im_disposition_paid", "im_current", "im_withheld", "offset"]},
            "status": "DRAFT — NOT RELEASED"}


def write_xlsx(res, sens, path):
    wb = Workbook(); H = PatternFill("solid", fgColor="1B2430"); money = '#,##0.00;(#,##0.00);"-"'

    def sheet(ws, hdr, data, widths):
        ws.append(hdr)
        for c in ws[ws.max_row]:
            c.font = Font(bold=True, color="FFFFFF"); c.fill = H
        for r in data:
            ws.append([float(x) if isinstance(x, Decimal) else x for x in r])
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for row in ws.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value, float):
                    c.number_format = money
    t = res["totals"]; cp = res["cap"]
    ws = wb.active; ws.title = "Summary"
    for r in [[f"Distribution waterfall — {res['investment']} — {res['date']}"], [res["status"]], [],
              ["Disposition Proceeds", res["disposition"]], ["Current Proceeds", res["current"]], [],
              ["A Return of capital (Members)", t["A"]], ["B Preferred return (Members)", t["B"]],
              ["C Catch-up (Investment Manager)", t["C_im"]], ["D Split — Members", t["D_member"]], ["D Split — Investment Manager", t["D_im"]],
              ["Current: preferred return (Members)", t["iiA"]], ["Current: catch-up (IM)", t["iiB_im"]],
              ["Current: split — Members", t["iiC_member"]], ["Current: split — IM", t["iiC_im"]], [],
              ["Incentive on Disposition Proceeds before cap", cp["im_before_cap"]], ["Cap (net gains basis)", cp["cap"]],
              ["Withheld from Investment Manager", cp["withheld"]], [],
              ["Total to Members (gross)", t["member_total"]], ["Offsets against Defaulting Members", t["offset"]],
              ["Total Investment Manager (paid)", t["im_disposition_paid"] + t["im_current"]], [],
              ["Prepared by", "Agent pipeline"], ["Reviewed and approved by", "________________  Senior Fund Accountant"]]:
        ws.append([float(x) if isinstance(x, Decimal) else x for x in r])
    ws["A1"].font = Font(bold=True, size=13); ws.column_dimensions["A"].width = 46; ws.column_dimensions["B"].width = 22
    for row in ws.iter_rows(min_row=4, min_col=2, max_col=2):
        for c in row:
            if isinstance(c.value, float):
                c.number_format = money
    R = res["rows"]
    sheet(wb.create_sheet("By member"),
          ["ID", "Investor", "Share", "Contributed", "Capital returned before", "6% required at date", "Disposition share",
           "A Capital", "B Pref", "C IM catch-up", "D Member", "D IM", "Current share", "ii(A) Pref", "ii(B) IM", "ii(C) Member",
           "ii(C) IM", "IM withheld", "Member gross", "Offset", "Member net"],
          [[o["id"], o["investor"], float(o["share"]), o["contributed"], o["capital_returned_before"], o["pref_required_at_date"],
            o["disposition"], o["A"], o["B"], o["C_im"], o["D_member"], o["D_im"], o["current"], o["iiA"], o["iiB_im"],
            o["iiC_member"], o["iiC_im"], o["im_withheld"], o["member_total"], o["offset"], o["member_net"]] for o in R],
          [5, 30, 8] + [15] * 18)
    sheet(wb.create_sheet("Cap test"), ["Item", "Amount"],
          [["Cumulative realized capital gains", cp["realized_gains"]], ["less cumulative realized capital losses", -cp["realized_losses"]],
           ["less unrealized capital depreciation", -cp["unrealized_depreciation"]], ["Net gains for the cap", cp["net_gains"]],
           ["Cap (20% of net gains, less prior incentive)", cp["cap"]], ["Incentive per tiers C and D", cp["im_before_cap"]],
           ["Withheld", cp["withheld"]], ["Unrealized appreciation (not counted)", cp["unrealized_appreciation_ignored"]]], [52, 20])
    if sens:
        sheet(wb.create_sheet("Sensitivity"), ["Exit proceeds", "Capital (A)", "Pref (B)", "IM before cap", "Cap", "IM paid", "Withheld", "Members total"],
              [[s["P"], s["A"], s["B"], s["im_before"], s["cap"], s["im_paid"], s["withheld"], s["members"]] for s in sens], [16] * 8)
    sheet(wb.create_sheet("Checks"), ["Check", "Status"], [[c["check"], c["status"]] for c in res["checks"]], [70, 10])
    sheet(wb.create_sheet("Exceptions"), ["ID", "Severity", "Issue", "Treatment"],
          [[e["id"], e["severity"], e["issue"], e["treatment"]] for e in res["exceptions"]], [5, 10, 100, 100])
    wb.save(path)


def write_statements(res, folder):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    ink = colors.HexColor("#1B2430")
    h1 = ParagraphStyle("h1", fontName="Times-Bold", fontSize=15, leading=19, textColor=ink)
    b = ParagraphStyle("b", fontName="Helvetica", fontSize=9, leading=12.5, textColor=ink, spaceAfter=5)
    red = ParagraphStyle("r", fontName="Helvetica-Bold", fontSize=9, textColor=colors.HexColor("#B42318"))
    os.makedirs(folder, exist_ok=True)
    for o in res["rows"]:
        rows = [["Tier", "Clause", "Amount (USD)"],
                ["Return of Capital Contributions", "6.2(b)(i)(A)", f"{o['A']:,.2f}"],
                ["Preferred Return", "6.2(b)(i)(B)", f"{o['B']:,.2f}"],
                ["90/10 — Member share", "6.2(b)(i)(D)", f"{o['D_member']:,.2f}"],
                ["Current Proceeds — Preferred Return", "6.2(b)(ii)(A)", f"{o['iiA']:,.2f}"],
                ["Current Proceeds — 90/10 Member share", "6.2(b)(ii)(C)", f"{o['iiC_member']:,.2f}"],
                ["Distribution (gross)", "", f"{o['member_total']:,.2f}"]]
        if o["offset"]:
            rows += [["Applied to amounts owed (s.5.2(e)(i)) — subject to election", "5.2(e)(i)", f"({o['offset']:,.2f})"],
                     ["Net distribution", "", f"{o['member_net']:,.2f}"]]
        t = Table(rows, colWidths=(95 * mm, 35 * mm, 40 * mm))
        t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
                               ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8.5), ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.6, ink), ("LINEABOVE", (0, -1), (-1, -1), 0.6, ink)]))
        doc = SimpleDocTemplate(os.path.join(folder, f"Distribution_Statement_{o['id']}.pdf"), pagesize=A4, leftMargin=20 * mm,
                                rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title=f"Distribution statement — {o['id']}")
        doc.build([Paragraph(res["status"], red), Spacer(1, 4), Paragraph("Distribution Statement", h1),
                   Paragraph(f"To: {o['investor']} ({o['id']}) &nbsp;·&nbsp; Distribution date: {res['date']:%d %B %Y} &nbsp;·&nbsp; "
                             f"Source: {res['investment']}", b),
                   Paragraph(f"Your share of proceeds from this investment: {float(o['share']):.4%} (by Capital Contributions in respect of it).", b),
                   t, Spacer(1, 8),
                   Paragraph(f"Capital Contributions to date {o['contributed']:,.2f} · capital returned before this distribution "
                             f"{o['capital_returned_before']:,.2f} · after {o['capital_returned_before'] + o['A']:,.2f}.", b)])


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _portable(path):
    """Record manifest inputs relative to the repo so they survive a clone."""
    absolute = os.path.abspath(path)
    try:
        rel = os.path.relpath(absolute, ROOT)
    except ValueError:
        return absolute
    return absolute if rel.startswith("..") else rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--terms", required=True); ap.add_argument("--history", required=True)
    ap.add_argument("--instruction", required=True); ap.add_argument("--out-dir", required=True)
    ap.add_argument("--disposition", type=Decimal); ap.add_argument("--sensitivity")
    a = ap.parse_args()
    T = json.load(open(a.terms))["terms"]
    flows, members, appo = read_history(a.history)
    ins = read_instruction(a.instruction)
    res = run(T, flows, members, appo, ins, a.disposition)
    sens = []
    for p in ([Decimal(x) for x in a.sensitivity.split(",")] if a.sensitivity else []):
        s = run(T, flows, members, appo, ins, p)
        sens.append({"P": p, "A": s["totals"]["A"], "B": s["totals"]["B"], "im_before": s["cap"]["im_before_cap"], "cap": s["cap"]["cap"],
                     "im_paid": s["totals"]["im_disposition_paid"], "withheld": s["cap"]["withheld"], "members": s["totals"]["member_total"]})
    out = os.path.join(a.out_dir, "waterfall"); os.makedirs(out, exist_ok=True)
    tag = "" if a.disposition is None else f"_whatif_{int(a.disposition)}"
    inputs = {k: _portable(getattr(a, k)) for k in ("terms", "history", "instruction")}
    json.dump(dict(res, sensitivity=sens, inputs=inputs), open(os.path.join(out, f"waterfall{tag}.json"), "w"), indent=2, default=str)
    write_xlsx(res, sens, os.path.join(out, f"Waterfall_Workpaper{tag}.xlsx"))
    if a.disposition is None:
        write_statements(res, os.path.join(out, "statements"))
    t, cp = res["totals"], res["cap"]
    print(f"Waterfall — {res['investment']} — {res['date']:%d %b %Y}: Disposition {res['disposition']:,.2f} + Current {res['current']:,.2f}")
    print(f"  A capital {t['A']:,.2f} · B pref {t['B']:,.2f} · C catch-up {t['C_im']:,.2f} · D members {t['D_member']:,.2f} / IM {t['D_im']:,.2f}")
    print(f"  Current: pref {t['iiA']:,.2f} · catch-up {t['iiB_im']:,.2f} · split members {t['iiC_member']:,.2f} / IM {t['iiC_im']:,.2f}")
    print(f"  Cap: 20% x net gains {cp['net_gains']:,.2f} = {cp['cap']:,.2f}; incentive before cap {cp['im_before_cap']:,.2f}; withheld {cp['withheld']:,.2f}")
    print(f"{'ID':<4} {'Investor':<30} {'Share':>8} {'A':>14} {'B':>13} {'D mbr':>12} {'Curr mbr':>11} {'Gross':>14} {'Net':>14}")
    for o in res["rows"]:
        print(f"{o['id']:<4} {o['investor'][:30]:<30} {float(o['share']):>8.3%} {o['A']:>14,.2f} {o['B']:>13,.2f} {o['D_member']:>12,.2f} "
              f"{o['iiA'] + o['iiC_member']:>11,.2f} {o['member_total']:>14,.2f} {o['member_net']:>14,.2f}")
    for c in res["checks"]:
        print(f"  CHECK {c['status']} {c['check']}")
    for e in res["exceptions"]:
        print(f"  {e['id']} [{e['severity']}] {e['issue']}")
    for s in sens:
        print(f"  WHAT-IF exit {s['P']:>14,.0f}: IM before cap {s['im_before']:>12,.2f} · cap {s['cap']:>12,.2f} · paid {s['im_paid']:>12,.2f} · withheld {s['withheld']:>12,.2f}")


if __name__ == "__main__":
    main()
