import pytest

from app.runner import run_validation

GOOD = {"calc.py": "def add(a, b):\n    return a + b\n"}
TEST_OK = {"test_calc.py": "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"}
TEST_BAD = {"test_calc.py": "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 4\n"}


def go(files, changed=None, run_tests=True, timeout=30):
    changed = changed if changed is not None else [f for f in files if f.endswith(".py")]
    return run_validation(files, changed, timeout=timeout, run_tests=run_tests)


def test_syntax_error_fails():
    r = go({"bad.py": "def f(:\n"})
    assert r.ran and r.passed is False
    assert "py_compile: FAILED" in r.output and "bad.py" in r.output


def test_compile_and_pytest_pass():
    r = go({**GOOD, **TEST_OK})
    assert r.passed is True and "pytest: OK" in r.output


def test_failing_test_fails():
    r = go({**GOOD, **TEST_BAD})
    assert r.passed is False and "pytest: FAILED" in r.output


def test_pytest_off_by_default_path():
    r = go({**GOOD, **TEST_BAD}, run_tests=False)
    assert r.passed is True and "ENABLE_TEST_EXECUTION is off" in r.output


def test_non_python_pr_not_run():
    r = go({"README.md": "hi"}, changed=["README.md"])
    assert r.ran is False


def test_timeout():
    slow = {"test_slow.py": "import time\n\ndef test_x():\n    time.sleep(30)\n"}
    r = go(slow, timeout=2)
    assert r.passed is False and "timed out" in r.output


@pytest.mark.parametrize("bad", ["../evil.py", "/abs/evil.py", "a/../../evil.py", "C:/evil.py"])
def test_path_traversal_rejected(bad):
    with pytest.raises(ValueError, match="Unsafe"):
        go({bad: "x = 1\n"}, changed=[bad])


def test_secrets_not_in_subprocess_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-secret")
    t = {"test_env.py": "import os\n\ndef test_env():\n    assert not any('secret' in v for v in os.environ.values())\n"}
    assert go(t).passed is True


def test_shell_metacharacters_in_filename_are_inert(tmp_path):
    name = "a; echo pwned.py"
    r = go({name: "x = 1\n"}, changed=[name])
    assert r.passed is True


def test_src_layout_imports_pr_code_not_installed_package():
    files = {
        "src/mypkg/__init__.py": "VALUE = 42\n",
        "tests/test_pkg.py": "from mypkg import VALUE\n\ndef test_v():\n    assert VALUE == 42\n",
    }
    r = go(files, changed=["src/mypkg/__init__.py"])
    assert r.passed is True, r.output
