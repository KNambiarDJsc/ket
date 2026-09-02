from veriforge.domain.enums import RequirementKind, TestStatus
from veriforge.domain.models import ApiEndpoint, Requirement, Unknown, WorldModel
from veriforge.strategist.scientist import endpoint_key, promote_to_tests, rank_experiments, score_unknown


def make_world_model(requirements, unknowns):
    return WorldModel(project_id="proj_1", requirements=requirements, unknowns=unknowns)


def test_endpoint_key_extracts_method_and_path():
    rationale = 'Matched to DELETE /projects/ (app.py:46); handler source has no role/permission-check identifier.'
    assert endpoint_key(rationale) == "DELETE /projects/"


def test_endpoint_key_none_when_no_match():
    assert endpoint_key("No matching endpoint found by static analysis.") is None


def test_unchecked_authorization_endpoint_ranks_above_unmatched_requirement():
    req_authz = Requirement(
        id="req_authz", project_id="proj_1", source_text="Members cannot delete projects.",
        kind=RequirementKind.NEGATIVE, critical=True,
    )
    req_temporal = Requirement(
        id="req_temporal", project_id="proj_1", source_text="Creation must return within 2 seconds.",
        kind=RequirementKind.TEMPORAL, critical=True,
    )
    unknowns = [
        Unknown(
            project_id="proj_1", requirement_id="req_temporal",
            question="Has this been verified: creation timing?",
            rationale="No matching endpoint found by static analysis for this requirement's action/object; requirement coverage unknown.",
        ),
        Unknown(
            project_id="proj_1", requirement_id="req_authz",
            question="Has this been verified: no delete?",
            rationale="Matched to DELETE /projects/ (app.py:46); handler source has no role/permission-check identifier.",
        ),
    ]
    world_model = make_world_model([req_authz, req_temporal], unknowns)

    ranked = rank_experiments(world_model)

    assert ranked[0].requirement_id == "req_authz"
    assert ranked[0].score > ranked[1].score


def test_resolved_unknowns_are_excluded():
    req = Requirement(id="req_1", project_id="proj_1", source_text="X", critical=True)
    unknowns = [
        Unknown(project_id="proj_1", requirement_id="req_1", question="q", rationale="r", resolved=True),
    ]
    world_model = make_world_model([req], unknowns)

    assert rank_experiments(world_model) == []


def test_duplicate_endpoint_match_is_penalized_for_redundancy():
    req_a = Requirement(id="req_a", project_id="proj_1", source_text="A", critical=True)
    req_b = Requirement(id="req_b", project_id="proj_1", source_text="B", critical=True)
    rationale = "Matched to DELETE /projects/ (app.py:46); handler source has no role/permission-check identifier."
    unknowns = [
        Unknown(project_id="proj_1", requirement_id="req_a", question="q1", rationale=rationale),
        Unknown(project_id="proj_1", requirement_id="req_b", question="q2", rationale=rationale),
    ]
    world_model = make_world_model([req_a, req_b], unknowns)

    ranked = rank_experiments(world_model)

    assert ranked[0].score > ranked[1].score  # first occurrence wins, second is redundant


def test_promote_to_tests_marks_top_k_planned_rest_hypothesis():
    req = Requirement(id="req_1", project_id="proj_1", source_text="X", critical=True)
    unknowns = [
        Unknown(project_id="proj_1", requirement_id="req_1", question=f"q{i}", rationale="No matching endpoint found by static analysis.")
        for i in range(5)
    ]
    world_model = make_world_model([req], unknowns)
    ranked = rank_experiments(world_model)

    tests = promote_to_tests(ranked, top_k=2)

    statuses = [t.status for t in tests]
    assert statuses[:2] == [TestStatus.PLANNED, TestStatus.PLANNED]
    assert all(s == TestStatus.HYPOTHESIS for s in statuses[2:])


# ---- Phase 13: real change_relevance ----

def test_score_unknown_uses_placeholder_when_no_diff_available():
    req = Requirement(id="r", project_id="p", source_text="x", critical=True)
    unknown = Unknown(project_id="p", requirement_id="r", question="q", rationale="r")
    breakdown = score_unknown(unknown, req, set(), endpoint=None, changed_files=None)
    assert breakdown.change_relevance == 0.5


def test_score_unknown_scores_high_when_endpoint_file_in_diff():
    req = Requirement(id="r", project_id="p", source_text="x", critical=True)
    unknown = Unknown(project_id="p", requirement_id="r", question="q", rationale="r")
    endpoint = ApiEndpoint(project_id="p", method="DELETE", path="/x", source_file="app.py", source_line=1)
    breakdown = score_unknown(unknown, req, set(), endpoint=endpoint, changed_files={"app.py"})
    assert breakdown.change_relevance == 1.0


def test_score_unknown_scores_low_when_diff_available_but_file_untouched():
    req = Requirement(id="r", project_id="p", source_text="x", critical=True)
    unknown = Unknown(project_id="p", requirement_id="r", question="q", rationale="r")
    endpoint = ApiEndpoint(project_id="p", method="DELETE", path="/x", source_file="app.py", source_line=1)
    breakdown = score_unknown(unknown, req, set(), endpoint=endpoint, changed_files={"other.py"})
    assert breakdown.change_relevance == 0.2


def test_rank_experiments_boosts_the_unknown_whose_endpoint_actually_changed():
    endpoint_alpha = ApiEndpoint(project_id="p", method="DELETE", path="/alpha", source_file="alpha.py", source_line=1)
    endpoint_bravo = ApiEndpoint(project_id="p", method="DELETE", path="/bravo", source_file="bravo.py", source_line=1)
    req_alpha = Requirement(
        id="req_alpha", project_id="p", source_text="Members cannot delete alpha.", critical=True,
        structured={"actor": "members", "action": "delete", "object": "alpha", "expected": "denied"},
    )
    req_bravo = Requirement(
        id="req_bravo", project_id="p", source_text="Members cannot delete bravo.", critical=True,
        structured={"actor": "members", "action": "delete", "object": "bravo", "expected": "denied"},
    )
    unknowns = [
        Unknown(project_id="p", requirement_id="req_alpha", question="qa", rationale="Matched to DELETE /alpha."),
        Unknown(project_id="p", requirement_id="req_bravo", question="qb", rationale="Matched to DELETE /bravo."),
    ]
    world_model = WorldModel(
        project_id="p", requirements=[req_alpha, req_bravo], unknowns=unknowns,
        api_endpoints=[endpoint_alpha, endpoint_bravo],
    )

    ranked = rank_experiments(world_model, changed_files={"bravo.py"})

    assert ranked[0].requirement_id == "req_bravo"
    assert ranked[0].score > ranked[1].score


def test_exploration_derived_unknown_has_no_requirement_but_still_scores():
    unknowns = [
        Unknown(
            project_id="proj_1", question="What happens when a user activates: button \"Delete\"?",
            rationale='Discovered by browser exploration but not auto-clicked: button "Delete" (looks destructive — not auto-clicked)',
        ),
    ]
    world_model = make_world_model([], unknowns)

    ranked = rank_experiments(world_model)

    assert len(ranked) == 1
    assert ranked[0].requirement_id is None
    assert ranked[0].hypothesis == unknowns[0].question
