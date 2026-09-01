from veriforge.cartography.filesystem import scan_repository


def test_scan_nonexistent_repo_reports_not_exists(tmp_path):
    result = scan_repository(tmp_path / "does-not-exist")
    assert result["exists"] is False


def test_scan_detects_python_marker(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n")

    result = scan_repository(tmp_path)
    assert result["exists"] is True
    assert "python" in result["detected_languages"]
    assert result["file_count"] == 2
