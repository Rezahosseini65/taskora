from .base import *

# =========================
# Test Settings
# =========================

DEBUG = False

# Use fast password hashing during tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Use in-memory email backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Disable password validation during tests
AUTH_PASSWORD_VALIDATORS = []

# Avoid persistent database connections during tests
DATABASES["default"]["CONN_MAX_AGE"] = 0