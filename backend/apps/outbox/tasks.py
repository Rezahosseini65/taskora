
import logging

from celery import shared_task

from .handlers.registry import registry
from .services import (
    DEFAULT_BATCH_SIZE,
    claim_pending_events,
    mark_event_as_failed,
    mark_event_as_processed,
)

logger = logging.getLogger(__name__)


@shared_task
def process_outbox_events(batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    """
    Claim and process pending Outbox events.
    """

    events = claim_pending_events(batch_size=batch_size)

    processed = 0
    failed = 0
    skipped = 0

    for event in events:
        try:
            handler = registry.get(event.event_type)

            handler(
                event.aggregate_id,
                event.payload,
            )

        except Exception as exc:
            logger.exception(
                "Failed to process Outbox event %s (%s)",
                event.id,
                event.event_type,
            )

            if mark_event_as_failed(
                event.id,
                event.lock_token,
                exc,
            ):
                failed += 1
            else:
                skipped += 1

            continue

        if mark_event_as_processed(
            event.id,
            event.lock_token,
        ):
            processed += 1
        else:
            logger.warning(
                "Outbox event %s could not be marked as processed "
                "because its processing lock is no longer valid.",
                event.id,
            )
            skipped += 1

    return {
        "claimed": len(events),
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
    }
