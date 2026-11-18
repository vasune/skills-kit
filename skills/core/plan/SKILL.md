---
name: plan
description: Write a markdown plan before executing; do not build.
version: 2.3.0
author: fhfqndj
license: MIT
platforms: [linux, macos, windows]
metadata:
  tags: [planning, plan-mode, implementation, workflow, design, documentation]
  related_skills: [test-driven-development, requesting-code-review, verification-before-completion, subagent-driven-development, brainstorming]
---

# Plan Mode

Use this skill when the user wants a plan instead of execution.

If the goal is not agreed yet, run `brainstorming` first: a plan built on a guessed goal gets rewritten whole.

## Core behavior

For this turn, you are planning only.

- Do not implement code.
- Do not edit project files except the plan markdown file.
- Do not run mutating shell commands, commit, push, or perform external actions.
- You may inspect the repo or other context with read-only commands/tools when needed.
- Your deliverable is a markdown plan saved inside the active workspace, by default under the plan directory `plans/` (the plan directory and its path are set by the host).

## Output requirements

Write a markdown plan that is concrete and actionable.

Include, when relevant:
- Goal
- Current context / assumptions
- Proposed approach
- Step-by-step plan
- Files likely to change
- Tests / validation
- Risks, tradeoffs, and open questions

If the task is code-related, include exact file paths, likely test targets, and verification steps.

## Save location

Save the plan (write the file) under:
- `plans/YYYY-MM-DD_HHMMSS-<slug>.md`

Treat that as relative to the active working directory / workspace root: a relative path keeps the plan with the workspace on local, remote and container backends alike.

**The active directory is not always the project being planned.** If the session runs from a different repo or vault than the one the plan is about (for example the vault is open, while the target is a project in another directory), `plans/` under the CWD drops the plan into the wrong repository. Save by absolute path inside the target project — `<repo>/plans/YYYY-MM-DD_HHMMSS-<slug>.md` — and state that path in the reply. `plans/` is usually untracked: either add it to `.gitignore` or leave the plan out of the index, and say which you did.

If the runtime provides a specific target path, use that exact path. The exact plan directory is set by the host itself.
If not, create a sensible timestamped filename yourself under `plans/`.

## Existing plans: never start from a clean sheet

Before writing a new plan, check for unchecked items in the plans that already exist: `grep -rn '^- \[ \]' plans/*.md`.

- The new work extends an open plan → update it in place, or carry its unchecked items into the new plan with a link to the old file.
- It is unrelated work → carry the open items into the new plan as an explicit tail ("inherited from `<plan>`: N open items") or ask the user where they should go. Do not silently start clean: the open items may be mid-build in another session.
- Never delete, overwrite, or rename another plan's file to make room.

## Interaction style

- If the request is clear enough, write the plan directly.
- If no explicit instruction accompanies `/plan`, infer the task from the current conversation context.
- If it is genuinely underspecified, ask a brief clarifying question instead of guessing.
- After saving the plan, reply briefly with what you planned and the saved path.

### The user is thinking out loud — do not execute, do not write a plan file

Openings like "что будем делать?", "сегодня план такой…", "приступать не надо, просто думаю" mean conversational mode, not plan mode either: only reading and reconnaissance, and the reply is analysis — order of work, risks, and the decisions that stay with the user. Starting the work or creating `plans/*.md` is allowed on an explicit request only.

Before answering, rebuild the state from facts, never from memory alone: tail of `workspace/RUNS.md`, `git status --short --branch` for every active repo, the most recent session from past-session history (read its last messages), and `grep '^- \[ \]'` over `plans/*.md` for unchecked items. Only then propose what to do next.

Lay the options out as a numbered list in the message, not through a blocking question form: on an open "what shall we do" question the form sits waiting for up to an hour and leaves the turn unfinished, while text asks the same and does not block.

---

# Writing the Plan Well

The rest of this skill is the craft of authoring a *good* implementation plan — the content that goes inside the markdown file above.

## Overview

Write comprehensive implementation plans assuming the implementer has zero context for the codebase and questionable taste. Document everything they need: which files to touch, complete code, testing commands, docs to check, how to verify. Give them bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume the implementer is a skilled developer but knows almost nothing about the toolset or problem domain. Assume they don't know good test design very well.

**Core principle:** A good plan makes implementation obvious. If someone has to guess, the plan is incomplete.

