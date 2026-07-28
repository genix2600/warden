"""The event bus: one sequence, many listeners.

Every subscriber gets the same events in the same order with the same sequence
numbers, and a subscriber that joins late is handed the recent backlog first so
the interface can reconstruct current state without a separate snapshot
protocol. Sequence numbers exist so the UI can notice it missed something and
resynchronise rather than quietly rendering a gap.

A slow subscriber is dropped from the live feed rather than allowed to stall the
agent. A browser tab that has stopped reading must never delay a diagnosis.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import suppress

from warden.contracts import AgentEvent, utcnow

log = logging.getLogger(__name__)

_SUBSCRIBER_QUEUE_LIMIT = 512


class EventBus:
    def __init__(self, history: int = 400) -> None:
        self._seq = 0
        self._history: deque[AgentEvent] = deque(maxlen=history)
        self._subscribers: set[asyncio.Queue[AgentEvent]] = set()
        self._sinks: list[Callable[[AgentEvent], None]] = []

    @property
    def sequence(self) -> int:
        return self._seq

    def add_sink(self, sink: Callable[[AgentEvent], None]) -> None:
        """Register a synchronous consumer, such as the session recorder."""
        self._sinks.append(sink)

    def publish(self, event: AgentEvent) -> AgentEvent:
        """Stamp and fan out. Must be called from the event loop thread."""
        self._seq += 1
        stamped = event.model_copy(update={"seq": self._seq, "ts": utcnow()})
        self._history.append(stamped)

        for sink in self._sinks:
            try:
                sink(stamped)
            except Exception:
                log.exception("event sink failed")

        for queue in list(self._subscribers):
            try:
                queue.put_nowait(stamped)
            except asyncio.QueueFull:
                log.warning("dropping a subscriber that stopped reading")
                self._subscribers.discard(queue)
        return stamped

    def replay_buffer(self) -> list[AgentEvent]:
        return list(self._history)

    async def subscribe(self) -> AsyncIterator[AgentEvent]:
        """Yield the backlog, then live events, until the consumer goes away."""
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_LIMIT)
        backlog = self.replay_buffer()
        self._subscribers.add(queue)
        try:
            for event in backlog:
                yield event
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)
            with suppress(Exception):
                while not queue.empty():
                    queue.get_nowait()
