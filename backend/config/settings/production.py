
from .base import *

# =========================
# Production Settings
# =========================

DEBUG = False

# Security
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Proxy / HTTPS
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HSTS
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Static & Media
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Email
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