## When a Full Implementation Plan Helps

**Always use before:**
- Implementing multi-step features
- Breaking down complex requirements
- Delegating to subagents via subagent-driven-development

**Don't skip when:**
- Feature seems simple (assumptions cause bugs)
- You plan to implement it yourself (future you needs guidance)
- Working alone (documentation matters)

## Bite-Sized Task Granularity

**Each task = 2-5 minutes of focused work.**

Every step is one action:
- "Write the failing test" — step
- "Run it to make sure it fails" — step
- "Implement the minimal code to make the test pass" — step
- "Run the tests and make sure they pass" — step
- "Commit" — step

**Too big:**
```markdown
### Task 1: Build authentication system
[50 lines of code across 5 files]
```

**Right size:**
```markdown
### Task 1: Create User model with email field
[10 lines, 1 file]

### Task 2: Add password hash field to User
[8 lines, 1 file]

### Task 3: Create password hashing utility
[15 lines, 1 file]
```

## Task Size and Slicing

Size every task before writing it: XS–XL by number of files. L is split, and XL is split before it enters the plan — an implementer does best on S and M. A feature that spans UI and API is sliced vertically: one end-to-end path at a time, not "all backend, then all API, then all UI".

The sizing table, the four split triggers and the bad/good slicing example — `references/slicing.md`.

## Plan Document Structure

### Header (Required)

Every plan MUST start with:

```markdown
# [Feature Name] Implementation Plan

> **For the implementing agent:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

### Task Structure

Each task follows this format:

````markdown
### Task N: [Descriptive Name]

**Objective:** What this task accomplishes (one sentence)

**Acceptance criteria** (2–3 checkable items, not more):
- [ ] [Specific, testable condition]
- [ ] [Specific, testable condition]

When a criterion has more than one condition, write it as a Given/When/Then scenario — the format is in `brainstorming/references/spec-template.md` §7.

**Files:**
- Create: `exact/path/to/new_file.py`
- Modify: `exact/path/to/existing.py:45-67` (line numbers if known)
- Test: `tests/path/to/test_file.py`

**Step 1: Write failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

**Step 2: Run test to verify failure**

Run: `pytest tests/path/test.py::test_specific_behavior -v`
Expected: FAIL — "function not defined"

**Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

**Step 4: Run test to verify pass**

Run: `pytest tests/path/test.py::test_specific_behavior -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## Writing Process

### Step 1: Understand Requirements

Read and understand:
- Feature requirements
- Design documents or user description
- Acceptance criteria
- Constraints
- **Any earlier audit, note, or TODO list the plan is based on — re-verify it first.** Audits decay: by planning time items may be fixed, half-fixed, or misdescribed. Open each referenced `file:line` and classify every inherited item as `closed`, `partial` (state what exists and what is missing), or `still true`. A stale claim does not just waste a task — it hides the real gap ("no checkpoints" often means the resume data exists but nothing commits it). The plan quotes current `file:line`, never the audit's.

### Step 2: Explore the Codebase

Explore the project with read-only actions:

- find files by mask (for example `src/**/*.py`) to map the project structure;
- find code by content — search for the pattern of a similar feature;
- find tests by mask (`tests/**/*.py`) to see what already exists;
- read the key files in full before deciding anything.

### Step 3: Design Approach

Decide:
- Architecture pattern
- File organization
- Dependencies needed
- Testing strategy

### Step 4: Write Tasks

Create tasks in order:
1. Setup/infrastructure
2. Core functionality (TDD for each)
3. Edge cases
4. Integration
5. Cleanup/documentation

For a feature that spans UI and API, replace this layer-first order with vertical slices — one working end-to-end path per task; see `references/slicing.md`.

### Step 5: Insert Checkpoints

Insert a checkpoint after every 2–3 tasks, so a broken phase does not leak into the next one. A checkpoint is a checklist, not a paragraph:

```markdown
## Checkpoint: after Tasks 1–3
- [ ] Tests pass: `pytest -q` → 0 failed
- [ ] Build succeeds: `npm run build` → exit 0
- [ ] The end-to-end scenario works: `<exact command or URL>`
- [ ] The human has looked at the result
```

The last line is not decoration: a checkpoint nobody looks at is a line in a file. Run the checks yourself and quote fresh output — an implementer's report is not evidence (see `verification-before-completion`).

