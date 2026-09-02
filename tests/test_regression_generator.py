from veriforge.domain.enums import RequirementKind
from veriforge.domain.models import ApiEndpoint, Requirement
from veriforge.regression.generator import (
    generate_regression_test,
    regression_dir,
    regression_test_path,
    write_regression_test,
)


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


def test_generate_regression_test_is_valid_python():
    requirement = make_requirement()
    endpoints = make_endpoints()

    source = generate_regression_test(
        requirement=requirement, action_endpoint=endpoints[1],
        all_endpoints=endpoints, base_url="http://localhost:8000",
    )

    compile(source, "<generated>", "exec")  # raises SyntaxError if malformed
    assert f"def test_regression_{requirement.id}" in source
    assert "Verdict.PASS" in source
    assert requirement.source_text in source


def test_generate_regression_test_is_deterministic():
    requirement = make_requirement()
    endpoints = make_endpoints()

    first = generate_regression_test(
        requirement=requirement, action_endpoint=endpoints[1],
        all_endpoints=endpoints, base_url="http://localhost:8000",
    )
    second = generate_regression_test(
        requirement=requirement, action_endpoint=endpoints[1],
        all_endpoints=endpoints, base_url="http://localhost:8000",
    )

    assert first == second


def test_generate_regression_test_requires_structured_invariant():
    requirement = Requirement(project_id="p", source_text="The UI should feel snappy.", critical=False)
    endpoints = make_endpoints()

    try:
        generate_regression_test(
            requirement=requirement, action_endpoint=endpoints[1],
            all_endpoints=endpoints, base_url="http://localhost:8000",
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_write_regression_test_creates_file_and_init(tmp_path):
    requirement = make_requirement()
    endpoints = make_endpoints()
    repo_path = str(tmp_path)

    path = write_regression_test(
        repo_path=repo_path, requirement=requirement, action_endpoint=endpoints[1],
        all_endpoints=endpoints, base_url="http://localhost:8000",
    )

    assert path == regression_test_path(repo_path, requirement)
    assert path.exists()
    assert (regression_dir(repo_path) / "__init__.py").exists()
    compile(path.read_text(encoding="utf-8"), "<generated>", "exec")
