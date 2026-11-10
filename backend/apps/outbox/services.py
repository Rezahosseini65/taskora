import uuid
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import OutboxEvent


OUTBOX_LOCK_TIMEOUT = timedelta(minutes=5)
DEFAULT_BATCH_SIZE = 100


def create_outbox_event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any] | None = None,
) -> OutboxEvent:
    """
    Create an outbox event within the current database transaction.
    """

    return OutboxEvent.objects.create(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload or {},
    )


def claim_pending_events(
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    lock_timeout: timedelta = OUTBOX_LOCK_TIMEOUT,
) -> list[OutboxEvent]:
    """
    Recover stale events and atomically claim pending events.

    Events are claimed using SELECT FOR UPDATE SKIP LOCKED
    to prevent concurrent workers from processing the same event.
    Each claim receives a unique lock token to prevent stale
    workers from modifying events claimed by another worker.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero.")

    if lock_timeout <= timedelta(0):
        raise ValueError("lock_timeout must be greater than zero.")

    now = timezone.now()
    lock_expiration = now - lock_timeout

    with transaction.atomic():

        # Recover events whose processing lease has expired.
        stale_events = list(
            OutboxEvent.objects.select_for_update(
                skip_locked=True,
            )
            .filter(
                status=OutboxEvent.Status.PROCESSING,
            )   
            .filter(
                Q(locked_at__isnull=True)
    |           Q(locked_at__lt=lock_expiration)
            )
        )

        for event in stale_events:
            event.locked_at = None
            event.lock_token = None
            event.available_at = now
            event.updated_at = now

            if event.attempts >= event.max_attempts:
                event.status = OutboxEvent.Status.FAILED
                event.last_error = "Processing lease expired."
            else:
                event.status = OutboxEvent.Status.PENDING
                event.last_error = (
                    "Processing lease expired; event returned to pending."
                )

        if stale_events:
            OutboxEvent.objects.bulk_update(
                stale_events,
                [
                    "status",
                    "locked_at",
                    "lock_token",
                    "available_at",
                    "updated_at",
                    "last_error",
                ],
            )

        # Claim eligible pending events.
        events = list(
            OutboxEvent.objects.select_for_update(
                skip_locked=True,
            )
            .filter(
                status=OutboxEvent.Status.PENDING,
                available_at__lte=now,
                attempts__lt=F("max_attempts"),
            )
            .order_by("created_at")[:batch_size]
        )

        for event in events:
            event.status = OutboxEvent.Status.PROCESSING
            event.locked_at = now
            event.lock_token = uuid.uuid4()
            event.attempts += 1
            event.updated_at = now

        if events:
            OutboxEvent.objects.bulk_update(
                events,
                [
                    "status",
                    "locked_at",
                    "lock_token",
                    "attempts",
                    "updated_at",
                ],
            )

        return events


def mark_event_as_processed(
    event_id: UUID,
    lock_token: UUID,
) -> bool:
    """
    Mark an event as successfully processed.

    Only the worker holding the current lock token
    can mark the event as processed.
    """

    now = timezone.now()

    updated = OutboxEvent.objects.filter(
        id=event_id,
        status=OutboxEvent.Status.PROCESSING,
        lock_token=lock_token,
    ).update(
        status=OutboxEvent.Status.PROCESSED,
        processed_at=now,
        locked_at=None,
        lock_token=None,
        last_error="",
        updated_at=now,
    )

    return updated == 1



def mark_event_as_failed(
    event_id: UUID,
    lock_token: UUID,
    error: Exception | str,
) -> bool:
    """
    Mark an event as failed or schedule a retry.

    Only the worker holding the current lock token
    can modify the event.
    """

    now = timezone.now()

    with transaction.atomic():
        try:
            event = OutboxEvent.objects.select_for_update().get(
                id=event_id,
                status=OutboxEvent.Status.PROCESSING,
                lock_token=lock_token,
            )
        except OutboxEvent.DoesNotExist:
            return False

        event.locked_at = None
        event.lock_token = None
        event.last_error = str(error)[:10000]
        event.updated_at = now

        if event.attempts >= event.max_attempts:
            event.status = OutboxEvent.Status.FAILED
        else:
            retry_delay = 30 * (2 ** max(event.attempts - 1, 0))

            event.status = OutboxEvent.Status.PENDING
            event.available_at = now + timedelta(seconds=retry_delay)

        event.save(
            update_fields=[
                "status",
                "locked_at",
                "lock_token",
                "last_error",
                "available_at",
                "updated_at",
            ]
        )

        return True

