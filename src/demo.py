"""
The demo, which is the part most people actually read.

Runs every deterministic stage against the committed data room and prints a
transcript. It finishes BLOCKED, because nothing has been approved, and that is
the point of the whole repo.

No model is called. Extraction outputs are committed under data/extracted/,
which is what makes the arithmetic reproducible without an API key.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
EXTRACTED = os.path.join(DATA, "extracted")
DATAROOM = os.path.join(DATA, "dataroom")

RULE = 78


def _run(module: str, *args: str) -> None:
    cmd = [sys.executable, os.path.join(HERE, module), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit(f"{module} failed")


def _load(out: str, *parts: str) -> dict:
    with open(os.path.join(out, *parts)) as fh:
        return json.load(fh)


def _money(value) -> str:
    return f"{Decimal(str(value)):,.2f}"


def _line(tag: str, text: str) -> None:
    print(f"{tag:<19}{text}")


def main() -> int:
    work = tempfile.mkdtemp(prefix="fund-admin-agents-")
    try:
        print()
        print("fund-admin-agents · demo run")
        print("dataroom: data/dataroom/ · extraction outputs committed, no model calls")
        print()

        # 1 · terms, read from the committed extraction
        terms = _load(EXTRACTED, "terms.json")["terms"]
        fee = terms["combined_fee_pa"]
        _line("[1/5] terms", f"{fee['value']:.2%} p.a. aggregate, "
                             f"{terms['perf_fee_rate']['value']:.0%} performance over an "
                             f"{terms['hurdle_pa']['value']:.0%} hurdle")
        _line("", f"[offer document p.{fee['page']}]")

        # 2 · statement tie-out
        _run("tieout.py", "--extracted", os.path.join(EXTRACTED, "extracted.json"),
             "--out-dir", work)
        tie = _load(work, "tieout.json")
        summary = tie["summary"]
        _line("[2/5] tie-out", f"{len(tie['checks'])} checks · {summary['TIES']} exact · "
                               f"{summary['TIES (rounding)']} within published rounding · "
                               f"{summary['BREAK']} breaks")

        # 3 · fee recompute
        _run("fee_recompute.py",
             "--terms", os.path.join(EXTRACTED, "terms.json"),
             "--extracted", os.path.join(EXTRACTED, "extracted.json"),
             "--out-dir", work)
        fees = _load(work, "fees.json")
        rows = [t for t in fees["tests"] if t.get("variance_pct") is not None]
        movements = "   ".join(f"{t['id']} {t['variance_pct']:+.1%}" for t in rows)
        _line("[3/5] fees", f"management costs  {movements}")

        exposure = next((t for t in fees["tests"] if "hurdle" in t["test"].lower()), None)
        if exposure:
            outcome = exposure["status"].lower().replace(" — ", ", ").replace("hwm", "HWM")
            _line("", f"performance fee   {outcome}, exposure {_money(exposure['recomputed'])}")

        # 4 · capital call
        _run("capital_call.py",
             "--terms", os.path.join(EXTRACTED, "call_terms.json"),
             "--register", os.path.join(DATAROOM, "capital_call", "11_Investor_Register_2026-09-30.xlsx"),
             "--instruction", os.path.join(DATAROOM, "capital_call", "12_Drawdown_Instruction_Call7.pdf"),
             "--out-dir", work)
        call = _load(work, "capital_call", "call.json")
        _line("[4/5] capital call", f"due {call['due_date_used']}, not the requested "
                                    f"{call['instruction']['requested_due']}")
        _line("", f"{call['notice_bd_given']} business days' notice given against "
                  f"{call['notice_bd_required']} required. Columbus Day does not count.")

        worst = max(call["rows"], key=lambda r: Decimal(str(r.get("naive_diff", "0"))))
        _line("", f"a single commitment-% split over-calls {worst['id']} by "
                  f"{_money(worst['naive_diff'])}")

        # 5 · distribution waterfall
        _run("waterfall.py",
             "--terms", os.path.join(EXTRACTED, "waterfall_terms.json"),
             "--history", os.path.join(DATAROOM, "waterfall", "21_Capital_Account_History.xlsx"),
             "--instruction", os.path.join(DATAROOM, "waterfall", "22_Distribution_Instruction_Nov2026.pdf"),
             "--out-dir", work)
        fall = _load(work, "waterfall", "waterfall.json")
        cap = fall["cap"]
        _line("[5/5] waterfall", f"tiers pay the manager{'':>10}{_money(cap['im_before_cap'])}")
        _line("", f"incentive cap, 20% of net gains{'':>3}{_money(cap['cap'])}")
        _line("", f"withheld pending confirmation{'':>6}{_money(cap['withheld'])}")
        _line("", f"net gains exclude {_money(cap['unrealized_appreciation_ignored'])} "
                  f"of unrealised appreciation")

        # the gate
        print()
        status = _load(work, "capital_call", "call.json")["status"]
        _line("gate", f"BLOCKED: {status}")
        _line("", "nothing released, nothing sent")
        print()
        print("Approve with:")
        print("  python3 -m src.gate --out-dir outputs --stage capital_call \\")
        print('      --reviewer "Name, Title" --decision approve')
        print()
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
