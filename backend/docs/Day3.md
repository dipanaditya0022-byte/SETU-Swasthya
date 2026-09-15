# Day 3 — Harden, Test, Smoke-Test, Demo Ready

**SETU-Swasthya Backend · Stabilization Specification**

| Field | Value |
|---|---|
| Document | `Day3.md` |
| Backend owners | **Aditya + Iqra** |
| Builds on | `Day1.md` (identity, RBAC) · `Day2.md` (integration) |
| Objective | Make the Day 2 loop **predictable enough for a live demo** |
| Branch | `backend` → frozen to tag `demo-v1.0` |
| Companion | `Day3Prompt.md` (self-contained build prompts) |

---

## 0. The rule that defines today

> **Day 3 is a stabilization day, not a feature-expansion day.**

Everything below follows from that. The rules from Day 1 and Day 2 still apply (additive only, no secrets, fail closed, development data only, never hide an environment error, no git from the developer agent). Three new ones govern today:

| # | Rule |
|---|---|
| **C9 — No new features.** | If it is not on the Day 3 list, it does not get built today. A feature added on demo day has had zero soak time and is the most likely thing to fail on stage. The correct response to "we should also add…" is to write it in the Day 4 backlog. |
| **C10 — Every fix is verified by the request that failed.** | Not by a similar request, not by a unit test alone. Re-run the exact failing call, then re-run the whole chain around it. A local fix that breaks something upstream is the classic demo-day failure. |
| **C11 — After the freeze, nothing merges.** | The freeze is a hard stop with a named owner and a tag. Post-freeze changes require an explicit unfreeze decision from both backend owners, recorded. |

### 0.1 Bug triage — the rule that protects the day

Every bug found today gets a severity **before** anyone starts fixing it. Without this, Day 3 becomes Day 2.5 and the rehearsal never happens.

| Severity | Definition | Action |
|---|---|---|
| **P0 — Demo blocker** | Breaks a step in the demo script. The loop cannot complete. | Fix now. Stop other work. |
| **P1 — Demo risk** | Works, but fragile, slow, or fails on a second attempt. | Fix today if the P0 list is clear. |
| **P2 — Cosmetic / edge** | Wrong error message, odd field name, an edge case nobody will click. | **Log it. Do not fix it.** Add to `KNOWN_ISSUES.md` and the Day 4 backlog. |
| **P3 — Feature gap** | "It would be better if…" | Backlog only. Refuse to build it today. |

**The P2 discipline is the hard part.** A P2 fix costs 20 minutes of coding and an unknown amount of regression risk on the one day when regression risk is least acceptable.

---

## 1. Ownership and timeline

```
 09:00 ─┬─ 3.1  Morning bug sweep                          Aditya + Iqra  (both)
        │      clean checkout · replay · compare · triage
 11:00 ─┼─ 3.2  Validation + controlled error handling     Iqra
        │      validation matrix · global handlers · atomicity
 13:00 ─┼─ 3.3  Triage + referral reference cases          Iqra
        │      5 rule cases · API level · persistence · breach · transitions
 14:30 ─┼─ 3.4  Offline → reconnect → sync                 Aditya
        │      MANDATORY even if it passed on Day 2 evening
 15:30 ─┼─ 3.5  Two-device concurrency test                Aditya + Iqra
 16:30 ─┼─ 3.6  Deployment hardening                       Aditya
        │      headers · rate limits · CORS · secrets · backup
 17:15 ─┼─ 3.7  Demo seed + reset script                   Iqra
 18:00 ─┼─ 3.8  Production smoke test on the public URL    Both
 19:00 ─┼─ 3.9  Rehearsal + failure playbook               Both
 20:00 ─┴─ 3.10 FREEZE                                     Named owner
```

If the schedule slips, the items that get cut are **3.5** and parts of **3.6** — never 3.4, 3.8 or 3.9. A demo that has never been rehearsed against the deployed URL is not a demo, it is a hope.

---

## 2. Step 3.1 — Morning bug sweep

### 2.1 Clean checkout

> Pull the exact code that will be demonstrated, and start it from the **documented** setup — not from the state your laptop happens to be in.

```bash
cd /tmp && rm -rf setu-verify
git clone <repo-url> setu-verify && cd setu-verify
git checkout backend && git pull --rebase origin backend
git log -1 --format='%h %an %s'
```

Then follow `backend/docs/DockerPrompt.md` and the Pre-Day 2 checklist **as written**, from a fresh `.venv` and a fresh database volume. Nothing from your working directory, no undocumented step, no "oh you also need to…".

**Why this matters more than it sounds.** The most common demo failure is a step that only works because of something uncommitted on one laptop. A clean checkout is the only way to find it, and finding it at 09:00 is survivable while finding it at 19:00 is not.

