# Fund administration agents, with the math in code

A working pipeline that takes a fund's source documents and produces statement tie-outs, fee recomputations, a NAV variance report, capital call notices, and a distribution waterfall.

Extraction and judgment go to a language model. Arithmetic, business-day calendars, and allocations go to deterministic Python. Nothing releases without a named human approval recorded as a typed decision.

Built against a public drawdown fund's LLC agreement and a listed private equity trust's audited statements, with synthetic investor data. No client documents, no client names.

```bash
git clone <this repo> && cd fund-admin-agents
make setup && make demo
```

---

## Why this exists

A fund administrator's output gets signed by a person, and that person carries the liability. An agent that produces a 95% correct NAV pack is worth less than nothing, because checking the output costs more than doing the work by hand.

So the interesting part of this repo is not the agents. It is the checking. Which numbers are computed in code, which have to come from a model, how a wrong one is caught before release, and what a person needs to see before they will put their name on it.

`make demo` runs every stage in under a second with no API key and no network access.

```
fund-admin-agents · demo run
dataroom: data/dataroom/ · extraction outputs committed, no model calls

[1/5] terms        1.25% p.a. aggregate, 20% performance over an 8% hurdle
                   [offer document p.24]
[2/5] tie-out      63 checks · 55 exact · 8 within published rounding · 0 breaks
[3/5] fees         management costs  F1 -2.4%   F2 +0.5%   F3 -1.4%
                   performance fee   open, HWM required, exposure 1,411,651.73
[4/5] capital call due 2026-10-16, not the requested 2026-10-09
                   6 business days' notice given against 10 required. Columbus Day does not count.
                   a single commitment-% split over-calls I06 by 385,505.83
[5/5] waterfall    tiers pay the manager          1,408,809.71
                   incentive cap, 20% of net gains   700,000.00
                   withheld pending confirmation      708,809.71
                   net gains exclude 9,000,000.00 of unrealised appreciation

gate               BLOCKED: DRAFT — NOT RELEASED
                   nothing released, nothing sent
```

Approve it and the status moves to `RELEASED`, with the approver's name, title, timestamp, and a SHA-256 of the artefacts that were on screen. It is a typed record, not a checkbox.

---

## What the run finds

| # | Finding | Why it matters |
|---|---|---|
| 1 | The manager's incentive is **$708,809.71 lower** than the tier calculation produces | The agreement caps incentive at 20% of net gains after realised losses and *unrealised depreciation*. The portfolio carries $9M of unrealised appreciation, which does not count. A generic waterfall pays $1,408,809.71 and an auditor finds it. |
| 2 | A naive allocation **over-calls the defaulting member by $385,505.83** | The agreement uses three allocation keys depending on what the money is for. Splitting on commitment alone misallocates every member, and hits hardest the one who has already defaulted. |
| 3 | The requested call date is **six business days out, not ten** | 9 October looks like ten business days from 25 September. It is six, because Columbus Day closes the Fed. The earliest compliant date is 16 October, not 15 October. This is the kind of thing that becomes a dispute with an investor's lawyer. |
| 4 | Published NAV per unit is **0.68% below** the audited figure | $436,747.20 against a 0.30% regulatory tolerance. Most likely late underlying-manager valuations booked after the monthly report, so it is a request for the bridge rather than a finding of error. |
| 5 | Eight of sixty-three tie-out checks land **inside published rounding**, none break | Statements are rounded to $'000, notes are in whole dollars. Distinguishing "rounding" from "break" is a product decision: call both failures and the tool is useless, call neither and it is dangerous. |

---

## The gate

`src/gate.py` is the smallest and most important file here.

Every stage writes its manifest with `status: DRAFT` and drafts its release artefacts without sending anything. Promotion requires a named approver, a title, and an explicit decision. The gate writes that record into the manifest and refuses anything else.

```python
from src.gate import release

release(
    out_dir="outputs",
    stage="capital_call",
    reviewer="J. Okafor, Senior Fund Accountant",
    decision="approve",
    note="Exceptions E1-E4 accepted as proposed.",
)
```

