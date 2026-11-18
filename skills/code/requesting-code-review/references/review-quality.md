# Review quality: axes, severity, sizing, evidence, dependencies

Reference for every step of the pipeline in `../SKILL.md`. Commands stay in the
skill; this file holds the review criteria and the exact wording of the gates.

## 0. Two stages: spec compliance, then quality

Review in two passes, in this order. Stage 2 means nothing before Stage 1 passes.

**Stage 1 — compliance with the task.** Does the change do what the task, the plan or the issue
asked for? Read the original request, not the author's summary, and verify every requirement.

| Category | What it is | How to verify |
|---|---|---|
| Missing | A requested feature, state or error path is absent | Walk the requirements line by line against the diff |
| Incorrect | Present, but behaves differently: wrong default, wrong sort order, wrong status code | Run the scenario, or read the call path that implements it |
| Extra | Scope creep: unrequested features, speculative abstractions, premature optimization | Compare every added abstraction with the stated requirement |

**Verdict format.** Stage 1 reports PASS or ISSUES with the category of each issue (missing /
incorrect / extra). Only PASS moves the review to Stage 2 — the five axes, severity and evidence
below. **A failed Stage 1 stops the review:** reviewing the quality of code that implements the
wrong task wastes the whole pass, and a refactor suggestion may target code that should not exist
at all.

## 1. Five axes

Every review walks the same five axes, and every finding names its axis. Two or
three questions per axis are enough — a review is not an essay.

| Axis | Questions | Blocks merge when |
|---|---|---|
| Correctness | Does the change do what the task says? Are empty, null, boundary and error paths handled? Would a test fail if the code were wrong? | A user flow breaks or data is lost |
| Readability | Can a reader understand it without the author? Are names and structure consistent with the project? Is the control flow visible? | The reader cannot tell what the code does |
| Architecture | Does it follow existing patterns, or introduce a new one — justified? Are module boundaries and dependency direction intact? Is the abstraction level right? | A new pattern is unjustified, a layer is bypassed, a cycle appears |
| Security | Is input validated at the boundary? Are secrets out of code and logs? Are permissions checked? Are queries parameterized? | A vulnerability is reachable without protection |
| Performance | Any N+1, unbounded loop or fetch, sync work that should be async, missing pagination, avoidable re-renders? | Noticeable degradation on real data |

A "no" answer is a candidate finding, not an automatic blocker: check it against
the callers, guards and tests that reach the changed code, and drop it if they
rule it out. A finding that already existed in the base is reported separately
from a regression this change introduces. Zero findings is a valid outcome.

## 2. Severity labels

Every finding gets a label that tells the author what is required and what may
be ignored.

| Label | Meaning | Author action |
|---|---|---|
| Critical | Security vulnerability, data loss, broken functionality | Blocks merge: no APPROVE while it stands |
| Required | Missing test, missing error handling, wrong abstraction | Fix before merge, or defer explicitly with a reason |
| Optional | Simpler design, useful refactor, not required | May ignore — the owner decides |
| Nit | Formatting, naming taste within project rules | May ignore |
| FYI | Context for future work | No action |

Rules:

- **Critical blocks merge.** An APPROVE with an open Critical issue is a review
  failure, not a judgement call.
- Unlabeled feedback reads as "everything is mandatory" and burns the author's
  time on optional suggestions.
- Order findings by leverage: correctness and security first, then structural
  problems, then the rest. One structural problem and ten nits — the structural
  problem *is* the review.
- A finding without a measurement is a potential impact, not a measurement:
  "this may get slower" is not a finding; "N+1 on a 1000-row list adds ~50 ms per
  item" is. Never invent numbers.

## 3. Change sizing

```
~100 changed lines  → good, reviewable in one sitting
~300 changed lines  → acceptable only as one logical change
>1000 changed lines → too large, split before review
```

- A file pushed past ~1000 **total** lines is a decomposition signal (distinct
  from changed lines): extract helpers, subcomponents or modules first, then add.
