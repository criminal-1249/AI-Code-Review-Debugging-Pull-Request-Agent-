"""Read-only GitHub client: fetches everything the workflow needs about a PR."""
import io
import re
import tarfile # acess github actions
from pathlib import PurePosixPath ## for secure path fetching

import httpx # comminucate with github api

from app.config import get_settings
from app.state import PullRequest

MAX_DIFF_CHARS = 200_000 # max allowed changes
MAX_CHANGED_FILES = 300 
MAX_FILE_BYTES = 200_000  # for each file 
MAX_TOTAL_BYTES = 3_000_000 #This is the total size limit across all downloaded files.
MAX_TARBALL_BYTES = 50_000_000  #A tarball is an archive containing repository files.


RELEVANT_SUFFIXES = {".py"} # analyses only py files
## we cant ignore these files
RELEVANT_NAMES = {
    "pyproject.toml", "pytest.ini", "setup.cfg", "setup.py", "tox.ini",
    "requirements.txt", "conftest.py",
}
#ignore these 
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox"}


class GitHubError(RuntimeError):
    pass

# owner/repo#123 => (owner/repo, 123)
def parse_pr_ref(ref: str) -> tuple[str, int]:
    ref = ref.strip()
    m = re.fullmatch(r"https?://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)(?:[/?#].*)?", ref) or re.fullmatch(
        r"([\w.-]+/[\w.-]+)#(\d+)", ref
    )
    if not m:
        raise ValueError(f"Not a PR reference: {ref!r} (use owner/repo#123 or a PR URL)")
    
    return m.group(1), int(m.group(2))


class GitHubClient:
    def __init__(self, token: str = "", base_url: str = "https://api.github.com",
                 transport: httpx.BaseTransport | None = None, timeout: float = 30.0):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-code-review-agent",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        # httpx drops Authorization on cross-origin redirects (tarball -> codeload).
        self._http = httpx.Client(
            base_url=base_url, headers=headers, timeout=timeout,
            transport=transport, follow_redirects=True,
        )

    @classmethod
    def from_settings(cls) -> "GitHubClient":
        s = get_settings()
        return cls(token=s.github_token, base_url=s.github_api_url)

    def _get(self, path: str, **kw) -> httpx.Response:
        try:
            r = self._http.get(path, **kw)
        except httpx.HTTPError as e:
            raise GitHubError(f"GitHub request failed: {e}") from e
        if r.status_code >= 400:
            hint = " (rate limited? set GITHUB_TOKEN)" if r.status_code in (403, 429) else ""
            raise GitHubError(f"GitHub {r.status_code} for {path}{hint}: {r.text[:200]}")
        return r

    def fetch_pull_request(self, repo: str, number: int) -> PullRequest:
        meta = self._get(f"/repos/{repo}/pulls/{number}").json()
        diff = self._get(
            f"/repos/{repo}/pulls/{number}", headers={"Accept": "application/vnd.github.v3.diff"}
        ).text[:MAX_DIFF_CHARS]

        changed: list[str] = []
        page = 1
        while len(changed) < MAX_CHANGED_FILES:
            batch = self._get(
                f"/repos/{repo}/pulls/{number}/files", params={"per_page": 100, "page": page}
            ).json()
            changed += [f["filename"] for f in batch if f.get("status") != "removed"]
            if len(batch) < 100:
                break
            page += 1
        changed = changed[:MAX_CHANGED_FILES]

        head = meta["head"]
        head_repo = (head.get("repo") or {}).get("full_name") or repo  # fork may be deleted
        sha = head["sha"]
        files = self._snapshot(head_repo, sha, set(changed))

        return PullRequest(
            repo=repo, number=number, title=meta.get("title") or "",
            description=meta.get("body") or "", head_sha=sha, diff=diff,
            changed_files=changed, files=files,
        )

    def _snapshot(self, repo: str, sha: str, changed: set[str]) -> dict[str, str]:
        """Changed files + relevant Python/config files at `sha`, from one tarball download."""
        buf = io.BytesIO()
        try:
            with self._http.stream("GET", f"/repos/{repo}/tarball/{sha}") as r:
                if r.status_code >= 400:
                    raise GitHubError(f"GitHub {r.status_code} downloading tarball for {repo}@{sha[:7]}")
                for chunk in r.iter_bytes():
                    buf.write(chunk)
                    if buf.tell() > MAX_TARBALL_BYTES:
                        raise GitHubError("Repository tarball too large")
        except httpx.HTTPError as e:
            raise GitHubError(f"GitHub request failed: {e}") from e
        buf.seek(0)
        return extract_relevant(buf, changed)


def extract_relevant(fileobj, changed: set[str]) -> dict[str, str]:
    files: dict[str, str] = {}
    total = 0
    with tarfile.open(fileobj=fileobj, mode="r:gz") as tar:
        for m in tar:
            if not m.isfile() or m.size > MAX_FILE_BYTES:
                continue
            parts = PurePosixPath(m.name).parts[1:]  # strip the "<owner>-<repo>-<sha>/" prefix
            if not parts or ".." in parts or PurePosixPath(m.name).is_absolute():
                continue
            if any(p in SKIP_DIRS for p in parts):
                continue
            rel = "/".join(parts)
            is_changed = rel in changed
            is_relevant = parts[-1] in RELEVANT_NAMES or PurePosixPath(rel).suffix in RELEVANT_SUFFIXES
            if not (is_changed or is_relevant):
                continue
            if not is_changed and total + m.size > MAX_TOTAL_BYTES:
                continue
            fh = tar.extractfile(m)
            if fh is None:
                continue
            data = fh.read()
            try:
                files[rel] = data.decode("utf-8")
            except UnicodeDecodeError:
                continue  # binary
            total += len(data)
    return files
