"""Job lifecycle state machine.

This is the single place transitions are validated. Anything that wants to
move a Job forward must go through `JobStateMachine.transition` — the harness
and job runner never set `job.state` directly.
"""
from __future__ import annotations

from veriforge.domain.enums import JOB_STATE_TRANSITIONS, EventType, JobState
from veriforge.domain.models import Job, utcnow
from veriforge.events.bus import EventBus


class InvalidTransition(Exception):
    pass


class JobStateMachine:
    def __init__(self, event_bus: EventBus):
        self._bus = event_bus

    def transition(self, job: Job, to_state: JobState, *, reason: str = "") -> Job:
        allowed = JOB_STATE_TRANSITIONS.get(job.state, ())
        if to_state not in allowed:
            raise InvalidTransition(
                f"Cannot transition job {job.id} from {job.state} to {to_state} "
                f"(allowed: {[s.value for s in allowed]})"
            )
        from_state = job.state
        job.state = to_state
        job.updated_at = utcnow()
        self._bus.publish(
            job.id,
            EventType.JOB_STATE_CHANGED,
            {"from": from_state.value, "to": to_state.value, "reason": reason},
        )
        return job