Record how long setup takes. If it exceeds 20 minutes, the setup documentation is a P1 bug in its own right.

### 2.2 Replay the Day 2 smoke tests

Run the full chain again: **login → patient → triage → referral → dashboard**, plus `/referrals/exceptions` and `/sync/`.

```bash
BASE=http://localhost:8000
TOKEN=$(curl -s -X POST $BASE/login -H 'Content-Type: application/json' \
        -d '{"mobile":"+919000000001","password":"..."}' | jq -r .access_token)
A="Authorization: Bearer $TOKEN"

curl -s $BASE/health | jq
curl -s $BASE/me -H "$A" | jq
PID=$(curl -s -X POST $BASE/patients/ -H "$A" -H 'Content-Type: application/json' -d @fixtures/patient.json | jq -r .id)
curl -s $BASE/patients/$PID -H "$A" | jq
TID=$(curl -s -X POST $BASE/triage/ -H "$A" -H 'Content-Type: application/json' -d @fixtures/triage_anc_high_bp.json | jq -r .id)
RID=$(curl -s -X POST $BASE/referrals/ -H "$A" -H 'Content-Type: application/json' -d @fixtures/referral.json | jq -r .id)
curl -s -X PATCH $BASE/referrals/$RID/status -H "$A" -H 'Content-Type: application/json' -d '{"status":"SLOT_BOOKED","slot_datetime":"2026-09-02T09:40:00Z","destination_org_unit_id":"..."}' | jq
curl -s "$BASE/referrals/exceptions" -H "$A" | jq .summary
curl -s $BASE/dashboard/facility/$ORG -H "$A" | jq .metrics
curl -s -X POST $BASE/sync/ -H "$A" -H 'Content-Type: application/json' -d @fixtures/sync_batch.json | jq
```

### 2.3 Compare frontend behaviour against `/docs`

For **every** frontend failure, inspect four things in order and record all four in the bug log:

| # | Check | Common finding |
|---|---|---|
| 1 | **Method** | Frontend sends `PUT`, backend expects `PATCH` |
| 2 | **URL** | Trailing slash. `POST /patients` vs `POST /patients/` — FastAPI redirects with a `307`, and a redirect **drops the Authorization header on some clients**, producing a mystifying 401 |
| 3 | **Headers** | Missing `Content-Type: application/json`; `Bearer` capitalisation; token expired |
| 4 | **Body and response shape** | Field renamed, nested where the client expects flat, enum value casing |

**Do not fix the backend to match a frontend mistake without checking `API_CONTRACT.md` first.** If the contract says one thing and the frontend does another, the frontend is wrong, and silently bending the backend breaks the other client.

### 2.4 Check database state after every failure

> Confirm that failed requests are not partially writing incorrect records.

This is the check most teams skip and it is the one that produces the worst demo failure — a half-written referral that then makes the dashboard count wrong.

```sql
-- after a failed POST /triage/
SELECT id, patient_id, disposition, created_at FROM triage ORDER BY created_at DESC LIMIT 5;
-- a failed request must leave NO row. A row with disposition NULL means the
-- engine ran after persistence, or the transaction was not atomic.

-- after a failed PATCH /referrals/{id}/status
SELECT r.id, r.status, r.updated_at,
       (SELECT count(*) FROM referral_transitions t WHERE t.referral_id = r.id) AS transitions
FROM referrals r WHERE r.id = '<id>';
-- status and the transition count must agree. A status change with no
-- transition row means the audit write is outside the transaction.

-- orphan check
SELECT count(*) FROM triage WHERE disposition IS NULL AND created_at > now() - interval '1 day';
-- must be 0 for anything created today
```

**Every write path must be one transaction.** Compute the decision, write the row, write the transition, write the audit entry — commit once. If any of those is outside the transaction boundary, a failure leaves the database inconsistent and the dashboard starts lying.

### 2.5 Bug log format

One file, `backend/docs/DAY3_BUGS.md`, both owners appending:

```markdown
| # | Sev | Endpoint | Symptom | Root cause | Fix | Verified by | Owner |
|---|-----|----------|---------|------------|-----|-------------|-------|
| 1 | P0 | POST /triage/ | 500 when vitals empty | KeyError in fallback | guard + default | exact failing curl + full chain | Iqra |
| 2 | P2 | GET /me | role returned lowercase | serializer | DEFERRED to Day 4 | — | — |
```

### 2.6 Re-verification rule

Per C10, each fix is verified twice:

1. **The exact failing request.** Same method, URL, headers and body that failed.
2. **The complete chain.** login → patient → triage → referral → status → exceptions → dashboard → sync.

A local fix is not enough. The chain is what the demo runs.

---

## 3. Step 3.2 — Validation and controlled error handling

### 3.1 The principle

