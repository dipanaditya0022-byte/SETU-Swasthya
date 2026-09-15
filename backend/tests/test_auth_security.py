"""Argon2id password hashing, RS256/JWKS, and refresh-token rotation
with reuse detection (Day1.md SS10.3/SS10.4/SS11.1, app/core/password.py
and app/core/tokens.py, S13).
"""
import uuid

import jwt as pyjwt

from app.core.password import hash_password, verify_password
from app.core.tokens import get_jwks, issue_access_token, verify_access_token
from tests._fixtures import make_active_actor


# ============================================================
# Argon2id
# ============================================================

def test_password_hash_is_argon2id():
    h = hash_password("Correct-Horse-42!")
    assert h.startswith("$argon2id$"), f"expected an argon2id hash, got: {h[:20]}..."


def test_password_verify_round_trip():
    h = hash_password("Correct-Horse-42!")
    assert verify_password("Correct-Horse-42!", h) is True
    assert verify_password("wrong-password", h) is False


def test_password_verify_handles_none_hash_without_crashing():
    # A never-set password_hash (e.g. an ASHA/OTP_ONLY account) must not
    # crash verify_password -- SS10.5's timing-normalisation depends on
    # this path running a real-shaped (if dummy) comparison either way.
    assert verify_password("anything", None) is False


# ============================================================
# RS256 / JWKS
# ============================================================

def test_access_token_alg_is_rs256_not_hs256():
    token = issue_access_token(
        user_id=str(uuid.uuid4()), role="BMO", level=5, scope_org_id=None, scope_path=None,
        perms_hash="test", session_id=str(uuid.uuid4()), token_version=1, amr=["pwd"],
    )
    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "RS256"


def test_access_token_verifies_via_public_key_round_trip():
    user_id = str(uuid.uuid4())
    token = issue_access_token(
        user_id=user_id, role="BMO", level=5, scope_org_id=None, scope_path=None,
        perms_hash="test", session_id=str(uuid.uuid4()), token_version=1, amr=["pwd"],
    )
    claims = verify_access_token(token)
    assert claims["sub"] == user_id
    assert claims["role"] == "BMO"


def test_jwks_endpoint_exposes_a_public_rsa_key(client):
    resp = client.get("/.well-known/jwks.json")
    assert resp.status_code == 200
    body = resp.json()
    assert "keys" in body and len(body["keys"]) >= 1
    key = body["keys"][0]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert "n" in key and "e" in key
    # A public key exposes the modulus/exponent, never a private
    # exponent ("d") or any other private-key material.
    assert "d" not in key and "p" not in key and "q" not in key

    # get_jwks() (the function the route wraps) must agree.
    direct = get_jwks()
    assert direct["keys"][0]["kty"] == "RSA"


# ============================================================
# Refresh-token rotation + reuse detection (SS10.4)
# ============================================================

def test_refresh_rotation_and_reuse_detection_end_to_end(client, db, org_units, make_actor):
    from sqlmodel import text as sqltext
    from app.core.crypto import decrypt_field

    # CHO (role_level 7): password login, mfa_mandatory=False per
    # ROLE_SESSION_CONFIG (auth.py, S16) -- unlike BMO (level 5), setting
    # mfa_required=false on CHO doesn't violate chk_privileged_mfa
    # (role_level > 5), keeping this test focused purely on refresh
    # rotation rather than also going through an MFA challenge.
    cho_id, _ = make_actor("CHO", org_units["SUB_CENTRE"])
    password = "Correct-Horse-Battery-42!"
    db.exec(sqltext(
        "UPDATE users SET password_hash = :h, mfa_required = false WHERE id = :id"
    ), params={"h": hash_password(password), "id": str(cho_id)})
    db.commit()

    # Real login (password only) -- decrypt the fixture-generated mobile
    # back out to log in with it, exactly as a real client would supply it.
    enc = db.exec(sqltext("SELECT mobile_encrypted FROM users WHERE id = :id"),
                   params={"id": str(cho_id)}).first()[0]
    real_mobile = decrypt_field(bytes(enc))

    login_resp = client.post("/auth/login", json={"mobile": real_mobile, "password": password})
    assert login_resp.status_code == 200, login_resp.text
    tokens = login_resp.json()
    refresh1 = tokens["refresh_token"]

    # First refresh: succeeds, rotates to a new token.
    r1 = client.post("/auth/token/refresh", json={"refresh_token": refresh1, "device_fingerprint": None})
    assert r1.status_code == 200, r1.text
    refresh2 = r1.json()["refresh_token"]
    assert refresh2 != refresh1

    # Replay the OLD (already-rotated) token: reuse detection must fire.
    r2 = client.post("/auth/token/refresh", json={"refresh_token": refresh1, "device_fingerprint": None})
    assert r2.status_code == 401
    assert r2.json()["detail"]["code"] == "TOKEN_REUSE_DETECTED"

    # Reuse detection must have revoked the WHOLE family -- the second
    # (legitimately rotated) token must now also be dead.
    r3 = client.post("/auth/token/refresh", json={"refresh_token": refresh2, "device_fingerprint": None})
    assert r3.status_code == 401
    assert r3.json()["detail"]["code"] in ("INVALID_REFRESH_TOKEN", "TOKEN_REUSE_DETECTED")
