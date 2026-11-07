
from .base import *

# =========================
# Test Settings
# =========================

DEBUG = False

# Disable Django Debug Toolbar during tests
INSTALLED_APPS = [
    app for app in INSTALLED_APPS
    if app != "debug_toolbar"
]

MIDDLEWARE = [
    middleware for middleware in MIDDLEWARE
    if middleware != "debug_toolbar.middleware.DebugToolbarMiddleware"
]

# Use fast password hashing during tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Use in-memory email backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Avoid persistent database connections during tests
DATABASES["default"]["CONN_MAX_AGE"] = 0
