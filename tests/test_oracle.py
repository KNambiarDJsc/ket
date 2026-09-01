from veriforge.domain.enums import Verdict
from veriforge.oracle.oracle import judge_allowed_only_for_actor, judge_authorization, judge_data_invariant


def test_denied_status_with_resource_gone_matches_expected_denied():
    verdict = judge_authorization(expected="denied", response_status=403, resource_still_present=True)
    assert verdict.verdict == Verdict.PASS
    assert verdict.observed == "denied"
    assert verdict.confidence >= 0.85  # status and state agree


def test_allowed_status_with_resource_removed_violates_expected_denied():
    verdict = judge_authorization(expected="denied", response_status=200, resource_still_present=False)
    assert verdict.verdict == Verdict.FAIL
    assert verdict.observed == "allowed"
    assert "violates" in verdict.reasoning


def test_status_and_state_disagreement_lowers_confidence_but_state_wins():
    # status says success (2xx) but the resource is still there -- contradictory;
    # state is the ground truth, so observed should be "denied", with reduced confidence.
    verdict = judge_authorization(expected="denied", response_status=200, resource_still_present=True)
    assert verdict.observed == "denied"
    assert verdict.verdict == Verdict.PASS
    assert verdict.confidence < 0.9


def test_no_state_check_falls_back_to_status_only_with_lower_confidence():
    verdict = judge_authorization(expected="denied", response_status=403, resource_still_present=None)
    assert verdict.observed == "denied"
    assert verdict.verdict == Verdict.PASS
    assert verdict.confidence == 0.6


def test_ambiguous_status_without_state_check_is_uncertain():
    verdict = judge_authorization(expected="denied", response_status=500, resource_still_present=None)
    assert verdict.verdict == Verdict.UNCERTAIN
    assert verdict.observed == "unknown"


# ---- judge_data_invariant ----

def test_data_invariant_matches_expected_status():
    verdict = judge_data_invariant(expected_status=404, forbidden_status=500, response_status=404)
    assert verdict.verdict == Verdict.PASS


def test_data_invariant_hits_forbidden_status():
    verdict = judge_data_invariant(expected_status=404, forbidden_status=500, response_status=500)
    assert verdict.verdict == Verdict.FAIL
    assert "forbidden" in verdict.reasoning


def test_data_invariant_neither_expected_nor_forbidden_is_uncertain():
    verdict = judge_data_invariant(expected_status=404, forbidden_status=500, response_status=403)
    assert verdict.verdict == Verdict.UNCERTAIN


def test_data_invariant_with_no_forbidden_status_declared():
    verdict = judge_data_invariant(expected_status=200, forbidden_status=None, response_status=200)
    assert verdict.verdict == Verdict.PASS


# ---- judge_allowed_only_for_actor ----

def test_allowed_only_passes_when_actor_succeeds_and_other_denied():
    verdict = judge_allowed_only_for_actor(
        actor_status=200, actor_resource_gone=True, other_status=403, other_resource_gone=False,
    )
    assert verdict.verdict == Verdict.PASS


def test_allowed_only_fails_when_other_role_can_also_do_it():
    verdict = judge_allowed_only_for_actor(
        actor_status=200, actor_resource_gone=True, other_status=200, other_resource_gone=True,
    )
    assert verdict.verdict == Verdict.FAIL
    assert "not actually exclusive" in verdict.reasoning


def test_allowed_only_uncertain_when_actor_itself_is_denied():
    verdict = judge_allowed_only_for_actor(
        actor_status=403, actor_resource_gone=False, other_status=403, other_resource_gone=False,
    )
    assert verdict.verdict == Verdict.UNCERTAIN
