# 05 — Enforcement gates

Layer 5: compliance audits tell you what happened; gates decide what is allowed
to happen. For **irreversible** actions — force-push, `rm -rf`, deploys,
publishes, schema drops, billing changes — a post-hoc report is a post-mortem.
The gate runs *before*, at command time, and can say no.

## The PreToolUse hook protocol

Agent runtimes that support tool-call interception (the pattern was built
against a PreToolUse-style hook; the protocol generalizes) send the proposed
tool call to your hook as JSON on stdin:

```json
{
  "tool_name": "exec",
  "tool_input": {"command": "git -C ~/repos/site push --force origin main"}
}
```

Your hook responds with a permission decision on stdout:

```json
{"permissionDecision": "deny", "reason": "force-push to shared branch is gated (R-no-force-push); justify or use known_debt"}
```

Decisions: `allow`, `deny`, `ask` (defer to a human). The hook must be **fast**
(it sits in the agent's hot path) and **total** (every input gets a decision —
default `allow` for unknown tools is a choice you make consciously; default
`deny` for gated classes is the fail-safe choice).

## Command-position matching

The naive gate greps the command string for `push --force`. That misses
everything that isn't literally spelled that way. Real gates parse the command
into its *command positions* — the actual executables that will run — and match
rules against those positions.

A command line is not one command. It is a tree:

```
sudo env FOO=1 git -C /repo push --force origin main && echo done | tee log
└─┬─┘   └──┬──┘          └──────────┬──────────┘    └──┬──┘
 sudo    env wrapper            git push --force   pipeline second stage
```

Every leaf that resolves to an executable is a position to check. Wrappers
recurse: `sh -c '…'` means parse the *inner* string; `xargs`, `find -exec`,
`parallel` mean the wrapped command is data, not a position — but the wrapper
itself may be gated.

## Coverage: the wrappers agents actually emit

CASE-STUDIES.md (e) is the canonical failure: the parser handled `git push
--force` and missed `git -C repo push --force`, `git --git-dir=… push
--force`, `sh -c 'git push --force'`, `sudo git push --force`. Each wrapper is
trivial; the *set* is unbounded unless you harvest it.

The **parser-coverage rule**: for every gated command class, maintain a corpus
of ≥3 real variants collected from actual agent transcripts/logs — including
the wrappers your agents really emit — and a test that runs the gate against
all of them. Re-harvest periodically; the distribution drifts as models and
runtimes change. A gate tested only against imagined inputs is a gate tested
against the author's imagination.

Wrappers to expect in the wild:

| Wrapper | What it does to parsing |
|---|---|
| `sh -c '…'`, `bash -c '…'` | inner string is a new command line — recurse |
| `sudo`, `doas` | strips to the real command — recurse past it |
| `env VAR=… cmd` | strips assignments — recurse |
| `xargs`, `parallel` | command is an argument, not a position — gate the wrapper or the payload pattern |
| `git -C <path>`, `--git-dir=`, `--work-tree=` | global flags precede the subcommand — consume them |
| `cmd1 && cmd2`, `cmd1 \| cmd2`, `;` | multiple command lines — check each |
| `nohup`, `timeout`, `nice` | prefix wrappers — recurse |

## The scope table: gated vs. rule-only

Not everything gets a gate — gating everything trains agents to route around
the gate. The scope table classifies commands:

| Class | Examples | Treatment |
|---|---|---|
| **Gated** | `push --force`, `push --delete` to shared refs, `rm -rf` outside temp dirs, `DROP TABLE`, `gh release delete`, billing/API-key changes, force-push equivalents in other VCS | `deny` by default; `allow` only with explicit justification token or human `ask` |
| **Rule-only** | normal `git push`, `npm install`, file edits, read-only API calls | `allow`, but logged so compliance ([04](04-compliance.md)) can audit the session afterwards |
| **Always allow** | `ls`, `cat`, `git status`, searches | fast-path allow; no log spam |

The table is declared state — put it in YAML next to `rules.yaml` so the gate,
the docs, and the auditors all read the same classification. When you add a
command to gated, add a corpus variant to the parser tests in the same commit.

## Why gates beat post-hoc audits for irreversible actions

An audit answers "what happened?" A gate answers "may this happen?" For actions
whose blast radius exceeds what an alert can undo — a force-push that orphans
collaborators' work, an `rm -rf` on the wrong path, a published release — the
timeline matters:

```
audit:   propose → execute → damage → detect → report → human reacts → too late
gate:    propose → DENY → human/agent justifies or picks another path
```

Gates are not a replacement for compliance auditing — they are the complement.
Gates stop the irreversible; compliance audits everything the gates let through,
because a gate that allows is a claim that still needs evidence.

## Honest limitations

- **Gates can be worked around.** A determined or confused agent finds an
  unlisted wrapper, encodes the command, or achieves the same effect through a
  different tool. Gates raise the cost of irreversible mistakes; they do not
  make them impossible. Pair every gate with compliance auditing of what it
  allowed.
- **False denies are real.** A gate that blocks legitimate work teaches agents
  to fear it — and then the `ask` path becomes noise. Tune the scope table
  against real transcripts, not against what seems dangerous in the abstract.
- **The parser rots.** New wrappers appear as runtimes evolve. The corpus rule
  is the maintenance contract: no corpus, no trust.

Next: [06-alerting.md](06-alerting.md) — turning findings into signal.
