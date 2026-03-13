"""
Test-specific settings — overrides main settings to use SQLite in-memory.

Usage:
    python manage.py test core.tests --settings=seashore.settings_test
"""

from .settings import *  # noqa: F401, F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Faster password hashing in tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]
