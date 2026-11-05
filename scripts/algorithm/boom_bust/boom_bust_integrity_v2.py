"""SHA-256 integrity helpers for trusted Boom/Bust v2 artifacts."""

import hashlib
import hmac
import os
import stat
from pathlib import Path


def sha256_file(path):
    """Calculate the SHA-256 digest of a regular, non-symlinked file."""
    path = Path(path)

    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )

    try:
        metadata = os.fstat(descriptor)

        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Expected a regular file.")

        digest = hashlib.sha256()

        with os.fdopen(descriptor, "rb", closefd=False) as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)

        return digest.hexdigest()

    finally:
        os.close(descriptor)


def verify_sha256(path, expected_digest):
    """Verify a file against a previously trusted SHA-256 digest."""
    if not isinstance(expected_digest, str):
        raise ValueError("Expected digest must be a string.")

    if len(expected_digest) != 64:
        raise ValueError("Invalid SHA-256 digest length.")

    try:
        int(expected_digest, 16)
    except ValueError as exc:
        raise ValueError("Invalid SHA-256 digest format.") from exc

    actual_digest = sha256_file(path)

    if not hmac.compare_digest(
        actual_digest,
        expected_digest.lower(),
    ):
        raise ValueError("Model artifact integrity check failed.")

    return True
