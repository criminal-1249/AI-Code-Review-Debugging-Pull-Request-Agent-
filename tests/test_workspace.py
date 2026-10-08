import pytest

from app.config import get_settings
from app.fixes import apply_fix, write_applied_fixes
from app.state import FileEdit, FixOutput, PullRequest

PR = PullRequest(
    repo="o/r", number=1, changed_files=["calc.py"],
    files={"calc.py": "return a - b\n", "other.py": "X = 1\n"},
)


def fix(*edits):
    return FixOutput(summary="s", edits=[FileEdit(path=p, content=c) for p, c in edits])


def test_approved_fix_is_written(tmp_path):
    new, applied, _ = apply_fix(PR, fix(("calc.py", "return a + b\n")))
    assert write_applied_fixes(new, applied, tmp_path) == ["calc.py"]
    assert (tmp_path / "calc.py").read_text() == "return a + b\n"


def test_rejected_fix_is_not_written(tmp_path):
    new, applied, rejected = apply_fix(PR, fix(("other.py", "X = 2\n"), ("../evil.py", "x")))
    assert applied == [] and len(rejected) == 2
    write_applied_fixes(new, applied, tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bad", ["../evil.py", "a/../../evil.py", "/etc/passwd", "C:/x.py", "C:\\x.py"])
def test_unsafe_paths_rejected_and_nothing_written(tmp_path, bad):
    pr = PR.model_copy(update={"files": {**PR.files, bad: "x"}})
    with pytest.raises(ValueError):
        write_applied_fixes(pr, ["calc.py", bad], tmp_path)
    assert list(tmp_path.iterdir()) == []  # all-or-nothing


def test_parent_directories_created(tmp_path):
    new, applied, _ = apply_fix(PR, fix(("tests/unit/test_calc.py", "def test_x():\n    pass\n")))
    write_applied_fixes(new, applied, tmp_path)
    assert (tmp_path / "tests" / "unit" / "test_calc.py").is_file()


def test_missing_workspace_not_created(tmp_path):
    with pytest.raises(ValueError):
        write_applied_fixes(PR, ["calc.py"], tmp_path / "nope")
    assert not (tmp_path / "nope").exists()


def test_node_writes_only_applied_files(tmp_path, monkeypatch):
    from app.nodes import apply_fix as node

    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    get_settings.cache_clear()
    state = {
        "pr": PR, "score": 5.0,
        "proposed_fix": fix(("calc.py", "return a + b\n"), ("other.py", "X = 2\n")),
    }
    out = node(state)
    assert out["fix_log"][0]["written"] == ["calc.py"]
    assert [p.name for p in tmp_path.iterdir()] == ["calc.py"]
