# 02 — Reconcilers (`drift_*`)

Layer 2: small programs that answer one question per domain — *does reality
match the declaration?* — and append what they find to `drift.jsonl`.

## The cardinal rule: measure reality, not logs

A reconciler's input must be the thing itself, queried live:

| Domain | Measure via | NOT via |
|---|---|---|
| git state | `git fetch` + `git status`/`rev-list` against remote | the agent's "I pushed" message |
| daemons | `ps`, `systemctl is-active`, port probes | the daemon's own log file |
| PRs | `gh api` / GitHub API | memory of what was opened |
| deps | lockfile/manifest on disk | the install command's stdout |
| triggers | timer last-run timestamps, webhook delivery logs *from the platform* | the scheduler's config file alone |

Logs and transcripts are *claims about* reality — useful for forensics, useless
as measurement. If your reconciler's source of truth is a file a process wrote
about itself, you have built a second declaration, not a measurement.

## The `drift_*` class catalog

| Class | What it measures | Typical findings |
|---|---|---|
| `drift_git` | per-repo: unpushed commits, **behind** remote, dirty worktrees, unexpected branches, stale worktrees | `repo:X behind=9`, `repo:Y unpushed=3`, `worktree:Z dirty` |
| `drift_daemons` | every declared daemon/timer actually alive | `daemon:scout expected=active actual=inactive` |
| `drift_deps` | declared deps vs lockfile/manifest reality; drift between manifest and lock | `dep:left-pad in manifest, not in lock` |
| `drift_prs` | PRs that exist vs `prs.yaml`; stale approvals; merged-but-undeclared | `pr:#42 declared=open actual=merged` |
| `drift_spec` | artifacts vs the spec/issue they claim to implement | `spec:S1 artifact missing section 3` |
| `drift_triggers` | declared timers/webhooks/cron actually firing on schedule | `trigger:nightly last_run=3d ago expected=daily` |
| `drift_scope` | files changed outside a task/session's declared scope | `session:S touched out-of-scope: secrets/` |

You will not need all of them. Start with `drift_git` + `drift_daemons` — they
catch the most drift per line of code.

## Output schema: `drift.jsonl`

Append-only. One JSON object per finding, one line each:

```json
{"ts":"2026-11-16T13:00:00Z","class":"drift_git","key":"repo:site-behind","status":"DRIFT","detail":"behind=9 ahead=0 fetch_age=2m"}
{"ts":"2026-11-16T13:00:01Z","class":"drift_daemons","key":"daemon:scout","status":"VIOLATION","detail":"expected=active actual=inactive"}
```

Fields:

- `ts` — ISO-8601 UTC timestamp of the *measurement*, not of the event.
- `class` — which reconciler produced it.
- `key` — stable identifier for the thing measured (`repo:name`, `daemon:name`,
  `pr:owner/name#42`). Alerting dedups on this.
- `status` — see severity below.
- `detail` — the evidence: numbers, states, commands that produced the finding.
  Write it for a human reading the alert at 3am.

**Append-only means append-only.** Never rewrite or compact `drift.jsonl` in
place — history is the point. Rotation, if needed, is a separate concern
(`drift-YYYYMM.jsonl`), not an edit.

## Severity ordering

Statuses form a total order. A common ladder:

```
OK < REVIEW < VIOLATION < DRIFT
```

(`DRIFT` on top because "reality diverged from declaration" is the pattern's
namesake and outranks a rule violation.) Whatever ladder you choose:

- **It must be explicit and total** — every status comparable to every other.
  See CASE-STUDIES.md (c): a status that falls outside the comparison table
  can never be reported, and its absence looks like health.
- **Aggregation promotes on worst-seen.** When multiple findings share a key,
  the key's status is the maximum — initialized to a sentinel *below* `OK`
  (`None`), never to `"OK"` itself. `"OK"` is a conclusion, not a starting point.
- **`OK` findings are optional.** Some systems write only non-OK findings to
  keep the log small; if you do, meta-sweep must sample *expected-clean* keys
  too, or "no findings" is unfalsifiable.

## When to write vs. when to skip

- **Write** on every completed measurement that found something — including
  `REVIEW`-level "huh, that's odd" findings. Cheap to store, expensive to
  reconstruct.
- **Write the skip.** If a measurement couldn't run (no network, missing
  `gh` auth, repo path absent), append a finding with status like `UNKNOWN` or
  `SKIP` and the reason in `detail`. A skipped measurement is itself drift
  signal — silence is not health. (Fail-safe principle: when in doubt, assume
  drift.)
- **Don't write** duplicate findings within a run — one per `(class, key)` per
  run, worst status wins. Dedup across *runs* is alerting's job
  ([06-alerting.md](06-alerting.md)), not the reconciler's.

## Implementing a reconciler

A reconciler is deliberately dumb: read declarations → measure reality → emit
JSONL. No alerting, no state, no memory of previous runs. That simplicity is
what makes meta-sweep able to re-implement it independently
([03-meta-verification.md](03-meta-verification.md)) — if your reconciler
imports a framework, accumulates state, or calls the alerter, the meta-sweep
can no longer be a clean-room check.

Next: [03-meta-verification.md](03-meta-verification.md) — verifying the verifier.