> Convert expected failures into controlled HTTP responses. Never expose a stack trace.

A 500 with a traceback on a public demo URL is both an unprofessional demo moment and a genuine information disclosure — it names your file paths, your library versions and sometimes your SQL.

### 3.2 Validation matrix

Every row must return the stated status with a specific, plain-language message. "Invalid input" is not acceptable anywhere.

| Endpoint | Input | Expected | Code |
|---|---|---|---|
| `POST /patients/` | missing `full_name` | 422 | field named |
| `POST /patients/` | neither `date_of_birth` nor `age_years` | 422 | `AGE_REQUIRED` |
| `POST /patients/` | `age_years: 200` | 422 | `INVALID_AGE` |
| `POST /patients/` | malformed mobile | 422 | `INVALID_MOBILE` |
| `GET /patients/{id}` | non-UUID id | 422 | `INVALID_UUID` |
| `GET /patients/{id}` | valid UUID, no such patient | 404 | `NOT_FOUND` |
| `GET /patients/{id}` | exists, other district | **404** | `NOT_FOUND` — never 403 |
| `POST /triage/` | unknown `protocol` | 422 | `INVALID_PROTOCOL` |
| `POST /triage/` | `bp_systolic: 400` | 422 | `VITAL_OUT_OF_RANGE`, names field and range |
| `POST /triage/` | `bp_systolic: "high"` | 422 | type error, field named |
| `POST /triage/` | vitals `{}` on ANC | **200** | `insufficient_data: true`, disposition `REFER` |
| `POST /triage/` | non-existent `patient_id` | 404 | `PATIENT_NOT_FOUND` |
| `POST /referrals/` | invalid `urgency` | 422 | `INVALID_URGENCY` |
| `POST /referrals/` | destination not a facility type | 422 | `INVALID_ORG_UNIT_TYPE` |
| `PATCH /referrals/{id}/status` | `INITIATED → CLOSED` | 409 | `INVALID_TRANSITION` + `allowed_next` |
| `PATCH /referrals/{id}/status` | status not in enum | 422 | `INVALID_STATUS`, lists valid values |
| `PATCH /referrals/{id}/status` | `→ ARRIVED` no proof | 422 | `ARRIVAL_PROOF_REQUIRED` |
| `PATCH /referrals/{id}/status` | already `CLOSED` | 409 | `TERMINAL_STATE` |
| `GET /dashboard/facility/{id}` | non-existent facility | 404 | `FACILITY_NOT_IN_SCOPE` |
| `GET /dashboard/facility/{id}` | other district | **404** | `FACILITY_NOT_IN_SCOPE` |
| `GET /referrals/exceptions` | bad `stage=99` | 422 | `INVALID_FILTER` |
| `POST /sync/` | malformed batch | 422 | names the failing index |
| `POST /sync/` | same batch twice | 200 | idempotent, no duplicate |
| any | missing token | 401 | `UNAUTHENTICATED` |
| any | expired token | 401 | `TOKEN_EXPIRED` |
| any | stale `ver` token | 401 | `TOKEN_STALE` |
| any | valid token, no permission | 403 | `PERMISSION_DENIED`, **does not name the permission** |
| any | body is not JSON | 400 | `MALFORMED_JSON` |
| any | body over 1 MB | 413 | `PAYLOAD_TOO_LARGE` |

**`vitals: {}` returning 200 is deliberate and is the most important row in the table.** Missing vitals is a clinical situation, not a client error. It escalates to `REFER` with `insufficient_data: true` — a 422 there would let a field worker's incomplete assessment vanish rather than escalate.

### 3.3 Global exception handlers

Four handlers, registered on the app. After these, no unhandled exception can reach the client.

```python
# app/core/errors.py
@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    first = exc.errors()[0]
    field = ".".join(str(p) for p in first["loc"] if p not in ("body", "query"))
    return JSONResponse(422, {"error": {
        "code": "VALIDATION_ERROR",
        "message": f"Check the '{field}' field.",
        "detail": first["msg"],
        "field": field,
        "request_id": request.state.request_id,
    }})

@app.exception_handler(AppError)              # every domain error subclasses this
async def app_error_handler(request, exc):
    return JSONResponse(exc.status_code, {"error": {
        "code": exc.code, "message": exc.message, "detail": exc.detail,
        "field": exc.field, "request_id": request.state.request_id, **exc.extra,
    }})

@app.exception_handler(IntegrityError)
async def integrity_handler(request, exc):
    code, msg = map_constraint_to_error(exc)   # named constraint → friendly message
    log.warning("integrity_error", constraint=constraint_name(exc),
                request_id=request.state.request_id)
    return JSONResponse(409, {"error": {
        "code": code, "message": msg, "request_id": request.state.request_id}})
    # NEVER return str(exc) — it contains the SQL and the column values

@app.exception_handler(Exception)
async def unhandled_handler(request, exc):
    log.exception("unhandled", request_id=request.state.request_id, path=request.url.path)
    return JSONResponse(500, {"error": {
        "code": "INTERNAL_ERROR",
        "message": "Something went wrong. Please try again.",
        "request_id": request.state.request_id,
    }})
    # No type, no message, no traceback. The request_id is how support correlates
    # it with the server log, which is where the detail belongs.
```

