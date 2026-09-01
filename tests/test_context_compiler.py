from veriforge.context.compiler import ContextCompiler
from veriforge.domain.enums import RiskLevel
from veriforge.domain.models import Requirement, Unknown, WorldModel
from veriforge.harness.tools import ToolRegistry, ToolSpec


def test_critical_requirements_ranked_first():
    world_model = WorldModel(
        project_id="proj_1",
        requirements=[
            Requirement(project_id="proj_1", source_text="Nice to have feature", critical=False),
            Requirement(project_id="proj_1", source_text="Members cannot delete projects", critical=True),
        ],
    )

    bundle = ContextCompiler().compile(world_model, goal="verify authorization")

    assert bundle.relevant_requirements[0].critical is True


def test_max_requirements_truncates_and_counts_omitted():
    world_model = WorldModel(
        project_id="proj_1",
        requirements=[
            Requirement(project_id="proj_1", source_text=f"requirement {i}") for i in range(10)
        ],
    )

    bundle = ContextCompiler().compile(world_model, goal="verify everything", max_requirements=3)

    assert len(bundle.relevant_requirements) == 3
    assert bundle.omitted_requirement_count == 7


def test_tool_registry_included_as_name_and_description_only():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="filesystem.scan_repository", description="scans a repo", risk=RiskLevel.READ),
        handler=lambda: None,
    )
    world_model = WorldModel(project_id="proj_1")

    bundle = ContextCompiler().compile(world_model, goal="analyze repo", tool_registry=registry)

    assert bundle.available_tools[0].name == "filesystem.scan_repository"
    assert bundle.available_tools[0].risk == "READ"


def test_render_prompt_is_compact_and_readable():
    world_model = WorldModel(
        project_id="proj_1",
        requirements=[Requirement(project_id="proj_1", source_text="Members cannot delete projects", critical=True)],
        unknowns=[Unknown(project_id="proj_1", question="Can a member delete a project anyway?")],
    )

    bundle = ContextCompiler().compile(world_model, goal="verify authorization")
    rendered = bundle.render_prompt()

    assert "GOAL: verify authorization" in rendered
    assert "Members cannot delete projects" in rendered
    assert "Can a member delete a project anyway?" in rendered
