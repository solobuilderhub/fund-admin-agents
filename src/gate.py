"""
Release gate.

Every stage writes its manifest with status DRAFT and drafts its release
artefacts without sending anything. Promotion to RELEASED requires a named
approver, a title, and an explicit decision, and the approval is written into
the manifest together with a digest of the artefacts it covers.

There is deliberately no flag to bypass this. A run that is not approved stays
at DRAFT, and the artefacts are never emitted.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import capital_call as cc  # noqa: E402
import waterfall as wf  # noqa: E402


DRAFT = "DRAFT — NOT RELEASED"
RELEASED = "RELEASED"
RETURNED = "RETURNED FOR REWORK"

# stage -> manifest path relative to the output directory
MANIFESTS = {
    "capital_call": os.path.join("capital_call", "call.json"),
    "waterfall": os.path.join("waterfall", "waterfall.json"),
    "benchmark": "benchmark.json",
}

# stage -> directory of artefacts that the approver is signing off
ARTEFACTS = {
    "capital_call": os.path.join("capital_call", "notices"),
    "waterfall": os.path.join("waterfall", "statements"),
    "benchmark": "",
}

DECISIONS = ("approve", "reject")


class ApprovalRequired(Exception):
    """Raised when a release is attempted without an attributable decision."""


class ReleaseRefused(Exception):
    """Raised when a draft no longer reproduces from its recorded inputs."""


def _describe(reviewer: str) -> tuple[str, str]:
    """Split 'Name, Title' into its parts and refuse an unattributed name."""
    if not reviewer or not reviewer.strip():
        raise ApprovalRequired(
            "A release needs a named reviewer, as 'Name, Title'. An approval "
            "that cannot be attributed is not an approval."
        )
    name, _, title = reviewer.partition(",")
    if not name.strip() or not title.strip():
        raise ApprovalRequired(
            f"Reviewer {reviewer!r} must be given as 'Name, Title'. The record "
            "has to say who released it and what their role was."
        )
    return name.strip(), title.strip()


def digest(out_dir: str, stage: str) -> str:
    """SHA-256 over the sorted artefacts the approver is releasing.

    The digest is what makes the approval specific: it proves what was on
    screen when the decision was made.
    """
    if stage not in ARTEFACTS:
        raise ValueError(f"Unknown stage {stage!r}. Known: {sorted(ARTEFACTS)}")
    folder = os.path.join(out_dir, ARTEFACTS[stage])
    if not folder or not os.path.isdir(folder):
        return ""
    h = hashlib.sha256()
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            h.update(name.encode())
            with open(path, "rb") as fh:
                for block in iter(lambda: fh.read(65536), b""):
                    h.update(block)
    return h.hexdigest()


def manifest_path(out_dir: str, stage: str) -> str:
    if stage not in MANIFESTS:
        raise ValueError(f"Unknown stage {stage!r}. Known: {sorted(MANIFESTS)}")
    return os.path.join(out_dir, MANIFESTS[stage])


def release(
    out_dir: str,
    stage: str,
    reviewer: str,
    decision: str,
    note: str = "",
) -> dict:
    """Record a human decision against a drafted stage.

    Approving emits the stage's release artefacts. Rejecting returns the stage
    to rework and emits nothing. Either way the decision is written into the
    manifest's audit trail.
    """
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}, got {decision!r}")
    name, title = _describe(reviewer)

    path = manifest_path(out_dir, stage)
    if not os.path.exists(path):
        raise FileNotFoundError(f"No manifest at {path}. Run the stage first.")

    with open(path) as fh:
        res = json.load(fh)

    expert_ids = [e.get("id") for e in (res.get("exceptions") or []) if e.get("id")]
    stamp = dt.datetime.now().strftime("%d %b %Y %H:%M")
    record = {
        "at": stamp,
        "reviewer": name,
        "reviewer_title": title,
        "decision": decision,
        "stage": stage,
        "artefacts_digest": digest(out_dir, stage),
        "exceptions_acknowledged": expert_ids,
        "note": note,
    }

    res["status"] = (
        f"{RELEASED} — approved by {name}, {title}, {stamp}"
        if decision == "approve"
        else f"{RETURNED} — {name}, {title}, {stamp}"
    )
    res.setdefault("audit_trail", []).append(record)

    if decision == "approve":
        _emit(out_dir, stage, res)

    with open(path, "w") as fh:
        json.dump(res, fh, indent=2, default=str)
    return record


def _emit(out_dir: str, stage: str, res: dict) -> None:
    """Write the release artefacts for an approved stage.

    These are drafts that a person then issues through the normal channel.
    The gate never sends anything.
    """
    from decimal import Decimal

    if stage == "capital_call":
        ins = res["instruction"]
        for key in ("notice_date", "requested_due"):
            ins[key] = dt.date.fromisoformat(ins[key])
        for key in ("pi", "fees", "expenses", "total", "nav_per_unit"):
            ins[key] = Decimal(ins[key])
        res["due_date_used"] = dt.date.fromisoformat(res["due_date_used"])
        for row in res["rows"]:
            for key, value in row.items():
                if key not in ("id", "investor", "type", "status"):
                    row[key] = Decimal(value)
        cc.write_notices(res, os.path.join(out_dir, ARTEFACTS[stage]))

    elif stage == "waterfall":
        folder = os.path.join(out_dir, ARTEFACTS[stage])
        fresh = _reproduce_waterfall(res)
        wf.write_statements(fresh, folder)

    # benchmark has no separate artefacts: the workpaper is the output


def _resolve(path: str) -> str:
    """Manifests record inputs relative to the repo root when they can."""
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def _reproduce_waterfall(res: dict) -> dict:
    """Re-derive the distribution from its recorded inputs before releasing it.

    The approver is signing the numbers they were shown. If the same inputs no
    longer produce the same withholding, the draft is stale and must not be
    released, so this recomputes and compares rather than trusting the JSON.
    """
    from decimal import Decimal

    inp = res.get("inputs") or {}
    terms = json.load(open(_resolve(inp["terms"])))["terms"]
    flows, members, appo = wf.read_history(_resolve(inp["history"]))
    instruction = wf.read_instruction(_resolve(inp["instruction"]))
    fresh = wf.run(terms, flows, members, appo, instruction)

    drafted = Decimal(str(res["cap"]["withheld"]))
    reproduced = Decimal(str(fresh["cap"]["withheld"]))
    if drafted != reproduced:
        raise ReleaseRefused(
            f"Draft withholds {drafted:,.2f} but the recorded inputs now produce "
            f"{reproduced:,.2f}. The draft is stale; re-run the stage before "
            "approving it."
        )
    return fresh


def status(out_dir: str, stage: str) -> str:
    with open(manifest_path(out_dir, stage)) as fh:
        return json.load(fh).get("status", "")


def _main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="Approve or reject a drafted stage.")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--stage", required=True, choices=sorted(MANIFESTS))
    ap.add_argument("--reviewer", required=True, help="'Name, Title'")
    ap.add_argument("--decision", required=True, choices=DECISIONS)
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)

    try:
        record = release(a.out_dir, a.stage, a.reviewer, a.decision, a.note)
    except ApprovalRequired as exc:
        print(f"BLOCKED: {exc}")
        return 2

    print(status(a.out_dir, a.stage))
    if record["exceptions_acknowledged"]:
        print("Exceptions acknowledged:", ", ".join(record["exceptions_acknowledged"]))
    print("Nothing has been sent. Issue through the approved channel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
