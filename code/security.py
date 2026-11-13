"""Password hashing and verification helpers."""

import hashlib
import hmac
import secrets


ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000
SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Hash a password with a fresh random salt."""
    if not password:
        raise ValueError("Password must not be empty.")

    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        ITERATIONS,
    )
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Check a password against a stored hash."""
    try:
        algorithm, rounds_text, salt_text, digest_text = stored_hash.split("$")
        if algorithm != ALGORITHM:
            return False

        rounds = int(rounds_text)
        if rounds != ITERATIONS:
            return False

        salt = bytes.fromhex(salt_text)
        expected_digest = bytes.fromhex(digest_text)
        if len(salt) != SALT_BYTES or len(expected_digest) != 32:
            return False
    except (ValueError, TypeError):
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        rounds,
    )
    return hmac.compare_digest(actual_digest, expected_digest)
