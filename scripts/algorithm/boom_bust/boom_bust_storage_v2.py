"""Storage for trusted, versioned Boom/Bust v2 models."""

import hashlib
import hmac
import os
import stat
import tempfile
from pathlib import Path

import joblib

from scripts.algorithm.boom_bust.boom_bust_artifacts_v2 import (
    POSITIONS,
    validate_model_artifact,
)

MODEL_DIRECTORY = Path(__file__).resolve().parent / "models_v2"


def model_path(position):
    if position not in POSITIONS:
        raise ValueError(f"Unsupported position: {position}")
    return MODEL_DIRECTORY / f"{position.lower()}_boom_bust_v2.joblib"


def checksum_path(position):
    return Path(str(model_path(position)) + ".sha256")


def _check_directory():
    if MODEL_DIRECTORY.is_symlink():
        raise ValueError("Model directory cannot be a symlink.")
    if MODEL_DIRECTORY.exists() and not MODEL_DIRECTORY.is_dir():
        raise ValueError("Model storage path is not a directory.")


def _read_regular_file(path):
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Expected a regular file.")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)


def save_model_artifact(artifact):
    """Save a validated model and checksum without overwriting files."""
    validate_model_artifact(artifact)

    position = artifact["position"]
    destination = model_path(position)
    checksum = checksum_path(position)

    _check_directory()
    MODEL_DIRECTORY.mkdir(mode=0o700, parents=False, exist_ok=True)

    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    if checksum.exists() or checksum.is_symlink():
        raise FileExistsError(checksum)

    temporary_path = None
    created_model = False

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=MODEL_DIRECTORY,
            prefix=f".{position.lower()}_",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            os.chmod(temporary_path, 0o600)
            joblib.dump(artifact, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())

        digest = hashlib.sha256(
            _read_regular_file(temporary_path)
        ).hexdigest()

        # Exclusive hard links prevent replacement of existing files.
        os.link(temporary_path, destination)
        created_model = True

        try:
            descriptor = os.open(
                checksum,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w") as stream:
                stream.write(digest + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            # Remove only the model file this call created.
            if created_model:
                destination.unlink(missing_ok=True)
            raise

        return destination

    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_model_artifact(position):
    """Verify trusted local model bytes before joblib deserialization.

    WARNING: SHA-256 does not authenticate a model when an attacker can
    modify both the artifact and its checksum. Never load untrusted files.
    """
    destination = model_path(position)
    checksum = checksum_path(position)

    _check_directory()

    expected = _read_regular_file(checksum).decode("ascii").strip()

    if len(expected) != 64:
        raise ValueError("Invalid model checksum length.")
    try:
        int(expected, 16)
    except ValueError as exc:
        raise ValueError("Invalid model checksum format.") from exc

    descriptor = os.open(
        destination,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Model artifact must be a regular file.")

        # Hash the same file descriptor used for deserialization.
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            digest = hashlib.sha256()
            for chunk in iter(
                lambda: stream.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

            if not hmac.compare_digest(
                digest.hexdigest(),
                expected.lower(),
            ):
                raise ValueError("Model artifact integrity check failed.")

            stream.seek(0)
            artifact = joblib.load(stream)

    finally:
        os.close(descriptor)

    validate_model_artifact(
        artifact,
        expected_position=position,
    )
    return artifact
