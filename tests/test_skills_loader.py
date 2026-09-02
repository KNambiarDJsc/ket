import pytest

from veriforge.skills.loader import discover_skills, parse_skill_file


def write_skill(tmp_path, folder, content):
    skill_dir = tmp_path / folder
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_skill_file_extracts_frontmatter_and_body(tmp_path):
    path = write_skill(
        tmp_path, "my-skill",
        "---\nname: my-skill\ndescription: Does a thing.\nversion: 2\n---\n\n# Body\n\nSome procedure.\n",
    )
    skill = parse_skill_file(path)
    assert skill.name == "my-skill"
    assert skill.description == "Does a thing."
    assert skill.version == 2
    assert skill.body == "# Body\n\nSome procedure."
    assert skill.source_path == str(path)


def test_parse_skill_file_defaults_version_to_1(tmp_path):
    path = write_skill(tmp_path, "my-skill", "---\nname: my-skill\ndescription: x\n---\nbody\n")
    skill = parse_skill_file(path)
    assert skill.version == 1


def test_parse_skill_file_requires_frontmatter(tmp_path):
    path = write_skill(tmp_path, "my-skill", "# No frontmatter here\n")
    with pytest.raises(ValueError, match="missing frontmatter"):
        parse_skill_file(path)


def test_parse_skill_file_requires_name(tmp_path):
    path = write_skill(tmp_path, "my-skill", "---\ndescription: x\n---\nbody\n")
    with pytest.raises(ValueError, match="required 'name'"):
        parse_skill_file(path)


def test_parse_skill_file_rejects_non_integer_version(tmp_path):
    path = write_skill(tmp_path, "my-skill", "---\nname: x\nversion: not-a-number\n---\nbody\n")
    with pytest.raises(ValueError, match="must be an integer"):
        parse_skill_file(path)


def test_discover_skills_finds_all_and_sorts_by_path(tmp_path):
    write_skill(tmp_path, "zeta", "---\nname: zeta\ndescription: z\n---\nbody\n")
    write_skill(tmp_path, "alpha", "---\nname: alpha\ndescription: a\n---\nbody\n")

    skills = discover_skills(tmp_path)
    assert [s.name for s in skills] == ["alpha", "zeta"]


def test_discover_skills_skips_malformed_without_crashing(tmp_path):
    write_skill(tmp_path, "good", "---\nname: good\ndescription: g\n---\nbody\n")
    write_skill(tmp_path, "bad", "no frontmatter at all\n")

    skills = discover_skills(tmp_path)
    assert [s.name for s in skills] == ["good"]


def test_discover_skills_returns_empty_list_for_missing_directory(tmp_path):
    assert discover_skills(tmp_path / "does-not-exist") == []


def test_real_bundled_skills_all_parse():
    # The three Phase 12 skills actually shipped in this repo's skills/ dir
    # must themselves be valid -- catches a real authoring typo, not just
    # exercises the parser against synthetic fixtures.
    from pathlib import Path
    repo_skills_dir = Path(__file__).resolve().parents[1] / "skills"
    skills = discover_skills(repo_skills_dir)
    names = {s.name for s in skills}
    assert {"authorization-testing", "data-integrity-testing", "api-contract-testing"} <= names
    for skill in skills:
        assert skill.description
        assert skill.body
