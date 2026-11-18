# Observed requirements: reverse-spec template

Shape of the document a reconnaissance produces when the result must outlive the session: a spec of
what the system **does today**, from code and runs. Filled only for sections that apply; every claim
carries `path:line`, every guess is labelled.

```markdown
# Reverse spec: [system or feature]

## Overview
Two or three sentences: what it is, who uses it, what it is for.

## Architecture
- Stack and versions (from lockfiles and configs, not memory).
- Module map: directory → responsibility, one line each.
- Data flow: request → guard → handler → service → storage → integrations.

## Observed functional requirements

| ID | Requirement (EARS) | Evidence |
|---|---|---|
| OBS-AUTH-1 | When a request has no token, the system shall return 401. | `app/auth/guard.py:41` |
| OBS-IMPORT-3 | While an import is running, the system shall reject a second run. | `app/import/service.py:88` |

EARS: `The system shall …` / `When <trigger>, …` / `While <state>, …` / `While <state>, when <trigger>, …` / `Where <feature>, …`.

## Contracts, data, non-functional behaviour
Shapes, validation rules, status codes, constraints, migrations; timeouts, retries, limits,
pagination defaults, logging, error formats — numbers as in code.

## Inferred (not observed)
Hypotheses about intent, never fact; each names what would confirm or refute it.

## Uncertainties / Recommendations
Open questions with an owner, then what to fix or verify next by impact. No fixes here.
```

## Rules

- **Observed first, evidence each.** A requirement exists only if code or a run shows it;
  `path:line`, a command or a run id sits next to it.
- **Numbers copied, not paraphrased;** scope stated, so silence is not read as "nothing is there".
