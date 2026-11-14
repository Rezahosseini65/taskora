
from types import SimpleNamespace
from unittest.mock import patch, Mock
from uuid import uuid4

from django.test import SimpleTestCase
from django.conf import settings

from apps.outbox.tasks import process_outbox_events
from apps.users.tasks import send_password_changed_email

class ProcessOutboxEventsTests(SimpleTestCase):
    def setUp(self):
        self.event = SimpleNamespace(
            id=uuid4(),
            event_type="users.email_verification_requested",
            aggregate_id=uuid4(),
            payload={"email": "user@example.com"},
            lock_token=uuid4(),
        )

    @patch("apps.outbox.tasks.mark_event_as_processed")
    @patch("apps.outbox.tasks.registry.get")
    @patch("apps.outbox.tasks.claim_pending_events")
    def test_successfully_processes_event(
        self,
        mock_claim,
        mock_get,
        mock_mark_processed,
    ):
        handler = mock_get.return_value
        mock_claim.return_value = [self.event]
        mock_mark_processed.return_value = True

        result = process_outbox_events.run()

        handler.assert_called_once_with(
            self.event.aggregate_id,
            self.event.payload,
        )

        mock_mark_processed.assert_called_once_with(
            self.event.id,
            self.event.lock_token,
        )

        self.assertEqual(result, {
            "claimed": 1,
            "processed": 1,
            "failed": 0,
            "skipped": 0,
        })

    @patch("apps.outbox.tasks.mark_event_as_failed")
    @patch("apps.outbox.tasks.registry.get")
    @patch("apps.outbox.tasks.claim_pending_events")
    def test_handler_failure_marks_event_as_failed(
        self,
        mock_claim,
        mock_get,
        mock_mark_failed,
    ):
        mock_claim.return_value = [self.event]
        mock_get.side_effect = RuntimeError("Handler failed")
        mock_mark_failed.return_value = True

        result = process_outbox_events.run()

        mock_mark_failed.assert_called_once()

        args = mock_mark_failed.call_args.args

        self.assertEqual(args[0], self.event.id)
        self.assertEqual(args[1], self.event.lock_token)
        self.assertIsInstance(args[2], RuntimeError)

        self.assertEqual(result, {
            "claimed": 1,
            "processed": 0,
            "failed": 1,
            "skipped": 0,
        })

    @patch("apps.outbox.tasks.mark_event_as_failed")
    @patch("apps.outbox.tasks.registry.get")
    @patch("apps.outbox.tasks.claim_pending_events")
    def test_missing_handler_marks_event_as_failed(
        self,
        mock_claim,
        mock_get,
        mock_mark_failed,
    ):
        mock_claim.return_value = [self.event]
        mock_get.side_effect = ValueError("Handler not found")
        mock_mark_failed.return_value = True

        result = process_outbox_events.run()

        mock_mark_failed.assert_called_once()

        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["processed"], 0)

    @patch("apps.outbox.tasks.mark_event_as_failed")
    @patch("apps.outbox.tasks.registry.get")
    @patch("apps.outbox.tasks.claim_pending_events")
    def test_failed_event_update_is_counted_as_skipped(
        self,
        mock_claim,
        mock_get,
        mock_mark_failed,
    ):
        mock_claim.return_value = [self.event]
        mock_get.side_effect = RuntimeError("Handler failed")
        mock_mark_failed.return_value = False

        result = process_outbox_events.run()

        self.assertEqual(result, {
            "claimed": 1,
            "processed": 0,
            "failed": 0,
            "skipped": 1,
        })

    @patch("apps.outbox.tasks.mark_event_as_processed")
    @patch("apps.outbox.tasks.registry.get")
    @patch("apps.outbox.tasks.claim_pending_events")
    def test_invalid_lock_token_is_counted_as_skipped(
        self,
        mock_claim,
        mock_get,
        mock_mark_processed,
    ):
        mock_claim.return_value = [self.event]
        mock_mark_processed.return_value = False

        result = process_outbox_events.run()

        self.assertEqual(result, {
            "claimed": 1,
            "processed": 0,
            "failed": 0,
            "skipped": 1,
        })

    @patch("apps.outbox.tasks.claim_pending_events")
    def test_returns_zero_counts_when_no_events_exist(
        self,
        mock_claim,
    ):
        mock_claim.return_value = []

        result = process_outbox_events.run()

        self.assertEqual(result, {
            "claimed": 0,
            "processed": 0,
            "failed": 0,
            "skipped": 0,
        })

    @patch("apps.outbox.tasks.claim_pending_events")
    def test_passes_custom_batch_size_to_claim_service(
        self,
        mock_claim,
    ):
        mock_claim.return_value = []

        process_outbox_events.run(batch_size=25)

        mock_claim.assert_called_once_with(batch_size=25)

    @patch("apps.outbox.tasks.mark_event_as_processed")
    @patch("apps.outbox.tasks.registry.get")
    @patch("apps.outbox.tasks.claim_pending_events")
    def test_continues_processing_after_previous_event_failure(
        self,
        mock_claim,
        mock_get,
        mock_mark_processed,
    ):
        second_event = SimpleNamespace(
            id=uuid4(),
            event_type="users.email_verification_requested",
            aggregate_id=uuid4(),
            payload={"email": "second@example.com"},
            lock_token=uuid4(),
        )

        mock_claim.return_value = [self.event, second_event]

        first_handler = Mock(
            side_effect=RuntimeError("First event failed")
        )
        second_handler = Mock()

        mock_get.side_effect = [
            first_handler,
            second_handler,
        ]

        with patch(
            "apps.outbox.tasks.mark_event_as_failed",
            return_value=True,
        ):
            mock_mark_processed.return_value = True

            result = process_outbox_events.run()

        self.assertEqual(result, {
            "claimed": 2,
            "processed": 1,
            "failed": 1,
            "skipped": 0,
        })

        mock_mark_processed.assert_called_once_with(
            second_event.id,
            second_event.lock_token,
        )


class SendPasswordChangedEmailTests(SimpleTestCase):

    @patch("apps.users.tasks.send_mail")
    def test_successfully_sends_password_changed_email(
        self,
        mock_send_mail,
    ):
        email = "user@example.com"

        result = send_password_changed_email.run(
            email=email,
        )

        mock_send_mail.assert_called_once()

        kwargs = mock_send_mail.call_args.kwargs

        self.assertEqual(
            kwargs["subject"],
            "Your Taskora password has been changed",
        )
        self.assertEqual(
            kwargs["from_email"],
            settings.DEFAULT_FROM_EMAIL,
        )
        self.assertEqual(
            kwargs["recipient_list"],
            [email],
        )
        self.assertIn(
            "password has been changed",
            kwargs["message"],
        )
        self.assertFalse(kwargs["fail_silently"])

        self.assertTrue(result)

    @patch(
        "apps.users.tasks.send_password_changed_email.retry",
        side_effect=RuntimeError("Retry requested"),
    )
    @patch("apps.users.tasks.send_mail")
    def test_retries_when_email_sending_fails(
        self,
        mock_send_mail,
        mock_retry,
    ):
        mock_send_mail.side_effect = RuntimeError(
            "SMTP connection failed"
        )

        with self.assertRaisesMessage(
            RuntimeError,
            "Retry requested",
        ):
            send_password_changed_email.run(
                email="user@example.com",
            )

        mock_retry.assert_called_once()
