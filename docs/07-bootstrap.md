# 07 — Bootstrap: zero to ecosystem

`scripts/bootstrap.sh` takes a directory from nothing to a working skeleton in
one pass. This document is the same walkthrough by hand — read it even if you
run the script, because every step is a decision you are making, not a default
you are accepting.

## What you need before starting

- bash + python3 (Linux-first; adapt paths for macOS, see platform notes below)
- `git`, and `gh` authenticated if you reconcile PRs
- 15 minutes and honest answers to "what should exist here?"

## Step 1 — run the script

```bash
./scripts/bootstrap.sh /path/to/your/ecosystem
```

It creates:

```
<target>/
  state/                  # declared state lives here, in git
    repos.yaml            # from examples/*.yaml.example
    daemons.yaml
    prs.yaml
    rules.yaml
    reconciliation.yaml   # cadence, enabled classes, auto_fix, alerting
    triggers.yaml         # (optional) tool/trigger manifest
  bin/
    drift_git.py          # from templates/*.py.tmpl — skeletons with TODOs
    drift_daemons.py
    drift_reconcile.sh    # orchestrator: runs enabled classes, writes runlog
    lib/
      jsonl.py            # append-only drift.jsonl writer (flock)
      cmd.py              # timeout-aware command runner
      alert.py            # latest-per-key, quiet hours, known_debt
      severity.py         # total ordering — read CASE-STUDIES (c)
      xdg.py              # XDG state/config/data dirs
  systemd/                # drift-reconcile.service/.timer (daily 03:00 UTC)
  logs/  backups/         # runtime output lands here, gitignored
```

Then `cd <target> && git init && git add -A && git commit` — declared state is
versioned from minute one, or it is not declared state.

## Step 2 — edit the four YAMLs that matter

The templates are deliberately full of `TODO`s. The four that gate everything:

1. **`repos.yaml`** — every repo path, remote, default branch. Start with the
   repos you actually touch daily; you can add more later. Each entry is a
   claim a reconciler will test.
2. **`daemons.yaml`** — the processes/timers that must be alive. If you can't
   name the check command (`systemctl is-active …`, `pgrep -f …`), the daemon
   isn't declarable yet — declare it when you can measure it.
3. **`rules.yaml`** — start with TWO rules max: one `command_scan` VIOLATION
   for your most-feared irreversible command, one `REVIEW` for something you
   want visibility on. Rules accrete; they don't arrive wholesale.
4. **`reconciliation.yaml`** — cadence (`daily` is the sane default), enabled
   classes (`[git, daemons]` to start), `meta_sweep.sample_rate: 0.2`.

## Step 3 — first drift run

```bash
cd <target> && bash state/bin/drift_reconcile.sh
```

(or run a single class directly: `python3 state/bin/drift_git.py`).

Expect findings — a fresh ecosystem always has drift; that is the pattern
working, not failing. Read `state/drift.jsonl`. For every finding ask: is this
real? If a finding is wrong, the reconciler has a bug — fix it before wiring
alerting, or you will alert on fiction.

## Step 4 — first meta-sweep

Run the meta-sweep template once by hand (`python3 state/bin/meta_sweep.py`,
after filling its TODOs), or defer it: the *path* existing matters more than
the sample size on day one. Read
[03-meta-verification.md](03-meta-verification.md) before extending it: keep
it small and written differently from the reconcilers.

## Step 5 — wire a daily timer

systemd user timer (Linux):

```ini
# ~/.config/systemd/user/devin-state-reconcile.timer
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now drift-reconcile.timer
```

(The `templates/systemd/drift-reconcile.{service,timer}` pair bootstrap copied
into `state/systemd/` is the same thing, fully commented — install those.)

cron equivalent: `0 3 * * * cd /path/to/ecosystem/state && bash bin/drift_reconcile.sh`. Order matters when you add alerting: reconcile → meta-sweep → alert, so alerts see both legs of "green requires both agree."

## Step 6 — add your first compliance rule and gate

- Pick your most-feared irreversible command. Add it to the gate's scope table
  as **gated**, and add ≥3 real command variants (with wrappers) to the parser
  corpus — harvested from actual transcripts, per the parser-coverage rule.
- Add one `rules.yaml` entry with a `validated_against` anchor you can
  actually produce (a commit SHA, a PR number). Run `compliance.py --self-check`
  against a fixture containing a deliberate violation.

## Step 7 — the first week

Do not touch anything for a week except reading alerts. The first week of a
state-pattern deployment is calibration: which findings are real, which are
reconciler bugs, which deserve `known_debt`. Tune severity→channel and quiet
hours based on what actually annoyed you. A pattern calibrated on real noise
beats a theoretically perfect one.

## Platform notes

- **Linux**: as written — bash, python3, systemd.
- **macOS**: same, with `launchd` plists instead of systemd units; `systemctl`
  checks in `daemons.yaml` become `launchctl list` / `pgrep`.
- **Windows**: PowerShell wrappers and Task Scheduler are left to the adopter —
  the pattern is platform-agnostic; only the plumbing differs. The hook protocol
  (JSON stdin → JSON stdout) and the YAML/JSONL formats carry over unchanged.
