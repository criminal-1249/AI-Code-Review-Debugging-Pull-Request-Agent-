import io
import tarfile

import httpx
import pytest

from app.github import GitHubClient, GitHubError, parse_pr_ref


def make_tarball(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(f"o-r-abc123/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


TARBALL = make_tarball({
    "calc.py": b"def add(a, b):\n    return a + b\n",
    "util.py": b"X = 1\n",
    "README.md": b"# readme",
    "docs/guide.md": b"# guide",
    "logo.png": b"\x89PNG\xff\xfe",
    "node_modules/x/index.py": b"ignored = 1\n",
    "pytest.ini": b"[pytest]\n",
})


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/repos/o/r/pulls/7/files":
        files = [
            {"filename": "calc.py", "status": "modified"},
            {"filename": "docs/guide.md", "status": "added"},
            {"filename": "old.py", "status": "removed"},
        ]
        return httpx.Response(200, json=files if request.url.params["page"] == "1" else [])
    if path == "/repos/o/r/pulls/7":
        if "diff" in request.headers["accept"]:
            return httpx.Response(200, text="diff --git a/calc.py b/calc.py\n+x")
        return httpx.Response(200, json={
            "title": "Add calc", "body": "Adds add()",
            "head": {"sha": "abc123", "repo": {"full_name": "fork/r"}},
        })
    if path == "/repos/fork/r/tarball/abc123":
        return httpx.Response(302, headers={"location": "https://codeload.github.com/t.tgz"})
    if request.url.host == "codeload.github.com":
        return httpx.Response(200, content=TARBALL)
    return httpx.Response(404, text="nope")


def client():
    return GitHubClient(token="t", transport=httpx.MockTransport(handler))


def test_fetch_pull_request():
    pr = client().fetch_pull_request("o/r", 7)
    assert (pr.repo, pr.number, pr.title, pr.description) == ("o/r", 7, "Add calc", "Adds add()")
    assert pr.head_sha == "abc123" and "calc.py b/calc.py" in pr.diff
    assert pr.changed_files == ["calc.py", "docs/guide.md"]  # removed file excluded
    assert set(pr.files) == {"calc.py", "util.py", "docs/guide.md", "pytest.ini"}
    # README (unchanged, non-source), binary and node_modules files are left out


def test_http_error():
    with pytest.raises(GitHubError, match="404"):
        client().fetch_pull_request("o/missing", 1)


@pytest.mark.parametrize("ref,expected", [
    ("o/r#7", ("o/r", 7)),
    ("https://github.com/o/r/pull/7", ("o/r", 7)),
    ("https://github.com/o/r/pull/7/files", ("o/r", 7)),
])
def test_parse_ref(ref, expected):
    assert parse_pr_ref(ref) == expected


def test_parse_ref_invalid():
    with pytest.raises(ValueError):
        parse_pr_ref("not a pr")


def test_api_returns_clean_errors(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main
    from app.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()
    monkeypatch.setattr(
        main.GitHubClient, "from_settings", classmethod(lambda cls: client())
    )
    c = TestClient(main.app)
    assert c.get("/health").json() == {"status": "ok"}
    assert c.post("/review", json={"pr": "nonsense"}).status_code == 422
    assert c.post("/review", json={"pr": "o/missing#1"}).status_code == 502
    r = c.post("/review", json={"pr": "o/r#7"})
    assert r.status_code == 503 and "GROQ_API_KEY" in r.json()["detail"]
    get_settings.cache_clear()
