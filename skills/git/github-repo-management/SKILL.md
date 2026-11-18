---
name: github-repo-management
description: "Use when creating a repo or tidying its settings."
version: 1.2.0
author: fhfqndj
license: MIT
platforms: [linux, macos, windows]
metadata:
  tags: [GitHub, Repositories, Git, Releases, Secrets, Configuration]
  related_skills: [github-auth, github-pr-workflow, github-issues]
---

# GitHub Repository Management

Create, clone, fork, configure, and manage GitHub repositories. Each section shows `gh` first, then the `git` + `curl` fallback.

## When to Use

- A repository must be created, forked, or cloned with its settings.
- Topics, description, visibility, or default branch need fixing.
- A release or tag must be cut.

## Prerequisites

- Authenticated with GitHub (see `github-auth` skill)

### Setup

```bash
if command -v gh &>/dev/null && gh auth status &>/dev/null; then
  AUTH="gh"
else
  AUTH="git"
  if [ -z "$GITHUB_TOKEN" ]; then
    # Read the token from the git credential store; where your host keeps its own token — see your host's docs.
    GITHUB_TOKEN=$(printf 'protocol=https\nhost=github.com\n' | GIT_TERMINAL_PROMPT=0 git credential fill 2>/dev/null | sed -n 's/^password=//p')
  fi
fi

# Get your GitHub username (needed for several operations)
if [ "$AUTH" = "gh" ]; then
  GH_USER=$(gh api user --jq '.login')
else
  GH_USER=$(curl -s -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user | python -c "import sys,json; print(json.load(sys.stdin)['login'])")
fi
```

If you're inside a repo already:

```bash
REMOTE_URL=$(git remote get-url origin)
OWNER_REPO=$(echo "$REMOTE_URL" | sed -E 's|.*github\.com[:/]||; s|\.git$||')
OWNER=$(echo "$OWNER_REPO" | cut -d/ -f1)
REPO=$(echo "$OWNER_REPO" | cut -d/ -f2)
```

---

## 1. Cloning Repositories

Cloning is pure `git` — works identically either way:

```bash
# Clone via HTTPS (works with credential helper or token-embedded URL)
git clone https://github.com/owner/repo-name.git

# Clone into a specific directory
git clone https://github.com/owner/repo-name.git ./my-local-dir

# Shallow clone (faster for large repos)
git clone --depth 1 https://github.com/owner/repo-name.git

# Clone a specific branch
git clone --branch develop https://github.com/owner/repo-name.git

# Clone via SSH (if SSH is configured)
git clone git@github.com:owner/repo-name.git
```

**With gh (shorthand):**

```bash
gh repo clone owner/repo-name
gh repo clone owner/repo-name -- --depth 1
```

## 2. Creating Repositories

**With gh:**

```bash
# Create a public repo and clone it
gh repo create my-new-project --public --clone

# Private, with description and license
gh repo create my-new-project --private --description "A useful tool" --license MIT --clone

# Under an organization
gh repo create my-org/my-new-project --public --clone

# From existing local directory
cd /path/to/existing/project
gh repo create my-project --source . --public --push
```

After `gh repo create ... --source . --push` the repository still carries the default branch `main`, which nothing has pushed: the repo URL opens looking empty even though `master` is there. Fix it immediately — `gh api -X PATCH repos/<owner>/<repo> -f default_branch=master` — and set topics in a single call, remembering that topics **replace** the whole list: `gh api --method PUT repos/<owner>/<repo>/topics -f "names[]=react" -f "names[]=vite"`.

**Do not chain creation with configuration in one command.** A line like `git commit … && gh repo create … --source . --push && gh api -X PATCH …` is refused wholesale by the long-lived-process guard in the agent's command runner, so none of it runs. Split it: commit, then `gh repo create … --push` as its own call (if that one is still refused, run it in the background per your host's instructions and check `git status --short --branch` afterwards), then settings through `gh api`. `gh repo edit` trips the same guard — use the API for description, topics and default branch.

