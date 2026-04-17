from __future__ import annotations

import pytest

from commit_check_mcp import server


def test_validate_commit_message_requires_non_empty_message() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        server.validate_commit_message("   ")


def test_validate_branch_name_forwards_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_validate_branch(branch: str | None, *, config: dict | None):
        captured["branch"] = branch
        captured["config"] = config
        return {"status": "pass", "checks": []}

    monkeypatch.setattr(server, "_validate_branch", fake_validate_branch)

    result = server.validate_branch_name(" feature/add-mcp ", {"branch": {"conventional_branch": True}})

    assert result["status"] == "pass"
    assert captured == {
        "branch": "feature/add-mcp",
        "config": {"branch": {"conventional_branch": True}},
    }


def test_validate_commit_context_requires_at_least_one_field() -> None:
    with pytest.raises(ValueError, match="At least one"):
        server.validate_commit_context()


def test_validate_author_info_forwards_normalized_values(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_validate_author(name: str | None, email: str | None, *, config: dict | None):
        captured["name"] = name
        captured["email"] = email
        captured["config"] = config
        return {"status": "pass", "checks": []}

    monkeypatch.setattr(server, "_validate_author", fake_validate_author)

    result = server.validate_author_info(
        author_name=" Ada Lovelace ",
        author_email=" ada@example.com ",
        config={"commit": {"subject_imperative": True}},
    )

    assert result["status"] == "pass"
    assert captured == {
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "config": {"commit": {"subject_imperative": True}},
    }
