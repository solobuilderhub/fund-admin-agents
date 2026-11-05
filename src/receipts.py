#!/usr/bin/env python3
"""
After the Drawdown Due Date: match bank receipts to Funding Notices, then run
the agreement's default timetable for anything short or unpaid.

Matching: (1) reference CALL<n>-<ID> and exact amount; (2) no reference but the
payer name matches the register and the amount is exact -> matched, flagged to
confirm; (3) equalisation receipts matched to amounts due. Anything else is
unidentified. Shortfalls get: written notice date, cure deadline (Business
Days per agreement), Default Rate interest, and the amended Funding Notice
amounts non-defaulting members would fund if the Managing Members designate a
default (allocated on the same keys, capped at Remaining Capital Commitment).

Usage:
  python3 receipts.py --call <call.json> --terms <call_terms.json> --bank <statement.csv>
      --register <register.xlsx> --out-dir <dir> [--as-of YYYY-MM-DD]
"""
import argparse, csv, datetime as dt, json, os, re, sys
from decimal import Decimal
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capital_call as cc  # noqa: E402

STOP = {"tt", "credit", "the", "of", "and", "fund", "plan", "company", "drawdown"}


def toks(s):
    return {t for t in re.findall(r"[a-z]{3,}", s.lower()) if t not in STOP}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--call", required=True); ap.add_argument("--terms", required=True)
    ap.add_argument("--bank", required=True); ap.add_argument("--register", required=True)
    ap.add_argument("--out-dir", required=True); ap.add_argument("--as-of")
    a = ap.parse_args()
    call = json.load(open(a.call)); T = json.load(open(a.terms))["terms"]
    members, fund = cc.read_register(a.register)
    closed, _ = cc.load_calendar()
    D = lambda v: Decimal(str(v))
    due = dt.date.fromisoformat(str(call["due_date_used"]))
    n = call["call_no"]
    rows = {r["id"]: r for r in call["rows"]}
    names = {m["ID"]: m["Investor"] for m in members}
    eq_due = {m["ID"]: D(m.get("Equalisation Due") or 0) for m in members}
    bank = list(csv.DictReader(open(a.bank)))
    as_of = dt.date.fromisoformat(a.as_of) if a.as_of else max(dt.date.fromisoformat(b["Date"]) for b in bank)

    paid = {i: Decimal(0) for i in rows}
    matches, unidentified, eq_rec = [], [], {}
    for b in bank:
        if not b["Amount"] or D(b["Amount"]) <= 0:
            continue
        amt, ref, desc = D(b["Amount"]), b["Reference"], b["Description"]
        m = re.search(rf"CALL{n}-(I\d+)", ref)
        if m:
            i = m.group(1); paid[i] += amt
            ok = amt == D(rows[i]["total"])
            matches.append({"date": b["Date"], "member": i, "amount": amt, "basis": "reference",
                            "status": "MATCHED" if ok else "PART PAYMENT", "note": "" if ok else f"expected {D(rows[i]['total']):,.2f}"})
            continue
        m = re.search(r"EQUALISATION (I\d+)", ref)
        if m and eq_due.get(m.group(1), 0) == amt:
            eq_rec[m.group(1)] = (b["Date"], amt)
            matches.append({"date": b["Date"], "member": m.group(1), "amount": amt, "basis": "equalisation reference",
                            "status": "EQUALISATION RECEIVED", "note": "s.5.3(c)"})
            continue
        cands = [i for i in rows if toks(names[i]) & toks(desc + " " + ref) and D(rows[i]["total"]) == amt]
        if len(cands) == 1:
            i = cands[0]; paid[i] += amt
            matches.append({"date": b["Date"], "member": i, "amount": amt, "basis": "payer name + exact amount",
                            "status": "MATCHED — CONFIRM", "note": f"no call reference; payer '{desc}'. Confirm with investor."})
        else:
            unidentified.append({"date": b["Date"], "description": desc, "reference": ref, "amount": amt})

    notice = cc.add_bd(due, 1, closed)
    cure = cc.add_bd(notice, T["default_cure_business_days"]["value"], closed)
    prime = D(call["instruction"]["prime_rate"])
    rate = prime + Decimal("0.04")
    days = (as_of - due).days
    shortfalls, total_short = [], Decimal(0)
    for i, r in rows.items():
        s = D(r["total"]) - paid[i]
        if s > 0:
            total_short += s
            shortfalls.append({"member": i, "investor": names[i], "called": D(r["total"]), "received": paid[i], "shortfall": s,
                               "written_notice": notice, "cure_deadline": cure,
                               "default_interest_to_as_of": (s * rate * days / 365).quantize(Decimal("0.01")),
                               "status": "UNPAID" if paid[i] == 0 else "PART PAID"})
    # amended Funding Notice if all shortfalls are designated defaults (s.5.2(b)) — same keys, capped
    non_def = [i for i in rows if i not in {s["member"] for s in shortfalls} and not rows[i]["status"].lower().startswith("defaulting")]
    amended = {}
    if shortfalls and non_def:
        pi_s = sum(D(rows[s["member"]]["pi"]) * s["shortfall"] / D(rows[s["member"]]["total"]) for s in shortfalls).quantize(Decimal("0.01"))
        fee_s = sum(D(rows[s["member"]]["fees"]) * s["shortfall"] / D(rows[s["member"]]["total"]) for s in shortfalls).quantize(Decimal("0.01"))
        exp_s = total_short - pi_s - fee_s
        a1 = cc.split(pi_s, {i: D(rows[i]["remaining_after"]) for i in non_def})
        a2 = cc.split(fee_s, {i: D(rows[i]["invested_capital_pct"]) for i in non_def})
        a3 = cc.split(exp_s, {i: D(rows[i]["commitment_pct"]) for i in non_def})
        amended = {i: {"pi": a1[i], "fees": a2[i], "expenses": a3[i], "total": a1[i] + a2[i] + a3[i],
                       "within_remaining": a1[i] + a2[i] + a3[i] <= D(rows[i]["remaining_after"])} for i in non_def}
    pay_by = cc.add_bd(cure, T["amended_notice_business_days"]["value"], closed) if shortfalls else None

    res = {"call_no": n, "due_date": due, "as_of": as_of, "matches": matches, "unidentified": unidentified,
           "equalisation_received": eq_rec, "shortfalls": shortfalls,
           "default_rate": {"rate": rate, "basis": f"Prime {prime:.2%} + 4.00% (lesser of that and the legal maximum; "
                                                   "legal maximum not assessed). Day count not specified in the agreement: actual/365 assumed."},
           "amended_notice": {"if_designated_on": cure, "payable_by": pay_by, "allocations": amended},
           "status": "DRAFT — NO NOTICES SENT"}
    out = os.path.join(a.out_dir, "capital_call"); os.makedirs(out, exist_ok=True)
    json.dump(res, open(os.path.join(out, "receipts.json"), "w"), indent=2, default=str)
    write_xlsx(res, os.path.join(out, f"Capital_Call_{n}_Receipts_and_Defaults.xlsx"))

    print(f"Receipts as of {as_of:%d %b %Y} for Drawdown {n} (due {due:%d %b %Y})")
    for m in matches:
        print(f"  {m['date']} {m['member']:<4} {m['amount']:>14,.2f}  {m['status']:<22} {m['basis']}  {m['note']}")
    for u in unidentified:
        print(f"  UNIDENTIFIED {u['date']} {u['amount']:,.2f} {u['description']} {u['reference']}")
    for s in shortfalls:
        print(f"  SHORTFALL {s['member']} {s['status']}: {s['shortfall']:,.2f} · written notice {s['written_notice']:%d %b} · "
              f"cure by {s['cure_deadline']:%d %b %Y} · default interest to date {s['default_interest_to_as_of']:,.2f} @ {rate:.2%}")
    if amended:
        print(f"  If designated on {cure:%d %b %Y}: amended Funding Notice to {len(amended)} members, payable by {pay_by:%d %b %Y}; "
              f"all within Remaining Capital Commitment: {all(v['within_remaining'] for v in amended.values())}")


