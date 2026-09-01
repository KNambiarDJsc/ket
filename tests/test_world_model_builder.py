from veriforge.domain.enums import RequirementKind
from veriforge.domain.models import Requirement
from veriforge.world_model.builder import build_world_model

REPO_FACTS_WITH_UNCHECKED_DELETE = {
    "endpoints": [
        {
            "method": "DELETE",
            "path": "/projects/",
            "source_file": "app.py",
            "source_line": 46,
            "mentions_role_check": False,
        },
        {
            "method": "GET",
            "path": "/projects",
            "source_file": "app.py",
            "source_line": 30,
            "mentions_role_check": False,
        },
    ],
}


def test_authorization_requirement_matches_unchecked_endpoint_and_flags_it():
    req = Requirement(
        project_id="proj_1", source_text="Members cannot delete projects.",
        kind=RequirementKind.NEGATIVE, critical=True,
    )
    world_model = build_world_model("proj_1", [req], REPO_FACTS_WITH_UNCHECKED_DELETE)

    assert req.structured == {
        "actor": "members", "action": "delete", "object": "projects", "expected": "denied",
    }
    assert len(world_model.api_endpoints) == 2
    assert len(world_model.unknowns) == 1
    rationale = world_model.unknowns[0].rationale
    assert "DELETE /projects/" in rationale
    assert "no role/permission-check identifier" in rationale


def test_authorization_requirement_matches_checked_endpoint_differently():
    repo_facts = {
        "endpoints": [
            {
                "method": "DELETE",
                "path": "/projects/",
                "source_file": "app.py",
                "source_line": 46,
                "mentions_role_check": True,
            },
        ],
    }
    req = Requirement(
        project_id="proj_1", source_text="Members cannot delete projects.",
        kind=RequirementKind.NEGATIVE, critical=True,
    )
    world_model = build_world_model("proj_1", [req], repo_facts)

    rationale = world_model.unknowns[0].rationale
    assert "does reference a role/permission-looking identifier" in rationale


def test_requirement_with_no_matching_endpoint():
    req = Requirement(
        project_id="proj_1", source_text="Members cannot archive projects.",
        kind=RequirementKind.NEGATIVE, critical=True,
    )
    world_model = build_world_model("proj_1", [req], {"endpoints": []})

    rationale = world_model.unknowns[0].rationale
    assert "No matching endpoint found" in rationale


def test_non_critical_requirements_produce_no_unknown():
    req = Requirement(project_id="proj_1", source_text="The UI should feel snappy.", critical=False)
    world_model = build_world_model("proj_1", [req], {})

    assert world_model.unknowns == []
