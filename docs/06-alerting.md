# 06 — Alerting

Layer 6: everything above produces findings; alerting decides what a human ever
sees. The governing principle is **signal vs. noise** — a pattern that cries
wolf gets muted, and a muted pattern protects nothing. Every mechanism below
exists to keep the alert stream worth reading.

## Latest-per-key aggregation

`drift.jsonl` accumulates one finding per measurement per run; a key that stays
broken generates a finding every run forever. Alerting collapses this: for each
`(class, key)`, only the **latest** status is shown, with first-seen and
last-seen timestamps.

```
drift.jsonl:  repo:site-behind DRIFT (run 1) → DRIFT (run 2) → DRIFT (run 3)
alert shows: repo:site-behind — DRIFT — behind=9 — first seen 3d ago — still open
```

One broken thing is one alert, not N. When the key recovers (`OK` finding), the
alert closes — optionally with a "resolved" notification if the outage was
previously alerted.

## Quiet hours

Non-urgent severities are held until a human-plausible hour. A `REVIEW` finding
at 03:00 waits for 08:00; a `VIOLATION` does not — severity decides what can
wait:

| Severity | Quiet hours? | Rationale |
|---|---|---|
| `VIOLATION` / gate-denied-then-bypassed | no | irreversible or rule-breaking — now |
| `DRIFT` | yes, unless age > threshold | drift compounds slowly; morning is fine |
| `REVIEW` | yes | digest material by definition |
| `meta_sweep` discrepancy | no if `reconciler_wrong`, else yes | a broken verifier corrupts everything above it |

## Dedup windows

Even latest-per-key can re-alert the same unresolved item on every digest. A
dedup window suppresses repeats: the same `(class, key, status)` does not
re-alert within N hours (N per severity — violations re-alert sooner than
reviews). State changes *do* re-alert immediately: `REVIEW → VIOLATION` is new
information even inside the window.

## `known_debt` with `expires`

Declared exceptions live in `known_debt` ([01-declared-state.md](01-declared-state.md)):

```yaml
known_debt:
  - key: repo:site-behind
    reason: "waiting on upstream fix, issue #123"
    owner: icaros
    expires: 2026-12-01
```

Alerting filters findings whose key matches an unexpired `known_debt` entry —
they appear in a "known debt" digest, not the main alert stream. **When
`expires` passes, the exception evaporates**: the next finding for that key
alerts normally. This is the entire point of the field — debt without expiry is
drift with better branding, and the alerter must treat expired entries as
absent, not as warnings about the declaration itself. (Optionally: an
"expiring soon" REVIEW at T-7 days, so exceptions get renewed deliberately
rather than silently lapsing.)

## Severity → channel mapping

Different audiences for different severities:

| Severity | Channel | Cadence |
|---|---|---|
| `VIOLATION`, gate bypass attempts | direct message / page | immediate |
| `meta_sweep` discrepancy (`reconciler_wrong`) | direct message | immediate — the verifier is broken |
| `DRIFT` | team channel | batched digest, daily |
| `REVIEW` | digest | weekly, or folded into daily if volume is low |
| resolved-after-alert | same channel as original | one-line close-out |

The mapping is configuration, not code — but it is *declared* configuration,
reviewable in git like everything else.

## Auto-fix opt-in, per class

Some drift has a safe mechanical fix: `git fetch` before measuring, `pip
install` to sync a venv, restarting a dead timer. Auto-fix is tempting and
dangerous — a wrong auto-fix is worse than an alert, because it acts silently.

The rule: **auto-fix is opt-in per `drift_*` class, never global.**

```yaml
auto_fix:
  drift_git:
    fetch_first: true        # safe: fetch is read-only-ish, refreshes refs
    prune_worktrees: false   # opt-in only after the class proves itself
  drift_daemons:
    restart: false           # restarting the wrong daemon is its own incident
```

A class earns auto-fix by surviving a period of alerts-without-surprises. Until
then it alerts and a human (or agent, with justification) fixes. Auto-fixed
findings still write to `drift.jsonl` — with `detail.auto_fixed: true` — so the
audit trail shows what the machine did on its own.

## The alert contract

Every alert should answer, without follow-up questions:

- **What**: `(class, key)` and current status.
- **Since when**: first-seen timestamp; age in human units.
- **Evidence**: the `detail` field — the numbers/states that produced it.
- **What to do**: a pointer — the reconciler doc, the declared-state file, or
  the known_debt entry if one exists.
- **How to silence it legitimately**: fix it, or declare `known_debt` with an
  owner and an expiry. Never "ignore this alert type."

An alert that requires a meeting to interpret is a failed alert.

Next: [07-bootstrap.md](07-bootstrap.md) — zero to ecosystem.
