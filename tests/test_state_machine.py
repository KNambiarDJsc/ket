import pytest

from veriforge.domain.enums import JobState
from veriforge.domain.models import Job
from veriforge.events.bus import EventBus
from veriforge.orchestrator.state_machine import InvalidTransition, JobStateMachine


def test_valid_transition_updates_state_and_emits_event(store):
    bus = EventBus(store)
    sm = JobStateMachine(bus)
    job = Job(project_id="proj_1")

    sm.transition(job, JobState.REQUIREMENTS_RECEIVED)

    assert job.state == JobState.REQUIREMENTS_RECEIVED
    events = bus.history(job.id)
    assert len(events) == 1
    assert events[0].payload["to"] == "REQUIREMENTS_RECEIVED"


def test_invalid_transition_raises(store):
    bus = EventBus(store)
    sm = JobStateMachine(bus)
    job = Job(project_id="proj_1")

    with pytest.raises(InvalidTransition):
        sm.transition(job, JobState.COMPLETED)


def test_terminal_states_allow_no_further_transitions(store):
    bus = EventBus(store)
    sm = JobStateMachine(bus)
    job = Job(project_id="proj_1", state=JobState.COMPLETED)

    with pytest.raises(InvalidTransition):
        sm.transition(job, JobState.JOB_CREATED)
