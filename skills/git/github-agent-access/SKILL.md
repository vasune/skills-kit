---
name: github-agent-access
description: "Use when giving an agent scoped GitHub access."
version: 1.1.0
author: fhfqndj
license: MIT
metadata:
  tags: [github, access, token, pat, least-privilege, onboarding, device-flow, git-identity]
  related_skills: [github-auth, github-pr-workflow, git-naming, local-work-hygiene]
---

# GitHub access for an agent

Equipping an agent with its own GitHub credentials so it can commit, push, branch, and open PRs — least privilege, revocable, and verifiable. Complements the bundled `github-auth` skill, which covers *how* to authenticate; this one covers *what to agree on first*, *what to request*, and *how to prove it works*.

## When to Use

- The user offers to hand over GitHub access ("can you commit and open PRs for me?")
- An agent account, token, or SSH key must be set up, narrowed, rotated, or audited
- Commits are landing under the wrong author, or a push fails on permissions

## 1. Settle the terms before touching anything

Ask for all of these up front; guessing costs a round trip and can leak access to the wrong account.

| Question | Why it matters |
|---|---|
| Which account — personal or a dedicated agent account? | Never operate a personal account unless the user says so explicitly. Record the off-limits account as a standing rule. |
| Which repos are allowed, which are forbidden? | "All repos I can reach" is usually not the intent. |
| Commit name + email | The email must be attached to that GitHub account (noreply address or the account's verified address), or commits never attribute to the profile. |
| Which branch is the main one? | Ask — do not assume `main`. Some projects run `master`. |
| What goes straight to main, what goes through a PR? | Typical answer: environment/bootstrap setup direct, everything else via PR. |
| Who merges; what needs confirmation? | Merges, force-push, and branch/repo deletion are always gated on explicit user confirmation. |
| Token expiry | A date lets you offer a reminder instead of silently losing access. |

## 2. Get the credential without putting it in the chat

1. **Preferred: `gh` device flow.** The user opens the verification URL and enters a one-time code; the token goes straight into `gh` (macOS keychain on this platform), and the requested scopes are exactly what the GitHub CLI OAuth app uses (`repo`, `read:org`, `gist`, `workflow`). Nothing secret crosses the conversation.
2. **Acceptable: user writes the token themselves** into the host's credential file as `GH_TOKEN=...` (exact location — see your host's docs).
3. **Never:** ask the user to paste a token into chat. If they do it unprompted, treat that token as compromised — recommend revoke + reissue, do not persist it as the long-term credential, and never echo it back or print it into a diff/log.

After login: `gh auth setup-git` wires the git credential helper (HTTPS pushes stop prompting).

## 3. Verify — read it back, never trust the hand-off

```bash
gh auth status                     # account + the scopes actually granted
gh api user --jq '"login: \(.login)"'   # who you really are
gh repo list --limit 30            # repos you can actually see
git clone https://github.com/<owner>/<repo>.git "$SANDBOX/<name>"   # end-to-end proof of the helper
```

Clone into a sandbox directory (see `local-work-hygiene`), and delete the clone when the check is done. A successful clone also proves the credential helper, which `gh auth status` alone does not.

**Prove attribution, not just access.** A push succeeding says nothing about whether the commits land on the right profile:

```bash
gh api user/emails --jq '.[] | "\(.email) | primary: \(.primary) | verified: \(.verified)"'   # only these attribute commits
gh api repos/<owner>/<repo>/commits --jq '.[] | "\(.sha[0:7]) | \(.commit.author.email) | author: \(if .author then .author.login else "UNLINKED" end)"'
```

A commit whose `author` comes back `null`/UNLINKED was authored with an email the account does not own — fix the per-repo identity before making more commits, or the whole history stays unattributed.

