"""T15 / Day1.md SS15/SS20: "Wrong-role field injection -- Sending ASHA
fields as an MO -- Pydantic discriminated union with extra: 'forbid' ->
422". Every one of the 18 staff profile models (app/schemas/profiles.py,
S14) declares `model_config = ConfigDict(extra="forbid")`.
"""
from tests._fixtures import auth_header, common_block, posting_block, profile_block


def test_wrong_role_fields_rejected_with_422(client, org_units, make_actor):
    """Send MEDICAL_OFFICER's envelope (role="MEDICAL_OFFICER") but with
    ASHA's own profile fields instead of MedicalOfficerProfile's --
    MedicalOfficerProfile's extra="forbid" must reject every ASHA-only
    field as unrecognised, not silently accept or ignore them."""
    bmo_id, token = make_actor("BMO", org_units["BLOCK"])
    body = {
        "role": "MEDICAL_OFFICER",
        "common": common_block("MEDICAL_OFFICER"),
        "posting": posting_block("MEDICAL_OFFICER", org_units["PHC"]),
        "profile": profile_block("ASHA", org_units["VILLAGE"]),  # wrong shape on purpose
    }
    resp = client.post("/users", headers=auth_header(token), json=body)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"


def test_extra_unknown_field_in_correct_profile_rejected(client, org_units, make_actor):
    """Even a syntactically-plausible but undefined extra field on the
    CORRECT profile shape must be rejected, not silently dropped."""
    bmo_id, token = make_actor("BMO", org_units["BLOCK"])
    profile = profile_block("MEDICAL_OFFICER", org_units["PHC"])
    profile["not_a_real_field"] = "malicious payload"
    body = {
        "role": "MEDICAL_OFFICER",
        "common": common_block("MEDICAL_OFFICER"),
        "posting": posting_block("MEDICAL_OFFICER", org_units["PHC"]),
        "profile": profile,
    }
    resp = client.post("/users", headers=auth_header(token), json=body)
    assert resp.status_code == 422, resp.text


def test_extra_unknown_field_in_common_block_rejected(client, org_units, make_actor):
    """CommonCore also declares extra='forbid' (SS5.2)."""
    bmo_id, token = make_actor("BMO", org_units["BLOCK"])
    common = common_block("MEDICAL_OFFICER")
    common["role"] = "SUPERUSER"  # trying to smuggle a privilege-escalation field into common
    body = {
        "role": "MEDICAL_OFFICER",
        "common": common,
        "posting": posting_block("MEDICAL_OFFICER", org_units["PHC"]),
        "profile": profile_block("MEDICAL_OFFICER", org_units["PHC"]),
    }
    resp = client.post("/users", headers=auth_header(token), json=body)
    assert resp.status_code == 422, resp.text
