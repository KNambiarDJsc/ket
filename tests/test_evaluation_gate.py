from veriforge.domain.enums import Verdict
from veriforge.evaluation.gate import evaluate_candidate
from veriforge.evaluation.harness_auditor import BenchmarkResult, RequirementAudit


def _audit(expected, observed):
    return RequirementAudit(source_text="x", expected=expected, observed=observed, reasoning=None)


def _result(name, audits, tool_calls_used=10):
    return BenchmarkResult(benchmark_name=name, audits=audits, tool_calls_used=tool_calls_used)


# Five scored requirements -- exactly the gate's own minimum, mirroring
# learning/engine.py's _MIN_RUNS_FOR_DECISION precedent.
_FIVE_AUDITS = [
    _audit(Verdict.FAIL, Verdict.FAIL),
    _audit(Verdict.FAIL, Verdict.FAIL),
    _audit(Verdict.PASS, Verdict.PASS),
    _audit(Verdict.PASS, Verdict.PASS),
    _audit(Verdict.PASS, Verdict.PASS),
]


def test_insufficient_scored_requirements_returns_none():
    baseline = [_result("b", _FIVE_AUDITS[:4])]  # only 4, below the minimum of 5
    candidate = [_result("b", _FIVE_AUDITS[:4])]

    verdict = evaluate_candidate(baseline, candidate)

    assert verdict.kept is None
    assert "need at least" in verdict.reason


def test_identical_candidate_is_kept():
    baseline = [_result("b", _FIVE_AUDITS)]
    candidate = [_result("b", list(_FIVE_AUDITS))]

    verdict = evaluate_candidate(baseline, candidate)

    assert verdict.kept is True
    assert verdict.regressions == []


def test_candidate_with_new_false_positive_is_not_kept():
    baseline = [_result("b", _FIVE_AUDITS)]
    regressed = [
        _audit(Verdict.FAIL, Verdict.FAIL),
        _audit(Verdict.FAIL, Verdict.FAIL),
        _audit(Verdict.PASS, Verdict.FAIL),  # new false positive
        _audit(Verdict.PASS, Verdict.PASS),
        _audit(Verdict.PASS, Verdict.PASS),
    ]
    candidate = [_result("b", regressed)]

    verdict = evaluate_candidate(baseline, candidate)

    assert verdict.kept is False
    assert any("false_positive_rate" in r for r in verdict.regressions)


def test_candidate_that_misses_a_previously_found_bug_is_not_kept():
    baseline = [_result("b", _FIVE_AUDITS, tool_calls_used=10)]
    regressed = [
        _audit(Verdict.FAIL, Verdict.PASS),  # missed a bug it used to find
        _audit(Verdict.FAIL, Verdict.FAIL),
        _audit(Verdict.PASS, Verdict.PASS),
        _audit(Verdict.PASS, Verdict.PASS),
        _audit(Verdict.PASS, Verdict.PASS),
    ]
    candidate = [_result("b", regressed, tool_calls_used=10)]

    verdict = evaluate_candidate(baseline, candidate)

    assert verdict.kept is False
    assert any("verified_findings_per_compute" in r for r in verdict.regressions)


def test_candidate_with_new_uncertain_verdict_is_not_kept():
    baseline = [_result("b", _FIVE_AUDITS)]
    regressed = [
        _audit(Verdict.FAIL, Verdict.FAIL),
        _audit(Verdict.FAIL, Verdict.UNCERTAIN),  # used to be decisive
        _audit(Verdict.PASS, Verdict.PASS),
        _audit(Verdict.PASS, Verdict.PASS),
        _audit(Verdict.PASS, Verdict.PASS),
    ]
    candidate = [_result("b", regressed)]

    verdict = evaluate_candidate(baseline, candidate)

    assert verdict.kept is False
    assert any("information_gain_per_experiment" in r for r in verdict.regressions)


def test_candidate_that_strictly_improves_is_kept():
    worse_baseline = [
        _audit(Verdict.FAIL, Verdict.UNCERTAIN),  # missed, undecided
        _audit(Verdict.FAIL, Verdict.FAIL),
        _audit(Verdict.PASS, Verdict.FAIL),  # false positive
        _audit(Verdict.PASS, Verdict.PASS),
        _audit(Verdict.PASS, Verdict.PASS),
    ]
    baseline = [_result("b", worse_baseline)]
    candidate = [_result("b", _FIVE_AUDITS)]  # strictly better on all 3 metrics

    verdict = evaluate_candidate(baseline, candidate)

    assert verdict.kept is True
