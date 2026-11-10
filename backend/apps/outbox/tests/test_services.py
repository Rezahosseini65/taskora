
import threading
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.db import close_old_connections, transaction
from django.test import (
    TestCase,
    TransactionTestCase,
    skipUnlessDBFeature,
)
from django.utils import timezone

from apps.outbox.models import OutboxEvent
from apps.outbox.services import (
    claim_pending_events,
    create_outbox_event,
    mark_event_as_failed,
    mark_event_as_processed,
)


class CreateOutboxEventTests(TestCase):

    def test_create_event_with_default_payload(self):
        event = create_outbox_event(
            event_type="user.registered",
            aggregate_type="user",
            aggregate_id=uuid4(),
        )

        self.assertEqual(event.event_type, "user.registered")
        self.assertEqual(event.aggregate_type, "user")
        self.assertEqual(event.payload, {})
        self.assertEqual(event.status, OutboxEvent.Status.PENDING)
        self.assertEqual(event.attempts, 0)

    def test_create_event_with_custom_payload(self):
        payload = {"user_id": "123", "source": "registration"}

        event = create_outbox_event(
            event_type="user.registered",
            aggregate_type="user",
            aggregate_id=uuid4(),
            payload=payload,
        )

        self.assertEqual(event.payload, payload)

    def test_event_creation_uses_current_transaction(self):
        event_id = uuid4()

        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                create_outbox_event(
                    event_type="user.registered",
                    aggregate_type="user",
                    aggregate_id=event_id,
                )
                raise RuntimeError("Rollback transaction")

        self.assertFalse(
            OutboxEvent.objects.filter(
                aggregate_id=event_id,
            ).exists()
        )


class ClaimPendingEventsTests(TestCase):

    def setUp(self):
        self.now = timezone.now()

    def create_event(self, **kwargs):
        defaults = {
            "event_type": "user.registered",
            "aggregate_type": "user",
            "aggregate_id": uuid4(),
            "status": OutboxEvent.Status.PENDING,
            "attempts": 0,
            "max_attempts": 5,
            "available_at": self.now - timedelta(minutes=1),
        }
        defaults.update(kwargs)

        return OutboxEvent.objects.create(**defaults)

    @patch("apps.outbox.services.timezone.now")
    def test_claim_pending_event(self, mock_now):
        mock_now.return_value = self.now

        event = self.create_event()

        claimed_events = claim_pending_events()

        self.assertEqual(len(claimed_events), 1)

        claimed_event = claimed_events[0]
        event.refresh_from_db()

        self.assertEqual(event.status, OutboxEvent.Status.PROCESSING)
        self.assertEqual(event.attempts, 1)
        self.assertEqual(event.locked_at, self.now)
        self.assertIsNotNone(event.lock_token)
        self.assertEqual(claimed_event.lock_token, event.lock_token)

    @patch("apps.outbox.services.timezone.now")
    def test_claim_respects_batch_size(self, mock_now):
        mock_now.return_value = self.now

        for _ in range(5):
            self.create_event()

        claimed_events = claim_pending_events(batch_size=2)

        self.assertEqual(len(claimed_events), 2)

    @patch("apps.outbox.services.timezone.now")
    def test_claim_ignores_future_events(self, mock_now):
        mock_now.return_value = self.now

        event = self.create_event(
            available_at=self.now + timedelta(minutes=5),
        )

        claimed_events = claim_pending_events()

        self.assertEqual(claimed_events, [])

        event.refresh_from_db()

        self.assertEqual(event.status, OutboxEvent.Status.PENDING)
        self.assertEqual(event.attempts, 0)

    @patch("apps.outbox.services.timezone.now")
    def test_claim_ignores_non_pending_events(self, mock_now):
        mock_now.return_value = self.now

        event = self.create_event(
            status=OutboxEvent.Status.PROCESSED,
            processed_at=self.now,
        )

        claimed_events = claim_pending_events()

        self.assertEqual(claimed_events, [])

        event.refresh_from_db()

        self.assertEqual(event.status, OutboxEvent.Status.PROCESSED)

    @patch("apps.outbox.services.timezone.now")
    def test_claim_ignores_events_with_exhausted_attempts(self, mock_now):
        mock_now.return_value = self.now

        event = self.create_event(
            attempts=5,
            max_attempts=5,
        )

        claimed_events = claim_pending_events()

        self.assertEqual(claimed_events, [])

        event.refresh_from_db()

        self.assertEqual(event.status, OutboxEvent.Status.PENDING)

    @patch("apps.outbox.services.timezone.now")
    def test_recovers_stale_event_and_reclaims_it(self, mock_now):
        mock_now.return_value = self.now

        old_token = uuid4()

        event = self.create_event(
            status=OutboxEvent.Status.PROCESSING,
            attempts=2,
            locked_at=self.now - timedelta(minutes=6),
            lock_token=old_token,
        )

        claimed_events = claim_pending_events()

        self.assertEqual(len(claimed_events), 1)
        self.assertEqual(claimed_events[0].id, event.id)

        event.refresh_from_db()

        self.assertEqual(event.status, OutboxEvent.Status.PROCESSING)
        self.assertEqual(event.attempts, 3)
        self.assertEqual(event.locked_at, self.now)
        self.assertIsNotNone(event.lock_token)
        self.assertNotEqual(event.lock_token, old_token)

    @patch("apps.outbox.services.timezone.now")
    def test_marks_stale_event_as_failed_when_attempts_exhausted(
        self,
        mock_now,
    ):
        mock_now.return_value = self.now

        event = self.create_event(
            status=OutboxEvent.Status.PROCESSING,
            attempts=5,
            max_attempts=5,
            locked_at=self.now - timedelta(minutes=6),
            lock_token=uuid4(),
        )

        claimed_events = claim_pending_events()

        self.assertEqual(claimed_events, [])

        event.refresh_from_db()

        self.assertEqual(event.status, OutboxEvent.Status.FAILED)
        self.assertIsNone(event.locked_at)
        self.assertIsNone(event.lock_token)
        self.assertEqual(event.last_error, "Processing lease expired.")

    def test_rejects_invalid_batch_size(self):
        with self.assertRaises(ValueError):
            claim_pending_events(batch_size=0)

        with self.assertRaises(ValueError):
            claim_pending_events(batch_size=-1)

    def test_rejects_invalid_lock_timeout(self):
        with self.assertRaises(ValueError):
            claim_pending_events(
                lock_timeout=timedelta(seconds=0),
            )

        with self.assertRaises(ValueError):
            claim_pending_events(
                lock_timeout=timedelta(seconds=-1),
            )

    def test_recovers_processing_event_with_null_locked_at(self):
        event = OutboxEvent.objects.create(
            event_type="user.registered",
            aggregate_type="user",
            aggregate_id=uuid4(),
            status=OutboxEvent.Status.PROCESSING,
            attempts=1,
            max_attempts=5,
            locked_at=None,
            lock_token=uuid4(),
        )
        old_token = event.lock_token

        claimed_events = claim_pending_events()

        self.assertEqual(len(claimed_events), 1)

        claimed_event = claimed_events[0]

        self.assertEqual(claimed_event.id, event.id)
        self.assertEqual(
            claimed_event.status,
            OutboxEvent.Status.PROCESSING,
        )
        self.assertIsNotNone(claimed_event.locked_at)
        self.assertIsNotNone(claimed_event.lock_token)
        self.assertNotEqual(claimed_event.lock_token, old_token)
        self.assertEqual(claimed_event.attempts, 2)

