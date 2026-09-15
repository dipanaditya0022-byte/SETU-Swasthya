"""T16 / Day1.md SS7.2 & SS20 (T14): a response must never contain an
invite token, a password, or a password hash. "Write a test that
asserts the response body contains no 43-character URL-safe string"
(SS7's own words for secrets.token_urlsafe(32)'s output length).
"""
import re

from sqlmodel import text as sqltext

from tests._fixtures import auth_header, registration_body

# secrets.token_urlsafe(32) produces a 43-character base64url string
# (32 raw bytes -> ceil(32*8/6) = 43 chars, no padding).
_URLSAFE_43 = re.compile(r"[A-Za-z0-9_-]{43}")


def test_post_users_response_never_contains_the_invite_token(client, db, org_units, make_actor):
    bmo_id, token = make_actor("BMO", org_units["BLOCK"])
    body = registration_body("MEDICAL_OFFICER", org_units["PHC"])
    resp = client.post("/users", headers=auth_header(token), json=body)
    assert resp.status_code == 201, resp.text

    assert not _URLSAFE_43.search(resp.text), (
        f"POST /users response contains a 43-char URL-safe string (looks like a leaked invite token): {resp.text}"
    )
    assert '"password"' not in resp.text.lower()
    assert "argon2" not in resp.text.lower()

    new_user_id = resp.json()["id"]

    # The DB itself must only ever hold the token's hash, never the raw value.
    row = db.exec(sqltext(
        "SELECT token_hash FROM user_invitations WHERE user_id = :uid"
    ), params={"uid": new_user_id}).first()
    assert row is not None
    token_hash = row[0]
    # A sha256 hex digest is exactly 64 lowercase hex characters -- note
    # this does NOT get checked against _URLSAFE_43: hex digits are
    # themselves a subset of the base64url alphabet, so any 43+-char hex
    # string trivially "matches" that pattern by construction. That's
    # expected for a hash (not a leak) -- the real assertion is the
    # length/charset shape, which token_urlsafe(32)'s own 43-char mixed-
    # case+-_ output would not have.
    assert len(token_hash) == 64, "token_hash should be a sha256 hex digest (64 chars)"
    assert re.fullmatch(r"[0-9a-f]{64}", token_hash), "token_hash must be a lowercase hex digest, not a raw token"


def test_audit_log_never_contains_the_invite_token_or_a_password(client, db, org_units, make_actor):
    bmo_id, token = make_actor("BMO", org_units["BLOCK"])
    body = registration_body("MEDICAL_OFFICER", org_units["PHC"])
    resp = client.post("/users", headers=auth_header(token), json=body)
    assert resp.status_code == 201, resp.text

    rows = db.exec(sqltext("SELECT action, metadata FROM audit_log")).all()
    for action, metadata in rows:
        blob = str(metadata)
        assert not _URLSAFE_43.search(blob), f"audit_log row for action={action} may contain a leaked token: {blob}"
        assert "password" not in blob.lower()


def test_get_users_list_and_detail_never_contain_password_hash(client, db, org_units, make_actor):
    bmo_id, token = make_actor("BMO", org_units["BLOCK"])
    body = registration_body("MEDICAL_OFFICER", org_units["PHC"])
    create_resp = client.post("/users", headers=auth_header(token), json=body)
    new_user_id = create_resp.json()["id"]

    detail = client.get(f"/users/{new_user_id}", headers=auth_header(token))
    assert detail.status_code == 200, detail.text
    assert "password_hash" not in detail.text
    assert "argon2" not in detail.text.lower()
    assert not _URLSAFE_43.search(detail.text)

    listing = client.get("/users", headers=auth_header(token))
    assert listing.status_code == 200, listing.text
    assert "password_hash" not in listing.text
    assert not _URLSAFE_43.search(listing.text)
