# Task Sizing and Vertical Slicing

Reference for `plan`. Open it when a plan has more than a couple of tasks, or when a feature spans UI and API.

## Sizing

Size every task by the number of files it touches — the cheapest honest signal, available before any code is written.

| Size | Files | Scope | Example |
|---|---|---|---|
| XS | 1 | single function or config change | add a validation rule |
| S | 1–2 | one component or endpoint | add a new API endpoint |
| M | 3–5 | one feature slice | user registration flow |
| L | 5–8 | multi-component feature | search with filtering and pagination |
| XL | 8+ | **too large — split it** | — |

L and XL are split before the plan is saved: an implementer performs best on S and M. A task of size L is not a unit of work, it is a phase with a title.

## Four split triggers

Any one of them is enough to split a task:

1. It would take more than one focused session (roughly 2 hours of agent work).
2. You cannot describe its acceptance criteria in 3 or fewer checkable items.
3. It touches two or more independent subsystems (auth and billing).
4. You find yourself writing "and" in the task title — that is two tasks.

The reverse is also true: do not split below XS. A step with no checkable outcome is a note, not a task.

## Vertical slices

For a feature that spans UI and API, build one complete path at a time instead of one layer at a time. The first slice proves the whole chain works before there are four layers to debug.

Bad — horizontal:
1. Build the entire database schema. 2. Build all API endpoints. 3. Build all UI components. 4. Connect everything.

Good — vertical:
1. User can sign up (schema + API + screen). 2. User can log in. 3. User can create a task.

Each vertical slice delivers working, testable behavior that can be demonstrated to the human on its own. Keep layer-first ordering only for pure infrastructure (a migration runner, a logging setup), where there is no user-visible path to slice.

## Order

Dependencies first (bottom-up), then vertical slices; high-risk tasks early so a failure happens while there is still time to react. Checkpoints between phases are specified in the skill's `Step 5: Insert Checkpoints`.