**Verify what actually landed.** Four numbers after the push: `gh api repos/O/R --jq '.default_branch'` equals your branch; the blob count `gh api "repos/O/R/git/trees/master?recursive=1" --jq '[.tree[]|select(.type=="blob")]|length'` equals `git ls-files | wc -l`; `gh api repos/O/R/commits --jq 'length'` equals the number of commits you meant to publish (1 for a clean start); `git rev-parse HEAD origin/master` prints the same SHA twice.

**With git + curl:**

```bash
# Create the remote repo via API
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/user/repos \
  -d '{
    "name": "my-new-project",
    "description": "A useful tool",
    "private": false,
    "auto_init": true,
    "license_template": "mit"
  }'

# Clone it
git clone https://github.com/$GH_USER/my-new-project.git
cd my-new-project

# -- OR -- push an existing local directory to the new repo
cd /path/to/existing/project
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/$GH_USER/my-new-project.git
git push -u origin main
```

To create under an organization:

```bash
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/orgs/my-org/repos \
  -d '{"name": "my-new-project", "private": false}'
```

### From a Template

**With gh:**

```bash
gh repo create my-new-app --template owner/template-repo --public --clone
```

**With curl:**

```bash
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/owner/template-repo/generate \
  -d '{"owner": "'"$GH_USER"'", "name": "my-new-app", "private": false}'
```

## 3. Forking Repositories

**With gh:**

```bash
gh repo fork owner/repo-name --clone
```

**With git + curl:**

```bash
# Create the fork via API
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/owner/repo-name/forks

# Wait a moment for GitHub to create it, then clone
sleep 3
git clone https://github.com/$GH_USER/repo-name.git
cd repo-name

# Add the original repo as "upstream" remote
git remote add upstream https://github.com/owner/repo-name.git
```

### Fork vs private mirror

A fork of a public repo **cannot** be made private: `gh api -X PATCH repos/<owner>/<repo> -f private=true` answers `422 Validation Failed … Public forks can't be made private`. When the copy must be private (source-available licence, client work, internal fork), create a separate private repo and push into it — keep the upstream link by hand:

```bash
gh api user --jq .login                       # active account decides where the repo lands
gh repo create <owner>/<repo>-private --private --description "..."
git -C repo remote add public-fork https://github.com/<owner>/<repo>.git
git -C repo remote set-url origin https://github.com/<owner>/<repo>-private.git
git -C repo push -u origin HEAD               # HEAD: default branch may be main, not master
gh api repos/<owner>/<repo>-private --jq '"\(.full_name) private=\(.private) fork=\(.fork) size=\(.size)KB"'
```

- **A shallow clone cannot be pushed into an empty repo.** The push dies with `remote: fatal: did not receive expected object <sha>` and `remote unpack failed: index-pack failed` — a `--depth 1` pack is incomplete by construction. Fetch full history first (`git fetch --unshallow upstream`) and fetch it from a remote that actually has it — upstream or the public fork, never the new empty private repo — then push; the local `.git` grows to the real size of the project.
- **Read the default branch instead of assuming:** vendors differ (`master` for n8n, `main` for Activepieces), and `git push origin master` then fails with `src refspec master does not match any`.
- **Verify what landed:** `private=true`, `fork=false` and a non-zero `size` on the API are the proof; a size of `0KB` means the push has not finished or was rejected.
- **Private visibility does not relax the licence.** A private copy of a source-available project is still internal-use only, and if the licence is not permissive, delete the public fork afterwards — a public copy is distribution, a private one is internal use.

### Keeping a Fork in Sync

```bash
# Pure git — works everywhere
git fetch upstream
git checkout main
git merge upstream/main
git push origin main
```

**With gh (shortcut):**

```bash
gh repo sync $GH_USER/repo-name
```

## 4. Repository Information

**With gh:**

```bash
gh repo view owner/repo-name
gh repo list --limit 20
gh search repos "machine learning" --language python --sort stars
```

**With curl:**

