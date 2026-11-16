[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![tests](https://github.com/Icaro0310/devin-state-pattern/actions/workflows/test.yml/badge.svg)](https://github.com/Icaro0310/devin-state-pattern/actions/workflows/test.yml)

# devin-state-pattern

**Autonomous agents produce state that nobody verifies. This pattern verifies it.**

An agent ecosystem — coding agents, scheduled jobs, daemons, CI runners — produces
state all day: git branches, worktrees, pull requests, timers, caches, transcripts,
ledgers. Every piece of that state is *declared* somewhere (a config file, a plan,
a rule) and *real* somewhere else (a git remote, a process list, an API). The two
drift apart. Nobody notices, because the dashboard reads the declarations, not the
reality. The system reports "all green" while the ground truth diverges — that is
the failure mode this pattern exists to kill.

This repository is a **pattern, not a framework**. There is no `pip install`, no
runtime dependency, no abstraction layer you must adopt wholesale. You read the
documents, copy the templates, and adapt the pieces you need to your own stack.
The pattern is seven cooperating layers — declared state, reconcilers,
meta-verification, compliance, enforcement gates, alerting, and bootstrap — that
together turn "the agent said it finished" into "reality was measured and agrees."

## What this is not

- **Not a monitoring product.** No dashboards, no SaaS, no agents to deploy.
  The "product" is a set of conventions plus small scripts you own.
- **Not a silver bullet.** It does not prevent bugs — reconcilers have blind
  spots, parsers miss wrappers, meta-sweep can itself drift. It prevents bugs
  from staying *invisible*. See [CASE-STUDIES.md](CASE-STUDIES.md) for the six
  false-greens that motivated every layer.
- **Not all-or-nothing.** Adopt one layer, feel the value, add the next. The
  layers compose but do not require each other to exist.

## A concrete picture

Without the pattern, a typical agent ecosystem looks like this: a cron job runs
a scout every 20 minutes and posts to Slack; a session-end hook checks commit
trailers; a handful of YAML files describe what should exist; and everyone
*assumes* the timer is alive, the repos are pushed, the PRs are tracked, the
rules are followed. The assumptions are never tested. Months later you discover
a repo sat 9 commits behind, a daemon died quietly, and a compliance rule was
never actually checked — because nothing ever measured reality against the
declarations.

With the pattern, the same ecosystem has `drift.jsonl` accumulating measured
findings, a `meta_sweep` that re-checks the reconcilers' claims independently,
rules that require evidence anchors to close, gates that deny force-pushes at
command time, and alerts that dedup, respect quiet hours, and expire declared
debt on schedule. The system can still be wrong — but it cannot be *silently*
wrong, and silent wrongness is what scales into lost work.

## The seven layers at a glance

1. **Declared state** — versioned YAML files are the source of truth for what
   *should* exist: repos, daemons, PRs, rules, triggers.
2. **Reconcilers** — `drift_*` classes measure reality (not logs, not memories)
   and append findings to `drift.jsonl`.
3. **Meta-verification** — `meta_sweep` independently re-measures what the
   reconcilers claim. A reconciler reports; meta-sweep verifies.
4. **Compliance** — `rules.yaml` turns conventions into auditable rules with
   `validated_against` evidence anchors, checked per session.
5. **Enforcement gates** — PreToolUse hooks deny irreversible actions at command
   time, not in a post-hoc report.
6. **Alerting** — latest-per-key dedup, quiet hours, `known_debt` with expiry,
   severity-to-channel mapping. Signal vs. noise.
7. **Bootstrap** — `scripts/bootstrap.sh` scaffolds a working skeleton.

Full detail: [ARCHITECTURE.md](ARCHITECTURE.md).

## The seven principles

1. **Declared vs. real** — never assume YAML is truth. The YAML is a claim;
   reality is measured.
2. **Measure before alerting** — never alert on what a process *said*; alert on
   what a measurement *found*.
3. **Verify the verifier** — reconcilers drift too. `meta_sweep` exists because
   the layer that checks can itself be wrong.
4. **Evidence, not checkboxes** — compliance requires `validated_against` anchors
   (PR number, SHA, URL, path, tool name), not "done" flags.
5. **Gates, not audits** — irreversible actions are denied at command time by
   PreToolUse hooks, not flagged after the damage is done.
6. **Signal vs. noise** — latest-per-key dedup, quiet hours, `known_debt` with
   expiry. A pattern that cries wolf gets muted, and then it protects nothing.
7. **Fail-safe** — when in doubt, assume drift. Missing data is drift, not health.

## Read these

- [ARCHITECTURE.md](ARCHITECTURE.md) — the seven layers in detail, with the data
  flow diagram and severity model.
- [CASE-STUDIES.md](CASE-STUDIES.md) — six real false-greens this pattern caught
  in a production multi-repo agent ecosystem, and what each one teaches. **Start
  here if you want to know why any of this matters.**
- [docs/](docs/) — one document per layer:
  - [01 — Declared state](docs/01-declared-state.md)
  - [02 — Reconcilers](docs/02-reconcilers.md)
  - [03 — Meta-verification](docs/03-meta-verification.md)
  - [04 — Compliance](docs/04-compliance.md)
  - [05 — Enforcement gates](docs/05-enforcement-gates.md)
  - [06 — Alerting](docs/06-alerting.md)
  - [07 — Bootstrap](docs/07-bootstrap.md)
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to adapt the pattern to your ecosystem.
- `templates/` — YAML and hook templates to copy and fill in.
- `scripts/bootstrap.sh` — scaffold a working skeleton in a new ecosystem.

## How to use this (it is a pattern, remember)

There is nothing to install. The path is:

1. Read [ARCHITECTURE.md](ARCHITECTURE.md) and pick the layers that match your
   actual pain. You do not need all seven on day one.
2. Copy `templates/` into your repo and fill in the `TODO`s.
3. Run `scripts/bootstrap.sh` (or replicate its steps by hand) to wire the
   skeleton: directories, YAML stubs, hook registration, a first timer.
4. Point the reconcilers at your YAMLs, schedule a daily run, and add enforcement
   gates for the commands that are irreversible *for you*.

## Platform support

Linux-first. The scripts are bash + python3, timers are systemd units (cron works
too), and hooks are JSON-over-stdin. Windows equivalents — PowerShell wrappers,
Task Scheduler — are left to the adopter; the pattern itself is
platform-agnostic, only the plumbing differs.

## License

MIT — see [LICENSE](LICENSE).