class MarkEventAsProcessedTests(TestCase):

    def create_processing_event(self, **kwargs):
        defaults = {
            "event_type": "user.registered",
            "aggregate_type": "user",
            "aggregate_id": uuid4(),
            "status": OutboxEvent.Status.PROCESSING,
            "attempts": 1,
            "locked_at": timezone.now(),
            "lock_token": uuid4(),
        }
        defaults.update(kwargs)

        return OutboxEvent.objects.create(**defaults)

    def test_marks_processing_event_as_processed(self):
        event = self.create_processing_event()

        result = mark_event_as_processed(
            event.id,
            event.lock_token,
        )

        self.assertTrue(result)

        event.refresh_from_db()

        self.assertEqual(event.status, OutboxEvent.Status.PROCESSED)
        self.assertIsNotNone(event.processed_at)
        self.assertIsNone(event.locked_at)
        self.assertIsNone(event.lock_token)
        self.assertEqual(event.last_error, "")

    def test_does_not_process_pending_event(self):
        event = OutboxEvent.objects.create(
            event_type="user.registered",
            aggregate_type="user",
            aggregate_id=uuid4(),
        )

        result = mark_event_as_processed(
            event.id,
            uuid4(),
        )

        self.assertFalse(result)

        event.refresh_from_db()

        self.assertEqual(event.status, OutboxEvent.Status.PENDING)
        self.assertIsNone(event.processed_at)

    def test_returns_false_for_nonexistent_event(self):
        result = mark_event_as_processed(
            uuid4(),
            uuid4(),
        )

        self.assertFalse(result)

    def test_rejects_outdated_lock_token(self):
        event = self.create_processing_event()
        old_token = event.lock_token

        event.lock_token = uuid4()
        event.save(update_fields=["lock_token"])

        result = mark_event_as_processed(
            event.id,
            old_token,
        )

        self.assertFalse(result)

        event.refresh_from_db()

        self.assertEqual(event.status, OutboxEvent.Status.PROCESSING)
        self.assertEqual(event.lock_token, event.lock_token)