### 3.4 Request ID middleware

Every request gets a UUID, echoed in the `X-Request-ID` response header, present in every log line and every error body. Without it, "it failed once around 3pm" is unsearchable.

### 3.5 Atomicity audit

For each of the five write paths, confirm one transaction wraps everything:

| Path | Must be atomic |
|---|---|
| `POST /patients/` | user row + patient row + consent row |
| `POST /triage/` | triage row + audit row |
| `POST /referrals/` | referral row + initial transition row + audit row |
| `PATCH /referrals/{id}/status` | referral update + transition row + audit row |
| `POST /sync/` | **per item**, not per batch — one bad item must not reject 49 good ones |

`POST /sync/` is the exception on purpose. A field worker syncing a day's work should not lose 49 records because item 23 is malformed. Process per item, return a per-item result array, and report partial success.

---

## 4. Step 3.3 — Triage and referral validation

### 4.1 Five reference cases — locked

These five are the demo's clinical credibility. They are defined once, committed as fixtures, and must return identical output every run.

| # | Case | Input | Expected disposition | Expected urgency |
|---|---|---|---|---|
| **R1** | Normal ANC | BP 118/76, Hb 11.4, no danger signs | `MANAGE_HERE` | `ROUTINE` |
| **R2** | Borderline ANC | BP 142/92, no danger signs | `REFER` | `WITHIN_24H` |
| **R3** | Emergency — hypertensive | BP 172/116 | `EMERGENCY` | `IMMEDIATE` |
| **R4** | Emergency — danger sign | BP 130/84, `danger_signs: ["convulsions"]` | `EMERGENCY` | `IMMEDIATE` |
| **R5** | Emergency — universal vital | any protocol, `spo2: 86` | `EMERGENCY` | `IMMEDIATE` |
| **R6** | Insufficient data | ANC, `vitals: {}` | `REFER` + `insufficient_data: true` | `WITHIN_24H` |

R5 exists to prove the universal-emergency rule fires **before** the protocol rules. R6 proves uncertainty escalates. Both are the cases a judge or clinician will ask about.

### 4.2 Run them at two levels

1. **Unit** — call the engine directly. Fast, and isolates rule bugs.
2. **API** — `POST /triage/` over real HTTP. This is the one that counts; a rule that works in Python and fails through the endpoint is still a broken demo.

### 4.3 Persistence check

For each case, after the API call:

```sql
SELECT disposition, urgency, insufficient_data, engine, protocol_version
FROM triage WHERE id = '<returned id>';
```

**Stored values must equal returned values, field for field.** A mismatch means the response is computed from something other than what was written, and the dashboard will disagree with the API.

### 4.4 Referral creation from a triage decision

For `REFER` and `EMERGENCY` cases, create the referral and link it:

- `referral.triage_id` points at the triage encounter
- `referral.urgency` derives from the triage urgency: `IMMEDIATE → EMERGENCY`, `WITHIN_2H/WITHIN_24H → URGENT`, `WITHIN_72H → PRIORITY`, `WITHIN_7D/ROUTINE → ROUTINE`
- `due_at` computed from that urgency

Verify the mapping explicitly. A triage that says "immediate" producing a referral due in 7 days is a silent, serious bug.

### 4.5 Breach check — controlled synthetic overdue case

Do **not** wait for a real breach, and do **not** change the server clock.

```python
# Create a referral with initiated_at backdated, then run detection
referral.initiated_at = now - timedelta(hours=30)
referral.due_at = compute_due_at(referral.initiated_at, "URGENT")   # = now - 6h
await detect_breaches(session)
# assert it now appears in GET /referrals/exceptions
```

Backdating the row is deterministic and repeatable. Moving the system clock breaks JWT validation and confuses everything else on the machine.

Then verify:
- it appears in `/referrals/exceptions` with `breached_at` set
- `escalation.stage >= 1`
- the dashboard `breached` count incremented by exactly 1
- `detect_breaches()` run twice does not escalate twice

### 4.6 Transition check

Walk the full path and record each response:

```
INITIATED → SLOT_BOOKED → TRANSPORT_ARRANGED → ARRIVED → CONSULTED → BACK_REFERRED → CLOSED
```

Then the rejections:

