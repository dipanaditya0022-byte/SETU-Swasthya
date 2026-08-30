# SETU-Swasthya API Contract

## Purpose

This document defines the Day 1 backend API contract for the SETU-Swasthya MVP.

The backend is built with FastAPI and PostgreSQL.

All frontend integrations should use the endpoint paths, request shapes, and response shapes documented here.

## POST /patients/

Creates a new patient. Requires `Authorization: Bearer <access_token>`
and the `patient:create` permission (Day 1 RBAC, backend/docs/Day1.md
§14.1).

**Amended 2026-08-30 (Day 1 RBAC, §20):** `phone` is now required. It
was previously accepted as `null` -- as of the credential-expiry/RBAC
work, `POST /patients/` also links a `users` identity row (Day1.md
§5.4's "Assisted registration"), which needs a mobile number to exist
at all. A request with `phone: null` or omitted now returns `422
PHONE_REQUIRED`. This is a deliberate, approved change to this
documented contract, confirmed directly with the document owner --
every other field is unchanged.

### Request

```json
{
  "name": "Test Patient",
  "age": 25,
  "village": "Test Village",
  "phone": "+919000000001",
  "facility_id": "00000000-0000-0000-0000-000000000001",
  "client_uuid": null
}
```

### Response

Returns the created patient with a generated `id` and `created_at`.
Also now includes `created_by_user_id` and `org_unit_id` (the
authenticated actor and their posting), added additively as part of
Day 1's authorization model -- not client-supplied.

## GET /patients/{patient_id}

Returns a patient by UUID. Requires `Authorization: Bearer <access_token>`
and the `patient:read` permission; the record must also be within the
actor's scope. PHI reads are audited.

### Path Parameter

- `patient_id`: UUID of the patient

### Response

Returns the matching patient. Returns `404` if the patient does not
exist, and also `404` (not `403`) if it exists but is outside the
actor's scope -- deliberate, so a 403 can't be used to probe for the
existence of a record outside your area (Day 1 RBAC, §16.2).

## POST /triage/

Creates a triage encounter for a patient. Requires `Authorization:
Bearer <access_token>` and the `triage:create` permission; the
referenced patient must be within the actor's scope.

### Request

```json
{
  "patient_id": "b76d30d8-faa5-4fbb-b347-2e42dbb8218e",
  "facility_id": "00000000-0000-0000-0000-000000000001",
  "triage_disposition": "Manage here",
  "referral_urgency": "routine"
}
```

### Response

Returns the created triage encounter with a generated `id` and `created_at`.

## POST /referrals/

Creates a referral for a patient. Requires `Authorization: Bearer
<access_token>` and the `referral:create` permission; the referenced
patient must be within the actor's scope.

### Request

```json
{
  "patient_id": "b76d30d8-faa5-4fbb-b347-2e42dbb8218e",
  "from_facility_id": "00000000-0000-0000-0000-000000000001",
  "destination_facility_id": "00000000-0000-0000-0000-000000000001",
  "reason": "Specialist consultation required",
  "urgency": "routine",
  "receiving_unit": "General OPD",
  "owner": "Test User"
}
```

### Response

Returns the created referral with status `INITIATED`.

## PATCH /referrals/{referral_id}/status

Updates the status of an existing referral. Requires `Authorization:
Bearer <access_token>` and the `referral:update_status` permission; the
referral must be within the actor's scope.

### Path Parameter

- `referral_id`: UUID of the referral

### Query Parameter

- `status`: New referral status

### Response

Returns the updated referral. Returns `404` if the referral does not
exist, and also `404` (not `403`) if it exists but is outside the
actor's scope -- same reasoning as GET /patients/{patient_id} above.

## POST /sync/

Accepts a batch of offline-created records keyed by `client_uuid`.
Requires `Authorization: Bearer <access_token>`. Any record carrying its
own `org_unit_id` is checked against the actor's scope; a record failing
that check is marked `"status": "rejected"` in the response rather than
failing the whole batch.

### Request

```json
[
{
  "client_uuid": "test-client-001",
  "name": "Offline Patient 1"
},
{
  "client_uuid": "test-client-002",
  "name": "Offline Patient 2"
}
]
```

### Response

Returns the number of records submitted (`synced`, unchanged meaning)
and each record's own `status` (`"accepted"` or `"rejected"`).

## POST /login

**Amended 2026-08-30 (Day 1 RBAC, §16).** Permanent alias of
`POST /auth/login` (both routes call the exact same handler). No longer
authenticates a hardcoded user — this now checks real accounts in the
RBAC `users` table. The request body accepts every field either login
method needs; you only ever fill in the subset your account's role
actually requires, per Day1.md §10.1's per-role login method table.

### Request

```json
{
  "mobile": "string",
  "email": "string",
  "password": "string",
  "otp_token": "string",
  "device_fingerprint": "string",
  "device_label": "string"
}
```

| Field | Required when | Notes |
|---|---|---|
| `mobile` | Always, unless `email` is given | Whichever identifier the account was registered/invited with |
| `email` | Only if `mobile` is omitted | Same as above |
| `password` | Role's login method is `password` (most staff roles) | Set via `POST /auth/invite/accept` at account activation, or later via `POST /auth/password/change`/`reset` |
| `otp_token` | Role's login method is `otp` (`ASHA`, `PATIENT`, `VHSNC_MEMBER`) | **Not** the raw 6-digit code. Call `POST /auth/otp/request` first (sends/prints an OTP), then `POST /auth/otp/verify` with that raw OTP — its response is this `otp_token` |
| `device_fingerprint` | Never required | Optional client-supplied label, shown later in `GET /auth/sessions` |
| `device_label` | Never required | Same as above |

### Response

Normal success — a JWT bearer token, refresh token, and expiry:

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "bearer",
  "expires_in": 900
}
```

If the role has mandatory MFA and is already enrolled, a correct
password/OTP instead returns an MFA challenge, not tokens yet:

```json
{"mfa_required": true, "mfa_challenge_token": "...", "amr_so_far": ["pwd"]}
```

Complete the login by calling `POST /auth/mfa/verify` with that
`mfa_challenge_token` and a current TOTP code.

---

## GET /me

**Amended 2026-08-30 (Day 1 RBAC, §14.1).** Permanent alias of
`GET /auth/me`. Response gains `role`, `permissions`, and `scope` on top
of the original identity fields — no existing field was removed.

### Header

- `Authorization: Bearer <access_token>`

### Response

```json
{
  "id": "...",
  "role": "BMO",
  "permissions": ["patient:create", "patient:read", "..."],
  "scope": {"org_unit_id": "...", "scope_path": "/UP/KANPUR/..."},
  "full_name": "...",
  "mobile_masked": "+91XXXXX00001"
}
```

---

# Day 1 identity & RBAC API surface (added 2026-08-30, §14.2/§14.3/§22)

Everything below this line is additive documentation for the identity,
registration, and access-control endpoints built across Day 1's RBAC
work (backend/docs/Day1.md §5-§17). Nothing above this line was changed
by adding this section. Every request field, response field, error
code, and permission name here is either quoted directly from Day1.md
or, where Day1.md gives no literal example (most of §14.3's authenticated
routes), taken from the actual, tested route implementation in
`app/api/routes/auth.py`, `app/api/routes/users.py`, and
`app/api/routes/governance.py`.

Base URL for all examples below: `http://localhost:8002` (or your own
deployment). All request/response bodies are `application/json` unless
stated otherwise. `Authorization: Bearer <access_token>` is required on
every endpoint in the "Authenticated" section and optional/absent on
every endpoint in the "Public" section.

