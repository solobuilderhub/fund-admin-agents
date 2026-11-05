# Limits

What this repo does not solve, and which gap I would attack first.

## No judge calibration

There is no automated judge anywhere in this pipeline. The tie-out checks are explicit assertions, so there is nothing that grades a grader.

That is fine when every check is deterministic. It stops being fine the moment a model is asked whether a disclosure is adequate, or whether an anomaly is material. At that point you need a judge, and a judge needs a reference set, a versioned rubric, and a measured disagreement rate against human reviewers. None of that exists here.

**This is the first thing I would build.** The 63 tie-out checks are already labelled ground truth in disguise: each one is a human decision about what ties. Freeze the prompt, model, and rubric together, run the judge against those checks, and publish the confusion matrix. A judge that agrees with a human on 58 of 63 is useful; one whose agreement rate is unknown is not.

## No golden-set provenance

The checks were written against two statement periods of one trust. Nothing records how each check was derived, who decided on the tolerance, or what happens when a fund changes auditors and the note structure moves.

So the suite cannot tell you when it has stopped covering the thing it was built to cover. A check that silently stops being meaningful is worse than no check, because it manufactures confidence.

## No re-extraction strategy

Terms are extracted once and frozen by hand. If a fund amends its PPM, or a new drawdown agreement supersedes an old one, re-extraction is manual and there is no diff between versions.

At a thousand agents, the interesting question is not how to extract terms but how to notice that the terms changed. That is a versioning and monitoring problem, and it is unsolved here.

## No cost attribution

Every stage runs locally at zero marginal cost, so there is no per-run accounting. In production each extraction call is billed, and the invoice will not explain which fund, which workflow, or which customer consumed it.

Cost attribution belongs at span level, tagged by run, fund, and stage. The business metric that matters is cost per close pack, not cost per token.

## Single-fund scale

Everything is per fund, per period, invoked by a person. There is no registry, no scheduling, no run history across agents, and no way to answer "what is failing right now across four hundred agents."

The failures at scale are also different in kind. Today a bad output is caught because someone reads it. At scale, the failure mode is alert fatigue: a dashboard that flags forty things, of which two matter, trains people to ignore it. Separating an exception from an issue is the hard product problem, and this repo only gestures at it.
