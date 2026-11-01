
from .base import *

# =========================
# Development Settings
# =========================

DEBUG = True

# Django Debug Toolbar
INSTALLED_APPS += [
    'drf_spectacular',
    "debug_toolbar",
]

MIDDLEWARE.insert(
    1,
    "debug_toolbar.middleware.DebugToolbarMiddleware",
)

# Debug Toolbar access
SPECTACULAR_SETTINGS = {
    'TITLE': 'API Documentation',
    'DESCRIPTION': 'API documentation for Your Project',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SERVE_PERMISSIONS': ['rest_framework.permissions.AllowAny'],
    'SERVE_AUTHENTICATION': []
}

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