```bash
# View repo details
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO \
  | python -c "
import sys, json
r = json.load(sys.stdin)
print(f\"Name: {r['full_name']}\")
print(f\"Description: {r['description']}\")
print(f\"Stars: {r['stargazers_count']}  Forks: {r['forks_count']}\")
print(f\"Default branch: {r['default_branch']}\")
print(f\"Language: {r['language']}\")"

# List your repos
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/user/repos?per_page=20&sort=updated" \
  | python -c "
import sys, json
for r in json.load(sys.stdin):
    vis = 'private' if r['private'] else 'public'
    print(f\"  {r['full_name']:40}  {vis:8}  {r.get('language', ''):10}  ★{r['stargazers_count']}\")"

# Search repos
curl -s \
  "https://api.github.com/search/repositories?q=machine+learning+language:python&sort=stars&per_page=10" \
  | python -c "
import sys, json
for r in json.load(sys.stdin)['items']:
    print(f\"  {r['full_name']:40}  ★{r['stargazers_count']:6}  {r['description'][:60] if r['description'] else ''}\")"
```

## 5. Repository Settings

**With gh:**

```bash
gh repo edit --description "Updated description" --visibility public
gh repo edit --enable-wiki=false --enable-issues=true
gh repo edit --default-branch main
gh repo edit --add-topic "machine-learning,python"
gh repo edit --enable-auto-merge
```

**With curl:**

```bash
curl -s -X PATCH \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO \
  -d '{
    "description": "Updated description",
    "has_wiki": false,
    "has_issues": true,
    "allow_auto_merge": true
  }'

# Update topics
curl -s -X PUT \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.mercy-preview+json" \
  https://api.github.com/repos/$OWNER/$REPO/topics \
  -d '{"names": ["machine-learning", "python", "automation"]}'
```

## 6. Branch Protection

```bash
# View current protection
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/branches/main/protection

# Set up branch protection
curl -s -X PUT \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/branches/main/protection \
  -d '{
    "required_status_checks": {
      "strict": true,
      "contexts": ["ci/test", "ci/lint"]
    },
    "enforce_admins": false,
    "required_pull_request_reviews": {
      "required_approving_review_count": 1
    },
    "restrictions": null
  }'
```

## 7. Secrets Management (GitHub Actions)

**With gh:**

```bash
gh secret set API_KEY --body "your-secret-value"
gh secret set SSH_KEY < ~/.ssh/id_rsa
gh secret list
gh secret delete API_KEY
```

**With curl:**

Secrets require encryption with the repo's public key — more involved via API:

```bash
# Get the repo's public key for encrypting secrets
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/actions/secrets/public-key

# Encrypt and set (requires Python with PyNaCl)
python -c "
from base64 import b64encode
from nacl import encoding, public
import json, sys

# Get the public key
key_id = '<key_id_from_above>'
public_key = '<base64_key_from_above>'

# Encrypt
sealed = public.SealedBox(
    public.PublicKey(public_key.encode('utf-8'), encoding.Base64Encoder)
).encrypt('your-secret-value'.encode('utf-8'))
print(json.dumps({
    'encrypted_value': b64encode(sealed).decode('utf-8'),
    'key_id': key_id
}))"

# Then PUT the encrypted secret
curl -s -X PUT \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/actions/secrets/API_KEY \
  -d '<output from python script above>'

# List secrets (names only, values hidden)
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/actions/secrets \
  | python -c "
import sys, json
for s in json.load(sys.stdin)['secrets']:
    print(f\"  {s['name']:30}  updated: {s['updated_at']}\")"
```

Note: For secrets, `gh secret set` is dramatically simpler. If setting secrets is needed and `gh` isn't available, recommend installing it for just that operation.

## 8. Releases

**With gh:**

```bash
gh release create v1.0.0 --title "v1.0.0" --generate-notes
gh release create v2.0.0-rc1 --draft --prerelease --generate-notes
gh release create v1.0.0 ./dist/binary --title "v1.0.0" --notes "Release notes"
gh release list
gh release download v1.0.0 --dir ./downloads
```

**With curl:**

