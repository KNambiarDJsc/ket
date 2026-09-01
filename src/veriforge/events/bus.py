"""In-process event bus with mandatory persistence.

Every event is written to the Store (durable) before any in-process
subscriber runs. This means the event log survives a crash even if no
subscriber ever fires — required for the "state must survive crashes"
harness principle (§1 Principle 1 / §16 Observability).
"""
from __future__ import annotations

from typing import Callable

from veriforge.domain.enums import EventType
from veriforge.domain.models import Event
from veriforge.storage.repository import Store

Subscriber = Callable[[Event], None]


class EventBus:
    def __init__(self, store: Store):
        self._store = store
        self._subscribers: list[Subscriber] = []

    def subscribe(self, fn: Subscriber) -> None:
        self._subscribers.append(fn)

    def publish(self, job_id: str, type_: EventType, payload: dict | None = None) -> Event:
        event = Event(job_id=job_id, type=type_, payload=payload or {})
        self._store.events.save(event, job_id=job_id)
        for fn in self._subscribers:
            fn(event)
        return event

    def history(self, job_id: str) -> list[Event]:
        events = self._store.events.list_by_job(job_id)
        return sorted(events, key=lambda e: e.timestamp)