**Dry-run the whole cycle in a throwaway repo before writing to a repo the user cares about.** Create a private sandbox repo (with their OK) and run the loop once end to end: first commit on the main branch → feature branch → commit → push branch → push a file under `.github/workflows/` (the only honest proof that the `workflow` scope works) → open a PR → wait for CI with `gh run list` / `gh pr checks` → merge **only after the user says so** → `git checkout <main> && git pull` to resync the clone. Capability claims are worth nothing next to a merged PR and a green check; the same run also shows the user exactly what the agent can and cannot touch.

## 4. Least privilege — audit the scopes you were handed

Needed: `repo`, `workflow`, `read:org`, `gist` (`workflow` is mandatory to push changes under `.github/workflows/`; without it those pushes are rejected).

A user who says "I gave it everything" has usually ticked every box. Anything beyond the four (`delete_repo`, `admin:org`, `admin:enterprise`, `admin:public_key`, `write:packages`, `copilot`, `user`, `audit_log`, …) is blast radius, not convenience: the agent reads untrusted text (issues, PR bodies, dependency files), so an over-scoped token converts a prompt-injection attempt into a repo deletion. Report the extra scopes and ask for a reissue with the four — the fix is one page in GitHub settings.

Fine-grained PATs are stricter and safer but hit known `gh` gaps; see `references/pat-scopes.md` for the permission list, the classic-vs-fine-grained trade-off, and the failure signature to expect.

## 5. Identity, branches, and the empty-repo trap

- Set identity **per repository**: `git config --local user.name` / `user.email`. Never rewrite the user's global config — they keep committing as themselves. When both parties commit in the same repo, override per command instead: `GIT_AUTHOR_NAME=… GIT_AUTHOR_EMAIL=… git commit …`.
- **Empty repo:** `git init` and cloning an empty repo both leave you on `main` while the project may require `master`. Create the first commit with `git init -b master` so the branch name is right from the start — renaming later is avoidable noise.
- Branch and commit wording follows the project's own conventions; when the user has a naming skill (e.g. `git-naming`), load it rather than inventing a style.
- `gh auth status` shows one active account per host. For a second account use per-repo credential usernames or SSH host aliases in `~/.ssh/config`; mixing them silently pushes as the wrong identity.

## 6. Report back in one message

State: which account is authenticated, the scopes you saw, what you verified (and how), what the user still needs to do (revoke an exposed token, reissue narrower), and where any test artifact was created and whether it was removed. Flag security problems plainly — an over-scoped or leaked token is worth the extra paragraph.

## Pitfalls

- **Do not start a login flow before confirming which account.** The browser's active GitHub session decides who authorizes the code; a code issued for account A gets approved as account B.
- **Kill an abandoned device-flow poller** when the user changes their mind — an unapproved code expires on its own, but the background loop should not outlive the decision. Clean up its log file too.
- **A pasted token is compromised.** Completing setup with it anyway and saying nothing is the failure mode; say it, and offer the reissue path.
- **`git` writes to the remote even when the commit author looks right.** Author identity (who the commit says) and credentials (who may push) are separate; both must point at the agent account.
- **A verified email is not a private one.** With email visibility set to public, the account's real address rides inside the commit metadata of every repository it is ever pushed to, and git history cannot be scrubbed retroactively. If the user would rather hide it, switch the identity to the account's `noreply` address before the first push into a public repo.
- **"It only holds private repos, so nothing can happen" is not a mitigation.** The realistic failure with an over-scoped token is your own misfire, not an intruder: `delete_repo` and `admin:org` are not recoverable by `git reflog`, and a token that has appeared in a chat log widens the blast radius regardless of repo visibility. State this once, plainly, then accept the owner's call — do not re-argue it in later turns. Hold the line on the one thing that actually contains the damage: repo deletion, force-push, branch deletion, org and credential changes all wait for explicit confirmation, and write that gate into the project's notes so the next session inherits it.
- **Do not persist a token that may be revoked.** When a reissue is pending, leave the credential only where the CLI put it (keychain) and do not also write it into the agent's env file — otherwise a stale value outlives the rotation and shadows the new one.
