"""Compiler/test tool.

Runs a FIXED set of validation steps. Nothing here accepts a command from an LLM or from
the PR: argv lists are built in this file only, and subprocess is never used with a shell.

SECURITY: py_compile only parses code. pytest EXECUTES the PR's code on this machine; there
is no real sandbox (only a temp dir, a scrubbed environment and a timeout), so it is gated
behind ENABLE_TEST_EXECUTION. Use a container/VM for untrusted repositories.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.state import ExecutionResult

MAX_OUTPUT_CHARS = 8_000
COMPILE_BATCH = 50
_ENV_KEEP = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "LANG", "LC_ALL")


def _scrubbed_env(home: Path) -> dict[str, str]:
    """Pass through only what Python needs: no API keys, tokens or PYTHONPATH."""
    env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
    env.update(
        HOME=str(home), USERPROFILE=str(home), TEMP=str(home), TMP=str(home),
        PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
    )
    return env


def validate_rel_path(rel: str) -> None:
    """Raise ValueError unless `rel` is a plain relative path with no traversal."""
    posix, win = PurePosixPath(rel), PureWindowsPath(rel)
    if (
        not rel or posix.is_absolute() or win.is_absolute() or win.drive
        or ".." in posix.parts or ".." in win.parts
    ):
        raise ValueError(f"Unsafe file path: {rel!r}")


def _materialize(files: dict[str, str], root: Path) -> None:
    root = root.resolve()
    for rel, content in files.items():
        validate_rel_path(rel)
        dest = (root / rel).resolve()
        if root not in dest.parents:
            raise ValueError(f"Unsafe file path: {rel!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8", newline="")


def _run(argv: list[str], cwd: Path, env: dict[str, str], timeout: int) -> tuple[int | None, str]:
    """Run argv (never a shell). Returns (returncode or None on timeout, combined output)."""
    try:
        p = subprocess.run(
            argv, cwd=cwd, env=env, shell=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
        )
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout}s"


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "\n[...truncated...]"


def is_test_file(rel: str) -> bool:
    name = PurePosixPath(rel).name
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def run_validation(
    files: dict[str, str], changed_files: list[str], *, timeout: int, run_tests: bool
) -> ExecutionResult:
    changed_py = [f for f in changed_files if f.endswith(".py") and f in files]
    if not changed_py:
        return ExecutionResult(ran=False, output="No Python files changed; nothing to validate.")

    compile_out = test_out = ""
    passed = True
    with tempfile.TemporaryDirectory(prefix="review_") as tmp:
        root = Path(tmp)
        _materialize(files, root)
        env = _scrubbed_env(root)

        # 1. Syntax check (parses only; does not execute the code).
        failures = []
        for i in range(0, len(changed_py), COMPILE_BATCH):
            batch = changed_py[i : i + COMPILE_BATCH]
            code, out = _run([sys.executable, "-m", "py_compile", *batch], root, env, timeout)
            if code != 0:
                failures.append(out)
        if failures:
            passed = False
            compile_out = "py_compile: FAILED\n" + "\n".join(failures)
        else:
            compile_out = f"py_compile: OK ({len(changed_py)} files)"

        # 2. pytest, if enabled, installed here, and the repo has tests.
        has_tests = any(is_test_file(f) for f in files)
        if not has_tests:
            test_out = "pytest: skipped (no test files)"
        elif not run_tests:
            test_out = "pytest: skipped (ENABLE_TEST_EXECUTION is off)"
        elif importlib.util.find_spec("pytest") is None:
            test_out = "pytest: skipped (pytest not installed)"
        elif not passed:
            test_out = "pytest: skipped (syntax errors)"
        else:
            # Make the PR's own packages importable (flat or src/ layout) ahead of anything installed.
            paths = [str(root)] + ([str(root / "src")] if any(f.startswith("src/") for f in files) else [])
            env = {**env, "PYTHONPATH": os.pathsep.join(paths)}
            argv = [sys.executable, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider"]
            code, out = _run(argv, root, env, timeout)
            if code == 0:
                test_out = "pytest: OK\n" + out
            else:
                passed = False
                test_out = f"pytest: FAILED (exit {code})\n" + out

    compile_out, test_out = _clip(compile_out), _clip(test_out)
    return ExecutionResult(
        ran=True, passed=passed, compile_output=compile_out, test_output=test_out,
        output=f"{compile_out}\n{test_out}",
    )
