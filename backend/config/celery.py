import os

from celery import Celery

# Use Django development settings by default
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings.development",
)

app = Celery("taskora")

# Load Celery settings from Django settings
# All Celery settings must have the CELERY_ prefix
app.config_from_object("django.conf:settings", namespace="CELERY")

# Automatically discover tasks.py in installed Django apps
app.autodiscover_tasks()