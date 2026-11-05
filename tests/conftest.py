"""Shared test fixtures: run the stages into a temporary directory."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
DATAROOM = os.path.join(ROOT, "data", "dataroom")
EXTRACTED = os.path.join(ROOT, "data", "extracted")

sys.path.insert(0, SRC)


def run(module: str, *args: str, out_dir: str) -> subprocess.CompletedProcess:
    """Run one stage from src/ with the repo's own interpreter."""
    cmd = [sys.executable, os.path.join(SRC, module), *args, "--out-dir", out_dir]
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


@pytest.fixture
def outputs(tmp_path):
    """A temporary output tree with the benchmark, call and waterfall drafted."""
    d = str(tmp_path)

    run(
        "tieout.py",
        "--extracted", os.path.join(EXTRACTED, "extracted.json"),
        out_dir=d,
    )
    run(
        "fee_recompute.py",
        "--terms", os.path.join(EXTRACTED, "terms.json"),
        "--extracted", os.path.join(EXTRACTED, "extracted.json"),
        out_dir=d,
    )
    run(
        "nav_benchmark.py",
        "--extracted", os.path.join(EXTRACTED, "extracted.json"),
        out_dir=d,
    )
    run(
        "capital_call.py",
        "--terms", os.path.join(EXTRACTED, "call_terms.json"),
        "--register", os.path.join(DATAROOM, "capital_call", "11_Investor_Register_2026-09-30.xlsx"),
        "--instruction", os.path.join(DATAROOM, "capital_call", "12_Drawdown_Instruction_Call7.pdf"),
        out_dir=d,
    )
    run(
        "waterfall.py",
        "--terms", os.path.join(EXTRACTED, "waterfall_terms.json"),
        "--history", os.path.join(DATAROOM, "waterfall", "21_Capital_Account_History.xlsx"),
        "--instruction", os.path.join(DATAROOM, "waterfall", "22_Distribution_Instruction_Nov2026.pdf"),
        out_dir=d,
    )
    return d


@pytest.fixture
def manifest(outputs):
    def load(stage):
        path = os.path.join(
            outputs,
            {"capital_call": "capital_call/call.json",
             "waterfall": "waterfall/waterfall.json",
             "benchmark": "benchmark.json"}[stage],
        )
        with open(path) as fh:
            return json.load(fh)
    return load