| Attempt | Expected |
|---|---|
| `INITIATED → CLOSED` | 409 `INVALID_TRANSITION`, `allowed_next` listed |
| `CLOSED → ARRIVED` | 409 `TERMINAL_STATE` |
| `→ ARRIVED` without proof | 422 `ARRIVAL_PROOF_REQUIRED` |
| `→ REFUSED` without reason | 422 `TRANSITION_FIELD_REQUIRED` |

And the recovery branch, because it is the one nobody tests:

```
INITIATED → NOT_ARRIVED → TRACED → RESCHEDULED → SLOT_BOOKED → ARRIVED → CONSULTED → CLOSED
```

Confirm `RESCHEDULED` cleared `breached_at` and recomputed `due_at`.

---

## 5. Step 3.4 — Offline → reconnect → sync

> **Mandatory again on Day 3 even if it passed on Day 2 evening.**

That instruction is in the source plan and it is correct. Sync is the single most fragile path in an offline-first system, and it is the one most likely to be broken by an unrelated Day 3 fix.

### 5.1 The nine steps

| # | Step | Verification |
|---|---|---|
| 1 | **Disconnect** — airplane mode on the device/emulator | No network reachable; confirm the app knows it |
| 2 | **Register** a patient | Row exists in local storage; UI shows local-first behaviour; **no error shown to the user** |
| 3 | **Triage offline** | Vitals captured; **disposition produced locally**; red flag fires offline if applicable |
| 4 | **Create referral** | Stored locally with a client-generated UUID |
| 5 | **Reconnect** | Connectivity restored |
| 6 | **Automatic sync** | Listener fires **without a manual tap**. Log the trigger |
| 7 | **Backend receipt** | `POST /sync/` receives the batch; rows persisted; server IDs reconciled |
| 8 | **Idempotency** | Replay the identical batch → no duplicates, same response |
| 9 | **Dashboard** | Counts reflect the synced records |

### 5.2 What must be true at step 3

The offline disposition must come from the **same rule set** as the server. If the device runs one version and the server another, a patient triaged offline gets a different answer than the same patient triaged online. Verify the protocol version string matches.

If the client cannot run the rules, the record syncs without a disposition and the server computes it on receipt — but then the field worker had no red-flag warning at the point of care, which is the entire clinical value of offline triage. Know which of these your build does, and be able to say so.

### 5.3 What must be true at step 8

Idempotency key is the **client-generated record UUID**, not a batch hash. A retry with one extra record must insert one record, not reject the batch and not duplicate the other 49.

```
First send:  50 records → 200, {"created": 50, "duplicates": 0}
Replay:      same 50    → 200, {"created": 0,  "duplicates": 50}
Replay + 1:  51 records → 200, {"created": 1,  "duplicates": 50}
```

### 5.4 Run it twice

Once early (14:30) and once after the deployment hardening in 3.6. Security headers, CORS and rate limits have all broken working sync paths before.

---

## 6. Step 3.5 — Two-device concurrency test

> Test with at least two devices or emulators through the real backend.

This is not the same test twice. It exists to find concurrency bugs.

| # | Scenario | Expected |
|---|---|---|
| 1 | Two devices, two different ASHAs, same village, register patients simultaneously | Both succeed, two distinct records, no ID collision |
| 2 | Both sync batches at the same moment | Both accepted, no deadlock, no lost batch |
| 3 | Device A and device B both `PATCH` the **same referral** to different statuses | One succeeds; the other gets **409 `INVALID_TRANSITION`** against the already-updated state — not a silent overwrite |
| 4 | Device A registers a patient offline; device B registers **the same person** online | Both land. Duplicate-detection flags them. **Neither is silently dropped** |
| 5 | Two devices open the dashboard during a sync | Counts may differ by seconds; neither errors |
| 6 | ASHA from block A requests a referral belonging to block B | 404, and the audit log records the denial |

**Scenario 3 is the important one.** Last-write-wins on a referral status would let a device with stale state move a `CLOSED` referral back to `ARRIVED`. The transition guard already prevents it — this test proves the guard is checked against the **current database state**, not against the state the client believed.

---

## 7. Step 3.6 — Deployment hardening

Before the public smoke test, not after.

### 7.1 Security headers

```python
@app.middleware("http")
async def security_headers(request, call_next):
    r = await call_next(request)
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["Referrer-Policy"] = "no-referrer"
    r.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    r.headers["Cache-Control"] = "no-store"          # responses carry PHI
    r.headers.pop("Server", None)
    r.headers.pop("X-Powered-By", None)
    return r
```

### 7.2 CORS

Explicit origins only. `allow_origins=["*"]` with `allow_credentials=True` is both rejected by browsers and a real vulnerability.

