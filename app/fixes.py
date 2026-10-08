"""Validate and apply a FixOutput to a PullRequest. Pure code, no LLM."""
from pathlib import Path

from app.runner import is_test_file, validate_rel_path
from app.state import FixOutput, PullRequest

MAX_EDITS = 10
MAX_FILE_CHARS = 200_000

#"Is this fix allowed, and what would the updated PR look like?"
def apply_fix(pr: PullRequest, fix: FixOutput) -> tuple[PullRequest, list[str], dict[str, str]]:
    """Return (updated PR, applied paths, {rejected path: reason}).

    An edit is allowed only if it targets a file the PR already changed, or a test file
    (existing or new). Anything else is rejected, so the fixer cannot touch unrelated files.
    """
    files = dict(pr.files)
    changed = list(pr.changed_files)
    applied: list[str] = []
    rejected: dict[str, str] = {}

    for i, edit in enumerate(fix.edits):
        path = edit.path.replace("\\", "/")
        if i >= MAX_EDITS:
            rejected[path] = f"more than {MAX_EDITS} edits"
            continue
        try:
            validate_rel_path(path)
        except ValueError:
            rejected[edit.path] = "unsafe path"
            continue
        if path not in pr.changed_files and not is_test_file(path):
            rejected[path] = "not a file changed by this PR or a test file"
            continue
        if len(edit.content) > MAX_FILE_CHARS:
            rejected[path] = "file too large"
            continue
        if files.get(path) == edit.content:
            rejected[path] = "no change"
            continue
        files[path] = edit.content
        if path not in changed:
            changed.append(path)
        applied.append(path)

    return pr.model_copy(update={"files": files, "changed_files": changed}), applied, rejected


#Actually write the approved fix
def write_applied_fixes(pr: PullRequest, applied: list[str], workspace_dir: str | Path) -> list[str]:
    """Write the already-validated `applied` files of `pr` under `workspace_dir`.

    Only writes (creating parent dirs as needed); never deletes, commits or pushes.
    Raises ValueError for an unsafe path or one that resolves outside the workspace.
    """
    root = Path(workspace_dir).resolve()
    if not root.is_dir():
        raise ValueError(f"Workspace directory does not exist: {root}")
    targets: list[tuple[str, Path]] = []
    for rel in applied:  # resolve everything first so a bad path writes nothing
        validate_rel_path(rel)
        dest = (root / rel).resolve()
        if not dest.is_relative_to(root) or dest == root:
            raise ValueError(f"Path escapes workspace: {rel!r}")
        targets.append((rel, dest))
    for rel, dest in targets:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(pr.files[rel], encoding="utf-8", newline="")
    return [rel for rel, _ in targets]