- **Feature work and refactoring go into separate commits.** A diff doing both
  is two changes; mechanical renames may ride along at the reviewer's discretion.
- Too large — pick one of two splitting strategies:
  - **By file group** — separate changes for groups with different reviewers or
    ownership (cross-cutting work).
  - **Vertical slices** — thin end-to-end slices of one feature, each shippable
    and testable on its own.

## 4. Verification Story

APPROVE is not accepted without the author's evidence. The story must state:

- what was run — command, key output, exit code (not "tests pass");
- whether the build succeeds — command and exit code;
- for UI changes — a screenshot or a measured number (console error count, HTTP
  statuses, DOM node count); "looks fine" is not evidence;
- for a bug fix — the regression test fails before the fix and passes after;
- for a performance change — before/after numbers taken the same way and under
  the same conditions.

No story — REQUEST CHANGES. "I will check it later" is not a verification story.

## 5. Mutation check

Test the tests by experiment, not by reading:

1. Copy the file the change touches.
2. Invert one condition the change adds: drop a `!`, swap `&&` for `||`, change
   `>=` to `>`.
3. Run the suite.
4. Restore the file from the copy.

A mutation that stays green is a finding: name the test case that is missing.
Never leave the mutation in the tree.

## 6. Dependency discipline

Before adding a dependency: does the existing stack solve this? How large is it?
Is it actively maintained? Does it have known vulnerabilities? Is the license
compatible? Prefer the standard library and existing utilities — every
dependency is a liability.

Upgrading is a code change like any other:

1. **Read the changelog, not just the version number.** Semver is a promise the
   maintainer may not have kept; a "patch" can carry a behavior change. For a
   major bump, read the migration notes and find what breaks.
2. **One dependency per change.** When a bulk bump breaks the build you cannot
   tell which package did it; a single change has an obvious cause and a clean
   revert.
3. **Let the tests decide.** Green before and after, not "it installed". Thin
   coverage around the dependency's behavior is the real finding — add a test
   first.
4. **Read the lockfile diff, not just the manifest.** One direct bump can pull
   in dozens of transitive changes. Commit the lockfile and never hand-edit it.
5. **Run the audit before release** — `npm audit --audit-level=high`, `pip-audit`
   or the project's equivalent — and triage what is reachable. **An audit catches
   only known CVEs**: a typosquat or a newly malicious package passes green.

## 7. Review report block

Besides findings, the report answers three questions:

- **What changed** — files and behavior, not just a file list.
- **What was deliberately not touched** — known problems left out of scope, with
  the reason.
- **Risks and assumptions** — what can break after merge and what the author
  assumed.

## 8. Do not lower the bar

A red gate is not fixed by skipping the failing test, adding a suppression or
lint-ignore, lowering a threshold, or deleting the assertion. If the bar cannot
be met, report the failure and its reason. The only legitimate way to green is
to fix, or to defer explicitly with the owner's decision.

## 9. Receiving review

A finding is a hypothesis to verify, not an instruction to execute.

- **Restate before changing.** Put the comment in your own words and check it against the code:
  "You are saying the query runs once per row, not once per page — is that the claim?" If the
  restatement is wrong, the fix would be wrong too.
- **Verify, then agree or disagree with evidence.** Do not answer "agreed" before running the
  check: a wrong finding accepted politely is a regression. Disagreement has a shape — fact,
  evidence, alternative: "This query is bounded to 50 rows (`schema.ts:12`), so the filter is
  O(50); here is the profile" beats "I don't think that's necessary".
- **No agreement theater.** "Great catch!", "You're absolutely right!" add no information and hide
  whether the code was actually checked. The fix and the test that proves it are the response.
- **One finding at a time, verified.** Fix it, run the gate, report the evidence; then take the
  next one. If a fix cannot be verified, say so and name what is missing instead of claiming
  "should be fixed".
