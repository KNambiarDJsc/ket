from veriforge.domain.enums import RequirementKind
from veriforge.requirements.parser import parse_requirements_text

SAMPLE = """
# Example App — Requirements

- Members cannot delete projects.
- Only an owner may delete a project.
- Project creation must return within 2 seconds.
- Deleting a project that does not exist must return a 404, not a 500.
"""


def test_parses_one_requirement_per_bullet():
    reqs = parse_requirements_text(SAMPLE, project_id="proj_1")
    assert len(reqs) == 4
    assert all(r.project_id == "proj_1" for r in reqs)


def test_classifies_negative_requirement():
    reqs = parse_requirements_text(SAMPLE, project_id="proj_1")
    negative = [r for r in reqs if r.source_text.startswith("Members cannot")]
    assert negative[0].kind == RequirementKind.NEGATIVE
    assert negative[0].critical is True


def test_classifies_temporal_requirement():
    reqs = parse_requirements_text(SAMPLE, project_id="proj_1")
    temporal = [r for r in reqs if "2 seconds" in r.source_text]
    assert temporal[0].kind == RequirementKind.TEMPORAL


def test_classifies_only_actor_as_authorization():
    reqs = parse_requirements_text(SAMPLE, project_id="proj_1")
    only_owner = [r for r in reqs if r.source_text.startswith("Only an owner")]
    assert only_owner[0].kind == RequirementKind.AUTHORIZATION


def test_classifies_status_code_sentence_as_data_invariant():
    reqs = parse_requirements_text(SAMPLE, project_id="proj_1")
    status_req = [r for r in reqs if "404" in r.source_text]
    assert status_req[0].kind == RequirementKind.DATA_INVARIANT
