"""Database-free security tests for encrypted ESPN credentials."""

import unittest

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from leagues.integrations.espn_credentials import (
    decrypt_espn_credentials,
    encrypt_espn_credentials,
)


class ESPNCredentialSecurityTests(unittest.TestCase):

    def setUp(self):
        self.key = Fernet.generate_key().decode("ascii")
        self.settings_override = override_settings(
            ESPN_CREDENTIALS_ENCRYPTION_KEY=self.key
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def test_credentials_round_trip(self):
        encrypted = encrypt_espn_credentials(
            "{TEST-SWID}", "test-session"
        )

        self.assertEqual(
            decrypt_espn_credentials(encrypted),
            ("{TEST-SWID}", "test-session"),
        )

    def test_credentials_not_stored_as_plaintext(self):
        encrypted = encrypt_espn_credentials(
            "{TEST-SWID}", "test-session"
        )

        self.assertNotIn("TEST-SWID", encrypted)
        self.assertNotIn("test-session", encrypted)

    def test_missing_credentials_rejected(self):
        with self.assertRaises(ValueError):
            encrypt_espn_credentials("", "test-session")

        with self.assertRaises(ValueError):
            encrypt_espn_credentials("{TEST-SWID}", "")

    def test_missing_encryption_key_rejected(self):
        with override_settings(
            ESPN_CREDENTIALS_ENCRYPTION_KEY=None
        ):
            with self.assertRaises(ImproperlyConfigured):
                encrypt_espn_credentials(
                    "{TEST-SWID}", "test-session"
                )

    def test_wrong_encryption_key_rejected(self):
        encrypted = encrypt_espn_credentials(
            "{TEST-SWID}", "test-session"
        )

        with override_settings(
            ESPN_CREDENTIALS_ENCRYPTION_KEY=(
                Fernet.generate_key().decode("ascii")
            )
        ):
            with self.assertRaises(ValueError):
                decrypt_espn_credentials(encrypted)

    def test_corrupted_ciphertext_rejected(self):
        with self.assertRaises(ValueError):
            decrypt_espn_credentials("invalid-ciphertext")

    def test_empty_saved_credentials_rejected(self):
        with self.assertRaises(ValueError):
            decrypt_espn_credentials(None)
