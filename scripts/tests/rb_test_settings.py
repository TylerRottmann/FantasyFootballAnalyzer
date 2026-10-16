"""Isolated database settings for RB page integration tests."""

from FantasyFootballAnalyzer.settings import *


DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
}
SECRET_KEY = "rb-page-integration-tests"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
# These tests exercise current page models, not PostgreSQL migration history.
MIGRATION_MODULES = {"analyzer": None, "leagues": None}
