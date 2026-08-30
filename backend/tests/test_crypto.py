"""Field encryption and blind index (Day1.md SS11.2, app/core/crypto.py,
S12). Pure unit tests -- no database, no HTTP.
"""
from app.core.crypto import blind_index, decrypt_field, encrypt_field, mask_mobile


def test_encrypt_decrypt_round_trip():
    plaintext = "+919876543210"
    ciphertext = encrypt_field(plaintext)
    assert isinstance(ciphertext, (bytes, bytearray))
    assert ciphertext != plaintext.encode()
    assert decrypt_field(bytes(ciphertext)) == plaintext


def test_encryption_is_nondeterministic():
    """AES-256-GCM with a random nonce per call -- encrypting the same
    plaintext twice must not produce the same ciphertext (a fixed nonce
    would be a real cryptographic weakness)."""
    plaintext = "+919876543210"
    c1 = encrypt_field(plaintext)
    c2 = encrypt_field(plaintext)
    assert c1 != c2
    assert decrypt_field(bytes(c1)) == decrypt_field(bytes(c2)) == plaintext


def test_blind_index_is_deterministic():
    """Unlike encryption, the blind index MUST be deterministic -- it's
    what makes an encrypted field searchable (unique index on
    mobile_blind_index, S6)."""
    mobile = "+919876543210"
    assert blind_index(mobile) == blind_index(mobile)


def test_blind_index_differs_for_different_input():
    assert blind_index("+919876543210") != blind_index("+919876543211")


def test_blind_index_is_not_the_plaintext_or_a_simple_hash_of_nothing():
    mobile = "+919876543210"
    bi = blind_index(mobile)
    assert mobile not in bi
    assert len(bi) >= 32  # a real HMAC digest (hex or similar), not a short/truncated value


def test_mask_mobile_hides_the_middle_digits():
    masked = mask_mobile("+919876543210")
    assert masked != "+919876543210"
    assert masked.startswith("+91")
    assert masked.endswith("3210")
    assert "9876" not in masked  # the masked-out middle digits must not leak through


def test_ciphertext_never_equals_plaintext_bytes():
    for value in ("+919876543210", "test@example.com", "HPR-0001-2026"):
        assert encrypt_field(value) != value.encode()
