#!/usr/bin/env python3
"""
Independently recompute a fund's fees from its disclosed terms and compare to
what was reported. Deterministic: every estimate states its method and inputs.

Tests
  F1  Management costs, half 1 — monthly NAV path x (aggregate rate / 12)
  F2  Management costs, half 2 — same, using published monthly NAVs where available
  F3  Year-end fee payable = one month's fee on June NAV (monthly in arrears)
  F4  Performance fee — hurdle test vs reported nil accrual; HWM dependency
  F5  Secondaries carried interest — half-year movement analysis

Usage:
  python3 fees.py --terms <terms.json> --extracted <extracted.json> --out-dir <dir> [--tolerance 0.025]
"""
import argparse, json, os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


def lin(a, b, n):  # n points strictly after a, ending at b
    return [a + (b - a) * (i + 1) / n for i in range(n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--terms", required=True)
    ap.add_argument("--extracted", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--tolerance", type=float, default=0.025)
    a = ap.parse_args()
    T = json.load(open(a.terms))["terms"]
    e = json.load(open(a.extracted))
    F, Y, M = e["fy"], e["hy"], e["monthly"]
    fl = lambda d, s, k, c=None: (d[s]["lines"][k][c] if c is not None else d[s]["lines"][k])

    rate = T["combined_fee_pa"]["value"]
    perf, hurdle = T["perf_fee_rate"]["value"], T["hurdle_pa"]["value"]
    tests, open_items = [], []

    # units path (month-end), interpolated between audited year-end counts
    u0, u1 = fl(F, "units_count", "Closing", 1), fl(F, "units_count", "Closing", 0)
    units = lin(u0, u1, 12)                                   # Jul-25 .. Jun-26
    nav25 = fl(F, "fp", "Total unitholders' equity", 1) / u0  # audited 30 Jun 2025
    dec_units = units[5]
    dec_dist = fl(F, "distributions", "Distribution paid - December", 0)
    nav_dec = fl(Y, "fp", "Total unitholders' equity") / dec_units
    jan = Y["subsequent_nav"]["nav_per_unit"]
    jun_cum = M["2026-06"]["nav_cum"]
    may = jun_cum / (1 + M["2026-06"]["return_1m"])
    ppu = lin(nav25, nav_dec, 6) + [jan] + lin(jan, may, 4) + [jun_cum]   # per-unit, Jul-25 .. Jun-26
    months = ["Jul-25", "Aug-25", "Sep-25", "Oct-25", "Nov-25", "Dec-25", "Jan-26", "Feb-26", "Mar-26", "Apr-26", "May-26", "Jun-26"]
    source = ["interpolated"] * 5 + ["half-year accounts"] + ["published (half-year report)"] + ["interpolated"] * 3 \
        + ["derived: Jun cum NAV / (1 + Jun return)", "published monthly report (cum)"]
    base = [p * u for p, u in zip(ppu, units)]
    base[5] += dec_dist                                          # fee base is before distributions
    fee = [b * rate / 12 for b in base]
    path = [{"month": m, "nav_per_unit": round(p, 4), "units": round(u), "fee_base": round(b, 2), "fee": round(f, 2), "source": s}
            for m, p, u, b, f, s in zip(months, ppu, units, base, fee, source)]

    rep_h1 = fl(Y, "fees_note", "RE and management fee expense")
    rep_fy = fl(F, "fees_note", "RE and management fee expense", 0)
    rep_h2 = rep_fy - rep_h1
    for tid, label, est, rep in [("F1", "Management costs H1 (Jul-Dec 2025)", sum(fee[:6]), rep_h1),
                                 ("F2", "Management costs H2 (Jan-Jun 2026)", sum(fee[6:]), rep_h2)]:
        var = rep - est
        pct = var / est
        st = "EXPLAINED" if abs(pct) <= a.tolerance else "UNEXPLAINED"
        tests.append({"id": tid, "test": label, "recomputed": round(est, 2), "reported": round(rep, 2),
                      "variance": round(var, 2), "variance_pct": round(pct, 4), "status": st,
                      "method": f"{rate:.2%} p.a. / 12 x month-end NAV before distributions; NAV path per 'NAV path' sheet",
                      "note": "Estimate: intra-period monthly NAVs partly interpolated. Close fully with the administrator's monthly fee schedule."})
    open_items.append({"id": "O1", "item": "Request the monthly management fee calculation schedule (fee base by month) "
                       "to replace interpolated NAVs in F1/F2.", "priority": "Low"})

    # F3 payable
    pay = fl(F, "fees_note", "RE and management fee payable", 0)
    exp_pay = fee[-1]
    implied_base = pay * 12 / rate
    var = pay - exp_pay
    tests.append({"id": "F3", "test": "Year-end fee payable = June fee (monthly in arrears)", "recomputed": round(exp_pay, 2),
                  "reported": round(pay, 2), "variance": round(var, 2), "variance_pct": round(var / exp_pay, 4),
                  "status": "EXPLAINED" if abs(var / exp_pay) <= a.tolerance else "UNEXPLAINED",
                  "method": "June fee on published June cum NAV x units",
                  "note": f"Payable implies a June fee base of {implied_base:,.0f} vs published cum NAV x units of {base[-1]:,.0f}."})

    # F4 performance fee
    nav26 = fl(F, "fp", "Total unitholders' equity", 0) / u1
    dpu = F["cents_per_unit_year"][0] / 100
    tr = (nav26 + dpu) / nav25 - 1
    excess = tr - hurdle
    open_nav = fl(F, "fp", "Total unitholders' equity", 1)
    indicative = max(0.0, perf * excess * open_nav)
    reported_pf = fl(F, "fees_note", "Performance fee payable", 0)
    tests.append({"id": "F4", "test": "Performance fee — hurdle test", "recomputed": round(indicative, 2),
                  "reported": reported_pf, "variance": round(reported_pf - indicative, 2),
                  "variance_pct": None, "status": "OPEN — HWM REQUIRED",
                  "method": f"Total return per unit incl. distributions {tr:.2%} vs hurdle {hurdle:.0%}; "
                            f"indicative fee = {perf:.0%} x excess x opening NAV if the HWM is not binding",
                  "note": "Nil accrual is correct only if NAV per unit remains below the high water mark. "
                          "The HWM and last payment period are not disclosed in the accounts."})
    open_items.append({"id": "O2", "item": "Request the high water mark schedule: HWM per unit, last performance fee payment "
                       "period, and capital-flow adjustments since. Confirms whether the nil performance fee is correct "
                       f"(indicative exposure if not binding: {indicative:,.0f}).", "priority": "High"})

    # F5 secondaries carry
    h1 = -fl(Y, "pl", "Secondaries management fee and carried interest fee")
    fy = -fl(F, "pl", "Secondaries management fee and carried interest fee", 0)
    h2 = fy - h1
    tests.append({"id": "F5", "test": "Secondaries mgmt fee & carried interest — H2 movement", "recomputed": None,
                  "reported": round(fy, 2), "variance": round(h2, 2), "variance_pct": None, "status": "QUERY",
                  "method": f"FY expense {fy:,.0f} less H1 expense {h1:,.0f} = H2 {h2:,.0f}",
                  "note": "H2 shows a net reversal of the carried interest accrual while the fund returned strongly. "
                          "Ask the manager for the secondaries carry calculation at 31 Dec and 30 Jun."})
    open_items.append({"id": "O3", "item": "Obtain the secondaries carried interest calculation at 31 Dec 2025 and "
                       "30 Jun 2026 to explain the H2 reversal.", "priority": "Medium"})

    res = {"terms_used": {"combined_fee_pa": rate, "perf_fee_rate": perf, "hurdle_pa": hurdle},
           "tests": tests, "nav_path": path, "open_items": open_items,
           "total_return_fy26": round(tr, 4), "audited_nav_per_unit": {"FY25": round(nav25, 6), "FY26": round(nav26, 6)}}
    os.makedirs(a.out_dir, exist_ok=True)
    json.dump(res, open(os.path.join(a.out_dir, "fees.json"), "w"), indent=2)

    wb = Workbook(); ws = wb.active; ws.title = "Fee tests"
    ws.append(["The Fund — independent fee recomputation (FY26)"]); ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Terms: aggregate fee {rate:.2%} p.a., performance fee {perf:.0%} over {hurdle:.0%} hurdle with HWM "
               "(from offer document extract)"]); ws.append([])
    hdr = ["ID", "Test", "Recomputed", "Reported", "Variance", "Variance %", "Status", "Method", "Note"]
    ws.append(hdr)
    for c in ws[4]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1B2430")
    for t in tests:
        ws.append([t["id"], t["test"], t["recomputed"], t["reported"], t["variance"], t["variance_pct"], t["status"], t["method"], t["note"]])
    for i, w in enumerate([5, 48, 15, 15, 14, 11, 22, 70, 80], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for r in ws.iter_rows(min_row=5, min_col=3, max_col=5):
        for c in r:
            c.number_format = '#,##0.00;(#,##0.00);"-"'
    for r in ws.iter_rows(min_row=5, min_col=6, max_col=6):
        for c in r:
            c.number_format = "0.00%"
    wp = wb.create_sheet("NAV path")
    wp.append(["Month", "NAV per unit", "Units", "Fee base", "Fee", "Source"])
    for p in path:
        wp.append([p["month"], p["nav_per_unit"], p["units"], p["fee_base"], p["fee"], p["source"]])
    for i, w in enumerate([10, 13, 14, 16, 13, 42], start=1):
        wp.column_dimensions[get_column_letter(i)].width = w
    wb.save(os.path.join(a.out_dir, "Fee_Recompute.xlsx"))

    for t in tests:
        pct = f"{t['variance_pct']:+.2%}" if t["variance_pct"] is not None else ""
        rc = f"{t['recomputed']:,.0f}" if t["recomputed"] is not None else "-"
        print(f"{t['id']} {t['test']:<55} recomputed {rc:>12}  reported {t['reported']:>12,.0f}  {pct:>8}  {t['status']}")
    print(f"FY26 total return per unit incl. distributions: {tr:.2%} (hurdle {hurdle:.0%})")


if __name__ == "__main__":
    main()
