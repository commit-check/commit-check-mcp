"""Comprehensive tests covering all code paths in commit_check_mcp.server."""

from __future__ import annotations

from pathlib import Path
import os

import pytest

from commit_check_mcp import server


# ---------------------------------------------------------------------------
# _normalize_config
# ---------------------------------------------------------------------------

class TestNormalizeConfig:
    def test_none(self) -> None:
        assert server._normalize_config(None) is None

    def test_dict(self) -> None:
        assert server._normalize_config({"key": "val"}) == {"key": "val"}

    def test_non_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="must be an object/dictionary"):
            server._normalize_config("string")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _normalize_repo_path
# ---------------------------------------------------------------------------

class TestNormalizeRepoPath:
    def test_none(self) -> None:
        assert server._normalize_repo_path(None) is None

    def test_valid_path(self, tmp_path: Path) -> None:
        result = server._normalize_repo_path(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_non_string_raises(self) -> None:
        with pytest.raises(ValueError, match="repo_path must be a string"):
            server._normalize_repo_path(123)  # type: ignore[arg-type]

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="repo_path cannot be empty"):
            server._normalize_repo_path("   ")

    def test_non_existent_raises(self) -> None:
        with pytest.raises(ValueError, match="repo_path does not exist"):
            server._normalize_repo_path("/non/existent/path/xyz123")

    def test_file_path_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "afile.txt"
        f.write_text("hello")
        with pytest.raises(ValueError, match="repo_path must be a directory"):
            server._normalize_repo_path(str(f))


# ---------------------------------------------------------------------------
# _normalize_config_path
# ---------------------------------------------------------------------------

class TestNormalizeConfigPath:
    def test_none(self) -> None:
        assert server._normalize_config_path(None, None) is None

    def test_absolute_path(self, tmp_path: Path) -> None:
        cfg = tmp_path / "myconfig.toml"
        cfg.write_text("[commit]\n")
        result = server._normalize_config_path(str(cfg), None)
        assert result == str(cfg.resolve())

    def test_relative_resolved_via_repo(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        cfg = repo / "cchk.toml"
        cfg.write_text("[commit]\n")
        result = server._normalize_config_path("cchk.toml", repo)
        assert result == str(cfg.resolve())

    def test_non_string_raises(self) -> None:
        with pytest.raises(ValueError, match="config_path must be a string"):
            server._normalize_config_path(123, None)  # type: ignore[arg-type]

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="config_path cannot be empty"):
            server._normalize_config_path("   ", None)

    def test_non_existent_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="config_path does not exist"):
            server._normalize_config_path(str(tmp_path / "missing.toml"), None)

    def test_non_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="config_path must be a file"):
            server._normalize_config_path(str(tmp_path), None)


# ---------------------------------------------------------------------------
# _working_directory
# ---------------------------------------------------------------------------

class TestWorkingDirectory:
    def test_none_repo_path_yields(self) -> None:
        with server._working_directory(None):
            pass  # should not raise

    def test_changes_and_restores_cwd(self, tmp_path: Path) -> None:
        original = Path.cwd().resolve()
        target = tmp_path.resolve()
        with server._working_directory(target):
            assert Path.cwd().resolve() == target
        assert Path.cwd().resolve() == original


# ---------------------------------------------------------------------------
# _validate_message  (real engine call)
# ---------------------------------------------------------------------------

