from veriforge.skills.loader import Skill
from veriforge.skills.retriever import SkillRetriever


def make_skill(name, description, version=1):
    return Skill(name=name, description=description, version=version, body="body", source_path=f"{name}/SKILL.md")


def test_retrieve_ranks_by_keyword_overlap():
    skills = [
        make_skill("unrelated", "Does something about unrelated topics entirely."),
        make_skill("authz", "Verifies authorization requirements about actors and permissions."),
    ]
    retriever = SkillRetriever(skills)

    results = retriever.retrieve("Verify authorization requirements before release")

    assert results[0].skill.name == "authz"
    assert results[0].score > 0


def test_retrieve_excludes_zero_overlap_skills():
    skills = [make_skill("unrelated", "Completely different topic with no shared words.")]
    retriever = SkillRetriever(skills)

    results = retriever.retrieve("Verify authorization requirements")

    assert results == []


def test_retrieve_respects_max_skills():
    skills = [
        make_skill("a", "Verify requirements about widgets."),
        make_skill("b", "Verify requirements about gadgets."),
        make_skill("c", "Verify requirements about gizmos."),
    ]
    retriever = SkillRetriever(skills)

    results = retriever.retrieve("Verify all requirements", max_skills=2)

    assert len(results) == 2


def test_retrieve_returns_full_skill_including_body():
    skills = [make_skill("authz", "Verify authorization requirements.")]
    retriever = SkillRetriever(skills)

    results = retriever.retrieve("Verify authorization requirements")

    assert results[0].skill.body == "body"
