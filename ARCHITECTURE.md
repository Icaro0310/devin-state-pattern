# Architecture

The pattern is seven layers. They are ordered by *when they act*: declared state
is written once and reviewed; reconcilers and meta-sweep run on a schedule;
compliance runs per session; gates run at command time; alerting is the output
surface for everything above; bootstrap is how you get started.

```
                        ┌──────────────────────────────────────────┐
                        │        LAYER 1: DECLARED STATE           │
                        │  versioned YAML — the claims             │
                        │  repos · fleet · daemons · prs · rules   │
                        │  reconciliation · known_debt             │
                        └──────────────────┬───────────────────────┘
                                           │ claims (what SHOULD be true)
                                           ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  LAYER 2: RECONCILERS (drift_*)                                │
        │  measure REALITY — git remote, process table, gh api, sqlite   │
        │  never trust logs, transcripts, or memory as truth             │
        │  append findings → drift.jsonl (append-only)                   │
        └───────────────┬────────────────────────────────┬─────────────┘
                        │ findings                        │ findings
                        ▼                                 ▼
        ┌───────────────────────────┐         ┌─────────────────────────┐
        │  drift.jsonl              │◄────────│  LAYER 3: META-SWEEP    │
        │  {ts,class,key,status,    │ re-      │  independently re-      │
        │   detail} append-only     │ measure  │  measures a sample of   │
        └─────────────┬─────────────┘         │  what reconcilers claim │
                      │                       └───────────┬─────────────┘
                      │ findings                            │ discrepancies
                      ▼                                     ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  LAYER 4: COMPLIANCE (rules.yaml)                              │
        │  per-session audit · check_type dispatch · REVIEW/VIOLATION    │
        │  validated_against = evidence anchor, not a checkbox           │
        └───────────────────────────┬──────────────────────────────────┘
                                    │
                                    ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  LAYER 6: ALERTING                                             │
        │  latest-per-key dedup · quiet hours · known_debt(expires)      │
        │  severity → channel · auto-fix opt-in per class               │
        └──────────────────────────────────────────────────────────────┘

   LAYER 5: ENFORCEMENT GATES run OUTSIDE the loop, at command time:
   PreToolUse hook → JSON on stdin → {"permissionDecision": "deny"|"allow"}

   LAYER 7: BOOTSTRAP (scripts/bootstrap.sh) wires all of the above.
```

The one sentence to remember: **reconciler reports, meta-sweep verifies, agent
declares green only when both agree.**

---

## Layer 1 — Declared state

Versioned YAML files are the source of truth for what *should* exist. Not docs,
not tribal knowledge, not "I think the timer runs at 3am" — files in git, with
review history and diffs.

Typical files:

| File | Declares |
|---|---|
| `repos.yaml` | every repo in the ecosystem: path, remote, default branch, expected state |
| `fleet.yaml` | machines/agents/workers and what each is responsible for |
| `daemons.yaml` | long-running processes and timers that must be alive |
| `prs.yaml` | open PRs and their expected lifecycle state |
| `rules.yaml` | compliance rules (see Layer 4) |
| `reconciliation.yaml` | which reconcilers run, at what cadence, with what thresholds |

Two conventions matter more than the schema:

- **`known_debt` is first-class.** Drift you already know about is declared with
  an owner and an `expires` date. Undeclared debt is indistinguishable from new
  breakage; declared debt is a decision with a fuse on it.
- **Comments carry the *why*.** YAML says what; the comment says why it is that
  way and who decided. When the YAML and reality disagree, the comment is often
  the only place the intent survives.

Detail: [docs/01-declared-state.md](docs/01-declared-state.md).

## Layer 2 — Reconcilers (`drift_*`)

A reconciler is a small program that answers one question: *does reality match
the declaration?* Each `drift_*` class owns one domain:

| Class | Measures |
|---|---|
| `drift_git` | unpushed commits, behind-remote, dirty worktrees, unexpected branches |
| `drift_daemons` | expected processes/timers actually alive (via `ps`, `systemctl`, not logs) |
| `drift_deps` | declared dependencies vs lockfile/manifest reality |
| `drift_prs` | PRs that exist vs PRs that are declared; stale approvals, orphaned branches |
| `drift_spec` | artifacts vs the spec they claim to implement |
| `drift_triggers` | declared timers/webhooks/cron actually firing on schedule |
| `drift_scope` | files changed outside the declared scope of a task/session |

Rules for every reconciler:

- **Measure reality, not logs.** A daemon is alive because `ps`/`systemctl` says
  so, not because its log's last line is cheerful. Logs are a claim too.
- **Append-only output.** Findings go to `drift.jsonl` as
  `{ts, class, repo/key, status, detail}`. You never rewrite history; you add a
  measurement.
- **Severity ordering.** Statuses rank `OK < REVIEW < VIOLATION < DRIFT` (names
  vary; the ordering must be explicit and total). Aggregation must *promote* on
  worst-seen, never silently keep the first value — see CASE-STUDIES.md (c).
- **Write vs. skip.** Reconcile on a schedule and on-demand; skip cleanly when a
  measurement is impossible (no network, missing binary) and record the skip —
  a skipped measurement is itself a finding, not a green.

Detail: [docs/02-reconcilers.md](docs/02-reconcilers.md).

## Layer 3 — Meta-verification (`meta_sweep`)

