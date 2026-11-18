# PAT scopes and permissions for agent access

What to request, what it buys, and where the two token types differ.

## Classic PAT — the pragmatic choice for an agent

Create at `https://github.com/settings/tokens/new` (Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token (classic)). The token string is shown once; afterwards it can only be deleted and recreated.

| Scope | Needed for |
|---|---|
| `repo` | clone/commit/push on private repos, PRs, issues, comments, labels, releases |
| `workflow` | pushing changes under `.github/workflows/` — without it those pushes are rejected even with `repo` |
| `read:org` | reading org membership/teams; required when repos belong to an organization |
| `gist` | `gh` uses gists for some helper operations |

Minimum for `gh` to behave like a normal user: `repo`, `read:org`, `gist`. Add `workflow` when the repos carry Actions workflows.

Downside: a classic token sees **every repository the account can see**. Acceptable for a dedicated agent account with a small repo set; not for a personal account.

## Fine-grained PAT — narrower, with rough edges

Create at `https://github.com/settings/personal-access-tokens/new`. Limit **Repository access → Selected repositories** and grant only these repository permissions:

| Permission | Level | For |
|---|---|---|
| Contents | Read and write | clone, commit, push, branches |
| Pull requests | Read and write | open/merge/review PRs |
| Issues | Read and write | open, comment, label, close |
| Workflows | Read and write | edits under `.github/workflows/` |
| Actions | Read and write | workflow runs, logs, re-run, cancel |
| Metadata | Read-only | added automatically, cannot be unselected |

Organization permission `Members: Read-only` if org repos are involved; account permission `Gists: Read and write` if `gh` gist helpers are used.

Full-functionality list reported for `gh` (wider than strictly necessary): Actions, Administration, Contents, Environments, Issues, Metadata, Pull requests, Workflows — all read and write.

### Known failure signature

`gh` commands that fan out into GraphQL — `gh pr create`, `gh pr view`, label operations — can fail with:

```
GraphQL: Resource not accessible by personal access token (repository.defaultBranchRef)
```

even when the documented permission set is granted, because those commands read extra fields (project cards, labels, default branch ref) that map to additional permissions. Options, in order: grant the missing permission (`Contents: read` fixes the default-branch case), drop the offending flag, or switch to a classic token. Do not burn time debugging it as a broken credential — the token is fine, the permission surface is short.

Also: each fine-grained token is bound to a single resource owner (one user **or** one org), so multi-org use needs multiple tokens.

## Reading GitHub docs cheaply

`docs.github.com` pages have a markdown twin: append `.md` to the URL and fetch it with `curl` — the rendered HTML path is JS-heavy and yields nothing useful to a plain fetch. Example: `https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens.md`.

## Rotation

Ask the expiry when the token is created, and offer a scheduled reminder ~a week before, so access does not lapse silently mid-task. Rotating means: new token → write it into place → verify with `gh auth status` + a clone → delete the old one in settings.
