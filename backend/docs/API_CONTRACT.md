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

Authenticates a hardcoded Day 1 user.

### Request

```json
{
  "username": "aditya",
  "password": "aditya123"
}
```

### Response

Returns a JWT bearer token and the user role.

---

## GET /me

Returns the username and role encoded in the JWT.

### Header

- `Authorization: Bearer <access_token>`

### Response

Returns the authenticated username and role.