def write_xlsx(res, path):
    wb = Workbook(); H = PatternFill("solid", fgColor="1B2430"); money = '#,##0.00;(#,##0.00);"-"'

    def sheet(ws, hdr, data, widths):
        ws.append(hdr)
        for c in ws[ws.max_row]:
            c.font = Font(bold=True, color="FFFFFF"); c.fill = H
        for r in data:
            ws.append([float(x) if isinstance(x, Decimal) else (str(x) if isinstance(x, dt.date) else x) for x in r])
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for row in ws.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value, float):
                    c.number_format = money
    ws = wb.active; ws.title = "Receipts"
    sheet(ws, ["Date", "Member", "Amount", "Status", "Match basis", "Note"],
          [[m["date"], m["member"], m["amount"], m["status"], m["basis"], m["note"]] for m in res["matches"]] +
          [[u["date"], "?", u["amount"], "UNIDENTIFIED", "", f"{u['description']} {u['reference']}"] for u in res["unidentified"]],
          [12, 8, 16, 24, 26, 70])
    sheet(wb.create_sheet("Shortfalls & default"), ["Member", "Investor", "Called", "Received", "Shortfall", "Status",
                                                    "Written notice", "Cure deadline", "Default interest to date"],
          [[s["member"], s["investor"], s["called"], s["received"], s["shortfall"], s["status"], s["written_notice"],
            s["cure_deadline"], s["default_interest_to_as_of"]] for s in res["shortfalls"]], [8, 30, 15, 15, 15, 12, 14, 14, 20])
    an = res["amended_notice"]
    sheet(wb.create_sheet("Amended notice (if designated)"), ["Member", "Portfolio Investment", "Fees", "Expenses", "Total", "Within remaining"],
          [[i, v["pi"], v["fees"], v["expenses"], v["total"], "YES" if v["within_remaining"] else "NO"] for i, v in an["allocations"].items()],
          [8, 20, 14, 14, 16, 16])
    ws = wb.create_sheet("Basis")
    for r in [["Default Rate", f"{res['default_rate']['rate']:.2%}"], ["Basis", res["default_rate"]["basis"]],
              ["Designation possible from", str(an["if_designated_on"])], ["Amended notice payable by", str(an["payable_by"])],
              ["Status", res["status"]]]:
        ws.append(r)
    ws.column_dimensions["A"].width = 28; ws.column_dimensions["B"].width = 110
    wb.save(path)


if __name__ == "__main__":
    main()