```bash
# Create a release
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/releases \
  -d '{
    "tag_name": "v1.0.0",
    "name": "v1.0.0",
    "body": "## Changelog\n- Feature A\n- Bug fix B",
    "draft": false,
    "prerelease": false,
    "generate_release_notes": true
  }'

# List releases
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/releases \
  | python -c "
import sys, json
for r in json.load(sys.stdin):
    tag = r.get('tag_name', 'no tag')
    print(f\"  {tag:15}  {r['name']:30}  {'draft' if r['draft'] else 'published'}\")"

# Upload a release asset (binary file)
RELEASE_ID=<id_from_create_response>
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Content-Type: application/octet-stream" \
  "https://uploads.github.com/repos/$OWNER/$REPO/releases/$RELEASE_ID/assets?name=binary-amd64" \
  --data-binary @./dist/binary-amd64
```

## 9. GitHub Actions Workflows

**With gh:**

```bash
gh workflow list
gh run list --limit 10
gh run view <RUN_ID>
gh run view <RUN_ID> --log-failed
gh run rerun <RUN_ID>
gh run rerun <RUN_ID> --failed
gh workflow run ci.yml --ref main
gh workflow run deploy.yml -f environment=staging
```

**With curl:**

```bash
# List workflows
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/actions/workflows \
  | python -c "
import sys, json
for w in json.load(sys.stdin)['workflows']:
    print(f\"  {w['id']:10}  {w['name']:30}  {w['state']}\")"

# List recent runs
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/actions/runs?per_page=10" \
  | python -c "
import sys, json
for r in json.load(sys.stdin)['workflow_runs']:
    print(f\"  Run {r['id']}  {r['name']:30}  {r['conclusion'] or r['status']}\")"

# Download failed run logs
RUN_ID=<run_id>
curl -s -L \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/actions/runs/$RUN_ID/logs \
  -o /tmp/ci-logs.zip
cd /tmp && unzip -o ci-logs.zip -d ci-logs

# Re-run a failed workflow
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/actions/runs/$RUN_ID/rerun

# Re-run only failed jobs
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/actions/runs/$RUN_ID/rerun-failed-jobs

# Trigger a workflow manually (workflow_dispatch)
WORKFLOW_ID=<workflow_id_or_filename>
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/actions/workflows/$WORKFLOW_ID/dispatches \
  -d '{"ref": "main", "inputs": {"environment": "staging"}}'
```

## 10. Gists

**With gh:**

```bash
gh gist create script.py --public --desc "Useful script"
gh gist list
```

**With curl:**

```bash
# Create a gist
curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/gists \
  -d '{
    "description": "Useful script",
    "public": true,
    "files": {
      "script.py": {"content": "print(\"hello\")"}
    }
  }'

# List your gists
curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/gists \
  | python -c "
import sys, json
for g in json.load(sys.stdin):
    files = ', '.join(g['files'].keys())
    print(f\"  {g['id']}  {g['description'] or '(no desc)':40}  {files}\")"
```

## 11. Grouping Repositories Across an Organization

GitHub has no folders or nested grouping. Only two things group repos, and they do different jobs:

| Mechanism | What it gives | Scope needed |
|---|---|---|
| **Topics** | Tags on the repo page, visible to everyone, searchable (`org:X topic:calc`) | `repo` |
| **Custom properties** | Org-level metadata with an enforced value list, drives the `prop` filter on the org Repositories page and can target rulesets | `admin:org` (classic) / `organization_custom_properties:write` (fine-grained) |

No topic filter exists in the org Repositories list — that filter only comes from custom properties. Set topics anyway: they are free, visible on the repo page, and searchable globally.

**Topics (replaces the whole list, does not append):**

```bash
gh api --method PUT "repos/$ORG/$REPO/topics" -H "Accept: application/vnd.github+json" -f "names[]=calculators"
```

**Custom property definition** — `PUT /orgs/{org}/properties/schema/{custom_property_name}`. The property name is a **path segment**, not a body field:

```bash
gh api --method PUT "/orgs/$ORG/properties/schema/product" -H "Accept: application/vnd.github+json" \
  --input - <<'JSON'
{"value_type":"single_select","allowed_values":["calculators","content"],"values_editable_by":"org_actors","required":false,"description":"Группа репозитория"}
JSON
```

