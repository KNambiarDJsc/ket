from veriforge.domain.enums import JobState, RequirementKind
from veriforge.domain.models import Job, Requirement


def test_job_defaults_to_created_state():
    job = Job(project_id="proj_1")
    assert job.state == JobState.JOB_CREATED
    assert job.id.startswith("job_")


def test_requirement_round_trips_through_json():
    req = Requirement(project_id="proj_1", source_text="Members cannot delete projects.", kind=RequirementKind.NEGATIVE)
    dumped = req.model_dump(mode="json")
    restored = Requirement.model_validate(dumped)
    assert restored.source_text == req.source_text
    assert restored.kind == RequirementKind.NEGATIVE