There is no flag to skip this. A run with no approver cannot produce a released artefact, and `tests/test_gate.py` asserts it.

Approval re-derives the numbers from the recorded inputs before emitting anything. If the draft no longer reproduces, the gate refuses to release it, so an approver is never signing figures that have gone stale under them.

**Why a typed record rather than a checkbox:** an approval that cannot be attributed is not an approval. If an investor disputes a call six months later, the record has to say who released it, when, what role they held, which exceptions they acknowledged, and exactly which artefacts they were looking at.

---

## Deterministic versus model

| Stage | Model does | Code does |
|---|---|---|
| Terms extraction | Locates fee and waterfall clauses, returns value plus clause and page reference | Nothing. Output is frozen to JSON and committed. |
| Statement tie-out | Nothing | 63 checks, each with an explicit tolerance and a source page |
| Fee recompute | Nothing | Rebuilds fees from terms over a NAV path, compares to reported |
| NAV benchmark | Nothing | Variance test, unit reconciliation, return recomputation |
| Capital call | Reads the drawdown instruction, extracts purpose and amount | Business-day arithmetic, three allocation keys, equalisation, default handling, bank matching |
| Waterfall | Reads the capital account history and instruction | Tier allocation per member, cap application, member offsets |
| Gate | Nothing | Enforces approver, title, decision, manifest state, artefact digest |

Extraction output is committed as JSON rather than computed at runtime. That is deliberate: the arithmetic is reproducible without a model, and the model's contribution is inspectable and diffable like any other input.

---

## What this does not do

- **No judge calibration.** There is no automated judge here, so nothing yet checks the checker. That is the next problem and it is not solved in this repo.
- **No golden-set provenance.** The 63 tie-out checks were written against two statement periods. Nothing tracks how they were derived, or what happens when a fund changes auditors and the note structure moves.
- **No re-extraction strategy.** The terms JSON is frozen by hand. If a fund amends its PPM, re-extraction is manual and there is no version diff.
- **No cost attribution.** Each stage runs locally, so there is no per-run token accounting.
- **Single-fund scale.** Everything is per fund, per period. Fleet oversight across hundreds of agents is out of scope.

---

## Layout

```
src/            the engine. one module per stage, plus gate.py
data/dataroom/  what the agent reads. committed, small, no client material
data/extracted/ extraction outputs, frozen, so the maths runs without a model
outputs/        a committed sample run. open the workpapers without running anything
references/     the business-day calendars the call logic depends on
tests/          the cap regression and the gate contract
docs/           findings, design decisions, and known limits
```

## Run it

```
make setup     # venv plus requirements
make demo      # the transcript above
make test      # 13 tests
```

Requires Python 3.11+. No API key, no network, no GPU.

On a machine where `python3` is older, point setup at a newer interpreter:

```
make setup PYTHON=python3.13
```

One stage on its own:

```
python3 -m src.waterfall --terms data/extracted/waterfall_terms.json \
    --history data/dataroom/waterfall/21_Capital_Account_History.xlsx \
    --instruction data/dataroom/waterfall/22_Distribution_Instruction_Nov2026.pdf \
    --out-dir outputs
```

---

## Provenance

- **Drawdown agreement.** An SEC EDGAR exhibit from a public closed-end fund's LLC agreement. Names and codes redacted, original page numbers kept.
- **Listed trust statements.** Published annual, half-year, and monthly reports from a listed Australian private equity unit trust. Names and registration numbers removed, amounts scaled by 0.125, unit counts by 0.1, per-unit values by 1.25. Ratios, returns, fee rates, and every variance are unchanged.
- **Investor register, bank statement, instruction memos, capital account history.** Synthetic. Registers are never public, so these were built to exercise the real agreement terms.

Nothing here is a client deliverable, and no client engagement is described.

MIT licensed. The agreement text is a public record and is included with attribution.
