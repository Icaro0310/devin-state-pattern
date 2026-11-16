# Case studies

Six bugs, all found in a production multi-repo agent ecosystem — a fleet of
coding agents, scheduled jobs, and daemons whose state was tracked by exactly the
kind of pattern described in [ARCHITECTURE.md](ARCHITECTURE.md). Every one of
them shares the same shape: **the system reported zero violations while reality
was quietly wrong.** These are not hypotheticals; each one is a false-green that
survived for days or weeks because nothing was measuring the right thing.

Read them as a set. Individually they are small bugs. Together they are the
argument for the pattern.

---

## (a) Behind vs. unpushed: the reconciler only looked one way

**Symptom.** A site repository sat 9 commits behind its remote for an unknown
number of days. No alert fired. The drift report was clean.

**Root cause.** The `drift_git` reconciler measured *unpushed* commits — local
commits not yet on the remote — because that was the direction the author
imagined mattered ("did the agent forget to push?"). It never measured *behind* —
remote commits the local clone had not fetched. A repo can be perfectly synced
in one direction and arbitrarily stale in the other.

**Why naive approaches miss it.** The check that existed was real and it worked;
it just answered a narrower question than the name `drift_git` implied. And even
had it measured "behind," a second subtlety lurked: `git status` compares against
the *local* remote-tracking ref, which is only as fresh as the last `git fetch`.
Measure "behind" without fetching first and you get a false green built on stale
refs — the reconciler confidently reporting "0 behind" against a remote-tracking
branch from last Tuesday.

**The lesson.** A repo is symmetric: measure both directions (ahead *and*
behind), and `git fetch` *before* measuring, never after. State the direction
each check covers in the finding's `detail`, so "clean" means "clean in the
directions we actually measured."

---

## (b) `dependabot[bot]` vs. `app/dependabot`: the filter matched a name that does not exist

**Symptom.** Fifteen dependabot PRs were double-counted in the PR reconciler's
totals — once as "bot PRs" and once as regular PRs — inflating open-PR counts
and polluting per-author breakdowns for weeks.

**Root cause.** The bot filter matched the login string `dependabot[bot]` — the
shape GitHub uses for user-account bots — but dependabot's canonical login via
the API is `app/dependabot`. The filter never matched anything; every dependabot
PR fell through to the "human/other" bucket, and a second code path that
deduplicated "known bot" PRs by a different identifier counted them again.

**Why naive approaches miss it.** The code looked correct, the tests (written
against the same wrong assumption) passed, and the totals were *plausible* — just
wrong. Nobody audits a count that looks reasonable. The bug was invisible
precisely because it produced output in the expected format.

**The lesson.** Use canonical identifiers and verify them against API reality,
not against memory or convention. When you filter on an external system's
identity (bot logins, app slugs, status enums), write a probe that prints what
the API *actually returns* and assert against that — once, at startup, loudly.

---

## (c) `MIGRATED` never promoted: the severity ordering had a hole exactly where it mattered

**Symptom.** Across every run the reconciler had ever produced, the count of
`MIGRATED` findings was **zero**. Not because nothing had migrated — because the
status could never survive aggregation.

**Root cause.** Findings per key were aggregated by "worst status wins," with
the accumulator initialized to `"OK"` and promotion defined by a strict ordering
like `OK < REVIEW < VIOLATION < MIGRATED` — except `MIGRATED` sat *outside* the
ordering used for comparison. Any finding worse than `OK` promoted correctly;
`MIGRATED`, being compared through a path that only knew the first four values,
was silently treated as non-promoting. First-write-wins on ties plus an init of
`"OK"` meant the hole was invisible: no error, no warning, just a status that
mathematically could not appear in output.

**Why naive approaches miss it.** The ordering *looked* total. Every status in
the enum had a place in the docs; the implementation's comparison table simply
never included the fifth value. And since `MIGRATED` is a rare, terminal-ish
state, its absence produced no anomalies — a counter reading zero looks like a
healthy system.

**The lesson.** Initialize severity accumulators to `None` (or a sentinel below
every real status), not to `"OK"` — `"OK"` is a *conclusion*, not a starting
point. Make the ordering explicit and *total*: every status must be comparable
to every other status, and a test should assert that every enum member appears
in the ordering table. Severity bugs hide forever because their symptom is a
plausible-looking zero.

---

## (d) `message_nodes` duplicates: the input was polluted before measurement began

**Symptom.** A transcript-analytics reconciler reported ~5000 session messages
across the fleet when only 2352 were unique. Every duplicate spawned its own
"claim" (a session asserting it had done work), inflating activity metrics and
generating phantom compliance findings.

**Root cause.** The sessions database had a "restored session" mechanism that
re-inserted prior transcript rows under new IDs instead of referencing them.
`message_nodes` — the table the reconciler read — contained each restored
message twice: once under the original node ID, once under the copy. The
reconciler counted rows; nobody had told it that rows are not messages.

**Why naive approaches miss it.** Row counts are the most natural thing to
measure, and they were *accurate* — the database really did contain 5000 rows.
The measurement was correct and the conclusion was wrong, because the input had
duplication semantics baked in upstream. Deduplication lived in the write path's
imagination, not in the data.

