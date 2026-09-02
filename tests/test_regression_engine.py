from veriforge.domain.enums import RequirementKind
from veriforge.domain.models import ApiEndpoint, Requirement
from veriforge.regression.engine import write_or_heal_regression_test


def make_requirement():
    return Requirement(
        project_id="p", source_text="Members cannot delete projects.",
        kind=RequirementKind.NEGATIVE, critical=True,
        structured={"actor": "members", "action": "delete", "object": "projects", "expected": "denied"},
    )


def make_endpoints():
    return [
        ApiEndpoint(project_id="p", method="POST", path="/projects", source_file="app.py", source_line=1),
        ApiEndpoint(project_id="p", method="DELETE", path="/projects/", source_file="app.py", source_line=2),
    ]


def test_first_write_creates_the_file(tmp_path):
    requirement = make_requirement()
    endpoints = make_endpoints()

    result = write_or_heal_regression_test(
        repo_path=str(tmp_path), requirement=requirement, action_endpoint=endpoints[1],
        all_endpoints=endpoints, base_url="http://localhost:8000",
    )

    assert result.action == "created"
    assert result.path.exists()


def test_second_write_with_no_drift_is_unchanged(tmp_path):
    requirement = make_requirement()
    endpoints = make_endpoints()
    kwargs = dict(
        repo_path=str(tmp_path), requirement=requirement, action_endpoint=endpoints[1],
        all_endpoints=endpoints, base_url="http://localhost:8000",
    )

    write_or_heal_regression_test(**kwargs)
    result = write_or_heal_regression_test(**kwargs)

    assert result.action == "unchanged"
    assert result.diff == ""


def test_write_with_a_new_base_url_heals_in_place(tmp_path):
    requirement = make_requirement()
    endpoints = make_endpoints()

    first = write_or_heal_regression_test(
        repo_path=str(tmp_path), requirement=requirement, action_endpoint=endpoints[1],
        all_endpoints=endpoints, base_url="http://localhost:8000",
    )
    second = write_or_heal_regression_test(
        repo_path=str(tmp_path), requirement=requirement, action_endpoint=endpoints[1],
        all_endpoints=endpoints, base_url="http://localhost:9000",
    )

    assert second.action == "healed"
    assert second.path == first.path
    assert "9000" in second.path.read_text(encoding="utf-8")
    assert "8000" in second.diff and "9000" in second.diff
