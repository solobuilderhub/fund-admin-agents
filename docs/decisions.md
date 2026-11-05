# Design decisions

Six calls that shape the pipeline. Each one is a trade, and the trade is the point.

## 1. Arithmetic runs in code; the model does not approximate

Every number a person signs is computed by Python `Decimal`, never produced by a model. The model's job is reading documents and deciding what a clause means.

The failure this prevents is quiet and confident. Asked to check a set of financial statements, a model will produce a plausible reconciliation narrative while silently transposing a figure. Asked to compute a waterfall, it will usually be right and occasionally be wrong in a way that looks exactly like being right.

This is the decision everything else follows from. If the math is deterministic, you can test it. If it is generated, you can only sample it.

## 2. Every number carries its source

Each figure in an output can be traced to a clause and a page, or to a cell in a workpaper. Where the source is a judgement call, the output says so and names the open question rather than filling the gap.

The alternative, a number with no provenance, is unusable in an audit. It is also unusable in a review, because the reviewer's only option is to redo the work.

## 3. Exceptions are the product, not the failure path

The outputs lead with what needs a decision: the call date that does not comply, the defaulting member excluded from the investment allocation, the equalisation already demanded, the undefined basis for sharing the subscription facility.

A tool that returns a clean table is telling the reviewer that nothing needs their attention. That claim is either true, in which case it is thin, or it is false, in which case it is dangerous. The exceptions *are* the value.

## 4. Release requires a named human, and the gate is typed

Nothing leaves `DRAFT` without an approver's name, their title, and an explicit decision. The record carries a timestamp, the exceptions that were acknowledged, and a SHA-256 of the artefacts that were on screen.

Not a checkbox, and not a confirm dialog. A checkbox is a habit; a typed record is an attestation. When someone has to type their name and title next to numbers, they read the numbers.

The gate also re-derives the stage from its recorded inputs before releasing. If the draft no longer reproduces, it refuses. An approver should never sign figures that have quietly gone stale.

## 5. Terms are extracted, never inferred

When the agreement does not state something, the pipeline says so. The waterfall run flags a limit whose percentage the agreement never gives. The capital call flags a basis the agreement never defines and states its assumption openly.

The temptation is to fill gaps with a sensible default, because the output looks complete. Completeness is the wrong target. A stated assumption can be checked by the reviewer and challenged by the client; an invented one cannot.

## 6. Tolerance is explicit, and rounding is not failure

Statements are presented in thousands, notes are in whole dollars. Eight of the sixty-three tie-out checks differ by less than one thousand dollars, which is exactly rounding.

The tolerance is a parameter, not a hidden constant, and "TIES (rounding)" is a different state from "BREAK". Collapse them and the tool reports eight false failures and destroys its own credibility. Ignore them and it hides real breaks. The distinction is a product decision about how much imprecision a customer can tolerate, and it belongs to a person, not a default.
