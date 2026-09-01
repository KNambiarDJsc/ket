from veriforge.domain.models import Job


def test_save_and_get_job(store):
    job = Job(project_id="proj_1")
    store.jobs.save(job, job_id=job.id, project_id="proj_1")

    fetched = store.jobs.get(job.id)
    assert fetched is not None
    assert fetched.id == job.id
    assert fetched.project_id == "proj_1"


def test_update_persists_new_payload(store):
    job = Job(project_id="proj_1")
    store.jobs.save(job, job_id=job.id, project_id="proj_1")

    from veriforge.domain.enums import JobState
    job.state = JobState.REQUIREMENTS_RECEIVED
    store.jobs.save(job, job_id=job.id, project_id="proj_1")

    fetched = store.jobs.get(job.id)
    assert fetched.state == JobState.REQUIREMENTS_RECEIVED


def test_list_by_project(store):
    job1 = Job(project_id="proj_1")
    job2 = Job(project_id="proj_1")
    job3 = Job(project_id="proj_2")
    for j in (job1, job2, job3):
        store.jobs.save(j, job_id=j.id, project_id=j.project_id)

    proj1_jobs = store.jobs.list_by_project("proj_1")
    assert {j.id for j in proj1_jobs} == {job1.id, job2.id}