## Public endpoints

### POST /auth/otp/request

Send an OTP to a mobile number. **Auth:** none. **Rate limit:** 5/h per
mobile, 20/h per IP (Day1.md §14.2).

**Request**
```json
{"mobile": "+919000000001", "purpose": "PATIENT_REGISTRATION"}
```
`purpose` is one of `PATIENT_REGISTRATION`, `LOGIN`, `INVITE_ACCEPT`,
`PASSWORD_RESET`.

**Response** `200`
```json
{"otp_sent": true, "expires_in": 300}
```
In development, the raw OTP is printed to the server's own log
(`DEV OTP for +91XXXXX00001 (purpose=...): 123456`) — **never** returned
in this response, and never sent this way in production (no SMS/email
gateway is wired up yet — `SMS_GATEWAY_URL` is an intentionally empty
placeholder).

### POST /auth/otp/verify

Verify an OTP, return a short-lived `otp_token`. **Auth:** none.
**Rate limit:** 10/h per mobile.

**Request**
```json
{"mobile": "+919000000001", "otp": "123456"}
```

**Response** `200`
```json
{"otp_token": "..."}
```

**Errors:** `401 OTP_INVALID` — wrong or expired code.

### POST /auth/patient/register

**The only public staff-or-patient registration endpoint** (Day1.md
§14.2's own words). No `role` field exists in this schema at all —
posting one is a `422`, not silently accepted as a staff role (this is
the whole point: staff self-registration is impossible by construction,
not by a runtime check). **Auth:** none. **Rate limit:** 3/h per mobile,
10/h per IP.

**Request**
```json
{
  "full_name": "Rekha Devi", "age_years": 28, "sex": "FEMALE",
  "mobile": "+919000000001", "is_shared_phone": false,
  "village_lgd_code": "V0012", "preferred_language": "hi",
  "consent_keep_record": true, "consent_share_specialist": true,
  "consent_share_facility": false, "consent_anonymised_planning": false,
  "consent_mode": "DIGITAL_SELF", "otp_token": "<from /auth/otp/verify>"
}
```
Also accepts: `full_name_local`, `date_of_birth` (one of `date_of_birth`
or `age_years` is required), `abha_number` (14 digits), `abha_address`,
`hamlet`, `house_number`, `household_id`, `guardian_name`/
`guardian_relation`/`guardian_mobile` (required if under 18),
`emergency_contact_name`/`emergency_contact_mobile`.

**All four `consent_*` fields may be `false` and registration still
succeeds** — refusing consent is never harder than granting it, and
never blocks account creation (Day1.md §5.4's own "critical rule").

**Response** `201`
```json
{"id": "...", "status": "ACTIVE", "created_by_user_id": null, "mobile_masked": "+91XXXXX00001"}
```

**Errors:** `409 MOBILE_ALREADY_REGISTERED`; `401 OTP_INVALID`/expired
token; `422` for a missing `role`-adjacent field, a bad ABHA checksum,
or a minor missing guardian fields.

### POST /auth/login

Password or OTP login, depending on the account's role (Day1.md §10.1's
own per-role table). **Auth:** none. **Rate limit:** 20/15 min per IP.
This is the handler `POST /login` (documented above, unchanged section)
is a permanent alias of — see that section for the full field table and
response shape (including the MFA-challenge response). Not repeated
here to avoid two sources of truth for the same body.

### POST /auth/mfa/verify

Second factor, completing a login that returned `mfa_required: true`.
**Auth:** none (the `mfa_challenge_token` itself is the credential — a
short-lived, purpose-scoped JWT, distinct from an access token).
**Rate limit:** 5 per login attempt.

**Request**
```json
{"mfa_challenge_token": "...", "totp_code": "123456", "device_fingerprint": null, "device_label": null}
```

**Response** `200` — same shape as `POST /auth/login`'s success response
(`access_token`, `refresh_token`, `token_type`, `expires_in`).

**Errors:** `401 INVALID_MFA_CHALLENGE` — expired/invalid challenge
token; `401 MFA_INVALID` — wrong TOTP code; `401 MFA_NOT_ENROLLED`.

### POST /auth/token/refresh

Rotate an access/refresh token pair. **Auth:** none (the refresh token
itself is the credential). **Rate limit:** 60/h per session.

**Request**
```json
{"refresh_token": "...", "device_fingerprint": null}
```

**Response** `200` — `{"access_token", "refresh_token", "token_type", "expires_in"}`, same shape as login.

**Errors:** `401 INVALID_REFRESH_TOKEN`; `401 TOKEN_REUSE_DETECTED` —
an already-rotated (or already-revoked) token was replayed; the entire
token family is immediately revoked and the DPO/security team is
alerted (Day1.md §10.4); `401 REFRESH_TOKEN_EXPIRED`;
`401 DEVICE_MISMATCH`; `401 ACCOUNT_NOT_ACTIVE`.

### POST /auth/invite/accept

Activate an invited staff or bootstrapped-SUPERUSER account. **Auth:**
none (the invite `token` is the credential). **Rate limit:** 5 per
token.

**Request**
```json
{"token": "...", "password": "Correct-Horse-42!", "password_confirm": "Correct-Horse-42!", "mobile_otp": "123456"}
```
`password`/`password_confirm` are omitted for `ASHA` (its `accept_mode`
is `OTP_ONLY` — no password is ever set). `mobile_otp` is always
required regardless of `accept_mode` — it's the second factor proving
possession of the phone the invite was addressed to (Day1.md §7.2:
"bound to the mobile... a stolen link alone is not enough"), obtained
via `POST /auth/otp/request` with `purpose: "INVITE_ACCEPT"`.

**Response** `200`
```json
{"status": "ACTIVE", "mfa_enrolment": {"mfa_secret": "...", "provisioning_uri": "otpauth://..."}}
```
`mfa_enrolment` is `{}` for a role that doesn't require MFA.
**The invite token is never in this response, in any form, at any
point** (Day1.md §7.2: "Never echoed to the creator — Absent from the
201 response body and from all logs").

**Errors:** `401 INVITE_INVALID`; `410 INVITE_ALREADY_USED` — replaying
a token that already activated an account; `410 INVITE_EXPIRED`;
`410 INVITE_REVOKED`; `401 OTP_INVALID`; `422 PASSWORD_MISMATCH`;
`422 PASSWORD_POLICY_VIOLATION`.

### POST /auth/password/reset-request

Begin a password reset. **Auth:** none. **Rate limit:** 3/h per mobile.

**Request** `{"mobile": "+919000000001"}`

**Response** `200 {"reset_requested": true}`-shaped acknowledgement
(uniform regardless of whether the mobile is registered, so this
endpoint cannot be used to enumerate accounts). In dev, the OTP is
printed to the server log the same way `/auth/otp/request` does.

### POST /auth/password/reset

Complete a password reset. **Auth:** none. **Rate limit:** 5 per token.

**Request**
```json
{"mobile": "+919000000001", "otp": "123456", "new_password": "Correct-Horse-42!", "new_password_confirm": "Correct-Horse-42!"}
```

**Response** `200 {"status": "PASSWORD_RESET"}`-shaped confirmation.

**Errors:** `401 OTP_INVALID`; `422 PASSWORD_MISMATCH`;
`422 PASSWORD_POLICY_VIOLATION`.

### GET /.well-known/jwks.json

The RS256 public signing key(s), for any service that needs to verify
an access token independently. **Auth:** none. **Rate limit:** none.

**Response** `200`
```json
{"keys": [{"kty": "RSA", "alg": "RS256", "kid": "...", "n": "...", "e": "..."}]}
```
Exposes only the public modulus/exponent — never a private key
component (Day1.md §10.3: "RS256; only the auth service holds the
private key").

---

## Authenticated endpoints

All require `Authorization: Bearer <access_token>` unless noted.
Endpoints marked with a specific permission additionally require the
caller's role to hold that permission (`role_permissions`, seeded per
Day1.md §8.2/§8.3) — a `403 PERMISSION_DENIED` response never reveals
*which* permission was missing (Day1.md §10.6, to avoid mapping the
permission model for an attacker).

### GET /auth/me

Alias target for `GET /me` (documented above, unchanged section) — see
that section for the full response shape. **Permission:** none beyond
being an authenticated, ACTIVE account.

### POST /auth/logout

Revokes the current session's refresh token only. **Permission:** none.

**Response** `200 {"logged_out": true}`

### POST /auth/logout-all

Revokes every refresh token for the calling account, across all
devices. **Permission:** none.

**Response** `200 {"logged_out": true, "sessions_revoked": true}`

### POST /auth/password/change

Requires the current password. **Permission:** none (self-service).

**Request**
```json
{"current_password": "OldPass1!", "new_password": "NewPass2!", "new_password_confirm": "NewPass2!"}
```

**Response** `200 {"status": "PASSWORD_CHANGED"}`

**Errors:** `401 INVALID_CURRENT_PASSWORD`; `422 PASSWORD_MISMATCH`;
`422 PASSWORD_POLICY_VIOLATION` (also checked against the account's own
password history, up to the last 5).

### POST /auth/mfa/enrol

Returns a TOTP secret + QR-encodable provisioning URI, **once**
(Day1.md §14.3). **Permission:** none (self-service).

**Response** `200 {"secret": "...", "provisioning_uri": "otpauth://..."}`

**Errors:** `409 MFA_ALREADY_ENROLLED` — re-enrolment is blocked while
an unrevoked TOTP credential exists.

### GET /auth/sessions

Lists the calling account's active devices/sessions. **Permission:** none.

**Response** `200`
```json
{"sessions": [{"session_id": "...", "device_label": "...", "ip": "...", "issued_at": "...", "active": true}]}
```

### DELETE /auth/sessions/{id}

Revoke one specific device/session. **Permission:** none (self-service
— only the account's own sessions).

**Response** `200 {"revoked": true}`

---

### GET /users/creatable-roles

**Drives the frontend role picker** (Day1.md §14.3) — the list of roles
the calling account is actually allowed to create, resolved live from
`role_creation_grants`, never hardcoded. **Permission:** `user:create`.

**Response** `200`
```json
{"creatable_roles": [
  {"role": "MEDICAL_OFFICER", "display_name": "Medical Officer", "requires_second_approver": false,
   "allowed_org_unit_types": ["PHC", "CHC", "SDH"], "schema_url": "/users/registration-schema/MEDICAL_OFFICER"}
]}
```
`[]` for every one of the nine roles Day1.md's own matrix (§3) grants no
creation authority to at all. `SUPERUSER` gets 18 entries (every role
except `PATIENT` — see the `POST /users` entry below for why `PATIENT`
is excluded from every creator's list, including `SUPERUSER`'s).

### GET /users/registration-schema/{role}

Drives the dynamic registration form for any one of the 19 roles.
**Permission:** `user:create`.

**Response** `200` — a renderable schema document: sections
(`common`, `posting`, `profile`) each with their own field list
(`name`, `type`, `required`, and any enum/validation hints derivable
from the underlying Pydantic model). See Day1.md §14.5 for the full
worked example shape.

### POST /users

Staff creation. **No password field exists anywhere in this schema —
the client can never type another account's password** (Day1.md §7.1).
**Permission:** `user:create`. Also enforces org-scope containment
(Gate 3) and role-level sanity (Gate 4) — see Day1.md §3.2. Supports an
optional `Idempotency-Key` header (Day1.md §15.3): a retried request
with the same key and an identical body replays the original response
verbatim; the same key with a *different* body is a `409`.

**Request** — `{"role": "...", "common": {...}, "posting": {...}, "profile": {...}}`.
See Day1.md §14.4 for the full worked `MEDICAL_OFFICER` example. `role`
must be one of the 18 staff roles — **`PATIENT` is not a valid value
here** (`422`): nobody may create a `PATIENT` through this endpoint,
including `SUPERUSER` — a patient identity is created *with* the
patient (via `POST /auth/patient/register` or the assisted-registration
path on `POST /patients/`), never *for* them (Day1.md §3.1).

**Response** `201` — see Day1.md §14.4's own full example. Field set:
`id`, `role`, `full_name`, `mobile_masked`, `status`
(`INVITED` or `PENDING_APPROVAL`), `scope_org_unit_id`, `scope_path`,
`reports_to_user_id`, `created_by_user_id`, `invite` (`{sent_to_masked,
channels, expires_at}`), `hpr_verification`, `created_at`. **No
password, no invite token, no unmasked mobile, ever** — the invite
token exists only as a `SHA-256` hash in `user_invitations.token_hash`
and is never returned by any endpoint or written to any log line
(automated test: `tests/test_no_secret_leakage.py`).

**Errors:** `401` no/invalid token; `403 PERMISSION_DENIED` — role
holds no `user:create` at all; `403 ROLE_NOT_CREATABLE`/
`403 LEVEL_VIOLATION` — no grant for this creator→target pair;
`403 OUT_OF_SCOPE` — target posting outside the actor's subtree;
`403 ACTOR_NOT_ACTIVE`/`403 MFA_REQUIRED` — actor's own account isn't
usable yet; `422` schema validation (every profile is a Pydantic
discriminated union with `extra: "forbid"` — sending one role's fields
under a different role is a `422`, not silently accepted, Day1.md's own
T15 threat); `422 MOBILE_IN_USE`/`422 HPR_IN_USE`; `409` idempotency-key
reuse with a different body.

### GET /users

Scoped list, with filtering and pagination. **Permission:** `user:read`.

**Query params:** `role`, `status`, `limit` (default 50, max 200),
`offset`.

**Response** `200` — a scoped list of user summaries (never a password
hash, never a raw mobile/email).

### GET /users/{id}

**Permission:** `user:read`. Returns `404` (not `403`) both when the
user doesn't exist and when it exists outside the actor's scope —
same anti-enumeration reasoning as `GET /patients/{patient_id}` above.

### PATCH /users/{id}

**Permission:** `user:update`. Editable: `full_name_local`,
`designation`, `employee_code`, `scope_org_unit_id`,
`reports_to_user_id`, `role`. A `role` or `scope_org_unit_id` change
bumps `token_version` — every access token already issued for that
account is immediately rejected on its next use (Day1.md §10.3).

**Request** (any subset) — `{"role": "ANM_MPW"}` or
`{"scope_org_unit_id": "..."}` etc.

**Response** `200 {"id": "...", "updated": true, "token_version_bumped": true}`

**Errors:** `403 SELF_ROLE_CHANGE_BLOCKED` — you cannot change your own
role, ever, even with `user:update` (Day1.md §20 threat T2);
`403 ROLE_NOT_CREATABLE` — you may not assign a role you don't hold a
creation grant for.

### POST /users/{id}/approve

Second-approver action for a `PENDING_APPROVAL` account. **Permission:**
`user:approve`. **The approver must differ from the requester** — the
whole point of dual approval.

**Response** `200 {"id": "...", "status": "INVITED"}`

**Errors:** `403 SELF_APPROVAL` — the creator cannot approve their own
request.

### POST /users/{id}/reject

**Permission:** `user:approve`.

**Request** `{"reason": "..."}`

**Response** `200` — the account moves to `DEACTIVATED` with the reason
recorded.

### POST /users/{id}/invite/resend

Issues a fresh invite token, burning the old one. **Permission:**
`user:create`.

**Response** `200 {"id": "...", "invite": {"sent_to_masked": "...", "expires_at": "..."}}`

**Errors:** `409 NOT_INVITED` — the account isn't currently in
`INVITED` status.

### POST /users/{id}/invite/revoke

**Permission:** `user:create`.

**Response** `200 {"id": "...", "invite_revoked": true}`

### POST /users/{id}/suspend

**Permission:** `user:suspend`. All the account's sessions are revoked
immediately.

**Request** `{"reason": "..."}`

**Response** `200 {"id": "...", "status": "SUSPENDED"}`

### POST /users/{id}/reactivate

**Permission:** `user:suspend`. Forces a password reset on next login
(`must_change_password`).

**Response** `200 {"id": "...", "status": "ACTIVE", "must_change_password": true}`

### POST /users/{id}/transfer

Moves a posting to a new org unit within the actor's own scope.
**Permission:** `user:transfer`.

**Request** `{"new_org_unit_id": "..."}`

**Response** `200 {"id": "...", "scope_org_unit_id": "...", "scope_path": "..."}`

**Errors:** `403 OUT_OF_SCOPE` — the new org unit is outside the
actor's own subtree; `422 INVALID_ORG_UNIT_TYPE` — target unit doesn't
exist or isn't active.

### POST /users/{id}/deactivate

Terminal. Credentials destroyed, sessions revoked. **Permission:**
`user:deactivate`. `reassign_to_user_id` is **required** if the account
being deactivated has subordinates (Day1.md §6.4's orphan-prevention
rule).

**Request** `{"reason": "...", "reassign_to_user_id": null}`

**Response** `200`

**Errors:** `409 SUBORDINATES_EXIST` — includes `subordinate_ids` and a
`suggested_reassign_to`; retry with `reassign_to_user_id` set;
`404 NOT_FOUND` — the given `reassign_to_user_id` doesn't exist;
`422 NEW_MANAGER_NOT_ACTIVE`/`422 NEW_MANAGER_CANNOT_MANAGE_ROLE`.

### GET /users/{id}/subordinates

Direct reports only. **Permission:** `user:read`.

### GET /users/hierarchy

The actor's own subtree, for an org chart. **Permission:** `user:read`.

---

### GET /audit

**New in this step (S22) — see below.** DPO-and-above oversight read of
the tamper-evident audit trail (Day1.md §12). **Permission:**
`audit:read` (`DPO`, `STATE_NHM`, `SUPERUSER` — Day1.md §8.3's own role
map). Not scoped by org unit — audit oversight is deliberately global
for the roles that hold it.

**Query params (all optional):** `actor_user_id`, `action`,
`target_type`, `target_id`, `occurred_from`, `occurred_to`, `limit`
(default 50, max 200), `offset`.

**Response** `200`
```json
{"entries": [
  {"id": 1, "occurred_at": "...", "actor_user_id": "...", "action": "USER_CREATED",
   "outcome": "SUCCESS", "target_type": "USER", "target_id": "...",
   "metadata": {}, "prev_hash": "...", "row_hash": "..."}
], "limit": 50, "offset": 0}
```
`prev_hash`/`row_hash` are included deliberately, not omitted as
"internal" — they're what lets a human reviewer verify the hash chain
themselves (Day1.md §12.3's own "a nightly verifier walks the chain"
idea, extended to an on-demand human check). Never a password, a
private key, or an invite token in any row's `metadata` (verified by
`tests/test_no_secret_leakage.py`).

### GET /consents/{patient_id}

Full consent history for one patient (append-only — every past consent
state is preserved, not overwritten, Day1.md §12's own design).
**New in this step (S22) — see below.** **Permission:** `consent:read`
(`PATIENT` — self only, `DPO`, `SUPERUSER` — Day1.md §8.3). A `PATIENT`
account requesting a *different* patient's consents gets `404`, not
`403` — same anti-enumeration convention as every other existing-record
scope check in this API.

**Response** `200`
```json
{"patient_id": "...", "consents": [
  {"id": "...", "keep_record": true, "share_specialist": true, "share_facility": false,
   "anonymised_planning": false, "mode": "DIGITAL_SELF", "witness_name": null,
   "language": "hi", "recorded_by": null, "recorded_at": "...", "superseded_at": null, "active": true}
]}
```
Most recent first; at most one row has `"active": true` /
`"superseded_at": null` at a time.

**Errors:** `404 NOT_FOUND` — no such patient, or a `PATIENT` actor
requesting someone else's record.

### POST /consents/{patient_id}/revoke

Withdraws consent. **Does not delete or edit the existing consent row**
— stamps its `superseded_at` and inserts a new row with all four
consent booleans `false` (Day1.md §12: "a change writes a new row and
stamps `superseded_at` on the old one"). **New in this step (S22) — see
below.** **Permission:** `consent:revoke` (`PATIENT` self, `DPO`,
`SUPERUSER`). Same 404-not-403 self-only scoping as `GET
/consents/{patient_id}`.

**Request** `{"reason": null}` (`reason` is optional, recorded in the audit entry only)

**Response** `200`
```json
{"patient_id": "...", "id": "...", "recorded_at": "...",
 "keep_record": false, "share_specialist": false, "share_facility": false, "anonymised_planning": false}
```

**Errors:** `404 NO_ACTIVE_CONSENT` — nothing to revoke.

### POST /system/break-glass

Emergency PHI access with justification (Day1.md §9.3 — this is
specifically `SUPERUSER`'s escape hatch: it "does not silently acquire
clinical data access" otherwise). **New in this step (S22) — see
below.** **Permission:** `system:break_glass` (`SUPERUSER` only,
Day1.md §8.3). Grants a 60-minute window; the DPO is notified
immediately (in dev, via the server's own log — no notification
gateway exists yet, same as every other dev-mode notification in this
codebase).

**Request** `{"justification": "<at least 50 characters>"}`

**Response** `200 {"id": "...", "expires_at": "...", "dpo_notified": true}`

**Errors:** `422` — justification under 50 characters (also enforced
at the database level, `chk_justification_length`); `403
PERMISSION_DENIED` — only `SUPERUSER` holds this permission.

---

## A note on the four endpoints marked "new in this step (S22)"

`GET /audit`, `GET /consents/{patient_id}`, `POST
/consents/{patient_id}/revoke`, and `POST /system/break-glass` are
listed in Day1.md §14.3's own API-surface table, and their permissions
(`audit:read`, `consent:read`, `consent:revoke`, `system:break_glass`)
were already fully seeded in `role_permissions` back in S11 — but no
route existed for any of them anywhere in this codebase before this
step. Found while starting what was framed as a documentation-only
step, confirmed directly with the document owner, and built here
(`app/api/routes/governance.py`) rather than either silently documenting
endpoints that would 404, or silently leaving Day1.md's own specified
surface incomplete. See that file's own module docstring for exactly
which parts of these four endpoints are verbatim Day1.md text versus
this step's own concrete design (Day1.md gives no literal request/
response JSON for any of the four, the same category of gap already
handled the same way for several of `auth.py`'s endpoints in S16).