```python
app.add_middleware(CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,     # the real frontend URLs, listed
    allow_credentials=True,
    allow_methods=["GET","POST","PATCH","DELETE","OPTIONS"],
    allow_headers=["Authorization","Content-Type","X-Request-ID"],
    expose_headers=["X-Request-ID"],
    max_age=600)
```

### 7.3 Rate limits on the public deployment

| Endpoint | Limit |
|---|---|
| `POST /login`, `/auth/login` | 20 per 15 min per IP |
| `POST /auth/otp/request` | 5/hour per mobile, 20/hour per IP |
| `POST /auth/patient/register` | 3/hour per mobile |
| `POST /sync/` | 60/hour per user (batches are large) |
| everything else | 300/min per user |

A rate-limited response is **429 with `Retry-After`**, never a dropped connection.

### 7.4 Deployment checklist

- [ ] `DEBUG=false`; FastAPI docs reachable but no debug middleware
- [ ] Every secret from the platform's secret store, none in the image
- [ ] **Demo keys are fresh and different from development keys.** If a dev key ever touched a chat message, it is compromised
- [ ] `DATABASE_URL` points at the demo database, not a laptop tunnel
- [ ] `alembic upgrade head` run against the deployed database; `alembic current` matches the local head
- [ ] `TRIAGE_ENGINE` and `ESCALATION_ENGINE` explicitly set — never left to `auto` in the demo, so the engine cannot change silently between rehearsal and performance
- [ ] TLS terminates correctly; HTTP redirects to HTTPS
- [ ] `/health` returns 200 **and** checks the database, and reports the migration head
- [ ] Logs are structured, carry `request_id`, and contain **no PHI and no tokens**
- [ ] A database snapshot exists, taken immediately before the smoke test

### 7.5 Deepen `/health`

```json
{
  "status": "ok",
  "version": "demo-v1.0",
  "commit": "a1b2c3d",
  "migration_head": "0012_dashboard_indexes",
  "database": "ok",
  "triage_engine": "fallback",
  "escalation_engine": "fallback",
  "time": "2026-09-01T18:02:11Z"
}
```

This stays public and must contain **no** counts, no names, no connection strings. Its value on demo day is answering "is it actually up, and is it the build we tested?" in one call.

---

## 8. Step 3.7 — Demo seed and reset

### 8.1 Deterministic synthetic dataset

`backend/scripts/seed_demo.py`, fixed UUIDs, fixed names, fixed values. Rerunning it produces the identical database.

```
1  district, 1 block, 1 PHC, 1 HWC, 2 villages
6  users: DHO, BMO, MO, CHO, ANM, ASHA  (+ 1 patient account)
12 patients — fake names, Indian-context, spread across both villages
8  triage encounters covering all four dispositions
5  referrals:  2 on track · 1 breached (backdated) · 1 closed · 1 refused
1  sync batch, pre-staged for the offline demo
```

**Deterministic IDs matter.** The demo script can then reference `patient 03` by a known UUID instead of someone squinting at a list on stage.

### 8.2 Reset script

`backend/scripts/reset_demo.sh` — truncate the demo tables, re-seed, verify counts. Must run in under 30 seconds, because you will run it between the rehearsal and the real thing, and possibly during.

### 8.3 Synthetic data only

> **Use synthetic data only during production smoke testing. A public demo backend is not permission to use real patient data.**

That line from the source plan is correct and is a legal position, not a style preference. Under the DPDP Act the demo backend is a data fiduciary the moment a real person's health data enters it, with every obligation that follows. Add an automated guard:

```python
# tests/test_no_real_data.py — runs in CI against the demo database
FORBIDDEN_PATTERNS = [r"\+91[6-9]\d{9}"]          # real-format mobiles outside the demo range
DEMO_MOBILE_RANGE = "+9190000000"                  # every seeded number starts with this
# assert every patient mobile in the demo DB starts with DEMO_MOBILE_RANGE
```

---

## 9. Step 3.8 — Production smoke test

> A hosting platform showing "deployed" is not enough. Run these against the actual public backend.

### 9.1 The smoke table

| # | Smoke test | Expected result |
|---|---|---|
| 1 | `GET /docs` | Loads from the public URL |
| 2 | `GET /health` | 200, no 5xx, correct `migration_head` |
| 3 | `POST /login` | Synthetic demo account receives a JWT |
| 4 | `GET /me` | Expected authenticated identity and role |
| 5 | `POST /patients/` | Synthetic patient created |
| 6 | `GET /patients/{id}` | Created patient returned |
| 7 | `POST /triage/` | Correct disposition returned |
| 8 | `POST /referrals/` | Referral created |
| 9 | `PATCH /referrals/{id}/status` | Valid transition succeeds |
| 10 | `GET /referrals/exceptions` | Breached synthetic cases returned |
| 11 | `GET /dashboard/facility/{id}` | Correct aggregate counts |
| 12 | `POST /sync/` | Offline batch accepted; retry is idempotent |

