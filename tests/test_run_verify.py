"""Phase 20: direct unit coverage of orchestrator/run_verify.py, extracted
from cli/main.py so the Dashboard could reuse it -- covered indirectly via
tests/test_cli.py already, this tests the function itself independent of
the CLI/Typer layer.
"""
import pytest

from veriforge.domain.enums import Verdict
from veriforge.events.bus import EventBus
from veriforge.llm.provider import LLMProvider, LLMUnavailableError
from veriforge.orchestrator.run_verify import VerifyParams, run_verify


class NullLLM(LLMProvider):
    def generate(self, prompt, *, system=None):
        raise LLMUnavailableError("no LLM in this test")

    def is_available(self):
        return False

    @property
    def model_name(self):
        return "null"


def test_run_verify_requires_at_least_one_target(store):
    bus = EventBus(store)
    with pytest.raises(ValueError, match="At least one"):
        run_verify(VerifyParams(), store=store, bus=bus, llm=NullLLM())


def test_run_verify_against_a_real_local_app_produces_a_real_finding(store, tmp_path, example_app_server):
    bus = EventBus(store)
    params = VerifyParams(
        repo="examples/example-app", requirements="examples/requirements.md",
        url=example_app_server + "/ui", workdir=str(tmp_path),
    )

    outcome = run_verify(params, store=store, bus=bus, llm=NullLLM())

    assert outcome.cloned_note is None  # a local path is never cloned
    assert outcome.summary.verdict == Verdict.FAIL.value
    assert outcome.summary.finding_count == 1
    assert outcome.project.name == "example-app"


def test_run_verify_reuses_the_same_project_across_two_calls(store, tmp_path, example_app_server):
    bus = EventBus(store)
    params = VerifyParams(
        repo="examples/example-app", requirements="examples/requirements.md",
        url=example_app_server + "/ui", workdir=str(tmp_path),
    )

    first = run_verify(params, store=store, bus=bus, llm=NullLLM())
    second = run_verify(params, store=store, bus=bus, llm=NullLLM())

    assert first.project.id == second.project.id
    assert first.job.id != second.job.id
