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


# ---- Phase 10: contract requirements ----

def test_creation_visible_contract_confirmed_by_static_analysis():
    repo_facts = {
        "endpoints": [
            {"method": "POST", "path": "/projects", "source_file": "app.py", "source_line": 38, "mentions_role_check": False},
            {"method": "GET", "path": "/projects", "source_file": "app.py", "source_line": 30, "mentions_role_check": False},
        ],
    }
    req = Requirement(
        project_id="proj_1",
        source_text="A newly created project must appear in GET /projects immediately after creation.",
        kind=RequirementKind.ORDERING, critical=True,
    )
    world_model = build_world_model("proj_1", [req], repo_facts)

    assert req.structured == {
        "contract": "creation_visible_in_listing", "object": "project", "method": "GET", "path": "/projects",
    }
    rationale = world_model.unknowns[0].rationale
    assert "Matched to GET /projects" in rationale
    assert "independently confirmed by static analysis (app.py:30)" in rationale
    assert "Phase 10" in rationale


def test_endpoint_exposed_contract_not_confirmed_by_static_analysis():
    req = Requirement(
        project_id="proj_1", source_text="The service must expose a health check at GET /.",
        kind=RequirementKind.FUNCTIONAL, critical=True,
    )
    world_model = build_world_model("proj_1", [req], {"endpoints": []})

    assert req.structured == {
        "contract": "endpoint_exposed", "label": "health check", "method": "GET", "path": "/",
    }
    rationale = world_model.unknowns[0].rationale
    assert "Matched to GET /" in rationale
    assert "NOT independently confirmed by static analysis" in rationale


def test_db_removal_requirement_matches_delete_endpoint():
    repo_facts = {
        "endpoints": [
            {"method": "POST", "path": "/projects", "source_file": "app.py", "source_line": 60, "mentions_role_check": False},
            {"method": "DELETE", "path": "/projects/", "source_file": "app.py", "source_line": 75, "mentions_role_check": False},
        ],
    }
    req = Requirement(
        project_id="proj_1",
        source_text="Deleted projects must be permanently removed from the database, not merely hidden.",
        kind=RequirementKind.FUNCTIONAL, critical=True,
    )
    world_model = build_world_model("proj_1", [req], repo_facts)

    assert req.structured == {"db_check": "removed_after_delete", "object": "projects", "action": "delete"}
    rationale = world_model.unknowns[0].rationale
    assert "Matched to DELETE /projects/" in rationale
    assert "Phase 11" in rationale
    assert "data-integrity requirement" in rationale
