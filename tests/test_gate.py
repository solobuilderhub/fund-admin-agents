"""
The gate, which is the other reason this repo exists.

No stage may reach a released state without a named approver, a title, and an
explicit decision. These tests are the evidence for that claim in the README.
"""

from __future__ import annotations

import json
import os

import pytest

import gate


def test_no_reviewer_is_refused(outputs):
    with pytest.raises(gate.ApprovalRequired):
        gate.release(outputs, "capital_call", "", "approve")


def test_a_name_without_a_title_is_refused(outputs):
    """An approval has to say what role the person held."""
    with pytest.raises(gate.ApprovalRequired):
        gate.release(outputs, "capital_call", "R. Ahmed", "approve")


def test_an_unknown_decision_is_refused(outputs):
    with pytest.raises(ValueError):
        gate.release(outputs, "capital_call", "J. Okafor, Senior Fund Accountant", "looks fine")


def test_rejection_returns_the_stage_and_emits_nothing(outputs):
    before = gate.digest(outputs, "capital_call")

    gate.release(
        outputs, "capital_call",
        "J. Okafor, Senior Fund Accountant",
        "reject", note="Call date does not comply with s.5.1(b)(i).",
    )

    assert gate.status(outputs, "capital_call").startswith(gate.RETURNED)
    # the drafted notices are left exactly as they were, still unreleased
    assert gate.digest(outputs, "capital_call") == before


def test_approval_releases_and_writes_the_record(outputs):
    record = gate.release(
        outputs, "capital_call",
        "J. Okafor, Senior Fund Accountant",
        "approve", note="Exceptions E1-E4 accepted as proposed.",
    )

    assert record["reviewer"] == "J. Okafor"
    assert record["reviewer_title"] == "Senior Fund Accountant"
    assert record["decision"] == "approve"
    assert record["exceptions_acknowledged"] == ["E1", "E3", "E2", "E4"]
    assert len(record["artefacts_digest"]) == 64

    assert gate.status(outputs, "capital_call").startswith(gate.RELEASED)
    assert len(os.listdir(os.path.join(outputs, "capital_call", "notices"))) == 8


def test_the_audit_trail_survives_a_second_decision(outputs):
    gate.release(outputs, "waterfall", "A. Mensah, Fund Controller", "reject")
    gate.release(outputs, "waterfall", "A. Mensah, Fund Controller", "approve")

    with open(gate.manifest_path(outputs, "waterfall")) as fh:
        trail = json.load(fh)["audit_trail"]

    assert [r["decision"] for r in trail] == ["reject", "approve"]


def test_the_digest_changes_when_an_artefact_changes(outputs):
    """The digest is what makes an approval specific to what was released."""
    gate.release(outputs, "capital_call", "J. Okafor, Senior Fund Accountant", "approve")
    first = gate.digest(outputs, "capital_call")

    notice = os.path.join(outputs, "capital_call", "notices", "Funding_Notice_Call7_I01.pdf")
    with open(notice, "ab") as fh:
        fh.write(b"\n% amended")

    assert gate.digest(outputs, "capital_call") != first


def test_every_stage_starts_as_a_draft(outputs):
    for stage in ("capital_call", "waterfall", "benchmark"):
        assert gate.status(outputs, stage).startswith(gate.DRAFT)
