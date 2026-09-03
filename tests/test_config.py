import os

from veriforge.config import load_dotenv_if_present


def test_loads_simple_key_value_pairs(tmp_path, monkeypatch):
    monkeypatch.delenv("VERIFORGE_TEST_FOO", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("VERIFORGE_TEST_FOO=bar\n", encoding="utf-8")

    load_dotenv_if_present(env_file)

    assert os.environ["VERIFORGE_TEST_FOO"] == "bar"
    del os.environ["VERIFORGE_TEST_FOO"]


def test_ignores_comments_and_blank_lines(tmp_path, monkeypatch):
    monkeypatch.delenv("VERIFORGE_TEST_BAZ", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("# a comment\n\nVERIFORGE_TEST_BAZ=qux\n", encoding="utf-8")

    load_dotenv_if_present(env_file)

    assert os.environ["VERIFORGE_TEST_BAZ"] == "qux"
    del os.environ["VERIFORGE_TEST_BAZ"]


def test_strips_surrounding_quotes(tmp_path, monkeypatch):
    monkeypatch.delenv("VERIFORGE_TEST_QUOTED", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text('VERIFORGE_TEST_QUOTED="hello world"\n', encoding="utf-8")

    load_dotenv_if_present(env_file)

    assert os.environ["VERIFORGE_TEST_QUOTED"] == "hello world"
    del os.environ["VERIFORGE_TEST_QUOTED"]


def test_real_environment_variable_wins_over_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIFORGE_TEST_PRECEDENCE", "from_shell")
    env_file = tmp_path / ".env"
    env_file.write_text("VERIFORGE_TEST_PRECEDENCE=from_dotenv\n", encoding="utf-8")

    load_dotenv_if_present(env_file)

    assert os.environ["VERIFORGE_TEST_PRECEDENCE"] == "from_shell"


def test_missing_file_is_a_silent_noop(tmp_path):
    load_dotenv_if_present(tmp_path / "does-not-exist.env")  # must not raise
