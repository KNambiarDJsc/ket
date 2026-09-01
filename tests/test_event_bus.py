from veriforge.domain.enums import EventType
from veriforge.events.bus import EventBus


def test_publish_persists_and_notifies_subscribers(store):
    bus = EventBus(store)
    received = []
    bus.subscribe(received.append)

    event = bus.publish("job_1", EventType.LOOP_ITERATION, {"n": 1})

    assert received == [event]
    persisted = store.events.list_by_job("job_1")
    assert len(persisted) == 1
    assert persisted[0].payload == {"n": 1}


def test_history_is_time_ordered(store):
    bus = EventBus(store)
    bus.publish("job_1", EventType.LOOP_ITERATION, {"n": 1})
    bus.publish("job_1", EventType.LOOP_ITERATION, {"n": 2})

    history = bus.history("job_1")
    assert [e.payload["n"] for e in history] == [1, 2]
