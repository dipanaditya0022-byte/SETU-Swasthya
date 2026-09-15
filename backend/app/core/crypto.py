"""Field-level encryption and searchable blind indexes, per Day1.md SS11.

`encrypt_field`, `decrypt_field`, and `blind_index` are copied verbatim
from Day1.md SS11.2's own `app/core/crypto.py` code block -- algorithm,
key sizes, nonce handling, and the blind-index normalisation rule
(`.strip().lower()`) are exactly as specified there. Two things are
added beyond that literal block, neither of which is spec-derived
fact -- both are documented here as such:

  - Key loading is wrapped in `_load_key()` with a clear, specific
    error (`CryptoConfigError`) instead of letting a bare KeyError /
    ValueError propagate from module import time. Day1.md's own
    snippet does `bytes.fromhex(os.environ["FIELD_ENCRYPTION_KEY"])`
    directly at module scope; this module preserves that "fail
    immediately, don't limp along with a missing/malformed key" intent
    (SS11.2's os.environ[...] already fails fast, not silently) but
    gives a message that says which key and why, per this task's own
    "safe failure if encryption keys are absent or malformed"
    requirement.

  - `mask_mobile()` is not given as code anywhere in Day1.md, but the
    exact output format is used identically and repeatedly throughout
    the document (SS11.1, SS12.4, SS13.2's mobile_masked column
    comment, SS14's example responses): `+91XXXXX43210` for an E.164
    Indian mobile matching SS5's own validation regex
    `^\\+91[6-9]\\d{9}$` -- keep the `+91` prefix, mask the first 5 of
    the 10 national digits, show the last 5. This is a mechanical
    derivation from a consistently repeated example, not an invented
    design choice, so it did not need to be flagged as a gap requiring
    the user's sign-off the way OrgUnitType/mfa_credentials/
    role_permissions did.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoConfigError(RuntimeError):
    """Raised when an encryption/blind-index key is missing or malformed.
    Fails closed: callers must not catch this and fall back to storing
    plaintext or skipping the blind index."""


def _load_key(env_var: str) -> bytes:
    raw = os.environ.get(env_var)
    if not raw:
        raise CryptoConfigError(
            f"{env_var} is not set. Field encryption cannot proceed without it "
            f"(see backend/.env.example)."
        )
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise CryptoConfigError(
            f"{env_var} is not valid hex. Expected 64 hex characters (32 bytes)."
        ) from exc
    if len(key) != 32:
        raise CryptoConfigError(
            f"{env_var} must decode to exactly 32 bytes for AES-256/HMAC-SHA256; "
            f"got {len(key)} bytes."
        )
    return key


_DEK = _load_key("FIELD_ENCRYPTION_KEY")
_BLIND_INDEX_KEY = _load_key("BLIND_INDEX_KEY")


def encrypt_field(plaintext: str) -> bytes:
    """AES-256-GCM, verbatim per Day1.md SS11.2. A fresh 12-byte nonce is
    generated on every call (os.urandom), so the same plaintext never
    produces the same ciphertext twice. The nonce is prepended to the
    returned blob (not secret, must be stored alongside the ciphertext
    to decrypt it)."""
    nonce = os.urandom(12)
    return nonce + AESGCM(_DEK).encrypt(nonce, plaintext.encode(), None)


def decrypt_field(blob: bytes) -> str:
    """Verbatim per Day1.md SS11.2. AESGCM.decrypt verifies the
    authentication tag itself and raises cryptography.exceptions.
    InvalidTag if the ciphertext (or the nonce/tag) was tampered with --
    this function does not catch that exception, so tampering fails
    closed by propagating, not by silently returning wrong data."""
    return AESGCM(_DEK).decrypt(blob[:12], blob[12:], None).decode()


def blind_index(plaintext: str) -> str:
    """Deterministic keyed hash, verbatim per Day1.md SS11.2. Enables
    exact-match lookup on encrypted data (e.g. `WHERE mobile_blind_index
    = blind_index(mobile)`) without ever decrypting the column.
    Normalisation is exactly Day1.md's own `.strip().lower()` -- no
    additional phone-specific reformatting is applied here, since
    Day1.md's own mobile validation (SS5) already requires E.164 input
    (`^\\+91[6-9]\\d{9}$`) before a value ever reaches this function, so
    there is no other format for it to normalise away.
    """
    normalised = plaintext.strip().lower()
    return hmac.new(_BLIND_INDEX_KEY, normalised.encode(), hashlib.sha256).hexdigest()


_MOBILE_RE = re.compile(r"^\+91[6-9]\d{9}$")


def mask_mobile(mobile: str) -> str:
    """Mask an E.164 Indian mobile for display/logs: `+91XXXXX43210`.
    Not from a Day1.md code block -- derived from the exact, repeatedly
    used example format (SS11.1, SS12.4, SS13.2, SS14) applied to
    SS5's own validation pattern. Fails closed (raises, does not return
    a best-effort guess) on anything that isn't a full E.164 Indian
    mobile matching that pattern -- masking the wrong thing wrong is
    worse than refusing to mask it at all."""
    if not _MOBILE_RE.match(mobile):
        raise ValueError(
            "mask_mobile expects a full E.164 Indian mobile matching "
            "^\\+91[6-9]\\d{9}$, e.g. '+919876543210'."
        )
    national_number = mobile[3:]  # strip '+91', leaves 10 digits
    return "+91" + "X" * 5 + national_number[5:]
