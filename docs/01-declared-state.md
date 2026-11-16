# 01 — Declared state

Layer 1 of the pattern: **versioned YAML as the source of truth for what should
exist.** Everything else in the pattern — reconcilers, meta-sweep, compliance,
gates, alerting — is downstream of this. If the declaration is vague, every
layer above it measures against fog.

## Why YAML, and why versioned

The alternative to declared state is tribal knowledge: "the deploy timer runs at
3am," "repo X is always ahead of main," "we don't gate `npm publish` because it
never broke anything." Tribal knowledge has three failure modes that YAML fixes:

- **It is not reviewable.** A claim in a file gets a diff, a reviewer, and a
  history. A claim in someone's head gets a meeting.
- **It is not measurable.** Reconcilers need a machine-readable "should."
  Prose can be parsed by humans only, and humans are the bottleneck.
- **It rots silently.** When reality changes and the mental model doesn't, the
  gap is invisible until something breaks loudly. A YAML file that disagrees
  with reality is *findable* — `git diff`, a reconcile run, a meta-sweep sample.

Versioned beats tribal knowledge for the same reason tests beat memory: the
claim survives the person who made it.

## What to declare

You do not need to declare everything. Declare the state whose drift would hurt
and whose drift is *measurable*. A starting set:

### `repos.yaml` — the fleet of repositories

```yaml
repos:
  - name: example-service
    path: ~/code/example-service        # TODO: your paths
    remote: git@github.com:you/example-service.git
    default_branch: main
    # expected: clean worktree, not ahead/behind without reason
```

### `daemons.yaml` — processes and timers that must be alive

```yaml
daemons:
  - name: discussion-scout
    check: systemctl --user is-active discussion-scout.timer
    expected: active
    # or: check: pgrep -f scout.py
```

A daemon declared here but dead in reality is `drift_daemons`' job to catch. A
daemon running but *not* declared is scope creep — decide which it is.

### `prs.yaml` — pull requests and their expected lifecycle

```yaml
prs:
  - repo: owner/name
    number: 42
    expect: merged | open | closed
    note: "release prep — TODO owner"
```

### `rules.yaml` — compliance rules

See [04-compliance.md](04-compliance.md). Rules are declared state too: they
say what *behavior* should be, and reconcilers/auditors measure whether it is.

### `reconciliation.yaml` — the measurement schedule itself

```yaml
reconciliation:
  cadence: daily            # or: hourly, on_session_end
  classes: [git, daemons, deps, prs]
  meta_sweep:
    sample_rate: 0.2        # fraction of findings independently re-measured
```

Declaring *how often you measure* matters: an ecosystem reconciled yearly is an
ecosystem that drifts for 364 days.

## `known_debt` and comments are first-class

Two conventions separate a living declaration from a wish list:

### `known_debt` — declared, owned, expiring exceptions

```yaml
known_debt:
  - key: repo:site-behind
    reason: "waiting on upstream fix, tracked in issue #123"
    owner: icaros
    expires: 2026-12-01    # TODO: real date
```

The `expires` field is the point. Debt without expiry is just drift with better
branding — it sits in the declaration forever and the reconciler learns to
ignore it. With expiry, the exception evaporates on schedule and the finding
alerts again if still true. See [06-alerting.md](06-alerting.md).

### Comments carry the *why*

```yaml
repos:
  - name: legacy-exporter
    frozen: true   # TODO: decommission after Q1 migration — decided 2026-10
```

YAML says *what*; the comment says *why* and *who decided*. When the
declaration and reality disagree, the comment is often the only place intent
survives. Write comments for the future you who will wonder why this looks
wrong.

## The one rule that governs all of Layer 1

**The YAML is a claim, not a truth.** Every declaration is a hypothesis that a
reconciler will test against reality. Write declarations you are willing to be
wrong about — because you will be, and the pattern's job is to find out where,
fast. A declaration nobody dares to write is a blind spot with extra steps.

Next: [02-reconcilers.md](02-reconcilers.md) — how reality gets measured.
