"""Password hashing and policy, per Day1.md SS10.2 and SS10.5.

`pwd_context` and `PASSWORD_RULES` are copied verbatim from Day1.md
SS10.2's own `app/core/password.py` code block (Argon2id parameters,
rule values). The hashing/verification functions and the policy
validator are new here -- Day1.md SS10.2 shows the *configuration*
(what the rules are), not the enforcement code itself, so building
`hash_password`/`verify_password`/`validate_password_policy` is this
step's own job, not a spec quote.

One deliberately incomplete piece, flagged rather than faked: SS10.2's
`forbid_common_passwords` rule references "top-10k list bundled
offline" -- no such list exists anywhere in Day1.md or this repository.
Day1.md doesn't provide the list's contents, so nothing here invents
10,000 passwords to match a number. `_COMMON_PASSWORDS` below is a
small, clearly-labelled starter set (a few dozen of the most
well-known weak passwords) that exercises the *mechanism* correctly;
dropping in the real bundled list later is a data change to that one
set, not a code change.
"""
from __future__ import annotations

import re
import secrets
import string
from datetime import datetime, timedelta, timezone

from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["argon2"],
    argon2__time_cost=3,
    argon2__memory_cost=65536,   # 64 MiB
    argon2__parallelism=4,
    deprecated="auto",
)

PASSWORD_RULES = {
    "min_length": 12,
    "min_length_privileged": 16,        # L <= 3
    "require_categories": 3,            # of lower, upper, digit, symbol
    "max_length": 128,                  # DoS guard on the KDF
    "forbid_user_attributes": True,     # name, mobile, email, employee_code
    "forbid_common_passwords": True,    # top-10k list bundled offline
    "forbid_sequential": True,          # 1234, qwerty, abcd
    "history_count": 5,
    "max_age_days": 180,                # privileged roles: 90
    "min_age_hours": 24,                # blocks instant cycling through history
}

# Starter set only -- see module docstring. Lower-cased for comparison.
_COMMON_PASSWORDS = frozenset({
    "password", "password1", "password123", "123456", "12345678",
    "123456789", "qwerty", "qwerty123", "letmein", "welcome",
    "admin", "admin123", "iloveyou", "monkey", "dragon", "master",
    "abc123", "111111", "123123", "changeme", "passw0rd",
})

_SEQUENTIAL_RUNS = ("1234", "2345", "3456", "4567", "5678", "6789",
                    "abcd", "bcde", "cdef", "qwerty", "asdf", "zxcv")

# A dummy hash used to normalise verify() timing when there is no real
# hash to check against (SS10.5: "On unknown-user, still run a dummy
# Argon2 verify so the response time does not reveal existence"). Fixed
# at import time so every call pays the same Argon2 cost; the plaintext
# behind this hash is not a real credential.
_DUMMY_HASH = pwd_context.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    """Argon2id hash. Never log or return the input or the result to a
    client -- callers must treat both as secret (Day1.md SS10.6/SS11.1)."""
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    """Verify a password against its hash. If `hashed` is None (no
    account, or an OTP-only role with no password_hash), a dummy verify
    still runs so a caller cannot distinguish "no such account" /
    "OTP-only account" / "wrong password" by response timing --
    SS10.5's timing-normalisation and uniform-error-text requirements
    both depend on this. Always returns a bool; never raises on a bad
    hash or wrong password (only on a truly malformed `hashed` value
    passlib itself can't parse, which propagates as passlib's own
    exception rather than being silently swallowed)."""
    if hashed is None:
        pwd_context.verify(password, _DUMMY_HASH)
        return False
    return pwd_context.verify(password, hashed)


def _has_categories(password: str) -> int:
    categories = 0
    if any(c.islower() for c in password):
        categories += 1
    if any(c.isupper() for c in password):
        categories += 1
    if any(c.isdigit() for c in password):
        categories += 1
    if any(c in string.punctuation for c in password):
        categories += 1
    return categories


def _contains_sequential(password: str) -> bool:
    lowered = password.lower()
    for run in _SEQUENTIAL_RUNS:
        if run in lowered:
            return True
    return False


def validate_password_policy(
    password: str,
    *,
    is_privileged: bool,
    user_attributes: list[str] | None = None,
    history_hashes: list[str] | None = None,
    password_changed_at: datetime | None = None,
) -> list[str]:
    """Check `password` against PASSWORD_RULES. Returns a list of
    violated rule names; an empty list means the password is valid.
    Fails closed: an unrecognised/empty password is rejected, never
    silently accepted.

    `user_attributes`: the account's own name/mobile/email/employee_code
    (plaintext, from the in-flight registration/change request, not
    read back from encrypted storage) -- checked for substring
    inclusion, case-insensitive.
    `history_hashes`: the account's last N password hashes
    (password_history.password_hash rows), checked via verify_password
    so history is never compared as plaintext.
    `password_changed_at`: when the current password was last set, to
    enforce min_age_hours. None (e.g. first password ever) skips this
    check.
    """
    violations: list[str] = []

    min_len = PASSWORD_RULES["min_length_privileged"] if is_privileged else PASSWORD_RULES["min_length"]
    if len(password) < min_len:
        violations.append("min_length")
    if len(password) > PASSWORD_RULES["max_length"]:
        violations.append("max_length")

    if _has_categories(password) < PASSWORD_RULES["require_categories"]:
        violations.append("require_categories")

    if PASSWORD_RULES["forbid_user_attributes"] and user_attributes:
        lowered = password.lower()
        # Split each attribute on whitespace/punctuation and check every
        # token separately (>= 3 chars) -- not just the whole attribute
        # as one substring. A full name like "Ramesh Kumar" would never
        # match "RameshKumar123!" as a literal substring (the space
        # isn't there), but each name part on its own should still be
        # rejected.
        for attr in user_attributes:
            if not attr:
                continue
            tokens = re.split(r"[\s\-_@.]+", attr)
            for token in tokens:
                if len(token) >= 3 and token.lower() in lowered:
                    violations.append("forbid_user_attributes")
                    break
            else:
                continue
            break

    if PASSWORD_RULES["forbid_common_passwords"] and password.lower() in _COMMON_PASSWORDS:
        violations.append("forbid_common_passwords")

    if PASSWORD_RULES["forbid_sequential"] and _contains_sequential(password):
        violations.append("forbid_sequential")

    if history_hashes:
        for old_hash in history_hashes[-PASSWORD_RULES["history_count"]:]:
            if verify_password(password, old_hash):
                violations.append("history_count")
                break

    if password_changed_at is not None:
        min_age = timedelta(hours=PASSWORD_RULES["min_age_hours"])
        if datetime.now(timezone.utc) - password_changed_at < min_age:
            violations.append("min_age_hours")

    return violations
