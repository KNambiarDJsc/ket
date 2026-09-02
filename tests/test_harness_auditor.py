from veriforge.domain.enums import Verdict
from veriforge.evaluation.benchmarks import EXAMPLE_APP, EXAMPLE_DB_APP
from veriforge.evaluation.harness_auditor import (
    RequirementAudit,
    aggregate_metrics,
    run_all_benchmarks,
    run_benchmark,
)


# ---- run_benchmark, against the real example apps ----

def test_run_benchmark_example_app_matches_every_known_ground_truth(tmp_path):
    result = run_benchmark(EXAMPLE_APP, tmp_path / "example-app")

    # 6 requirements in requirements.md, 1 (temporal) not yet executable.
    assert len(result.audits) == 5
    for audit in result.audits:
        assert audit.observed is not None, f"{audit.source_text!r} never became executable"
        assert audit.outcome == "correct", f"{audit.source_text!r}: {audit.expected} vs {audit.observed}"
    assert result.tool_calls_used > 0


def test_run_benchmark_example_db_app_matches_every_known_ground_truth(tmp_path):
    result = run_benchmark(EXAMPLE_DB_APP, tmp_path / "example-db-app")

    assert len(result.audits) == 3
    for audit in result.audits:
        assert audit.observed is not None, f"{audit.source_text!r} never became executable"
        assert audit.outcome == "correct", f"{audit.source_text!r}: {audit.expected} vs {audit.observed}"
    assert result.tool_calls_used > 0


def test_run_all_benchmarks_and_aggregate_are_perfect_against_known_ground_truth(tmp_path):
    results = run_all_benchmarks(tmp_path)
    metrics = aggregate_metrics(results)

    assert metrics["scored_requirement_count"] == 8.0  # 5 + 3
    assert metrics["false_positive_rate"] == 0.0
    assert metrics["information_gain_per_experiment"] == 1.0  # no UNCERTAIN verdicts
    assert metrics["verified_findings_per_compute"] > 0.0


# ---- BenchmarkResult metrics, against synthetic (non-perfect) audits ----

def _audit(expected, observed):
    return RequirementAudit(source_text="x", expected=expected, observed=observed, reasoning=None)


def test_false_positive_rate_counts_only_pass_ground_truth_wrongly_flagged_fail():
    from veriforge.evaluation.harness_auditor import BenchmarkResult

    result = BenchmarkResult(
        benchmark_name="synthetic",
        audits=[
            _audit(Verdict.PASS, Verdict.FAIL),  # false positive
            _audit(Verdict.PASS, Verdict.PASS),  # correct
            _audit(Verdict.FAIL, Verdict.FAIL),  # correct (true positive, irrelevant to FP rate)
        ],
        tool_calls_used=10,
    )
    assert result.false_positive_rate == 0.5  # 1 of 2 PASS-ground-truth requirements wrongly flagged


def test_information_gain_counts_uncertain_as_zero_information():
    from veriforge.evaluation.harness_auditor import BenchmarkResult

    result = BenchmarkResult(
        benchmark_name="synthetic",
        audits=[
            _audit(Verdict.FAIL, Verdict.FAIL),
            _audit(Verdict.PASS, Verdict.UNCERTAIN),
            _audit(Verdict.FAIL, Verdict.UNCERTAIN),
            _audit(Verdict.PASS, Verdict.PASS),
        ],
        tool_calls_used=10,
    )
    assert result.information_gain_per_experiment == 0.5  # 2 of 4 decisive


def test_verified_findings_per_compute_only_counts_true_positives():
    from veriforge.evaluation.harness_auditor import BenchmarkResult

    result = BenchmarkResult(
        benchmark_name="synthetic",
        audits=[
            _audit(Verdict.FAIL, Verdict.FAIL),  # true positive
            _audit(Verdict.FAIL, Verdict.PASS),  # false negative -- missed a real bug
            _audit(Verdict.PASS, Verdict.FAIL),  # false positive -- doesn't count as a "found" bug
        ],
        tool_calls_used=5,
    )
    assert result.verified_findings_per_compute == 1 / 5


def test_not_executable_audits_are_excluded_from_every_metric():
    from veriforge.evaluation.harness_auditor import BenchmarkResult

    result = BenchmarkResult(
        benchmark_name="synthetic",
        audits=[
            _audit(Verdict.FAIL, None),  # not yet executable against this repo
            _audit(Verdict.FAIL, Verdict.FAIL),
        ],
        tool_calls_used=3,
    )
    assert len(result.scored_audits) == 1
    assert result.information_gain_per_experiment == 1.0
