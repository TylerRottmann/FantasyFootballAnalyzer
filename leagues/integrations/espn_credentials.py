"""Encrypted storage helpers for private ESPN league credentials."""

import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _cipher():
    key = getattr(settings, "ESPN_CREDENTIALS_ENCRYPTION_KEY", None)
    if not key:
        raise ImproperlyConfigured(
            "ESPN_CREDENTIALS_ENCRYPTION_KEY is not configured."
        )

    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(
            "ESPN_CREDENTIALS_ENCRYPTION_KEY is invalid."
        ) from exc


def encrypt_espn_credentials(swid, espn_s2):
    if not swid or not espn_s2:
        raise ValueError("Both ESPN authentication cookies are required.")

    payload = json.dumps({
        "swid": swid,
        "espn_s2": espn_s2,
    }).encode("utf-8")

    return _cipher().encrypt(payload).decode("ascii")


def decrypt_espn_credentials(encrypted_value):
    if not encrypted_value:
        raise ValueError("No saved ESPN credentials are available.")

    try:
        payload = _cipher().decrypt(encrypted_value.encode("ascii"))
        credentials = json.loads(payload)
        swid = credentials["swid"]
        espn_s2 = credentials["espn_s2"]

        if not isinstance(swid, str) or not isinstance(espn_s2, str):
            raise ValueError("Invalid saved ESPN credentials.")

        if not swid or not espn_s2:
            raise ValueError("Invalid saved ESPN credentials.")

        return swid, espn_s2

    except (InvalidToken, UnicodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(
            "Saved ESPN credentials cannot be decrypted. Reconnect your ESPN league."
        ) from exc