class MarkEventAsFailedTests(TestCase):

    def create_processing_event(self, **kwargs):
        defaults = {
            "event_type": "user.registered",
            "aggregate_type": "user",
            "aggregate_id": uuid4(),
            "status": OutboxEvent.Status.PROCESSING,
            "attempts": 1,
            "max_attempts": 5,
            "locked_at": timezone.now(),
            "lock_token": uuid4(),
        }
        defaults.update(kwargs)

        return OutboxEvent.objects.create(**defaults)

    def test_schedules_retry_after_first_failure(self):
        now = timezone.now()
        event = self.create_processing_event(attempts=1)

        with patch("apps.outbox.services.timezone.now", return_value=now):
            result = mark_event_as_failed(
                event.id,
                event.lock_token,
                "Temporary email server error",
            )

        self.assertTrue(result)

        event.refresh_from_db()

        self.assertEqual(event.status, OutboxEvent.Status.PENDING)
        self.assertIsNone(event.locked_at)
        self.assertIsNone(event.lock_token)
        self.assertEqual(
            event.last_error,
            "Temporary email server error",
        )
        self.assertEqual(
            event.available_at,
            now + timedelta(seconds=30),
        )

    def test_uses_exponential_backoff(self):
        now = timezone.now()
        event = self.create_processing_event(attempts=3)

        with patch("apps.outbox.services.timezone.now", return_value=now):
            mark_event_as_failed(
                event.id,
                event.lock_token,
                "Temporary error",
            )

        event.refresh_from_db()

        self.assertEqual(
            event.available_at,
            now + timedelta(seconds=120),
        )

    def test_marks_event_failed_after_max_attempts(self):
        now = timezone.now()
        event = self.create_processing_event(
            attempts=5,
            max_attempts=5,
        )

        with patch("apps.outbox.services.timezone.now", return_value=now):
            result = mark_event_as_failed(
                event.id,
                event.lock_token,
                "Maximum attempts reached",
            )

        self.assertTrue(result)

        event.refresh_from_db()

        self.assertEqual(event.status, OutboxEvent.Status.FAILED)
        self.assertIsNone(event.locked_at)
        self.assertIsNone(event.lock_token)
        self.assertEqual(
            event.last_error,
            "Maximum attempts reached",
        )

    def test_does_not_fail_non_processing_event(self):
        event = self.create_processing_event(
            status=OutboxEvent.Status.PENDING,
        )

        result = mark_event_as_failed(
            event.id,
            event.lock_token,
            "Some error",
        )

        self.assertFalse(result)

        event.refresh_from_db()

        self.assertEqual(event.status, OutboxEvent.Status.PENDING)

    def test_returns_false_for_nonexistent_event(self):
        result = mark_event_as_failed(
            uuid4(),
            uuid4(),
            "Some error",
        )

        self.assertFalse(result)

    def test_truncates_long_error_message(self):
        event = self.create_processing_event()
        error_message = "x" * 12000

        mark_event_as_failed(
            event.id,
            event.lock_token,
            error_message,
        )

        event.refresh_from_db()

        self.assertEqual(len(event.last_error), 10000)

    def test_rejects_outdated_lock_token(self):
        event = self.create_processing_event()

        old_token = event.lock_token
        current_token = uuid4()

        event.lock_token = current_token
        event.save(update_fields=["lock_token"])

        result = mark_event_as_processed(
            event.id,
            old_token,
        )

        self.assertFalse(result)

        event.refresh_from_db()

        self.assertEqual(
            event.status,
            OutboxEvent.Status.PROCESSING,
        )
        self.assertEqual(event.lock_token, current_token)
        self.assertIsNone(event.processed_at)


@skipUnlessDBFeature("has_select_for_update")
class ConcurrentClaimTests(TransactionTestCase):

    reset_sequences = True

    def test_two_workers_do_not_claim_same_event(self):
        event = OutboxEvent.objects.create(
            event_type="user.registered",
            aggregate_type="user",
            aggregate_id=uuid4(),
            status=OutboxEvent.Status.PENDING,
            available_at=timezone.now() - timedelta(minutes=1),
        )

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def worker():
            close_old_connections()

            try:
                barrier.wait(timeout=5)

                claimed = claim_pending_events(batch_size=1)

                results.append([item.id for item in claimed])

            except Exception as exc:
                errors.append(exc)

            finally:
                close_old_connections()

        threads = [
            threading.Thread(target=worker),
            threading.Thread(target=worker),
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])

        claimed_ids = [
            event_id
            for worker_results in results
            for event_id in worker_results
        ]

        self.assertEqual(claimed_ids.count(event.id), 1)
