# Contributing — adapting the pattern

This is a pattern, not a framework. "Contributing" here means "here is how to
make it yours." There is no plugin API and no release cadence; there are
templates, docs, and a bootstrap script.

## Step 1 — decide which layers you need

You do not need all seven on day one. A reasonable order of adoption:

| If your pain is… | Start with |
|---|---|
| "I don't know what state my ecosystem is supposed to have" | Layer 1 (declared state) + Layer 2 (one reconciler) |
| "Things drift and nobody notices for weeks" | Layer 2 + Layer 3 (meta-sweep) |
| "Conventions exist but aren't enforced" | Layer 4 (compliance rules) |
| "Agents run destructive commands" | Layer 5 (enforcement gates) |
| "Alerts are noise and get muted" | Layer 6 (alerting discipline) |
| "Nothing exists yet" | Layer 7 (`scripts/bootstrap.sh`) |

Read [ARCHITECTURE.md](ARCHITECTURE.md) first; it explains how the layers
compose. [CASE-STUDIES.md](CASE-STUDIES.md) explains why each exists.

## Step 2 — copy the templates

```
templates/
  drift-*.py.tmpl          # reconciler + gate skeletons (TODO-marked)
  drift_reconcile.sh.tmpl  # orchestrator: runs enabled classes
  systemd/                 # daily timer + oneshot service
lib/                       # jsonl, cmd, alert, severity, xdg utilities
examples/                  # sanitized *.yaml.example manifests
scripts/
  bootstrap.sh             # scaffolds the whole skeleton in a target dir
  validate.sh              # the pattern tests itself
```

Copy what you need into your repo (or a dedicated `state/` directory). Fill in
every `TODO` — the templates are deliberately explicit about what you must
decide: which repos exist, which daemons must be alive, which commands are
gated.

## Step 3 — run bootstrap (or its steps by hand)

```bash
./scripts/bootstrap.sh /path/to/your/ecosystem
```

It creates the state directory, installs template YAMLs, registers hooks with
your agent runtime, installs a daily timer (systemd; cron works too), and runs
a first reconciliation pass so you see real output immediately. Read
[docs/07-bootstrap.md](docs/07-bootstrap.md) if you want to do it manually or on
a non-Linux platform.

## Step 4 — point reconcilers at your YAMLs

Each `drift_*` class reads the declarations it owns and measures reality.
Adaptation is mostly configuration: paths, remotes, process names, API
endpoints. Two rules that are not optional:

- **Measure reality, not logs.** If your reconciler reads a log file as its
  source of truth, it is measuring a claim, not a fact.
- **Append-only output.** Write findings to `drift.jsonl`; never rewrite
  history.

See [docs/02-reconcilers.md](docs/02-reconcilers.md) for the output schema and
the write-vs-skip rules.

## Step 5 — add gates for *your* irreversible commands

The scope table is the important artifact: list the commands that are
irreversible *for you* (force-push, `rm -rf`, deploys, publishes, schema drops)
as **gated**, and everything else as **rule-only**. Then apply the
parser-coverage rule: harvest 3+ real command variants per class from your
actual agent transcripts — including the wrappers your agents really emit —
before trusting the gate. See
[docs/05-enforcement-gates.md](docs/05-enforcement-gates.md).

## Step 6 — validate

- `scripts/validate.sh` (or your equivalent) checks that YAML parses, hooks
  return valid JSON, and the JSONL schema is intact.
- Run one full cycle manually: reconcile → meta-sweep → compliance → alert.
  Read the output like you would read a colleague's bug report: does it match
  what you know is true?

## What "done" looks like

Not "everything is green" — that is the trap this pattern exists to avoid.
Done is: declared state exists in git, at least one reconciler measures real
reality on a schedule, meta-sweep independently re-checks it, irreversible
commands are gated at command time, and alerts have survived contact with real
noise (dedup, quiet hours, `known_debt` with expiry).

## Filing things

Issues and PRs welcome. Because this repo documents a *pattern* rather than
shipping a framework, the most useful contributions are:

- New `drift_*` class proposals (with the reality it measures, not logs).
- Parser-coverage corpora: real command/transcript variants that broke a gate.
- Case studies — especially false-greens. [CASE-STUDIES.md](CASE-STUDIES.md)
  is the heart of the repo; more of them make it stronger.
- Platform notes: Windows/PowerShell or macOS equivalents for the plumbing.
