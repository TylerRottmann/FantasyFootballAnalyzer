"""Isolated test database: never connect to the configured shared database.

Run: python manage.py test --settings=FantasyFootballAnalyzer.test_settings
"""
from .settings import *  # noqa: F403

SECRET_KEY = 'local-tests-only'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