### 9.2 Additions the source table does not cover

Twelve positive cases prove it works. These prove it fails **safely**, which is what an audience or a judge probes.

| # | Test | Expected |
|---|---|---|
| 13 | Request with **no token** | 401, not 500 |
| 14 | Request with a **tampered token** | 401 |
| 15 | `INITIATED → CLOSED` | 409 with `allowed_next` |
| 16 | `GET /patients/{random-uuid}` | 404, no stack trace |
| 17 | Malformed JSON body | 400, no stack trace |
| 18 | `GET /dashboard/facility/{other-district}` | 404, not 403 |
| 19 | 25 rapid logins | 429 with `Retry-After`, service still up |
| 20 | Response headers | `X-Content-Type-Options`, `X-Frame-Options`, `X-Request-ID` present; no `Server` header |
| 21 | Any error response | Contains `request_id`, contains no file path and no SQL |
| 22 | **Latency** — 10 runs of the full chain | p95 under 2 s per call over public internet |
| 23 | HTTP (not HTTPS) | Redirects to HTTPS |
| 24 | Full chain run **twice in a row** | Identical behaviour both times |

**Test 24 catches state-dependent bugs**, which are the classic "it worked in rehearsal" failure. Something cached, a counter incremented, a row left behind.

**Test 22 matters because the demo is over public internet**, not localhost. A dashboard that returns in 80 ms locally and 4 s over the venue's wifi reads on stage as broken.

---

## 10. Step 3.9 — Rehearsal and failure playbook

### 10.1 Rehearse the actual demo

Against the **public URL**, with the **demo device**, on the **venue-like network** (tether to a phone if you can). Time each step. Anything over 5 seconds needs either a fix or a line of narration to cover it.

### 10.2 Failure playbook

Decide these **now**, in writing, while calm. Mid-demo is not when to invent a recovery.

| Failure on stage | Response |
|---|---|
| Public backend unreachable | Switch to the local backend on the laptop, pre-started and warm. Say so plainly: "I'll run this locally." |
| A call returns 500 | Do not retry twice. Move to the next demo step; return to it only if time allows |
| Sync does not fire | Trigger it manually. Explain that automatic sync is connectivity-listener driven |
| Dashboard counts look wrong | Run `reset_demo.sh`, which takes under 30 s, and continue |
| Auth fails | Use the pre-generated long-lived demo token from the runbook |
| Device or emulator dies | Continue from the API via a prepared HTTP client with the chain saved |
| Total network loss | Demonstrate the offline flow — it is a genuine feature, and this is the one failure that flatters the product |

### 10.3 Demo runbook

`backend/docs/DEMO_RUNBOOK.md`: exact click path and curl sequence, credentials for every demo account, the fixed UUIDs, the reset command, the playbook above, and a **do-not-click list** of known-fragile paths from `KNOWN_ISSUES.md`.

---

## 11. Step 3.10 — Freeze

### 11.1 What freeze means

> **Freeze the demo backend after rehearsal.**

Concretely:

1. **Tag it.** `git tag -a demo-v1.0 -m "Demo freeze"` on the exact commit that was rehearsed, and push the tag.
2. **Record the deployed commit.** `/health` must report a commit that matches the tag. If it does not, the thing you rehearsed is not the thing that is deployed — stop and redeploy.
3. **Snapshot the database.** `pg_dump` the demo database post-seed, stored somewhere restorable in under two minutes.
4. **Name a freeze owner.** One person. Only they can authorise an unfreeze.
5. **Stop merging.** No pushes to `backend` after the freeze. Work continues on `day4/*` branches.
6. **Record the state.** Deployed commit, migration head, engine settings, seed version, known issues — in `DEMO_RUNBOOK.md`.

### 11.2 Unfreeze criteria

Only a **P0 demo blocker discovered after the freeze** justifies unfreezing. Then:

- Both backend owners agree, in writing
- The fix is the smallest possible change
- The **full** production smoke test re-runs — all 24 tests, not just the fixed one
- A new tag `demo-v1.1`
- The rehearsal runs again

If there is not time to re-run the smoke test, there is not time to make the change. Ship the known bug and narrate around it. A known bug is manageable; an untested fix is not.

### 11.3 Rollback

```bash
git checkout demo-v1.0
# redeploy from the tag
psql $DEMO_DB < backups/demo_frozen_2026-09-01.sql
curl -s $PUBLIC/health | jq .commit   # must equal the tag's commit
```

Rehearse the rollback once. An untested rollback is a hope, not a plan.

---

## 12. Go / No-Go gate

Run at the end of Day 3. **Every P0 row must be green or the demo plan changes.**

