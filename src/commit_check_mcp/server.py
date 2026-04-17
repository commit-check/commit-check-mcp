"""MCP server for commit-check validations."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from importlib.metadata import version
import io
from typing import Any

from commit_check import __version__ as commit_check_version
from commit_check.config_merger import get_default_config
from commit_check.engine import ValidationContext, ValidationEngine, ValidationResult
from commit_check.rule_builder import RuleBuilder, ValidationRule
from mcp.server.fastmcp import FastMCP

from . import __version__

mcp = FastMCP(
    "commit-check-mcp",
    instructions=(
        "Use these tools to validate commit messages, branch names, and author metadata "
        "with commit-check."
    ),
)


def _normalize_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Ensure tool config input is JSON-object-like."""
    if config is None:
        return None
    if not isinstance(config, dict):
        raise ValueError("config must be an object/dictionary when provided")
    return config


def _merge_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Merge user config on top of commit-check defaults."""
    merged = get_default_config()
    if config:
        from commit_check.config_merger import deep_merge

        deep_merge(merged, config)
    return merged


def _run_checks(
    check_names: list[str],
    context: ValidationContext,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Run commit-check rules and always return structured per-check results."""
    rules = RuleBuilder(config).build_all_rules()
    filtered: list[ValidationRule] = [r for r in rules if r.check in check_names]

    checks: list[dict[str, Any]] = []
    for rule in filtered:
        with io.StringIO() as _out, io.StringIO() as _err:
            with redirect_stdout(_out), redirect_stderr(_err):
                status = ValidationEngine([rule]).validate_all(context)
        passed = status == ValidationResult.PASS
        checks.append(
            {
                "check": rule.check,
                "status": "pass" if passed else "fail",
                "value": context.stdin_text or "",
                "error": "" if passed else (rule.error or ""),
                "suggest": "" if passed else (rule.suggest or ""),
            }
        )

    overall = "fail" if any(c["status"] == "fail" for c in checks) else "pass"
    return {"status": overall, "checks": checks}


def _validate_message(
    message: str,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate message using commit-check engine internals."""
    cfg = _merge_config(config)
    return _run_checks(
        [
            "message",
            "subject_imperative",
            "subject_max_length",
            "subject_min_length",
            "subject_capitalized",
            "require_signed_off_by",
            "require_body",
            "allow_merge_commits",
            "allow_revert_commits",
            "allow_empty_commits",
            "allow_fixup_commits",
            "allow_wip_commits",
        ],
        ValidationContext(stdin_text=message, config=cfg),
        cfg,
    )


def _validate_branch(
    branch: str | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate branch name using commit-check engine internals."""
    cfg = _merge_config(config)
    return _run_checks(
        ["branch", "merge_base"],
        ValidationContext(stdin_text=branch, config=cfg),
        cfg,
    )


def _validate_author(
    name: str | None = None,
    email: str | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate author info using commit-check engine internals."""
    cfg = _merge_config(config)

    if name is not None and email is not None:
        name_result = _run_checks(
            ["author_name"],
            ValidationContext(stdin_text=name, config=cfg),
            cfg,
        )
        email_result = _run_checks(
            ["author_email"],
            ValidationContext(stdin_text=email, config=cfg),
            cfg,
        )
        checks = name_result["checks"] + email_result["checks"]
        return {
            "status": "fail" if any(c["status"] == "fail" for c in checks) else "pass",
            "checks": checks,
        }

    check_names: list[str] = []
    stdin = None
    if name is not None:
        check_names.append("author_name")
        stdin = name
    if email is not None:
        check_names.append("author_email")
        stdin = email
    if not check_names:
        check_names = ["author_name", "author_email"]

    return _run_checks(check_names, ValidationContext(stdin_text=stdin, config=cfg), cfg)


def _validate_all(
    message: str | None = None,
    branch: str | None = None,
    author_name: str | None = None,
    author_email: str | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate multiple commit-check contexts and combine outcomes."""
    checks: list[dict[str, Any]] = []

    if message is not None:
        checks.extend(_validate_message(message, config=config)["checks"])
    if branch is not None:
        checks.extend(_validate_branch(branch, config=config)["checks"])
    if author_name is not None or author_email is not None:
        checks.extend(_validate_author(author_name, author_email, config=config)["checks"])

    return {
        "status": "fail" if any(c["status"] == "fail" for c in checks) else "pass",
        "checks": checks,
    }


@mcp.tool()
def server_health() -> dict[str, str]:
    """Return server and dependency versions."""
    return {
        "server": "commit-check-mcp",
        "server_version": __version__,
        "commit_check_version": commit_check_version,
        "mcp_sdk_version": version("mcp"),
    }


@mcp.tool()
def validate_commit_message(
    message: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a commit message against commit-check rules."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string")
    return _validate_message(message.strip(), config=_normalize_config(config))


@mcp.tool()
def validate_branch_name(
    branch: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate branch naming conventions with commit-check."""
    normalized_branch = branch.strip() if isinstance(branch, str) else None
    if isinstance(branch, str) and not normalized_branch:
        raise ValueError("branch cannot be empty when provided")
    return _validate_branch(normalized_branch, config=_normalize_config(config))


@mcp.tool()
def validate_author_info(
    author_name: str | None = None,
    author_email: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate commit author name and/or email with commit-check."""
    normalized_name = author_name.strip() if isinstance(author_name, str) else None
    normalized_email = author_email.strip() if isinstance(author_email, str) else None

    if isinstance(author_name, str) and not normalized_name:
        raise ValueError("author_name cannot be empty when provided")
    if isinstance(author_email, str) and not normalized_email:
        raise ValueError("author_email cannot be empty when provided")

    return _validate_author(
        normalized_name,
        normalized_email,
        config=_normalize_config(config),
    )


@mcp.tool()
def validate_commit_context(
    message: str | None = None,
    branch: str | None = None,
    author_name: str | None = None,
    author_email: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run combined commit-check validations in one call."""
    normalized_message = message.strip() if isinstance(message, str) else None
    normalized_branch = branch.strip() if isinstance(branch, str) else None
    normalized_name = author_name.strip() if isinstance(author_name, str) else None
    normalized_email = author_email.strip() if isinstance(author_email, str) else None

    if isinstance(message, str) and not normalized_message:
        raise ValueError("message cannot be empty when provided")
    if isinstance(branch, str) and not normalized_branch:
        raise ValueError("branch cannot be empty when provided")
    if isinstance(author_name, str) and not normalized_name:
        raise ValueError("author_name cannot be empty when provided")
    if isinstance(author_email, str) and not normalized_email:
        raise ValueError("author_email cannot be empty when provided")

    if not any([normalized_message, normalized_branch, normalized_name, normalized_email]):
        raise ValueError(
            "At least one of message, branch, author_name, or author_email must be provided"
        )

    return _validate_all(
        message=normalized_message,
        branch=normalized_branch,
        author_name=normalized_name,
        author_email=normalized_email,
        config=_normalize_config(config),
    )


def main() -> None:
    """Run commit-check MCP server via stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
