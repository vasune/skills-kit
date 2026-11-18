---
name: codebase-reconnaissance
description: "Use when asked to study an unfamiliar repo or project."
version: 1.2.0
author: fhfqndj
license: MIT
platforms: [linux, macos, windows]
metadata:
  tags: [reconnaissance, onboarding, code-reading, verification, reporting]
  related_skills: [local-work-hygiene, systematic-debugging, plan]
---

# Codebase Reconnaissance

The user hands over a repository (or one subproject inside a larger one) and asks to study it — "изучи проект", "разберись, как это работает", "посмотри документацию и код". The deliverable is a VERIFIED understanding of how the thing is put together and what is wrong with it, not a paraphrase of its README.

## When to Use

- Any "study / understand / review this project" request, including when only one folder of a bigger repo is meant.
- Before implementing a feature or fix in a repo you have not read yet — the recon doubles as plan input.
- Not for size metrics (see `codebase-inspection`) and not for chasing a known bug with a repro (see `systematic-debugging`).

## 1. Read the repo's own context before the code

1. `README.md` at the repo root and at the subproject root.
2. Every file of whatever working-context directory the repo keeps (`local/`, `docs/`, `AGENTS.md`, `CLAUDE.md`, and any other agent-instruction file at the root). These hold the conventions, the settled contracts, and "what we deliberately do not do" — they outrank the README and outrank your assumptions.
3. Entry points, CLI, config, constants — then the modules those call.
4. Tests: they state intended behaviour more precisely than prose does.

Batch independent reads into one turn. Skip vendored and data blobs; measure their size instead of reading them.

## 2. Required areas and the coverage gate

Before writing anything, every area below is either read or explicitly declared out of scope. This list is the difference between "I looked around" and "I know what this system does".

| Area | What to find |
|---|---|
| Entry points | app entry, CLI commands, HTTP routers, jobs registered at startup |
| Config | env vars, config files, defaults, where secrets come from |
| Data schema | models, migrations, constraints, indexes |
| Background work | cron, queues, workers, schedulers |
| External integrations | outbound HTTP, SDKs, webhooks, quotas, retry policy |
| Auth | login, sessions, tokens, roles, permission checks per resource |
| Tests | what is asserted, what is missing, how to run them |
| Scripts | one-off and maintenance scripts, generated artifacts |
| Deploy | Dockerfile, compose, CI, targets, environments |
| Docs and context | README, `AGENTS.md`, `local/`, decision records |

**Coverage gate — answer all six before the report:**

- [ ] Are all entry points and routes accounted for?
- [ ] Are all data models and migrations mapped?
- [ ] Is the auth and authorization flow clear?
- [ ] Are error paths and external failure modes documented?
- [ ] Are all external dependencies and quotas listed?
- [ ] Is every open question either answered or listed as uncertain?

An unchecked box means either keep reading or state the gap as a finding — never generalize from the files you happened to open.

**Observed vs inferred.** Keep the two apart, in the report and in any spec built from it. An observed claim carries `path:line` and, where possible, a run that proves it. An inferred claim is a hypothesis about intent ("this retry exists because the vendor API is flaky") and is labelled as such. A report that mixes them is not reviewable. The reverse-spec shape is in `references/observed-requirements.md`.

## 3. Verify the docs against the artifacts, counts included

Prose drifts from data. Recompute every count a doc asserts (records, files, categories, parameter coverage) with a short script over the real artifacts and report the delta as a finding — a doc claiming N while the artifact holds M is a defect of the handover. Cheap probes: glob counts, `wc -l`, one `json.load` / `pandas.read_excel` pass that prints group counts.

## 4. Prove stage-to-stage contracts by running them, not by reading signatures

When the repo is a pipeline split into stages (producer → consumer, formatter → enricher, ETL → report), never assert compatibility from matching names in the code. Run the downstream stage against the upstream stage's REAL output, in the cheapest stub mode the CLI offers:

- offline fixture instead of the live service,
- fake/stub model plus a dry-run flag so nothing is written and no credits burn,
- a small limit to bound the run.

Then read what actually came out (log lines, the produced file's sheets/headers) and compare it with what the consumer expects. This is where the real gaps show up, and it costs nothing. Check which flags spend money before running anything live: a recon task must not fire paid API calls.

## 5. Explain surprising output down to the deciding branch

When a run behaves oddly, trace the derivation instead of guessing: where the "required"/"expected" set comes from, what the fallback is when the primary input is empty, which columns are filtered out as service/metadata, how identifiers are compared (case, `ё`, dots, numeric suffixes). Name the file and line that decides it. A finding without the mechanism is a complaint.

See `references/staged-data-pipeline-checks.md` for the concrete checklist of contract mismatches in staged spreadsheet/table pipelines (sheet-name casing, service columns leaking into the data schema, required-field fallbacks, dictionary key truncation, output naming, empty reference sheets). Read it whenever the pipeline reads or writes xlsx/csv.

## 6. Report shape (this user)

- Russian. Structured headings, no preamble, no restating the request.
- Open with what the project IS in two or three sentences, then the stages/flow, then the findings.
- Every finding: symptom → mechanism → `path:line` → how it was verified (command or run, with numbers). Ordered by impact.
- A short separate section on repository state when something there is actionable: untracked subtrees, uncommitted diffs that contradict the docs, `.gitignore` coverage for large generated directories. Check `.gitignore` (and per-subtree files) before suggesting any `git add`.
- Close with what you propose and what you deliberately did not touch, then ask for the go-ahead. A study task ends with findings; changing code or data is a separate, explicitly agreed step.
- When a refactor is the announced next step, close with acceptance numbers, not prose: run the project's own core headlessly (no-build plain JS: `node -e "global.window = global; eval(require('fs').readFileSync('core.js','utf8'))"`, then drive the state and print the totals) and put the real figures in the report, so the next task can prove nothing moved.
- Ask the follow-up questions as a short numbered list in the reply text, recommended option first — this user leaves question forms unanswered but answers in chat.
- A couple of screens. Depth goes into the findings, not into narrating the reading process.

## Pitfalls

- Do not run scripts that regenerate the repo's own artifacts during recon (rewriting extract/export passes). They rewrite produced data and make "what did you change?" unanswerable. Read the artifacts to verify counts instead.
- Repos with a context-file convention (an instruction file saying "update `local/` after every task") push you to write into those files. On a pure study task, offer that as a follow-up instead of editing silently — one line in the reply.
- Never present a found incompatibility as already fixed. State the gap and the exact rule that causes it; the fix belongs to the next, agreed task.
- Data files may be huge (tens to hundreds of MB). Never open them through the file-reading path — stream or sample them (`iterparse`, `nrows`, first N lines).
- Uninstalled packages or missing credentials are one-line setup findings, never the headline of the report.
