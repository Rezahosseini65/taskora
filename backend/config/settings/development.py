
from .base import *

# =========================
# Development Settings
# =========================

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "web", '0.0.0.0']

# Django Debug Toolbar
INSTALLED_APPS += [
    "debug_toolbar",
]

MIDDLEWARE.insert(
    1,
    "debug_toolbar.middleware.DebugToolbarMiddleware",
)

MIDDLEWARE += [
    "common.middleware.query_middleware.QueryCountMiddleware",
]

INTERNAL_IPS = [
    '127.0.0.1',
    'localhost',
    '0.0.0.0',
]

DEBUG_TOOLBAR_CONFIG = {
    'SHOW_TOOLBAR_CALLBACK': lambda request: True,
}

# Email Backend
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "noreply@taskora.local"
PASSWORD_RESET_URL = env(
    "PASSWORD_RESET_URL",
    default="http://localhost:3000/reset-password",
)
