"""cwd-dependent reads that happen before a tool enters ``_working_directory``.

Another thread is parked inside ``_working_directory(other)``, so the process
cwd is ``other`` and the lock is held. A call that resolves a relative path or
checks the git repository for ``repo_path=None`` must still see the directory
the server was started in, otherwise it validates against a repository it was
never asked about.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from commit_check_mcp import server


def _git_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)

    git("init", "-q", "-b", "main")
    (repo / "f").write_text("x")
    git("add", "f")
    git("commit", "-q", "-m", "feat: init")
    return repo


class _Parked:
    """Hold ``_working_directory(repo)`` open on another thread until released."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.inside = threading.Event()
        self.release = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        with server._working_directory(self.repo):
            self.inside.set()
            self.release.wait(30)

    def __enter__(self) -> _Parked:
        self.thread.start()
        assert self.inside.wait(5)
        return self

    def __exit__(self, *exc: object) -> None:
        self.release.set()
        self.thread.join(5)


def test_relative_config_path_without_repo_path_uses_the_at_rest_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "cchk.toml").write_text("[commit]\nsubject_max_length = 10\n")
    other = tmp_path / "other"
    other.mkdir()
    (other / "cchk.toml").write_text("[commit]\nsubject_max_length = 99\n")
    monkeypatch.chdir(home)
    parked = _Parked(other)
    parked.__enter__()
    try:
        resolver = threading.Thread(
            target=lambda: results.append(server._normalize_config_path("cchk.toml", None)),
            daemon=True,
        )
        results: list[str | None] = []
        resolver.start()
        resolver.join(0.5)
        assert resolver.is_alive(), "should be waiting for the parked chdir window to close"
    finally:
        parked.__exit__()
    resolver.join(5)
    assert results == [str(home / "cchk.toml")]


def test_relative_repo_path_uses_the_at_rest_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / "sub").mkdir(parents=True)
    other = tmp_path / "other"
    (other / "sub").mkdir(parents=True)
    monkeypatch.chdir(home)
    results: list[Path | None] = []
    with _Parked(other):
        t = threading.Thread(
            target=lambda: results.append(server._normalize_repo_path("sub")), daemon=True
        )
        t.start()
        t.join(0.5)
        assert t.is_alive(), "should be waiting for the parked chdir window to close"
    t.join(5)
    assert results == [home / "sub"]


def test_require_git_repo_without_repo_path_checks_the_at_rest_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    other = _git_repo(tmp_path, "other")
    monkeypatch.chdir(plain)
    results: list[BaseException | None] = []

    def check() -> None:
        try:
            server._require_git_repo(None)
        except ToolError as e:
            results.append(e)
        else:
            results.append(None)

    with _Parked(other):
        t = threading.Thread(target=check, daemon=True)
        t.start()
        t.join(0.5)
        assert t.is_alive(), "should be waiting for the parked chdir window to close"
    t.join(10)
    assert isinstance(results[0], ToolError)


def test_tool_with_relative_config_path_loads_the_right_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: config_path='cchk.toml' with no repo_path, while another
    call is inside its chdir window, loads the file next to the server."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "cchk.toml").write_text("[commit]\nsubject_max_length = 100\n")
    other = tmp_path / "other"
    other.mkdir()
    (other / "cchk.toml").write_text("[commit]\nsubject_max_length = 5\n")
    monkeypatch.chdir(home)
    results: list[dict] = []

    def call() -> None:
        results.append(
            server.validate_commit_message("feat: a long enough subject", config_path="cchk.toml")
        )

    with _Parked(other):
        t = threading.Thread(target=call, daemon=True)
        t.start()
        t.join(0.5)
        assert t.is_alive(), "should be waiting for the parked chdir window to close"
    t.join(10)
    sub = next(c for c in results[0]["checks"] if c["check"] == "subject_max_length")
    assert sub["status"] == "pass", sub
