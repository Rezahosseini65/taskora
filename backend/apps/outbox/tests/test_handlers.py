from django.test import SimpleTestCase

from apps.outbox.handlers.registry import HandlerRegistry


class HandlerRegistryTests(SimpleTestCase):
    def setUp(self):
        self.registry = HandlerRegistry()

    def sample_handler(self, aggregate_id, payload):
        return None

    def test_register_handler(self):
        self.registry.register(
            "user.registered",
            self.sample_handler,
        )

        self.assertTrue(
            self.registry.has_handler("user.registered")
        )

    def test_get_registered_handler(self):
        self.registry.register(
            "user.registered",
            self.sample_handler,
        )

        handler = self.registry.get("user.registered")

        self.assertEqual(handler, self.sample_handler)

    def test_get_unregistered_handler_raises_error(self):
        with self.assertRaisesMessage(
            ValueError,
            "No handler registered for event type: user.registered",
        ):
            self.registry.get("user.registered")

    def test_register_duplicate_handler_raises_error(self):
        self.registry.register(
            "user.registered",
            self.sample_handler,
        )

        with self.assertRaisesMessage(
            ValueError,
            "Handler already registered for event type: user.registered",
        ):
            self.registry.register(
                "user.registered",
                self.sample_handler,
            )

    def test_has_handler_returns_false_for_unregistered_event(self):
        self.assertFalse(
            self.registry.has_handler("user.registered")
        )