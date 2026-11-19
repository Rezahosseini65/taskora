
from typing import Any, Callable
from uuid import UUID


EventHandler = Callable[[UUID, dict[str, Any]], None]


class HandlerRegistry:
    def __init__(self):
        self._handlers: dict[str, EventHandler] = {}

    def register(self, event_type: str, handler: EventHandler) -> None:
        if event_type in self._handlers:
            raise ValueError(
                f"Handler already registered for event type: {event_type}"
            )

        self._handlers[event_type] = handler

    def get(self, event_type: str) -> EventHandler:
        try:
            return self._handlers[event_type]
        except KeyError:
            raise ValueError(
                f"No handler registered for event type: {event_type}"
            )

    def has_handler(self, event_type: str) -> bool:
        return event_type in self._handlers


registry = HandlerRegistry()
