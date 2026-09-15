"""The 361-case creator x target authority matrix -- Day1.md SS19.3:
"This is the single test that proves the whole authority model."

WHAT IS VERBATIM VS THIS STEP'S OWN DESIGN -- read before reviewing:

- The overall shape (19x19 parametrization, 201 for allowed pairs, 403
  for forbidden ones) is SS19.3's own illustrative test, adapted from
  its async/httpx pseudocode to this repo's synchronous TestClient.

- EXPECTED_GRANTS (tests/_fixtures.py) is an independent transcription
  of SS3's own literal matrix table -- test_seed_grants_match_expected_
  matrix (below) is the check that this transcription and the actual
  seeded role_creation_grants table (S11) agree, which is what makes
  the rest of this file a real test of the AUTHORIZATION CODE rather
  than a test of the seed data against itself.

- SS19.3's own illustrative assertion for forbidden cases only checks
  `error.code in ("ROLE_NOT_CREATABLE", "LEVEL_VIOLATION")`. Found by
  checking the actual seeded role_permissions (not assumed): `user:create`
  is granted ONLY to the 9 roles that have at least one row in
  role_creation_grants (SUPERUSER, STATE_NHM, COLLECTOR, DHO_CMO,
  HEALTH_ADMIN_DPM, BMO, MEDICAL_OFFICER, CHO, ANM_MPW) -- the other 10
  roles (including PATIENT) have no user:create permission at all, so
  EVERY one of their forbidden-target attempts is rejected by the
  `require("user:create")` dependency itself (403 PERMISSION_DENIED)
  before assert_can_create_user's Gate 2/4 ever run. This test checks
  for the PRECISE code given the actual authorization architecture,
  not a loosened "any 403" -- a looser check would silently pass even
  if PERMISSION_DENIED and ROLE_NOT_CREATABLE swapped roles.

- PATIENT as creator: PATIENT accounts authenticate (they have a real
  login method, SS10.1's own table) but SS3's matrix row for PATIENT
  shows "creates nothing" -- included here as one of the 19 creator
  roles, not skipped, since Day1.md's own matrix explicitly lists it as
  a row.
"""
import pytest
from sqlmodel import text

from tests._fixtures import ALL_ROLES, EXPECTED_GRANTS, ROLE_POSTING_TYPE, auth_header

# Roles with at least one real grant (== roles holding the user:create
# permission, per role_permissions -- verified live before writing this
# test, see module docstring).
_CREATOR_ROLES_WITH_GRANTS = {c for c, _ in EXPECTED_GRANTS}


def test_seed_grants_match_expected_matrix(db):
    rows = db.exec(text("SELECT creator_role, target_role FROM role_creation_grants")).all()
    seeded = {(r[0], r[1]) for r in rows}
    assert seeded == EXPECTED_GRANTS, (
        f"role_creation_grants (S11 seed) no longer matches Day1.md SS3's own matrix.\n"
        f"In seed but not expected: {seeded - EXPECTED_GRANTS}\n"
        f"Expected but not seeded: {EXPECTED_GRANTS - seeded}"
    )


@pytest.mark.parametrize("target_role", ALL_ROLES)
@pytest.mark.parametrize("creator_role", ALL_ROLES)
def test_creation_authority_matrix(client, db, org_units, make_actor, creator_role, target_role):
    expected_allowed = (creator_role, target_role) in EXPECTED_GRANTS

    posting_type = ROLE_POSTING_TYPE[creator_role]
    creator_org = org_units[posting_type] if posting_type else None
    creator_id, token = make_actor(creator_role, creator_org)

    if expected_allowed:
        grant_row = db.exec(text(
            "SELECT allowed_org_unit_types FROM role_creation_grants "
            "WHERE creator_role = :c AND target_role = :t"
        ), params={"c": creator_role, "t": target_role}).first()
        allowed_types = grant_row[0]
        from tests._fixtures import pick_target_org_unit, registration_body
        target_org = pick_target_org_unit(db, org_units, creator_org, allowed_types) if creator_org else \
            pick_target_org_unit(db, org_units, org_units["STATE"], allowed_types)
        second_approver = creator_id  # irrelevant to the 201/403 check itself; DPO/SUPERUSER profiles need *a* UUID
        body = registration_body(target_role, target_org, second_approver_id=second_approver)
        resp = client.post("/users", headers=auth_header(token), json=body)
        assert resp.status_code == 201, (
            f"{creator_role} should be able to create {target_role} -> got {resp.status_code}: {resp.text}"
        )
        assert resp.json().get("status") in ("INVITED", "PENDING_APPROVAL")
        # No invite token, no password, ever, in the response (SS14.4).
        assert "token" not in resp.text.lower().replace("token_version", "").replace("mobile_masked", "")
    elif target_role == "PATIENT":
        # PATIENT is not in ROLE_PROFILE_MAP (app/schemas/profiles.py) --
        # UserRegistrationRequest's own role validator rejects it, but
        # only ever gets the chance to run for a creator that already
        # holds user:create (FastAPI's require() dependency raises its
        # 403 immediately on failure, short-circuiting before body
        # validation runs at all -- found by testing, not assumed).
        # Nobody may create PATIENT through this route regardless (SS3.1:
        # "Patient identity is ... created *with* the patient, never
        # *for* them"), but the failure mode differs by creator.
        any_org = org_units["STATE"]
        body = {"role": "PATIENT", "common": {}, "posting": {"org_unit_id": str(any_org)}, "profile": {}}
        resp = client.post("/users", headers=auth_header(token), json=body)
        if creator_role in _CREATOR_ROLES_WITH_GRANTS:
            assert resp.status_code == 422, (
                f"{creator_role}->PATIENT should be rejected at the schema level -> {resp.status_code}: {resp.text}"
            )
        else:
            assert resp.status_code == 403 and resp.json()["detail"]["code"] == "PERMISSION_DENIED", (
                f"{creator_role} holds no user:create -> expected 403 PERMISSION_DENIED for "
                f"{creator_role}->PATIENT, got {resp.status_code}: {resp.text}"
            )
    else:
        # Use a plausible target org unit if we can resolve one; otherwise
        # any real unit works since the request should be rejected before
        # scope is ever checked (permission or grant failure comes first).
        any_org = org_units["STATE"]
        from tests._fixtures import registration_body
        body = registration_body(target_role, any_org, second_approver_id=creator_id)
        resp = client.post("/users", headers=auth_header(token), json=body)
        assert resp.status_code == 403, (
            f"{creator_role} must NOT be able to create {target_role} -> got {resp.status_code}: {resp.text}"
        )
        code = resp.json()["detail"]["code"]
        if creator_role in _CREATOR_ROLES_WITH_GRANTS:
            assert code in ("ROLE_NOT_CREATABLE", "LEVEL_VIOLATION"), (
                f"{creator_role}->{target_role}: expected ROLE_NOT_CREATABLE/LEVEL_VIOLATION, got {code}"
            )
        else:
            assert code == "PERMISSION_DENIED", (
                f"{creator_role} holds no user:create permission at all -- "
                f"expected PERMISSION_DENIED for {creator_role}->{target_role}, got {code}"
            )
