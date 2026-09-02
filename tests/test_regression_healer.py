from veriforge.regression.healer import heal_regression_test

_TEMPLATE = '''BASE_URL = os.environ.get("VERIFORGE_BASE_URL", "{base_url}")

def test_regression_req_abc123():
    ...
    assert result.oracle_verdict.verdict == Verdict.PASS, (
        f"Regression: {{_REQUIREMENT.source_text!r}} is violated again -- {{result.oracle_verdict.reasoning}}"
    )
'''


def test_heal_no_drift_returns_unhealed():
    source = _TEMPLATE.format(base_url="http://localhost:8000")
    result = heal_regression_test(source, source)
    assert result.healed is False
    assert result.reason == "no drift detected"
    assert result.diff == ""


def test_heal_applies_base_url_drift():
    old_source = _TEMPLATE.format(base_url="http://localhost:8000")
    new_source = _TEMPLATE.format(base_url="http://localhost:9000")

    result = heal_regression_test(old_source, new_source)

    assert result.healed is True
    assert result.new_source == new_source
    assert "8000" in result.diff and "9000" in result.diff


def test_heal_refuses_when_assertion_line_would_change():
    old_source = _TEMPLATE.format(base_url="http://localhost:8000")
    new_source = old_source.replace("Verdict.PASS", "Verdict.FAIL")

    result = heal_regression_test(old_source, new_source)

    assert result.healed is False
    assert result.new_source is None
    assert "refused" in result.reason
    assert result.diff  # still inspectable, even though refused


def test_heal_refuses_but_still_produces_a_diff_when_both_drift_and_assertion_change():
    old_source = _TEMPLATE.format(base_url="http://localhost:8000")
    new_source = _TEMPLATE.format(base_url="http://localhost:9000").replace("Verdict.PASS", "Verdict.FAIL")

    result = heal_regression_test(old_source, new_source)

    assert result.healed is False
    assert "8000" in result.diff and "9000" in result.diff