**Custom property values** — `PATCH /orgs/{org}/properties/values`; `properties` is an array of `{property_name, value}` objects, `repository_names` caps at 30 per call:

```bash
gh api --method PATCH "/orgs/$ORG/properties/values" -H "Accept: application/vnd.github+json" \
  --input - <<'JSON'
{"repository_names":["repo-a","repo-b"],"properties":[{"property_name":"product","value":"calculators"}]}
JSON
```

Verification: `GET /orgs/{org}/properties/schema` (empty `[]` means the feature is available but nothing is defined) and `GET /orgs/{org}/properties/values` (per-repo values). Check topics back with `GET /repos/{o}/{r}/topics`.

Pitfalls:

- `PUT /orgs/{org}/properties/schema` (collection form with a `properties` array) does not exist and 404s. One property = one call with the name in the path.
- A 404 from the custom-properties endpoints is usually a **scope** problem, not a missing org: the error text says `needs the "admin:org" scope`. Check `gh auth status` scopes first, and if `admin:org` is absent, hand the user the UI path (Org → Settings → Code, planning, and automation → Repository → Custom properties → New property, then the **Set values** tab) rather than guessing at a workaround.
- Custom properties are available on the Free plan (docs frontmatter `versions: fpt: '*'`); the schema endpoint answering with `[]` on a free org confirms the feature, not a plan limitation.
- Custom properties and topics never touch the repo path: URLs and existing clones keep working. Only renaming changes the path, and GitHub leaves a redirect from the old name.
- Topic names must be lowercase alphanumeric plus hyphen; a topic whose name collides with a language (`python`) makes the repo read as that language in filters.

When an endpoint you assume 404s, read the real path out of GitHub's OpenAPI description instead of guessing again:

```bash
curl -sL https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json -o /tmp/ghapi.json
python3 -c "import json;d=json.load(open('/tmp/ghapi.json'));[print(p, list(d['paths'][p])) for p in d['paths'] if 'propert' in p]"
```

## Creating repos in someone else's organization

- Creating a repository in a user's org and pushing the first commit is the owner's action, not a routine step: do it only when the request names the repo in the same turn. A "yes" picked from a choice list is not durable permission — the owner may have meant to do it themselves and ask to roll back.
- Know your undo before pushing: `gh repo delete` needs the `delete_repo` scope and otherwise answers `HTTP 403 ... needs the "delete_repo" scope`. `gh auth refresh -h github.com -s delete_repo` is interactive (browser approval), so it cannot be done silently mid-task; without it, deletion is UI-only for the owner — say that plainly instead of promising a rollback you cannot perform.
- Org policy can forbid deploy keys: `gh repo deploy-key add` answers `422 Deploy keys are disabled for this repository`. Read-only is the default (there is no `--allow-read-only` flag; only `-w/--allow-write`). If keys are blocked, plan delivery another way (fine-grained PAT scoped to Contents: read, or CI rsync instead of `git clone` on the server).

## Quick Reference Table

| Action | gh | git + curl |
|--------|-----|-----------|
| Clone | `gh repo clone o/r` | `git clone https://github.com/o/r.git` |
| Create repo | `gh repo create name --public` | `curl POST /user/repos` |
| Fork | `gh repo fork o/r --clone` | `curl POST /repos/o/r/forks` + `git clone` |
| Repo info | `gh repo view o/r` | `curl GET /repos/o/r` |
| Edit settings | `gh repo edit --...` | `curl PATCH /repos/o/r` |
| Create release | `gh release create v1.0` | `curl POST /repos/o/r/releases` |
| List workflows | `gh workflow list` | `curl GET /repos/o/r/actions/workflows` |
| Rerun CI | `gh run rerun ID` | `curl POST /repos/o/r/actions/runs/ID/rerun` |
| Set topics | `gh repo edit --add-topic a,b` | `curl PUT /repos/o/r/topics` |
| Custom property | — | `curl PUT /orgs/o/properties/schema/name` |
| Set secret | `gh secret set KEY` | `curl PUT /repos/o/r/actions/secrets/KEY` (+ encryption) |