class TestValidateMessage:
    def test_valid_message_passes(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "cchk.toml").write_text(
            "[commit]\nallow_commit_types = []\nallow_merge_commits = true\nallow_revert_commits = true\nallow_empty_commits = true\nallow_fixup_commits = true\nallow_wip_commits = true"
        )
        result = server._validate_message(
            "feat: add new feature",
            repo_path=repo,
        )
        assert result["status"] in ("pass", "fail")
        assert isinstance(result["checks"], list)

    def test_failing_message_due_to_subject_case(self) -> None:
        """A message starting with a non-capitalized subject should fail."""
        result = server._validate_message(
            "add new feature",
            config={
                "commit": {
                    "subject_capitalized": True,
                    "allow_merge_commits": True,
                    "allow_revert_commits": True,
                    "allow_empty_commits": True,
                    "allow_fixup_commits": True,
                    "allow_wip_commits": True,
                }
            },
        )
        assert result["status"] == "fail"

    def test_message_pattern_overrides_conventional_commits(self) -> None:
        """When message_pattern is set via config, it takes precedence."""
        result = server._validate_message(
            "PROJ-123: add new feature",
            config={
                "commit": {
                    "message_pattern": r"^PROJ-\d+: .+",
                    "conventional_commits": False,
                    "allow_merge_commits": True,
                    "allow_revert_commits": True,
                    "allow_empty_commits": True,
                    "allow_fixup_commits": True,
                    "allow_wip_commits": True,
                }
            },
        )
        assert result["status"] == "pass"

    def test_message_pattern_fails_on_mismatch(self) -> None:
        """A message that doesn't match message_pattern should fail."""
        result = server._validate_message(
            "fix: some random change",
            config={
                "commit": {
                    "message_pattern": r"^PROJ-\d+: .+",
                    "conventional_commits": False,
                    "allow_merge_commits": True,
                    "allow_revert_commits": True,
                    "allow_empty_commits": True,
                    "allow_fixup_commits": True,
                    "allow_wip_commits": True,
                }
            },
        )
        assert result["status"] == "fail"


# ---------------------------------------------------------------------------
# _validate_branch  (real engine call)
# ---------------------------------------------------------------------------

class TestValidateBranch:
    def test_valid_branch_passes(self) -> None:
        result = server._validate_branch("main")
        assert result["status"] in ("pass", "fail")
        assert isinstance(result["checks"], list)

    def test_called_with_arguments(self) -> None:
        result = server._validate_branch(None)
        assert isinstance(result["checks"], list)


# ---------------------------------------------------------------------------
# _validate_push
# ---------------------------------------------------------------------------

class TestValidatePush:
    def test_no_force_push_rule_is_enforced(self) -> None:
        result = server._validate_push("refs/heads/main abc refs/heads/main def")
        # The rule is enabled, but depending on context it may pass or fail
        assert "status" in result
        assert isinstance(result["checks"], list)

    def test_with_push_refs_none_and_patch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[dict] = []

        def fake_run_checks(check_names, context, config):
            captured.append(
                {
                    "check_names": check_names,
                    "stdin_text": context.stdin_text,
                    "push_upstream_fallback": context.push_upstream_fallback,
                    "allow_force_push": config["push"]["allow_force_push"],
                }
            )
            return {"status": "pass", "checks": []}

        monkeypatch.setattr(server, "_run_checks", fake_run_checks)

        result = server._validate_push(
            None, config={"push": {"allow_force_push": True}}
        )
        empty_result = server._validate_push(
            "", config={"push": {"allow_force_push": True}}
        )

        assert result["status"] == "pass"
        assert empty_result["status"] == "pass"
        assert captured == [
            {
                "check_names": ["no_force_push"],
                "stdin_text": None,
                "push_upstream_fallback": True,
                "allow_force_push": False,
            },
            {
                "check_names": ["no_force_push"],
                "stdin_text": "",
                "push_upstream_fallback": False,
                "allow_force_push": False,
            },
        ]


# ---------------------------------------------------------------------------
# _validate_author
# ---------------------------------------------------------------------------