The layer that checks can itself be wrong. `meta_sweep` is a deliberately small,
independent re-measurement of a sample of what the reconcilers claim.

- It does **not** import the reconciler code. It re-asks the question with
  different tooling (shell one-liners, a second API path, a different parser) so
  a shared bug cannot hide in both.
- It writes a **discrepancy report**: cases where reconciler output and
  independent measurement disagree.
- **Green requires both to agree.** A run is only "all green" when reconcilers
  report clean *and* meta-sweep finds no unexplained discrepancies.

Detail: [docs/03-meta-verification.md](docs/03-meta-verification.md).

## Layer 4 — Compliance (`rules.yaml`)

Conventions become rules. Each rule has:

- `id` — stable identifier (`R-commit-trailer`, `R-no-force-push`)
- `check_type` — how it is verified (`command_scan`, `file_glob`, `api_state`,
  `manual_evidence`, ...)
- `severity` — `REVIEW` (worth a look) or `VIOLATION` (must be justified)
- `validated_against` — the evidence anchor required to close the rule: a PR
  number, a commit SHA, a URL, a file path, a tool name. **Evidence, not
  checkboxes**: "I did it" is not validation; a pointer to where reality shows
  it is.

Compliance runs per session (via session-end hooks) and can also run standalone
with `--self-check`. A rule that cannot name its evidence is a rule that will be
checked by vibes.

Detail: [docs/04-compliance.md](docs/04-compliance.md).

## Layer 5 — Enforcement gates

Post-hoc audits tell you the damage after it happened. For irreversible actions
— `git push --force`, `rm -rf`, dropping tables, publishing releases — you need
a gate at command time.

The mechanism is a PreToolUse hook: the agent runtime sends the proposed tool
call as JSON on stdin; the hook returns `{"permissionDecision": "deny" | "allow"}`
(or `"ask"`). The hook parses the command, matches it against a **scope table**:

- **Gated** — irreversible or hard-to-reverse actions. Deny by default; allow
  only with explicit justification.
- **Rule-only** — reversible or low-blast-radius actions. Allowed, but logged so
  compliance can audit afterwards.

The parser is the hard part and the part that rots: it must understand command
wrappers (`sh -c`, `sudo`, `env`, `xargs`, pipes, `&&`) and git's global flags
(`-C`, `--git-dir`, `--work-tree`). See CASE-STUDIES.md (e) and
[docs/05-enforcement-gates.md](docs/05-enforcement-gates.md).

## Layer 6 — Alerting

Everything above produces findings; alerting decides what a human sees.

- **Latest-per-key aggregation** — one alert per `(class, key)` showing current
  state, not one per finding. A repo that is 3 commits behind is one alert, not
  three.
- **Quiet hours** — non-urgent severities are held until a human-plausible hour.
- **Dedup windows** — the same `(class, key, status)` does not re-alert within N
  hours.
- **`known_debt` with `expires`** — declared, owned, time-boxed exceptions.
  When `expires` passes, the exception evaporates and the finding alerts again.
  Debt without expiry is just drift with better branding.
- **Severity → channel** — `VIOLATION` pages; `REVIEW` digests; `DRIFT`
  batches.
- **Auto-fix opt-in per class** — some drift classes have safe mechanical fixes
  (fetch, prune). Auto-fix is opt-in *per class*, never global, because a wrong
  auto-fix is worse than an alert.

Detail: [docs/06-alerting.md](docs/06-alerting.md).

## Layer 7 — Bootstrap

`scripts/bootstrap.sh` takes a directory from zero to a working skeleton:
creates the state directory, copies template YAMLs with TODOs, registers the
hooks, installs a daily timer, and runs the first reconciliation pass so you see
real output on day one. Detail:
[docs/07-bootstrap.md](docs/07-bootstrap.md).

---

## Data flow, end to end

1. Agent proposes `git push --force` → **gate** parses command → scope table says
   gated → `deny` unless justified. (Layer 5)
2. Timer fires `reconcile.py` → each `drift_*` class measures reality → appends
   findings to `drift.jsonl`. (Layers 1+2)
3. `meta_sweep` samples findings, re-measures independently → writes
   `meta_report.json` with discrepancies. (Layer 3)
4. Session-end hook runs compliance → rules checked against session artifacts →
   `REVIEW`/`VIOLATION` entries with `validated_against` requirements. (Layer 4)
5. Alerter reads `drift.jsonl` + `meta_report.json` + compliance output →
   latest-per-key, dedup, quiet hours, `known_debt` filter → notifications.
   (Layer 6)

## Honest limitations

- The pattern is **opinionated**. It assumes you can name your declared state and
  measure reality cheaply. If your "state" is vibes, start smaller.
- Some checks are **heuristic** — command parsing, scope detection, transcript
  parsing. They have known blind spots (see CASE-STUDIES.md). Treat heuristic
  coverage as a floor to raise, not a ceiling.
- **`meta_sweep` can itself drift.** Mitigate by keeping it small, independent,
  and written in a different style than the reconcilers it checks. A large
  meta-sweep becomes a second thing to verify.
- Gates can be **worked around** (a determined agent finds an unlisted wrapper).
  They raise the cost of irreversible mistakes; they do not make them impossible.
  Pair gates with compliance auditing of what gates allowed.