**The lesson.** Inputs are polluted. Before measuring, ask what the storage
layer's invariants actually are — and dedup on the *content identity* (message
hash, session+sequence, canonical ID), not the storage identity (rowid, node
ID). A reconciler that trusts its input's uniqueness is measuring the input's
bugs, faithfully, forever.

---

## (e) `git -C` walked past the regex: the parser covered what its author imagined

**Symptom.** Destructive git commands executed through several wrapper forms
escaped every enforcement gate. `git -C /repo push --force`, `git --git-dir=…
push --force`, `sh -c 'git push --force'`, and `sudo git push --force` all
returned `allow`. The gate's tests were green; the ecosystem was not.

**Root cause.** The command parser matched `git` at a fixed position with a
fixed flag shape. Real agent transcripts — the actual distribution of commands
agents emit — contained forms the author never imagined: git's global options
(`-C`, `--git-dir`, `--work-tree`) appearing between `git` and the subcommand,
shell wrappers re-parsing the inner string, `sudo`/`env`/`xargs` prefixing the
real command, `&&`/`|` chaining a second command after a benign first one.

**Why naive approaches miss it.** Each individual wrapper is trivially handled
— the bug is *coverage*. The parser was tested against the commands the author
thought of, which is the same set the parser was written to handle. Tests
written from imagination cannot find what imagination missed. This is the
parser-coverage problem: a parser's correctness is bounded by the diversity of
inputs it was validated against, and agents produce inputs from a distribution,
not a spec.

**The lesson.** Adopt a parser-coverage rule: for every command class, validate
against **3+ real variants harvested from actual transcripts/logs**, including
the wrappers agents actually emit (`sh -c`, `sudo`, `env VAR=…`, `&&`, `|`).
Re-run the harvest periodically — the distribution drifts as agents and models
change. A gate that parses is only as good as its corpus.

---

## (f) `search()` found one tool per line: the multi-tool line lost data

**Symptom.** Compliance auditing of agent sessions under-counted tool usage:
lines where an agent invoked `exec` *and* `mcp_call_tool` together recorded only
the first tool. `tool_name` fields went missing for every second-and-later
marker on a line, silently dropping evidence the rules needed.

**Root cause.** The transcript parser used a single-match search (`.search()`)
to find `[tool:…]` markers per line. One line, one match, rest ignored. Agent
output routinely packs multiple tool calls per line (parallel tool use is the
default in most agent runtimes), so the parser structurally could not see more
than the first marker.

**Why naive approaches miss it.** Single-match search is the obvious first
implementation, it works on every test fixture the author wrote (which
contained one tool per line, because the author imagined one tool per line),
and the failure mode is *missing data* — which looks like "fewer tools were
used," i.e., benign. Absence of evidence reads as evidence of absence.

**The lesson.** `search()` is not `finditer()`. When parsing any repeated
structure, enumerate *all* matches and assert the count: if the format allows
N occurrences per line, the parser must produce N records or explicitly record
the truncation. The general form: **measure multiplicity, don't assume it.**

---

## What these have in common

Strip away the specifics and every case is the same bug wearing different
clothes: **the system said zero violations while being structurally incapable
of seeing the violation.**

- (a) measured one direction of a symmetric relation.
- (b) filtered on an identifier that did not exist in reality.
- (c) had a status the aggregation could not express.
- (d) counted storage rows that were not the thing being measured.
- (e) parsed the commands its author imagined, not the ones agents emit.
- (f) matched the first occurrence of a structure that occurs many times.

None of these produced errors. None crashed. All of them produced *plausible
output* — counts, statuses, clean reports — that happened to be wrong. That is
what makes them dangerous: a loud failure gets fixed; a quiet false-green gets
believed. And belief is what scales: one unchecked assumption in a reconciler
becomes a hundred unchecked conclusions downstream, because every layer above
the measurement trusts it.

Three mechanisms in the pattern exist specifically to break this shape:

1. **Meta-verification** ([docs/03-meta-verification.md](docs/03-meta-verification.md)).
   An independent re-measurement of what reconcilers claim catches the whole
   class of "the check itself is wrong" — cases (b), (c), and (e) would each
   have been caught the first time meta-sweep sampled them, because an
   independent measurement does not share the original's blind spot.

2. **`validated_against` evidence** ([docs/04-compliance.md](docs/04-compliance.md)).
   Requiring a pointer to where reality shows the claim — a PR number, a SHA,
   a URL — converts "the system believes it" into "here is where you can look."
   Case (d)'s phantom claims could not have produced evidence anchors; the
   requirement itself exposes the inflation.

3. **The parser-coverage rule** ([docs/05-enforcement-gates.md](docs/05-enforcement-gates.md)).
   Validate parsers against harvested real inputs, not imagined ones, with a
   minimum corpus per class. Cases (e) and (f) are the same failure — coverage
   bounded by imagination — and the same fix.

The punchline: **the pattern does not prevent the bug. It prevents the bug from
staying invisible.** Reconcilers will always have blind spots; parsers will
always miss a wrapper someone didn't think of; aggregations will always have an
edge case. What the pattern removes is the *silence* — the gap between "broken"
and "known to be broken." A measured, alerted, meta-verified ecosystem fails
loudly and gets fixed. An unmeasured one fails green and gets believed.
