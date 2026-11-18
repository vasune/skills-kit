# Security checks

Reference for `requesting-code-review`. Step 2's regex scan catches the obvious; this file is the
deeper pass for changes that touch input, auth, file paths, dependencies or an LLM.

## 1. Secrets in the staged diff

Scan by file name only — the command must never print the value into the transcript:

```bash
git diff --cached -i -G'password|secret|api_key|token' --name-only
```

Any output means "open these files and read them", not "copy the matching line". A secret that has
reached a remote is already compromised: rotate it first, then purge history — deleting the commit
is not enough.

## 2. Five-minute threat model

Controls bolted on without a threat model are guesses.

1. **Map trust boundaries:** HTTP requests, forms, uploads, webhooks, third-party APIs, LLM output,
   and local values written by processes you do not control (argv, env, filenames on a shared
   volume). Trust follows who *wrote* the value, not which channel delivered it.
2. **Name the assets:** credentials, PII, admin actions, money.
3. **Run STRIDE over each boundary** — a quick lens, not a ceremony.
4. **Write abuse cases:** "how would I misuse this?" — the answer is the first test.

| Threat | Ask | Typical mitigation |
|---|---|---|
| Spoofing | can someone impersonate a user/service? | authentication, signatures |
| Tampering | can data be altered in transit or at rest? | integrity checks, parameterized queries, HTTPS |
| Repudiation | can an action be denied later? | audit logging of security events |
| Information disclosure | can data leak? | encryption, field allowlists, generic errors |
| Denial of service | can it be overwhelmed? | rate limits, input size caps, timeouts |
| Elevation of privilege | can a user gain rights they shouldn't? | authorization checks, least privilege |

If you cannot name the trust boundaries for a feature, you are not ready to review its security.

## 3. Destructive path operations

A delete, move or overwrite is only as safe as the value naming its target. A shape check proves
well-formedness, not authorization. Require all of this before the call:

```python
from pathlib import Path

ALLOWED_ROOTS = [Path("/var/lib/app/sessions")]  # an allowlist, not a pattern

def resolve_deletable(candidate: str, expected_owner: str) -> Path:
    target = Path(candidate).resolve()      # symlinks resolved BEFORE the check
    roots = [root.resolve() for root in ALLOWED_ROOTS]
    rel = next((target.relative_to(r) for r in roots
                if target != r and target.is_relative_to(r)), None)
    if rel is None or len(rel.parts) < 1:   # outside every root, or the root itself
        log.warning("refusing: outside allowed roots (%s)", target)
        raise PermissionError(target)       # log the rejected target, then stop
    marker = target / ".owner"
    owner = marker.read_text().strip() if marker.exists() else None
    if owner != expected_owner:             # evidence read BEFORE the operation
        log.warning("refusing: unproven owner (%s)", target)
        raise PermissionError(target)
    return target
```

Rules around the snippet:

- **On refusal, log the target and stop.** Never fall back to a broader default path to "keep going".
- **The ownership marker is self-attestation.** Anything that can write inside the root can write
  `.owner`; `expected_owner` must come from authenticated state, and the marker needs integrity
  protection before it is authorization rather than a consistency check.
- **Returning a path leaves a check/use race.** Where an untrusted process can swap an ancestor
  between the check and the call, operate on a descriptor with no-follow semantics, or guarantee the
  hierarchy is immutable for the duration.

## 4. Dependency audit

Run the native audit before every release, against the committed lockfile:

```bash
npm audit --audit-level=high
pnpm audit
pip-audit
```

- Triage critical/high by **reachability** (runtime, build, test, deploy), not by count.
- Never apply forced remediation (`npm audit fix --force`) automatically — it can cross declared
  ranges. Preview, read changelogs, test each upgrade.
- Review the lockfile diff, not only the manifest; one direct bump can pull dozens of transitive
  changes, so one dependency per change keeps the cause and the revert clean.
- An audit matches **known advisories only**: it does not catch a newly malicious or typosquatted
  package, nor an unreviewed install script. Review ownership, maintenance, release age and
  provenance separately.
