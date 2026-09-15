# Security Policy

SETU-Swasthya is a healthcare platform: even at MVP stage, its whole design
target is eventually handling real patients' health information. We'd rather
hear about a problem privately and fix it than have it found the hard way.
This policy covers both the code you'd expect (auth, encryption, the API) and
one thing most security policies don't have to think about: real patient
data ending up somewhere it never should.

## Supported versions

This project is in active MVP development — there is no released/tagged
version line yet, and no long-term-support branch. Security fixes are made
against the tip of `main` only. If you're running an older commit or a
frozen demo snapshot (see `backend/DEMO_RUNBOOK.md`), update to current
`main` before assuming a report is unresolved.

## Reporting a vulnerability

**Preferred:** use GitHub's private vulnerability reporting — go to this
repository's **Security** tab → **Report a vulnerability**. This keeps the
report private to maintainers until a fix is ready, which matters more here
than in most projects, given the domain.

**Fallback**, if that's unavailable to you: email
**iqraakhan029@gmail.com** with:

- What you found and where (file/endpoint/commit).
- Steps to reproduce, or a minimal proof of concept.
- What you think the impact is (data exposure, auth bypass, privilege
  escalation, etc.).

We don't have a large security team behind this yet — treat response times
as best-effort, not an SLA. A reasonable target is an initial response
within 5 business days.

Please don't open a public GitHub issue for a suspected vulnerability until
a fix has landed — that's the one thing that turns a private report into a
public exploit guide.

## Found real patient data instead of a code bug? Report that too, and faster.

This is the one category of "security" issue specific to this project.
Every patient/village/facility record shipped in this repository or a demo
deployment is required to be synthetic — enforced by
`backend/tests/test_no_real_data.py`, which fails loudly (naming the
offending row) if it finds otherwise. If you ever come across what looks
like a **real person's actual health information** anywhere in this repo,
in an issue, in a demo instance, or in a screenshot/recording shared around
the project — treat it as more urgent than a typical code vulnerability and
report it the same way (GitHub private reporting, or the email above),
saying explicitly that it's real data, not a code finding. Under India's
DPDP Act, the moment real health data lands anywhere in this project, real
obligations follow — this gets fixed (removed, and the exposure understood)
before anything else.

## What's in scope

- The FastAPI backend (`backend/app/`) — auth/RBAC, the referral state
  machine, the offline `/sync/` endpoint, and the PHI blind-index/encryption
  layer (`backend/app/core/crypto.py`).
- The triage/escalation rule engines (`ml/triage/`, `ml/escalation/`) and
  their integration into the backend.
- Deployment configuration (`backend/Dockerfile`, `docker-compose.yml`,
  `backend/app/core/security_headers.py`, `backend/app/core/rate_limit.py`).

## What's out of scope

- The synthetic demo dataset itself being synthetic/unrealistic — that's
  intentional (see `backend/scripts/seed_demo.py`'s own docstring).
- The Flutter mobile client's local-only offline storage, until that code
  lands in this repository (as of this policy, it hasn't yet).
- Findings that require an already-compromised device or an already-leaked
  credential to exploit further.

Thank you for taking the time to report responsibly — it's genuinely
appreciated, especially on a project built around people's health data.