| # | Gate | P0? |
|---|---|---|
| 1 | Clean checkout runs from documented setup in under 20 min | P0 |
| 2 | Full chain passes locally | P0 |
| 3 | Full chain passes against the public URL | P0 |
| 4 | All six triage reference cases return expected output via HTTP | P0 |
| 5 | Stored triage values equal returned values | P0 |
| 6 | Valid transition path completes; invalid transition rejected with 409 | P0 |
| 7 | Synthetic breached referral appears in `/referrals/exceptions` | P0 |
| 8 | Dashboard counts match seeded data | P0 |
| 9 | Offline → reconnect → sync passes end to end | P0 |
| 10 | Sync replay is idempotent | P0 |
| 11 | No stack trace on any error path | P0 |
| 12 | No unhandled 500 in the 24-test smoke run | P0 |
| 13 | Two-device concurrency scenarios pass | P1 |
| 14 | p95 latency under 2 s over public internet | P1 |
| 15 | Security headers present; CORS restricted | P1 |
| 16 | Rate limits return 429 with `Retry-After` | P1 |
| 17 | Demo database contains synthetic data only | **P0 — legal** |
| 18 | Seed and reset scripts work; reset under 30 s | P0 |
| 19 | Rehearsal completed against the public URL | P0 |
| 20 | Failure playbook written | P0 |
| 21 | `demo-v1.0` tagged; deployed commit matches | P0 |
| 22 | Database snapshot taken and restore rehearsed | P1 |
| 23 | `KNOWN_ISSUES.md` written with a do-not-click list | P0 |
| 24 | Freeze owner named | P0 |

---

## 13. Known issues register

`backend/docs/KNOWN_ISSUES.md` — every P2 and P3 found today, with what it is, why it was deferred, and whether it is safe to touch during the demo.

```markdown
| # | Sev | Area | Symptom | Demo safe? | Do not click | Day 4 |
|---|-----|------|---------|-----------|--------------|-------|
| 1 | P2 | /me | role lowercase | yes | — | fix |
| 2 | P2 | dashboard | synced_today stale up to 60s (cache) | yes | don't refresh twice fast | document |
| 3 | P3 | exceptions | no CSV export | yes | export button absent | backlog |
```

**Writing this down is what converts a surprise into a talking point.** A team that says "yes, that's a known caching delay, it's in our issues list" reads as competent. The same team discovering it live reads as unprepared.

---

## 14. Day 3 Definition of Done

### Stability
- [ ] Clean checkout from documented setup succeeds, timed
- [ ] Day 2 smoke chain replays green
- [ ] Every P0 and P1 bug fixed and verified by the exact failing request **and** the full chain
- [ ] Every P2/P3 logged in `KNOWN_ISSUES.md`, not fixed
- [ ] No failed request leaves a partial row in any table

### Validation and errors
- [ ] Every row of the §3.2 validation matrix returns the stated status and code
- [ ] Four global exception handlers registered
- [ ] No stack trace, file path, SQL or library version in any response
- [ ] `X-Request-ID` on every response and in every log line
- [ ] All five write paths atomic; `/sync/` per-item

### Clinical correctness
- [ ] Six reference cases correct via unit **and** HTTP
- [ ] Stored values equal returned values
- [ ] Triage urgency → referral urgency mapping verified
- [ ] Synthetic breach appears in exceptions; escalation stage set
- [ ] Full valid transition path; all four rejection cases correct
- [ ] `RESCHEDULED` recovery branch verified

### Offline and concurrency
- [ ] Nine-step offline → sync passed, twice, second run after hardening
- [ ] Replay idempotent; partial-batch behaviour correct
- [ ] Six two-device scenarios pass
- [ ] Concurrent status update produces 409, not a silent overwrite

### Deployment
- [ ] Security headers; CORS restricted to named origins
- [ ] Rate limits return 429 with `Retry-After`
- [ ] `DEBUG=false`; secrets from the platform store; demo keys fresh
- [ ] `/health` reports version, commit, migration head, database, engines
- [ ] Deployed migration head equals local head
- [ ] Engines explicitly set, never `auto`

### Demo readiness
- [ ] Deterministic seed; reset under 30 s
- [ ] **Synthetic data only** — automated guard passes
- [ ] All 24 smoke tests pass against the public URL
- [ ] Full chain run twice produces identical behaviour
- [ ] Rehearsed against the public URL on a venue-like network
- [ ] `DEMO_RUNBOOK.md` complete with failure playbook and do-not-click list
- [ ] `demo-v1.0` tagged; `/health` commit matches
- [ ] Database snapshot taken; restore rehearsed
- [ ] Freeze owner named; team informed the branch is closed

---

*`Day3.md` · SETU-Swasthya backend · Stabilization · v1.0 · Companion: `Day3Prompt.md`*
