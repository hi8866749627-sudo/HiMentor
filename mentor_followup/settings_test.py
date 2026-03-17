from .settings import *  # noqa: F401,F403

import os

try:
    import dj_database_url
except ImportError:  # pragma: no cover
    dj_database_url = None


DEBUG = False
SECURE_SSL_REDIRECT = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "sslserver"]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

test_database_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
if dj_database_url and test_database_url:
    DATABASES["default"] = dj_database_url.config(
        default=test_database_url,
        conn_max_age=0,
        ssl_require=False,
    )

