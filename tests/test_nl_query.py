from veriforge.dashboard.nl_query import answer_question
from veriforge.domain.enums import FailureCategory, RequirementKind, Verdict
from veriforge.domain.models import Finding, Job, Project, Requirement, Test, TestRun
from veriforge.llm.provider import LLMProvider, LLMUnavailableError, NullLLMProvider


class FakeLLM(LLMProvider):
    def __init__(self, response: str):
        self._response = response

    def generate(self, prompt, *, system=None):
        self._last_prompt = prompt
        return self._response

    def is_available(self):
        return True

    @property
    def model_name(self):
        return "fake"


def _seed_one_job_with_a_finding(store):
    project = Project(name="demo-app", repo_path="examples/example-app")
    store.projects.save(project, project_id=project.id)
    job = Job(project_id=project.id, state="COMPLETED")
    store.jobs.save(job, job_id=job.id, project_id=project.id)
    requirement = Requirement(project_id=project.id, source_text="Members cannot delete projects.", kind=RequirementKind.NEGATIVE)
    store.requirements.save(requirement, job_id=job.id, project_id=project.id)
    finding = Finding(
        project_id=project.id, summary="VIOLATED: members can delete projects",
        category=FailureCategory.SECURITY_FINDING, confidence=0.9,
    )
    store.findings.save(finding, job_id=job.id, project_id=project.id)
    test = Test(project_id=project.id, name=requirement.source_text)
    store.tests.save(test, job_id=job.id, project_id=project.id)
    test_run = TestRun(test_id=test.id, verdict=Verdict.FAIL)
    store.test_runs.save(test_run, job_id=job.id, project_id=project.id)
    return job


def test_answer_question_degrades_to_raw_data_when_llm_unavailable(store):
    _seed_one_job_with_a_finding(store)

    result = answer_question(store, NullLLMProvider(), "any security bugs?")

    assert "No LLM is configured" in result.answer
    assert "SECURITY_FINDING" in result.answer
    assert len(result.matched_job_ids) == 1


def test_answer_question_with_no_jobs_says_so_plainly(store):
    result = answer_question(store, NullLLMProvider(), "any bugs?")
    assert "No jobs have been run yet" in result.answer
    assert result.matched_job_ids == []


def test_answer_question_uses_the_llm_and_includes_real_job_data_in_the_prompt(store):
    job = _seed_one_job_with_a_finding(store)
    llm = FakeLLM("Yes, one SECURITY_FINDING was confirmed.")

    result = answer_question(store, llm, "any security bugs?")

    assert result.answer == "Yes, one SECURITY_FINDING was confirmed."
    assert job.id in result.matched_job_ids
    assert job.id in llm._last_prompt  # the real job history was actually included, not a stub
    assert "SECURITY_FINDING" in llm._last_prompt


def test_answer_question_never_calls_llm_when_unavailable(store):
    class RaisingLLM(LLMProvider):
        def generate(self, prompt, *, system=None):
            raise AssertionError("should not be called when there's no data")

        def is_available(self):
            return False

        @property
        def model_name(self):
            return "raising"

    result = answer_question(store, RaisingLLM(), "anything?")
    assert "No jobs have been run yet" in result.answer