### Step 6: Add Complete Details

For each task, include:
- **Exact file paths** (not "the config file" but `src/config/settings.py`)
- **Complete code examples** (not "add validation" but the actual code)
- **Exact commands** with expected output
- **Verification steps** that prove the task works

### Step 7: Review the Plan

Check:
- [ ] Tasks are sequential and logical
- [ ] Each task is bite-sized (2-5 min)
- [ ] Each task carries 2–3 checkable acceptance criteria; a task is closed only when they pass together with the project's standing bar (the `definition-of-done` reference inside `verification-before-completion`)
- [ ] File paths are exact
- [ ] Code examples are complete (copy-pasteable)
- [ ] Commands are exact with expected output
- [ ] No missing context
- [ ] DRY, YAGNI, TDD principles applied

### Step 8: Pre-mortem the Plan

Assume the plan failed. The question is not "will this work?" but "it is three weeks from now and this failed — why?" (`the-fool` pre-mortem).

- **3–5 failure narratives.** Each names a specific trigger, a number or threshold where one exists, and the chain: trigger → first-order effect → second-order effect → how it would be noticed. "It didn't scale" is not a narrative; "the nightly import hits the 30-minute worker limit at ~40k rows, retries stack up, and the queue backs up for hours" is.
- **Rank by likelihood × impact**, keep the top ones in the plan's `## Risks and Mitigations` section (add it to the document if missing), each with an early warning sign and the first check that would catch it.
- **Run the inversion:** "what would guarantee this fails?" — no tests on the data path, one person owning a weekend deploy, a dependency with no lockfile. If any of those conditions already exists, it is a finding, not a hypothetical.
- **Gate:** the plan is not handed off until 2–3 named failures, their early signs and the check that catches them are written down. A plan with no failure modes was not stress-tested.

## Principles

### Order by Cost of Failure

Sequence work by what breaks when it breaks, not by ease or file layout: money spent twice or work lost mid-run first, data quality second, infrastructure third, cosmetic debt last. Group items that share one mechanism into one wave (checkpoints + cancellation + lease are the same machinery), so they are built and tested together.

### DRY (Don't Repeat Yourself)

**Bad:** Copy-paste validation in 3 places
**Good:** Extract validation function, use everywhere

### YAGNI (You Aren't Gonna Need It)

**Bad:** Add "flexibility" for future requirements
**Good:** Implement only what's needed now

```python
# Bad — YAGNI violation
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
        self.preferences = {}  # Not needed yet!
        self.metadata = {}     # Not needed yet!

# Good — YAGNI
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
```

### TDD (Test-Driven Development)

Every task that produces code should include the full TDD cycle:
1. Write failing test
2. Run to verify failure
3. Write minimal code
4. Run to verify pass

See `test-driven-development` skill for details.

### Frequent Commits

Commit after every task:
```bash
git add [files]
git commit -m "type: description"
```

## Common Mistakes

### Vague Tasks

**Bad:** "Add authentication"
**Good:** "Create User model with email and password_hash fields"

### Incomplete Code

**Bad:** "Step 1: Add validation function"
**Good:** "Step 1: Add validation function" followed by the complete function code

### Missing Verification

**Bad:** "Step 3: Test it works"
**Good:** "Step 3: Run `pytest tests/test_auth.py -v`, expected: 3 passed"

### Missing File Paths

**Bad:** "Create the model file"
**Good:** "Create: `src/models/user.py`"

## Execution Handoff

After saving the plan, offer the execution approach:

**"Plan complete and saved. Ready to execute using subagent-driven-development — I'll dispatch a fresh subagent per task with two-stage review (spec compliance then code quality). Shall I proceed?"**

When executing, use the `subagent-driven-development` skill:
- A fresh subagent per task, each with full context
- Spec compliance review after each task
- Code quality review after spec passes
- Proceed only when both reviews approve
- Each task ends with the `verification-before-completion` gate: fresh command output, not the child's report

## Files

- `references/slicing.md` — task sizing XS–XL, the four split triggers, vertical slices for features that span UI and API, and task ordering.

## Remember

```
Bite-sized tasks (2-5 min each)
Exact file paths
Complete code (copy-pasteable)
Exact commands with expected output
Verification steps
DRY, YAGNI, TDD
Frequent commits
```

**A good plan makes implementation obvious.**
