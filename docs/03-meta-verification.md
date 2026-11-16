# 03 — Meta-verification (`meta_sweep`)

Layer 3: the layer that checks can itself be wrong. `meta_sweep` is a small,
deliberately independent program that re-measures what the reconcilers claim —
because every bug in [CASE-STUDIES.md](../CASE-STUDIES.md) was a bug *in a
check*, and checks drift exactly like the state they measure.

## The rule it enforces

> **Reconciler reports, meta-sweep verifies, agent declares green only when both
> agree.**

A reconciliation run is not "green" because reconcilers printed clean. It is
green when reconcilers printed clean *and* meta-sweep's independent sample found
no unexplained discrepancies.

## What it does

1. **Samples** findings from `drift.jsonl` — both non-OK findings ("is this real?")
   and a slice of expected-clean keys ("is this *actually* clean, or blind?").
   Sampling only failures verifies nothing; the dangerous false-greens live in
   the clean set.
2. **Re-measures independently.** For each sampled key, it asks the same
   question the reconciler asked — through a *different* code path.
3. **Writes a discrepancy report** (`meta_report.json`): every case where
   reconciler output and independent measurement disagree, with both values and
   the commands used.

## How to keep it independent (the hard part)

The failure mode to avoid is meta-sweep becoming a copy of the thing it checks —
same parser, same helper functions, same assumptions, so the same blind spot
exists in both and "agreement" means nothing.

Techniques that work:

- **Different tooling.** If `drift_git` uses `rev-list --count`, meta-sweep uses
  `git log --format=%H | wc -l`, or `gh api compare`. Different code, same fact.
- **Different language or style.** Reconcilers in Python classes; meta-sweep in
  bash + `jq` + `gh`. Shared-bug surface shrinks to the API itself.
- **Different sampling each run.** A fixed sample gets gamed by drift that
  hides between samples; rotate deterministically (hash of date + key) so
  coverage accumulates.
- **Keep it small.** A meta-sweep with 20 checks you trust beats one with 200
  you don't. Every check in meta-sweep is itself a claim requiring evidence.

## The discrepancy report

```json
{
  "run": "2026-11-16T13:05:00Z",
  "sampled": 42,
  "discrepancies": [
    {
      "key": "repo:site-behind",
      "reconciler": {"status": "OK", "detail": "behind=0"},
      "meta": {"status": "DRIFT", "detail": "behind=9 (fresh fetch)"},
      "verdict": "reconciler_stale_refs"
    }
  ]
}
```

Verdicts worth distinguishing:

- `reconciler_wrong` — the measurement itself was buggy (CASE-STUDIES b, c, e).
- `reconciler_stale` — measured against stale state (CASE-STUDIES a: forgot to
  fetch first).
- `input_polluted` — the source data had duplicates/semantics the reconciler
  didn't model (CASE-STUDIES d).
- `meta_wrong` — meta-sweep itself erred. This verdict must exist; a meta-sweep
  that can never be wrong is just a bigger blind spot.

## Green requires both

Concretely, the "all green" signal is:

```
drift.jsonl has no non-OK findings for the window
AND meta_report.json has zero unexplained discrepancies
AND no UNKNOWN/SKIP findings went uninvestigated
```

Any leg failing means *not green* — and the alerting layer
([06-alerting.md](06-alerting.md)) decides how loudly to say so. A meta-sweep
that finds discrepancies should itself produce findings in the same JSONL
stream (`class: "meta_sweep"`), so alerting treats verifier-disagreement as
just another finding type.

## Honest limitation

Meta-sweep can itself drift — its checks rot, its sample misses the one broken
reconciler, its "independent" path quietly converges on the same bug. You cannot
fully verify the verifier; you can only *bound* the recursion. Practical bounds:

- Keep meta-sweep small enough to read end-to-end in one sitting.
- Write it differently from what it checks (above).
- Sample expected-clean keys, not just reported findings — the false-green
  hides where nobody looks.
- Accept that meta-sweep's own bugs surface as `meta_wrong` verdicts and odd
  discrepancy patterns, which a human reviews periodically.

Next: [04-compliance.md](04-compliance.md) — rules with evidence, not checkboxes.
