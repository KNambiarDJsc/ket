from veriforge.domain.models import Job, Strategy
from veriforge.learning.engine import compute_run_metric, record_run_learning


def test_compute_run_metric_zero_when_nothing_executed():
    assert compute_run_metric(0, None) == 0.0


def test_compute_run_metric_one_on_fail_verdict():
    assert compute_run_metric(1, "FAIL") == 1.0


def test_compute_run_metric_zero_on_pass_verdict():
    assert compute_run_metric(1, "PASS") == 0.0


def test_first_run_has_insufficient_data_for_a_verdict(store):
    strategy = Strategy(project_id="p1", name="default", version=1, weights={})
    job = Job(project_id="p1")

    learning = record_run_learning(store, "p1", strategy, job, metric=1.0)

    assert learning.kept is None
    assert learning.baseline_metric is None
    assert "Only 0 prior run" in learning.reason


def test_enough_prior_runs_yields_keep_when_metric_meets_baseline(store):
    strategy = Strategy(project_id="p1", name="default", version=1, weights={})
    # Seed 5 prior runs at metric=1.0 (the minimum needed for a verdict).
    for _ in range(5):
        record_run_learning(store, "p1", strategy, Job(project_id="p1"), metric=1.0)

    learning = record_run_learning(store, "p1", strategy, Job(project_id="p1"), metric=1.0)

    assert learning.kept is True
    assert learning.baseline_metric == 1.0


def test_enough_prior_runs_yields_revert_when_metric_falls_short(store):
    strategy = Strategy(project_id="p1", name="default", version=1, weights={})
    for _ in range(5):
        record_run_learning(store, "p1", strategy, Job(project_id="p1"), metric=1.0)

    learning = record_run_learning(store, "p1", strategy, Job(project_id="p1"), metric=0.0)

    assert learning.kept is False
