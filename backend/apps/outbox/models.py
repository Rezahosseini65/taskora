
import uuid

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class OutboxEvent(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PROCESSING = "processing", _("Processing")
        PROCESSED = "processed", _("Processed")
        FAILED = "failed", _("Failed")

    id = models.UUIDField(
        _("id"),
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    event_type = models.CharField(
        _("event type"),
        max_length=150,
        db_index=True,
    )

    aggregate_type = models.CharField(
        _("aggregate type"),
        max_length=100,
    )

    aggregate_id = models.UUIDField(
        _("aggregate id"),
    )

    payload = models.JSONField(
        _("payload"),
        default=dict,
    )

    lock_token = models.UUIDField(
        _("lock token"),
        null=True,
        blank=True,
        editable=False,
    )

    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    attempts = models.PositiveIntegerField(
        _("attempts"),
        default=0,
    )

    max_attempts = models.PositiveSmallIntegerField(
        _("maximum attempts"),
        default=5,
    )

    available_at = models.DateTimeField(
        _("available at"),
        default=timezone.now,
    )

    processed_at = models.DateTimeField(
        _("processed at"),
        null=True,
        blank=True,
    )

    locked_at = models.DateTimeField(
        _("locked at"),
        null=True,
        blank=True,
    )

    last_error = models.TextField(
        _("last error"),
        blank=True,
    )

    created_at = models.DateTimeField(
        _("created at"),
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        _("updated at"),
        auto_now=True,
    )

    class Meta:
        verbose_name = _("outbox event")
        verbose_name_plural = _("outbox events")
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["status", "available_at"],
                name="outbox_status_avail_idx",
            ),
            models.Index(
                fields=["aggregate_type", "aggregate_id"],
                name="outbox_aggregate_idx",
            ),
        ]

        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1),
                name="outbox_max_attempts_gte_1",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="processed",
                        processed_at__isnull=False,
                    )
                    | (
                        ~models.Q(status="processed")
                        & models.Q(processed_at__isnull=True)
                    )
                ),
                name="outbox_processed_at_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "pending",
                        "processing",
                        "processed",
                        "failed",
                    ]
                ),
                name="outbox_valid_status",
            ),
        ]


    def __str__(self):
        return f"{self.event_type} ({self.status})"

