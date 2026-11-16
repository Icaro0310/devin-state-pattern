# 04 — Compliance (`rules.yaml`)

Layer 4: conventions become rules. Reconcilers measure *state*; compliance
measures *behavior* — did the agent follow the rules while producing that
state? The distinguishing feature: **evidence, not checkboxes.**

## Why evidence anchors matter

"I followed the commit-trailer rule" is a claim. "Commit `a1b2c3d` on PR #57
ends with the required trailer" is evidence. The difference is not pedantry —
it is the difference between an audit and a vibe. Every rule must name the
`validated_against` artifact that would prove it was followed; if no such
artifact can exist, the rule is unenforceable and should be rewritten or
dropped.

## `rules.yaml` structure

```yaml
rules:
  - id: R-commit-trailer
    description: "every commit ends with the Devin/QA trailer"
    check_type: command_scan        # how compliance verifies it
    severity: VIOLATION
    scope: session                  # session | repo | global
    validated_against:
      kinds: [commit_sha, pr_number]
      pattern: "Generated with \\[Devin\\]"
    # a session is compliant when each commit it produced can be pointed to
    # (a SHA) and shown to match (the trailer pattern)

  - id: R-no-force-push
    description: "no force-push to shared branches"
    check_type: command_scan
    severity: VIOLATION
    scope: session
    validated_against:
      kinds: [command_log, pr_number]
      deny_pattern: "push\\s+.*--force"

  - id: R-pr-evidence
    description: "merged PRs link the issue they close"
    check_type: api_state
    severity: REVIEW
    scope: repo
    validated_against:
      kinds: [pr_number, url]
      require: "closing_issue_reference"
```

### Fields

- `id` — stable, `R-` prefixed. Compliance output and alerts reference it.
- `check_type` — dispatches to a checker implementation:
  - `command_scan` — parse the session's command log for patterns.
  - `file_glob` — check files exist/absent/match in the working tree.
  - `api_state` — query a live API (GitHub, your platform) for the declared
    state of a resource.
  - `manual_evidence` — requires a human/agent to attach an artifact; used for
    rules no scanner can verify.
- `severity` — `REVIEW` (worth a look, digest-level alert) or `VIOLATION`
  (must be justified or fixed, page-level alert). See
  [06-alerting.md](06-alerting.md) for severity→channel mapping.
- `validated_against` — the evidence contract: what *kinds* of anchors close
  the rule (`commit_sha`, `pr_number`, `url`, `path`, `tool_name`,
  `command_log` entry) and what they must show (`pattern`, `require`,
  `deny_pattern`).

## REVIEW vs. VIOLATION

- **VIOLATION** — the rule was broken and the evidence shows it. Blocks "green"
  until resolved or justified via `known_debt`.
- **REVIEW** — ambiguous: the checker found something a human should look at
  (a force-push that was later reverted, a PR merged without the link but with
  a comment explaining why). REVIEW never blocks green by itself; it accumulates
  in digests.

The distinction matters for signal vs. noise: if every ambiguity pages someone,
nothing does.

## Session hooks integration

Compliance runs at session end via a hook (Stop/SessionEnd, depending on your
agent runtime). The hook:

1. Collects the session's artifacts: command log, files touched, commits
   produced, PRs opened/merged, tool calls made.
2. Loads `rules.yaml`, dispatches each rule by `check_type`.
3. For each rule, emits a finding: `{rule_id, status: PASS|REVIEW|VIOLATION,
   validated_against: <evidence or null>, detail}`.
4. Appends non-PASS findings to the same `drift.jsonl` stream
   (`class: "compliance"`, `key: "rule:R-…/session:…"`) so alerting treats them
   uniformly.

A VIOLATION without `validated_against` evidence is itself suspicious — the
pattern's answer is to downgrade it to REVIEW with a note, because an
unverifiable violation claim is noise.

## The `--self-check` pattern

Every compliance implementation should ship a `--self-check` mode that runs the
rules against a *known-bad fixture*: a synthetic session containing deliberate
violations. If self-check doesn't flag the fixture, the checker is broken — and
that failure is itself a finding.

```bash
python3 compliance.py --self-check
# expected: flags fixture session F-001 for R-no-force-push, R-commit-trailer
# actual:   ...compare, exit non-zero on mismatch
```

Self-check is the compliance layer's meta-sweep: it verifies the verifier
without needing the full meta-sweep machinery. Run it in CI on every change to
a checker or to `rules.yaml`.

## Adding a rule — checklist

1. Write the rule so a scanner *could* verify it. If it requires judgment,
   that's `manual_evidence` — say so explicitly.
2. Name the `validated_against` kinds and the pattern/requirement.
3. Pick severity honestly: VIOLATION means "this must never happen without a
   declared exception."
4. Add a fixture to `--self-check` covering both the violating and the
   compliant case.
5. Declare any standing exceptions in `known_debt` with `expires` — never by
   weakening the rule globally.

Next: [05-enforcement-gates.md](05-enforcement-gates.md) — stopping bad actions
before they happen.