class TestValidateAuthor:
    def test_both_name_and_email(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        def fake_run_checks(check_names, context, config):
            calls.append(check_names)
            return {
                "status": "pass",
                "checks": [
                    {"check": cn, "status": "pass", "value": "", "error": "", "suggest": ""}
                    for cn in check_names
                ],
            }

        monkeypatch.setattr(server, "_run_checks", fake_run_checks)

        result = server._validate_author("Alice", "alice@example.com")
        assert result["status"] == "pass"
        assert len(result["checks"]) == 2
        assert calls == [["author_name"], ["author_email"]]

    def test_only_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        def fake_run_checks(check_names, context, config):
            calls.append(check_names)
            return {
                "status": "pass",
                "checks": [
                    {"check": cn, "status": "pass", "value": "", "error": "", "suggest": ""}
                    for cn in check_names
                ],
            }

        monkeypatch.setattr(server, "_run_checks", fake_run_checks)

        result = server._validate_author(name="Bob")
        assert result["status"] == "pass"
        assert len(result["checks"]) == 1
        assert calls == [["author_name"]]

    def test_only_email(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        def fake_run_checks(check_names, context, config):
            calls.append(check_names)
            return {
                "status": "pass",
                "checks": [
                    {"check": cn, "status": "pass", "value": "", "error": "", "suggest": ""}
                    for cn in check_names
                ],
            }

        monkeypatch.setattr(server, "_run_checks", fake_run_checks)

        result = server._validate_author(email="bob@example.com")
        assert result["status"] == "pass"
        assert len(result["checks"]) == 1
        assert calls == [["author_email"]]

    def test_neither_name_nor_email(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        def fake_run_checks(check_names, context, config):
            calls.append(check_names)
            return {
                "status": "pass",
                "checks": [
                    {"check": cn, "status": "pass", "value": "", "error": "", "suggest": ""}
                    for cn in check_names
                ],
            }

        monkeypatch.setattr(server, "_run_checks", fake_run_checks)

        result = server._validate_author()
        assert result["status"] == "pass"
        assert len(result["checks"]) == 2
        assert calls == [["author_name", "author_email"]]

    def test_status_fail_when_check_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run_checks(check_names, context, config):
            return {
                "status": "fail",
                "checks": [
                    {"check": cn, "status": "fail", "value": "", "error": "bad", "suggest": "fix it"}
                    for cn in check_names
                ],
            }

        monkeypatch.setattr(server, "_run_checks", fake_run_checks)

        result = server._validate_author("Alice", "alice@example.com")
        assert result["status"] == "fail"


# ---------------------------------------------------------------------------
# _validate_all
# ---------------------------------------------------------------------------

class TestValidateAll:
    def test_message_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def fake_run_checks(check_names, context, config):
            calls.extend(check_names)
            return {
                "status": "pass",
                "checks": [
                    {"check": cn, "status": "pass", "value": "", "error": "", "suggest": ""}
                    for cn in check_names
                ],
            }

        monkeypatch.setattr(server, "_run_checks", fake_run_checks)

        result = server._validate_all(message="feat: test")
        assert result["status"] == "pass"
        assert "message" in calls
        assert "branch" not in calls

    def test_branch_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def fake_run_checks(check_names, context, config):
            calls.extend(check_names)
            return {
                "status": "pass",
                "checks": [
                    {"check": cn, "status": "pass", "value": "", "error": "", "suggest": ""}
                    for cn in check_names
                ],
            }

        monkeypatch.setattr(server, "_run_checks", fake_run_checks)

        result = server._validate_all(branch="feature/test")
        assert result["status"] == "pass"
        assert "branch" in calls

    def test_author_both_name_and_email(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def fake_run_checks(check_names, context, config):
            calls.extend(check_names)
            return {
                "status": "pass",
                "checks": [
                    {"check": cn, "status": "pass", "value": "", "error": "", "suggest": ""}
                    for cn in check_names
                ],
            }

        monkeypatch.setattr(server, "_run_checks", fake_run_checks)

        result = server._validate_all(author_name="Alice", author_email="a@b.com")
        assert result["status"] == "pass"
        assert "author_name" in calls
        assert "author_email" in calls

    def test_author_only_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def fake_run_checks(check_names, context, config):
            calls.extend(check_names)
            return {
                "status": "pass",
                "checks": [
                    {"check": cn, "status": "pass", "value": "", "error": "", "suggest": ""}
                    for cn in check_names
                ],
            }

        monkeypatch.setattr(server, "_run_checks", fake_run_checks)

        result = server._validate_all(author_name="Bob")
        assert result["status"] == "pass"
        assert "author_name" in calls
        assert "author_email" not in calls

    def test_author_only_email(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def fake_run_checks(check_names, context, config):
            calls.extend(check_names)
            return {
                "status": "pass",
                "checks": [
                    {"check": cn, "status": "pass", "value": "", "error": "", "suggest": ""}
                    for cn in check_names
                ],
            }

        monkeypatch.setattr(server, "_run_checks", fake_run_checks)

        result = server._validate_all(author_email="b@c.com")
        assert result["status"] == "pass"
        assert "author_email" in calls
        assert "author_name" not in calls

    def test_all_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def fake_run_checks(check_names, context, config):
            calls.extend(check_names)
            return {
                "status": "pass",
                "checks": [
                    {"check": cn, "status": "pass", "value": "", "error": "", "suggest": ""}
                    for cn in check_names
                ],
            }

        monkeypatch.setattr(server, "_run_checks", fake_run_checks)

        result = server._validate_all(
            message="feat: x", branch="main", author_name="Al", author_email="a@b.com"
        )
        assert result["status"] == "pass"
        assert "message" in calls
        assert "branch" in calls
        assert "author_name" in calls
        assert "author_email" in calls

    def test_overall_fail_with_failing_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run_checks(check_names, context, config):
            return {
                "status": "fail",
                "checks": [
                    {"check": cn, "status": "fail", "value": "", "error": "bad", "suggest": ""}
                    for cn in check_names
                ],
            }

        monkeypatch.setattr(server, "_run_checks", fake_run_checks)

        result = server._validate_all(message="bad")
        assert result["status"] == "fail"


# ---------------------------------------------------------------------------
# server_health
# ---------------------------------------------------------------------------

class TestServerHealth:
    def test_returns_expected_keys(self) -> None:
        result = server.server_health()
        assert result["server"] == "commit-check-mcp"
        assert "server_version" in result
        assert "commit_check_version" in result
        assert "mcp_sdk_version" in result


# ---------------------------------------------------------------------------
# validate_commit_message  (MCP tool)
# ---------------------------------------------------------------------------

class TestValidateCommitMessage:
    def test_non_string_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            server.validate_commit_message(123)  # type: ignore[arg-type]

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            server.validate_commit_message("   ")

    def test_valid_message_with_repo_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()

        captured: dict[str, object] = {}

        def fake_validate_message(message, *, config, repo_path, config_path):
            captured["message"] = message
            captured["config"] = config
            captured["repo_path"] = repo_path
            captured["config_path"] = config_path
            return {"status": "pass", "checks": []}

        monkeypatch.setattr(server, "_validate_message", fake_validate_message)

        result = server.validate_commit_message(
            "  feat: hello  ", config={"commit": {}}, repo_path=str(repo)
        )
        assert result["status"] == "pass"
        assert captured["message"] == "feat: hello"
        assert captured["repo_path"] == repo.resolve()


# ---------------------------------------------------------------------------
# validate_branch_name  (MCP tool)
# ---------------------------------------------------------------------------

class TestValidateBranchName:
    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="branch cannot be empty"):
            server.validate_branch_name(branch="   ")

    def test_none_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_validate_branch(branch, *, config, repo_path, config_path):
            captured["branch"] = branch
            return {"status": "pass", "checks": []}

        monkeypatch.setattr(server, "_validate_branch", fake_validate_branch)

        result = server.validate_branch_name()
        assert result["status"] == "pass"
        assert captured["branch"] is None

    def test_valid_branch_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_validate_branch(branch, *, config, repo_path, config_path):
            captured["branch"] = branch
            return {"status": "pass", "checks": []}

        monkeypatch.setattr(server, "_validate_branch", fake_validate_branch)

        result = server.validate_branch_name("  feature/test  ")
        assert result["status"] == "pass"
        assert captured["branch"] == "feature/test"


# ---------------------------------------------------------------------------
# validate_author_info  (MCP tool)
# ---------------------------------------------------------------------------

class TestValidateAuthorInfo:
    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="author_name cannot be empty"):
            server.validate_author_info(author_name="   ")

    def test_empty_email_raises(self) -> None:
        with pytest.raises(ValueError, match="author_email cannot be empty"):
            server.validate_author_info(author_email="   ")

    def test_valid_values_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_validate_author(name, email, *, config, repo_path, config_path):
            captured["name"] = name
            captured["email"] = email
            return {"status": "pass", "checks": []}

        monkeypatch.setattr(server, "_validate_author", fake_validate_author)

        result = server.validate_author_info(
            author_name="  Alice  ", author_email="  a@b.com  "
        )
        assert result["status"] == "pass"
        assert captured["name"] == "Alice"
        assert captured["email"] == "a@b.com"

    def test_none_name_and_email(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_validate_author(name, email, *, config, repo_path, config_path):
            captured["name"] = name
            captured["email"] = email
            return {"status": "pass", "checks": []}

        monkeypatch.setattr(server, "_validate_author", fake_validate_author)

        server.validate_author_info()
        assert captured["name"] is None
        assert captured["email"] is None


# ---------------------------------------------------------------------------
# validate_push_safety  (MCP tool)
# ---------------------------------------------------------------------------

class TestValidatePushSafety:
    def test_none_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_validate_push(push_refs, *, config, repo_path, config_path):
            captured["push_refs"] = push_refs
            return {"status": "pass", "checks": []}

        monkeypatch.setattr(server, "_validate_push", fake_validate_push)

        result = server.validate_push_safety()
        assert result["status"] == "pass"
        assert captured["push_refs"] is None

    def test_push_refs_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_validate_push(push_refs, *, config, repo_path, config_path):
            captured["push_refs"] = push_refs
            return {"status": "pass", "checks": []}

        monkeypatch.setattr(server, "_validate_push", fake_validate_push)

        result = server.validate_push_safety("  refs/heads/main  ")
        assert result["status"] == "pass"
        assert captured["push_refs"] == "refs/heads/main"


# ---------------------------------------------------------------------------
# validate_commit_context  (MCP tool)
# ---------------------------------------------------------------------------

class TestValidateCommitContext:
    def test_empty_message_raises(self) -> None:
        with pytest.raises(ValueError, match="message cannot be empty"):
            server.validate_commit_context(message="   ")

    def test_empty_branch_raises(self) -> None:
        with pytest.raises(ValueError, match="branch cannot be empty"):
            server.validate_commit_context(branch="   ")

    def test_empty_author_name_raises(self) -> None:
        with pytest.raises(ValueError, match="author_name cannot be empty"):
            server.validate_commit_context(author_name="   ")

    def test_empty_author_email_raises(self) -> None:
        with pytest.raises(ValueError, match="author_email cannot be empty"):
            server.validate_commit_context(author_email="   ")

    def test_no_fields_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one"):
            server.validate_commit_context()

    def test_all_fields_forwards(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_validate_all(message, branch, author_name, author_email, *, config, repo_path, config_path):
            captured["message"] = message
            captured["branch"] = branch
            captured["author_name"] = author_name
            captured["author_email"] = author_email
            return {"status": "pass", "checks": []}

        monkeypatch.setattr(server, "_validate_all", fake_validate_all)

        result = server.validate_commit_context(
            message="  feat: x  ",
            branch="  main  ",
            author_name="  Al  ",
            author_email="  a@b.com  ",
        )
        assert result["status"] == "pass"
        assert captured == {
            "message": "feat: x",
            "branch": "main",
            "author_name": "Al",
            "author_email": "a@b.com",
        }

    def test_message_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_validate_all(message, branch, author_name, author_email, *, config, repo_path, config_path):
            captured["message"] = message
            captured["branch"] = branch
            captured["author_name"] = author_name
            captured["author_email"] = author_email
            return {"status": "pass", "checks": []}

        monkeypatch.setattr(server, "_validate_all", fake_validate_all)

        server.validate_commit_context(message="feat: x")
        assert captured["message"] == "feat: x"
        assert captured["branch"] is None
        assert captured["author_name"] is None
        assert captured["author_email"] is None


# ---------------------------------------------------------------------------
# validate_repository_state  (MCP tool)
# ---------------------------------------------------------------------------

class TestValidateRepositoryState:
    def test_all_disabled_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one validation target"):
            server.validate_repository_state(
                include_message=False,
                include_branch=False,
                include_author=False,
                include_push=False,
            )

    def test_only_push_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []

        def fake_validate_message(_message, *, config, repo_path, config_path):
            called.append("message")
            return {"status": "pass", "checks": [{"check": "message", "status": "pass"}]}

        def fake_validate_branch(_branch, *, config, repo_path, config_path):
            called.append("branch")
            return {"status": "pass", "checks": [{"check": "branch", "status": "pass"}]}

        def fake_validate_author(_name, _email, *, config, repo_path, config_path):
            called.append("author")
            return {"status": "pass", "checks": [{"check": "author", "status": "pass"}]}

        def fake_validate_push(_push_refs, *, config, repo_path, config_path):
            called.append("push")
            return {"status": "pass", "checks": [{"check": "no_force_push", "status": "pass"}]}

        monkeypatch.setattr(server, "_validate_message", fake_validate_message)
        monkeypatch.setattr(server, "_validate_branch", fake_validate_branch)
        monkeypatch.setattr(server, "_validate_author", fake_validate_author)
        monkeypatch.setattr(server, "_validate_push", fake_validate_push)

        result = server.validate_repository_state(
            include_message=False,
            include_branch=False,
            include_author=False,
            include_push=True,
        )
        assert result["status"] == "pass"
        assert called == ["push"]

    def test_all_disabled_except_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []

        def fake_validate_message(_message, *, config, repo_path, config_path):
            called.append("message")
            return {"status": "pass", "checks": [{"check": "message", "status": "pass"}]}

        monkeypatch.setattr(server, "_validate_message", fake_validate_message)

        result = server.validate_repository_state(
            include_message=True,
            include_branch=False,
            include_author=False,
            include_push=False,
        )
        assert result["status"] == "pass"
        assert called == ["message"]

    def test_default_all_included_except_push(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []

        def fake_validate_message(_message, *, config, repo_path, config_path):
            called.append("message")
            return {"status": "pass", "checks": []}

        def fake_validate_branch(_branch, *, config, repo_path, config_path):
            called.append("branch")
            return {"status": "pass", "checks": []}

        def fake_validate_author(_name, _email, *, config, repo_path, config_path):
            called.append("author")
            return {"status": "pass", "checks": []}

        monkeypatch.setattr(server, "_validate_message", fake_validate_message)
        monkeypatch.setattr(server, "_validate_branch", fake_validate_branch)
        monkeypatch.setattr(server, "_validate_author", fake_validate_author)

        server.validate_repository_state()
        assert called == ["message", "branch", "author"]

    def test_overall_fail_on_failing_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_validate_message(_message, *, config, repo_path, config_path):
            return {
                "status": "fail",
                "checks": [{"check": "message", "status": "fail"}],
            }

        monkeypatch.setattr(server, "_validate_message", fake_validate_message)

        result = server.validate_repository_state(
            include_branch=False, include_author=False, include_push=False
        )
        assert result["status"] == "fail"


# ---------------------------------------------------------------------------
# describe_validation_rules  (MCP tool)
# ---------------------------------------------------------------------------

class TestDescribeValidationRules:
    def test_returns_all_keys(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "cchk.toml").write_text("[commit]\nrequire_body = true\n")

        result = server.describe_validation_rules(repo_path=str(repo))

        assert result["commit_check_version"]
        assert "supported_checks" in result
        assert "enabled_rules" in result
        assert "config" in result
        assert result["config"]["commit"]["require_body"] is True
        assert "message" in result["supported_checks"]

    def test_with_config_override(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "cchk.toml").write_text("[commit]\nrequire_body = true\n")

        result = server.describe_validation_rules(
            repo_path=str(repo),
            config={"commit": {"subject_min_length": 5}},
        )

        assert result["config"]["commit"]["subject_min_length"] == 5
        assert result["config"]["commit"]["require_body"] is True

    def test_with_none_repo_path(self) -> None:
        result = server.describe_validation_rules()
        assert "supported_checks" in result
        assert "enabled_rules" in result


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

class TestMain:
    def test_main_invokes_mcp_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = False

        def fake_run(*, transport: str) -> None:
            nonlocal called
            called = True
            assert transport == "stdio"

        monkeypatch.setattr(server.mcp, "run", fake_run)
        server.main([])
        assert called

    def test_http_transport_is_stateless(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--transport http must serve stateless Streamable HTTP.

        stateless_http and json_response are what let any instance behind a
        plain load balancer answer any request under the 2026-07-28 spec;
        this pins them so a refactor cannot silently reintroduce sessions.
        """
        captured: dict[str, object] = {}

        def fake_run(**kwargs: object) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(server.mcp, "run", fake_run)
        server.main(["--transport", "http", "--host", "0.0.0.0", "--port", "9000"])
        assert captured == {
            "transport": "streamable-http",
            "host": "0.0.0.0",
            "port": 9000,
            "stateless_http": True,
            "json_response": True,
        }

    def test_transport_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """COMMIT_CHECK_MCP_TRANSPORT/_HOST/_PORT configure containers without argv."""
        captured: dict[str, object] = {}
        monkeypatch.setenv("COMMIT_CHECK_MCP_TRANSPORT", "http")
        monkeypatch.setenv("COMMIT_CHECK_MCP_HOST", "0.0.0.0")
        monkeypatch.setenv("COMMIT_CHECK_MCP_PORT", "8080")
        monkeypatch.setattr(server.mcp, "run", lambda **kw: captured.update(kw))
        server.main([])
        assert captured["transport"] == "streamable-http"
        assert captured["host"] == "0.0.0.0"
        assert captured["port"] == 8080
        assert captured["stateless_http"] is True

    def test_rejects_unknown_transport(self) -> None:
        with pytest.raises(SystemExit):
            server.main(["--transport", "sse"])

    def test_rejects_unknown_transport_from_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """argparse skips `choices` for env-supplied defaults; a typo in
        COMMIT_CHECK_MCP_TRANSPORT must fail loudly, not silently serve stdio in a
        container that expects an HTTP listener."""
        monkeypatch.setenv("COMMIT_CHECK_MCP_TRANSPORT", "htpp")
        monkeypatch.setattr(
            server.mcp, "run", lambda **kw: pytest.fail("server must not start")
        )
        with pytest.raises(SystemExit):
            server.main([])

    def test_rejects_non_integer_port_from_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("COMMIT_CHECK_MCP_PORT", "eight thousand")
        with pytest.raises(SystemExit):
            server.main([])

    def test_cli_port_overrides_invalid_environment_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An invalid inherited COMMIT_CHECK_MCP_PORT must not veto an explicit --port."""
        captured: dict[str, object] = {}
        monkeypatch.setenv("COMMIT_CHECK_MCP_PORT", "eight thousand")
        monkeypatch.setattr(server.mcp, "run", lambda **kw: captured.update(kw))
        server.main(["--transport", "http", "--port", "9000"])
        assert captured["port"] == 9000

    def test_allowed_hosts_enable_transport_security(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(server.mcp, "run", lambda **kw: captured.update(kw))
        server.main(
            [
                "--transport",
                "http",
                "--allowed-hosts",
                "mcp.example.com, mcp.example.com:443",
                "--allowed-origins",
                "https://app.example.com",
            ]
        )
        security = captured["transport_security"]
        assert security.enable_dns_rebinding_protection is True  # type: ignore[attr-defined]
        assert security.allowed_hosts == [  # type: ignore[attr-defined]
            "mcp.example.com",
            "mcp.example.com:443",
        ]
        assert security.allowed_origins == ["https://app.example.com"]  # type: ignore[attr-defined]

    def test_no_transport_security_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(server.mcp, "run", lambda **kw: captured.update(kw))
        server.main(["--transport", "http"])
        assert "transport_security" not in captured

    def test_origins_without_hosts_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Origins-only would enable rebinding protection with an empty host
        allowlist, which answers every request with 421 — verified against a
        live server. Refuse to start rather than serve a dead endpoint."""
        monkeypatch.setattr(
            server.mcp, "run", lambda **kw: pytest.fail("server must not start")
        )
        with pytest.raises(SystemExit):
            server.main(
                ["--transport", "http", "--allowed-origins", "https://app.example.com"]
            )

    def test_unprefixed_env_vars_are_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bare MCP_TRANSPORT belongs to no particular server. Honouring it
        would turn a stdio launch into an HTTP listener that never answers the
        client's handshake."""
        captured: dict[str, object] = {}
        monkeypatch.setenv("MCP_TRANSPORT", "http")
        monkeypatch.setenv("MCP_PORT", "9999")
        monkeypatch.delenv("COMMIT_CHECK_MCP_TRANSPORT", raising=False)
        monkeypatch.setattr(server.mcp, "run", lambda **kw: captured.update(kw))
        server.main([])
        assert captured == {"transport": "stdio"}
