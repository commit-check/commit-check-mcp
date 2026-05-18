from __future__ import annotations

from pathlib import Path

import pytest

from commit_check_mcp import server


def test_validate_commit_message_requires_non_empty_message() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        server.validate_commit_message("   ")


def test_validate_branch_name_forwards_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_validate_branch(
        branch: str | None,
        *,
        config: dict | None,
        repo_path: Path | None,
        config_path: str | None,
    ):
        captured["branch"] = branch
        captured["config"] = config
        captured["repo_path"] = repo_path
        captured["config_path"] = config_path
        return {"status": "pass", "checks": []}

    monkeypatch.setattr(server, "_validate_branch", fake_validate_branch)

    result = server.validate_branch_name(
        " feature/add-mcp ",
        {"branch": {"conventional_branch": True}},
        repo_path=".",
    )

    assert result["status"] == "pass"
    assert captured == {
        "branch": "feature/add-mcp",
        "config": {"branch": {"conventional_branch": True}},
        "repo_path": Path.cwd().resolve(),
        "config_path": None,
    }


def test_validate_commit_context_requires_at_least_one_field() -> None:
    with pytest.raises(ValueError, match="At least one"):
        server.validate_commit_context()


def test_validate_push_safety_forwards_normalized_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_validate_push(
        push_refs: str | None,
        *,
        config: dict | None,
        repo_path: Path | None,
        config_path: str | None,
    ):
        captured["push_refs"] = push_refs
        captured["config"] = config
        captured["repo_path"] = repo_path
        captured["config_path"] = config_path
        return {"status": "pass", "checks": []}

    monkeypatch.setattr(server, "_validate_push", fake_validate_push)

    result = server.validate_push_safety(
        " refs/heads/main abc refs/heads/main def ",
        {"push": {"allow_force_push": True}},
        repo_path=".",
    )

    assert result["status"] == "pass"
    assert captured == {
        "push_refs": "refs/heads/main abc refs/heads/main def",
        "config": {"push": {"allow_force_push": True}},
        "repo_path": Path.cwd().resolve(),
        "config_path": None,
    }


def test_validate_push_forces_no_force_push_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []

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

    result = server._validate_push(None, config={"push": {"allow_force_push": True}})
    empty_refs_result = server._validate_push(
        "",
        config={"push": {"allow_force_push": True}},
    )

    assert result["status"] == "pass"
    assert empty_refs_result["status"] == "pass"
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


def test_validate_author_info_forwards_normalized_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_validate_author(
        name: str | None,
        email: str | None,
        *,
        config: dict | None,
        repo_path: Path | None,
        config_path: str | None,
    ):
        captured["name"] = name
        captured["email"] = email
        captured["config"] = config
        captured["repo_path"] = repo_path
        captured["config_path"] = config_path
        return {"status": "pass", "checks": []}

    monkeypatch.setattr(server, "_validate_author", fake_validate_author)

    result = server.validate_author_info(
        author_name=" Ada Lovelace ",
        author_email=" ada@example.com ",
        config={"commit": {"subject_imperative": True}},
        repo_path=".",
    )

    assert result["status"] == "pass"
    assert captured == {
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "config": {"commit": {"subject_imperative": True}},
        "repo_path": Path.cwd().resolve(),
        "config_path": None,
    }


def test_merge_config_loads_repo_default_and_explicit_overrides(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "cchk.toml").write_text(
        """
[commit]
subject_max_length = 72
require_body = true

[branch]
require_rebase_target = "main"
""".strip()
    )

    merged = server._merge_config(
        {"commit": {"subject_min_length": 10}},
        repo_path=repo_path,
    )

    assert merged["commit"]["subject_max_length"] == 72
    assert merged["commit"]["require_body"] is True
    assert merged["commit"]["subject_min_length"] == 10
    assert merged["branch"]["require_rebase_target"] == "main"


def test_normalize_config_path_resolves_relative_to_repo(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    config_file = repo_path / ".github" / "commit-check.toml"
    config_file.parent.mkdir()
    config_file.write_text("[commit]\nsubject_max_length = 68\n")

    normalized = server._normalize_config_path(".github/commit-check.toml", repo_path)

    assert normalized == str(config_file.resolve())


def test_validate_repository_state_requires_one_enabled_target() -> None:
    with pytest.raises(ValueError, match="At least one validation target"):
        server.validate_repository_state(
            include_message=False,
            include_branch=False,
            include_author=False,
            include_push=False,
        )


def test_validate_repository_state_combines_requested_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_validate_message(
        message: str,
        *,
        config: dict | None,
        repo_path: Path | None,
        config_path: str | None,
    ):
        assert message == ""
        return {"status": "pass", "checks": [{"check": "message", "status": "pass"}]}

    def fake_validate_branch(
        branch: str | None,
        *,
        config: dict | None,
        repo_path: Path | None,
        config_path: str | None,
    ):
        assert branch is None
        return {"status": "pass", "checks": [{"check": "branch", "status": "pass"}]}

    def fake_validate_push(
        push_refs: str | None,
        *,
        config: dict | None,
        repo_path: Path | None,
        config_path: str | None,
    ):
        assert push_refs is None
        return {
            "status": "pass",
            "checks": [{"check": "no_force_push", "status": "pass"}],
        }

    monkeypatch.setattr(server, "_validate_message", fake_validate_message)
    monkeypatch.setattr(server, "_validate_branch", fake_validate_branch)
    monkeypatch.setattr(server, "_validate_push", fake_validate_push)

    result = server.validate_repository_state(include_author=False, include_push=True)

    assert result == {
        "status": "pass",
        "checks": [
            {"check": "message", "status": "pass"},
            {"check": "branch", "status": "pass"},
            {"check": "no_force_push", "status": "pass"},
        ],
    }


def test_describe_validation_rules_includes_loaded_config(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "cchk.toml").write_text(
        """
[commit]
require_body = true
allow_commit_types = ["feat", "fix", "docs"]

[branch]
allow_branch_names = ["develop"]
""".strip()
    )

    result = server.describe_validation_rules(repo_path=str(repo_path))

    assert result["commit_check_version"]
    assert result["config"]["commit"]["require_body"] is True
    assert result["config"]["branch"]["allow_branch_names"] == ["develop"]
    assert "message" in result["supported_checks"]
    assert "no_force_push" in result["supported_checks"]
    assert result["supported_checks"].count("ignore_authors") == 1
    assert any(rule["check"] == "require_body" for rule in result["enabled_rules"])
