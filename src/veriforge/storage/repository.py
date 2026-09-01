from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from veriforge.domain.models import (
    Artifact,
    Evidence,
    Event,
    Experiment,
    Finding,
    Job,
    Learning,
    LoopState,
    Observation,
    Project,
    Requirement,
    Strategy,
    Test,
    TestRun,
    WorldModel,
)
from veriforge.storage.schema import Record

M = TypeVar("M", bound=BaseModel)


class TypedRepository(Generic[M]):
    """CRUD over the generic `records` table for one Pydantic model type."""

    def __init__(self, session: Session, type_name: str, model_cls: type[M]):
        self._session = session
        self._type_name = type_name
        self._model_cls = model_cls

    def save(self, obj: M, *, job_id: str | None = None, project_id: str | None = None) -> M:
        row = self._session.get(Record, (self._type_name, obj.id))
        payload = obj.model_dump(mode="json")
        if row is None:
            row = Record(
                type=self._type_name,
                id=obj.id,
                job_id=job_id,
                project_id=project_id,
                payload=payload,
            )
            self._session.add(row)
        else:
            row.payload = payload
            if job_id is not None:
                row.job_id = job_id
            if project_id is not None:
                row.project_id = project_id
        self._session.commit()
        return obj

    def get(self, id_: str) -> M | None:
        row = self._session.get(Record, (self._type_name, id_))
        if row is None:
            return None
        return self._model_cls.model_validate(row.payload)

    def list_by_job(self, job_id: str) -> list[M]:
        stmt = select(Record).where(Record.type == self._type_name, Record.job_id == job_id)
        rows = self._session.execute(stmt).scalars().all()
        return [self._model_cls.model_validate(r.payload) for r in rows]

    def list_by_project(self, project_id: str) -> list[M]:
        stmt = select(Record).where(
            Record.type == self._type_name, Record.project_id == project_id
        )
        rows = self._session.execute(stmt).scalars().all()
        return [self._model_cls.model_validate(r.payload) for r in rows]

    def list_all(self) -> list[M]:
        stmt = select(Record).where(Record.type == self._type_name)
        rows = self._session.execute(stmt).scalars().all()
        return [self._model_cls.model_validate(r.payload) for r in rows]


class Store:
    """Aggregates typed repositories. One Store per Session/request/job run."""

    def __init__(self, session: Session):
        self.session = session
        self.jobs = TypedRepository[Job](session, "job", Job)
        self.events = TypedRepository[Event](session, "event", Event)
        self.artifacts = TypedRepository[Artifact](session, "artifact", Artifact)
        self.requirements = TypedRepository[Requirement](session, "requirement", Requirement)
        self.world_models = TypedRepository[WorldModel](session, "world_model", WorldModel)
        self.learnings = TypedRepository[Learning](session, "learning", Learning)
        self.loop_states = TypedRepository[LoopState](session, "loop_state", LoopState)
        self.experiments = TypedRepository[Experiment](session, "experiment", Experiment)
        self.tests = TypedRepository[Test](session, "test", Test)
        self.test_runs = TypedRepository[TestRun](session, "test_run", TestRun)
        self.observations = TypedRepository[Observation](session, "observation", Observation)
        self.findings = TypedRepository[Finding](session, "finding", Finding)
        self.evidence = TypedRepository[Evidence](session, "evidence", Evidence)
        self.projects = TypedRepository[Project](session, "project", Project)
        self.strategies = TypedRepository[Strategy](session, "strategy", Strategy)

    def close(self) -> None:
        self.session.close()
