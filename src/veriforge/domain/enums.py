from enum import Enum


class JobState(str, Enum):
    JOB_CREATED = "JOB_CREATED"
    REQUIREMENTS_RECEIVED = "REQUIREMENTS_RECEIVED"
    JOB_INITIALIZED = "JOB_INITIALIZED"
    ANALYSIS_PENDING = "ANALYSIS_PENDING"
    WORLD_MODEL_PENDING = "WORLD_MODEL_PENDING"
    TESTING_PENDING = "TESTING_PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


# Explicit allowed transitions. The state machine is the single source of
# truth for what can follow what — nothing else in the codebase should
# hardcode a transition.
JOB_STATE_TRANSITIONS: dict[JobState, tuple[JobState, ...]] = {
    JobState.JOB_CREATED: (JobState.REQUIREMENTS_RECEIVED, JobState.FAILED),
    JobState.REQUIREMENTS_RECEIVED: (JobState.JOB_INITIALIZED, JobState.FAILED),
    JobState.JOB_INITIALIZED: (JobState.ANALYSIS_PENDING, JobState.FAILED),
    JobState.ANALYSIS_PENDING: (JobState.WORLD_MODEL_PENDING, JobState.FAILED),
    JobState.WORLD_MODEL_PENDING: (JobState.TESTING_PENDING, JobState.FAILED),
    JobState.TESTING_PENDING: (JobState.COMPLETED, JobState.BLOCKED, JobState.FAILED),
    JobState.COMPLETED: (),
    JobState.FAILED: (),
    JobState.BLOCKED: (JobState.TESTING_PENDING, JobState.FAILED),
}


class RiskLevel(str, Enum):
    READ = "READ"
    LOW_RISK = "LOW_RISK"
    MEDIUM_RISK = "MEDIUM_RISK"
    HIGH_RISK = "HIGH_RISK"
    DESTRUCTIVE = "DESTRUCTIVE"
    BLOCKED = "BLOCKED"


class RequirementKind(str, Enum):
    FUNCTIONAL = "FUNCTIONAL"
    NEGATIVE = "NEGATIVE"
    AUTHORIZATION = "AUTHORIZATION"
    TEMPORAL = "TEMPORAL"
    ORDERING = "ORDERING"
    DATA_INVARIANT = "DATA_INVARIANT"
    SECURITY = "SECURITY"
    PERFORMANCE = "PERFORMANCE"
    UNSPECIFIED = "UNSPECIFIED"


class TestStatus(str, Enum):
    __test__ = False  # tell pytest this isn't a test class despite the name

    HYPOTHESIS = "HYPOTHESIS"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    OBSERVED = "OBSERVED"
    VERIFIED = "VERIFIED"
    KEPT = "KEPT"
    FAILED = "FAILED"
    TRIAGED = "TRIAGED"
    REPRODUCED = "REPRODUCED"
    BUG_VERIFIED = "BUG_VERIFIED"
    HEALING = "HEALING"


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNCERTAIN = "UNCERTAIN"


class FailureCategory(str, Enum):
    APPLICATION_BUG = "APPLICATION_BUG"
    TEST_BUG = "TEST_BUG"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    FLAKINESS = "FLAKINESS"
    EXPECTED_BEHAVIOR = "EXPECTED_BEHAVIOR"
    REQUIREMENT_AMBIGUITY = "REQUIREMENT_AMBIGUITY"
    SECURITY_FINDING = "SECURITY_FINDING"
    UNKNOWN = "UNKNOWN"


class EventType(str, Enum):
    JOB_STATE_CHANGED = "JOB_STATE_CHANGED"
    REQUIREMENT_PARSED = "REQUIREMENT_PARSED"
    ARTIFACT_WRITTEN = "ARTIFACT_WRITTEN"
    ANALYSIS_COMPLETED = "ANALYSIS_COMPLETED"
    WORLD_MODEL_UPDATED = "WORLD_MODEL_UPDATED"
    AGENT_RUN_STARTED = "AGENT_RUN_STARTED"
    AGENT_RUN_FINISHED = "AGENT_RUN_FINISHED"
    LOOP_ITERATION = "LOOP_ITERATION"
    JOB_FAILED = "JOB_FAILED"
    TOOL_CALL_STARTED = "TOOL_CALL_STARTED"
    TOOL_CALL_SUCCEEDED = "TOOL_CALL_SUCCEEDED"
    TOOL_CALL_FAILED = "TOOL_CALL_FAILED"
    TOOL_CALL_DENIED = "TOOL_CALL_DENIED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


class PermissionDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"


# Fail-safe default: an unmapped risk level resolves to DENY, and
# REQUIRES_CONFIRMATION with no confirmation callback wired up also resolves
# to DENY (see harness/permissions.py). The harness enforces this — nothing
# here is advisory to the LLM.
DEFAULT_RISK_POLICY: dict[RiskLevel, PermissionDecision] = {
    RiskLevel.READ: PermissionDecision.ALLOW,
    RiskLevel.LOW_RISK: PermissionDecision.ALLOW,
    RiskLevel.MEDIUM_RISK: PermissionDecision.ALLOW,
    RiskLevel.HIGH_RISK: PermissionDecision.REQUIRES_CONFIRMATION,
    RiskLevel.DESTRUCTIVE: PermissionDecision.DENY,
    RiskLevel.BLOCKED: PermissionDecision.DENY,
}
