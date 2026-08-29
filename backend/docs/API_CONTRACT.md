# SETU-Swasthya API Contract

## Purpose

This document defines the Day 1 backend API contract for the SETU-Swasthya MVP.

The backend is built with FastAPI and PostgreSQL.

All frontend integrations should use the endpoint paths, request shapes, and response shapes documented here.

## POST /patients/

Creates a new patient.

### Request

```json
{
  "name": "Test Patient",
  "age": 25,
  "village": "Test Village",
  "phone": null,
  "facility_id": "00000000-0000-0000-0000-000000000001",
  "client_uuid": null
}
```

### Response

Returns the created patient with a generated `id` and `created_at`.

## GET /patients/{patient_id}

Returns a patient by UUID.

### Path Parameter

- `patient_id`: UUID of the patient

### Response

Returns the matching patient. Returns `404` if the patient does not exist.

## POST /triage/

Creates a triage encounter for a patient.

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

Creates a referral for a patient.

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

Updates the status of an existing referral.

### Path Parameter

- `referral_id`: UUID of the referral

### Query Parameter

- `status`: New referral status

### Response

Returns the updated referral. Returns `404` if the referral does not exist.

## POST /sync/

Accepts a batch of offline-created records keyed by `client_uuid`.

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

Returns the number of accepted records and their client UUIDs.

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
