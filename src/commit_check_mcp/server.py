"""MCP server for commit-check validations."""

from __future__ import annotations

from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
import os
from typing import Any

from commit_check import __version__ as commit_check_version
from commit_check.config_merger import deep_merge, get_default_config, load_toml_config
from commit_check.engine import ValidationContext, ValidationEngine, CheckOutcome
from commit_check.rule_builder import RuleBuilder, ValidationRule
from commit_check.rules_catalog import BRANCH_RULES, COMMIT_RULES, PUSH_RULES
from mcp.server.mcpserver import MCPServer

from . import __version__

mcp = MCPServer(
    "commit-check-mcp",
    instructions=(
        "Use these tools to validate commit messages, branch names, author metadata, "
        "and push safety with commit-check."
    ),
)


def _normalize_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Ensure tool config input is JSON-object-like."""
    if config is None:
        return None
    if not isinstance(config, dict):
        raise ValueError("config must be an object/dictionary when provided")
    return config


def _normalize_repo_path(repo_path: str | None) -> Path | None:
    """Normalize and validate an optional repository path."""
    if repo_path is None:
        return None
    if not isinstance(repo_path, str):
        raise ValueError("repo_path must be a string when provided")
    normalized = repo_path.strip()
    if not normalized:
        raise ValueError("repo_path cannot be empty when provided")

    path = Path(normalized).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"repo_path does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"repo_path must be a directory: {path}")
    return path


def _normalize_config_path(config_path: str | None, repo_path: Path | None) -> str | None:
    """Normalize and validate an optional config path."""
    if config_path is None:
        return None
    if not isinstance(config_path, str):
        raise ValueError("config_path must be a string when provided")
    normalized = config_path.strip()
    if not normalized:
        raise ValueError("config_path cannot be empty when provided")

    path = Path(normalized).expanduser()
    if not path.is_absolute() and repo_path is not None:
        path = repo_path / path

    resolved = path.resolve()
    if not resolved.exists():
        raise ValueError(f"config_path does not exist: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"config_path must be a file: {resolved}")
    return str(resolved)


@contextmanager
def _working_directory(repo_path: Path | None):
    """Temporarily switch working directory for repo-relative config and git checks."""
    if repo_path is None:
        yield
        return

    original_cwd = Path.cwd()
    os.chdir(repo_path)
    try:
        yield
    finally:
        os.chdir(original_cwd)


def _merge_config(
    config: dict[str, Any] | None,
    *,
    repo_path: Path | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Merge repository config and user config on top of commit-check defaults."""
    merged = get_default_config()
    with _working_directory(repo_path):
        loaded_config = load_toml_config(config_path or "")
    if loaded_config:
        deep_merge(merged, loaded_config)
    if config:
        deep_merge(merged, config)
    return merged


def _run_checks(
    check_names: list[str],
    context: ValidationContext,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Run commit-check rules and return structured per-check results.

    Uses ValidationEngine.validate_all_detailed() which internally
    suppresses terminal output and collects structured failure details.
    """
    rules = RuleBuilder(config).build_all_rules()
    filtered: list[ValidationRule] = [r for r in rules if r.check in check_names]

    engine = ValidationEngine(filtered)
    outcomes: list[CheckOutcome] = engine.validate_all_detailed(context)
    checks = [o.to_dict() for o in outcomes]

    overall = "fail" if any(c["status"] == "fail" for c in checks) else "pass"
    return {"status": overall, "checks": checks}


def _validate_message(
    message: str,
    *,
    config: dict[str, Any] | None = None,
    repo_path: Path | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Validate message using commit-check engine internals."""
    cfg = _merge_config(config, repo_path=repo_path, config_path=config_path)
    with _working_directory(repo_path):
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
                "ai_attribution",
            ],
            ValidationContext(stdin_text=message, config=cfg),
            cfg,
        )


def _validate_branch(
    branch: str | None = None,
    *,
    config: dict[str, Any] | None = None,
    repo_path: Path | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Validate branch name using commit-check engine internals."""
    cfg = _merge_config(config, repo_path=repo_path, config_path=config_path)
    with _working_directory(repo_path):
        return _run_checks(
            ["branch", "merge_base"],
            ValidationContext(stdin_text=branch, config=cfg),
            cfg,
        )


def _validate_push(
    push_refs: str | None = None,
    *,
    config: dict[str, Any] | None = None,
    repo_path: Path | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Validate push ref updates against commit-check force-push protection."""
    cfg = _merge_config(config, repo_path=repo_path, config_path=config_path)
    cfg.setdefault("push", {})["allow_force_push"] = False
    with _working_directory(repo_path):
        return _run_checks(
            ["no_force_push"],
            ValidationContext(
                stdin_text=push_refs,
                config=cfg,
                push_upstream_fallback=push_refs is None,
            ),
            cfg,
        )


def _validate_author(
    name: str | None = None,
    email: str | None = None,
    *,
    config: dict[str, Any] | None = None,
    repo_path: Path | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Validate author info using commit-check engine internals."""
    cfg = _merge_config(config, repo_path=repo_path, config_path=config_path)

    with _working_directory(repo_path):
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
    repo_path: Path | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Validate multiple commit-check contexts and combine outcomes."""
    cfg = _merge_config(config, repo_path=repo_path, config_path=config_path)
    checks: list[dict[str, Any]] = []

    with _working_directory(repo_path):
        if message is not None:
            checks.extend(
                _run_checks(
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
                        "ai_attribution",
                    ],
                    ValidationContext(stdin_text=message, config=cfg),
                    cfg,
                )["checks"]
            )
        if branch is not None:
            checks.extend(
                _run_checks(
                    ["branch", "merge_base"],
                    ValidationContext(stdin_text=branch, config=cfg),
                    cfg,
                )["checks"]
            )
        if author_name is not None or author_email is not None:
            if author_name is not None:
                checks.extend(
                    _run_checks(
                        ["author_name"],
                        ValidationContext(stdin_text=author_name, config=cfg),
                        cfg,
                    )["checks"]
                )
            if author_email is not None:
                checks.extend(
                    _run_checks(
                        ["author_email"],
                        ValidationContext(stdin_text=author_email, config=cfg),
                        cfg,
                    )["checks"]
                )

    return {
        "status": "fail" if any(c["status"] == "fail" for c in checks) else "pass",
        "checks": checks,
    }


@mcp.tool()
def server_health() -> dict[str, str]:
    """Return server and dependency versions. Read-only, no side effects. Returns dict with server name, server version, commit-check version, and MCP SDK version. Useful as a first call to verify the server is running and check version compatibility."""
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
    repo_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Validate a commit message against commit-check rules. Read-only validation. Returns a structured result with overall status ('pass'/'fail') and a list of per-check results. Each check includes the check name, status, value, error message (on failure), and suggestion (on failure).

    Use this tool when you have a specific commit message string to validate. For batch validation of message, branch, and author together, use validate_commit_context instead.

    Parameters:
    - message (required): The commit message text to validate.
    - config (optional): Inline JSON config overrides on top of any loaded config file.
    - repo_path (optional): Path to the git repository for repo-relative config loading.
    - config_path (optional): Path to a custom commit-check TOML config file.
    """
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string")
    normalized_repo_path = _normalize_repo_path(repo_path)
    return _validate_message(
        message.strip(),
        config=_normalize_config(config),
        repo_path=normalized_repo_path,
        config_path=_normalize_config_path(config_path, normalized_repo_path),
    )


@mcp.tool()
def validate_branch_name(
    branch: str | None = None,
    config: dict[str, Any] | None = None,
    repo_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Validate branch naming conventions with commit-check. Read-only validation. Returns a structured result with overall status ('pass'/'fail') and per-check results (check name, status, value, error, suggest).

    Use this when you need to verify a branch name follows configured convention rules (e.g., feature/*, bugfix/*). For combined message+branch+author validation, use validate_commit_context.

    Parameters:
    - branch (optional): The branch name to validate. If omitted, detected from the current repo.
    - config (optional): Inline JSON config overrides.
    - repo_path (optional): Path to the git repository.
    - config_path (optional): Path to a custom commit-check TOML config file.
    """
    normalized_branch = branch.strip() if isinstance(branch, str) else None
    if isinstance(branch, str) and not normalized_branch:
        raise ValueError("branch cannot be empty when provided")
    normalized_repo_path = _normalize_repo_path(repo_path)
    return _validate_branch(
        normalized_branch,
        config=_normalize_config(config),
        repo_path=normalized_repo_path,
        config_path=_normalize_config_path(config_path, normalized_repo_path),
    )


@mcp.tool()
def validate_author_info(
    author_name: str | None = None,
    author_email: str | None = None,
    config: dict[str, Any] | None = None,
    repo_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Validate commit author name and/or email with commit-check. Read-only validation. Returns a structured result with overall status and per-check results (check name, status, value, error, suggest).

    Use this when you need to verify author metadata against configured rules (e.g., allowed email domains, name patterns). When both name and email are provided, both are validated. If neither is provided, both are checked against repo context. For combined validation, use validate_commit_context.

    Parameters:
    - author_name (optional): The author name to validate.
    - author_email (optional): The author email to validate.
    - config (optional): Inline JSON config overrides.
    - repo_path (optional): Path to the git repository.
    - config_path (optional): Path to a custom commit-check TOML config file.
    """
    normalized_name = author_name.strip() if isinstance(author_name, str) else None
    normalized_email = author_email.strip() if isinstance(author_email, str) else None

    if isinstance(author_name, str) and not normalized_name:
        raise ValueError("author_name cannot be empty when provided")
    if isinstance(author_email, str) and not normalized_email:
        raise ValueError("author_email cannot be empty when provided")
    normalized_repo_path = _normalize_repo_path(repo_path)

    return _validate_author(
        normalized_name,
        normalized_email,
        config=_normalize_config(config),
        repo_path=normalized_repo_path,
        config_path=_normalize_config_path(config_path, normalized_repo_path),
    )


@mcp.tool()
def validate_push_safety(
    push_refs: str | None = None,
    config: dict[str, Any] | None = None,
    repo_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Validate that a push is not a force push. Read-only validation. Returns a structured result with overall status and per-check results (check name, status, value, error, suggest). By default, force push is rejected; configure via 'push.allow_force_push' in config.

    Use this before performing a git push to ensure force-push protection rules are satisfied. Only validates the no_force_push rule. Use validate_commit_context for combined checks.

    Parameters:
    - push_refs (optional): The push ref specification to validate. If omitted, checks upstream fallback state.
    - config (optional): Inline JSON config overrides.
    - repo_path (optional): Path to the git repository.
    - config_path (optional): Path to a custom commit-check TOML config file.
    """
    normalized_push_refs = push_refs.strip() if isinstance(push_refs, str) else None
    normalized_repo_path = _normalize_repo_path(repo_path)
    return _validate_push(
        normalized_push_refs,
        config=_normalize_config(config),
        repo_path=normalized_repo_path,
        config_path=_normalize_config_path(config_path, normalized_repo_path),
    )


@mcp.tool()
def validate_commit_context(
    message: str | None = None,
    branch: str | None = None,
    author_name: str | None = None,
    author_email: str | None = None,
    config: dict[str, Any] | None = None,
    repo_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Run combined commit-check validations for message, branch, and/or author in one call. Read-only validation. Returns a structured result with overall status and a unified list of per-check results (check name, status, value, error, suggest).

    Use this when you need to validate multiple commit aspects simultaneously in a single call. At least one of message, branch, author_name, or author_email must be provided. For individual aspects, use the specific validate_commit_message, validate_branch_name, or validate_author_info tools.

    Parameters:
    - message (optional): Commit message text to validate.
    - branch (optional): Branch name to validate.
    - author_name (optional): Author name to validate.
    - author_email (optional): Author email to validate.
    - config (optional): Inline JSON config overrides on top of any loaded config file.
    - repo_path (optional): Path to the git repository for repo-relative config loading.
    - config_path (optional): Path to a custom commit-check TOML config file.
    """
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
    normalized_repo_path = _normalize_repo_path(repo_path)

    return _validate_all(
        message=normalized_message,
        branch=normalized_branch,
        author_name=normalized_name,
        author_email=normalized_email,
        config=_normalize_config(config),
        repo_path=normalized_repo_path,
        config_path=_normalize_config_path(config_path, normalized_repo_path),
    )


@mcp.tool()
def validate_repository_state(
    repo_path: str | None = None,
    config: dict[str, Any] | None = None,
    config_path: str | None = None,
    include_message: bool = True,
    include_branch: bool = True,
    include_author: bool = True,
    include_push: bool = False,
) -> dict[str, Any]:
    """Validate the current repository state including latest commit message, active branch, author metadata, and optional push safety. Read-only validation. Reads git data (message, branch, author) from the local repository. Returns a structured result with overall status and per-check results.

    Use this to validate the entire state of a local git repository in one call — ideal for pre-commit or CI hooks. Controls which checks run via boolean include_* flags. For validating arbitrary (non-repo) values, use validate_commit_context or individual validation tools instead.

    Parameters:
    - repo_path (optional): Path to the git repository. If omitted, uses current working directory.
    - config (optional): Inline JSON config overrides on top of any loaded config file.
    - config_path (optional): Path to a custom commit-check TOML config file.
    - include_message (optional, default true): Whether to validate the latest commit message.
    - include_branch (optional, default true): Whether to validate the current branch name.
    - include_author (optional, default true): Whether to validate the latest commit author.
    - include_push (optional, default false): Whether to validate push safety.
    """
    if not any([include_message, include_branch, include_author, include_push]):
        raise ValueError("At least one validation target must be enabled")

    normalized_repo_path = _normalize_repo_path(repo_path)
    normalized_config = _normalize_config(config)
    normalized_config_path = _normalize_config_path(config_path, normalized_repo_path)

    checks: list[dict[str, Any]] = []
    if include_message:
        checks.extend(
            _validate_message(
                "",
                config=normalized_config,
                repo_path=normalized_repo_path,
                config_path=normalized_config_path,
            )["checks"]
        )
    if include_branch:
        checks.extend(
            _validate_branch(
                None,
                config=normalized_config,
                repo_path=normalized_repo_path,
                config_path=normalized_config_path,
            )["checks"]
        )
    if include_author:
        checks.extend(
            _validate_author(
                None,
                None,
                config=normalized_config,
                repo_path=normalized_repo_path,
                config_path=normalized_config_path,
            )["checks"]
        )
    if include_push:
        checks.extend(
            _validate_push(
                None,
                config=normalized_config,
                repo_path=normalized_repo_path,
                config_path=normalized_config_path,
            )["checks"]
        )

    return {
        "status": "fail" if any(c["status"] == "fail" for c in checks) else "pass",
        "checks": checks,
    }


@mcp.tool()
def describe_validation_rules(
    config: dict[str, Any] | None = None,
    repo_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Return enabled commit-check rules after merging defaults, repo config, and inline overrides. Read-only, no side effects. Returns a dict with commit_check_version, the full merged config, supported check types, and enabled rules (each with check name, config, and pattern details).

    Use this to inspect which validation rules are currently active before running any validation. Helps debug rule configuration and check which checks will be applied.

    Parameters:
    - config (optional): Inline JSON config overrides on top of any loaded config file.
    - repo_path (optional): Path to the git repository for repo-relative config loading.
    - config_path (optional): Path to a custom commit-check TOML config file.
    """
    normalized_repo_path = _normalize_repo_path(repo_path)
    normalized_config = _normalize_config(config)
    normalized_config_path = _normalize_config_path(config_path, normalized_repo_path)
    merged_config = _merge_config(
        normalized_config,
        repo_path=normalized_repo_path,
        config_path=normalized_config_path,
    )
    rules = [rule.to_dict() for rule in RuleBuilder(merged_config).build_all_rules()]

    return {
        "commit_check_version": commit_check_version,
        "config": merged_config,
        "supported_checks": list(
            dict.fromkeys(
                entry.check for entry in COMMIT_RULES + BRANCH_RULES + PUSH_RULES
            )
        ),
        "enabled_rules": rules,
    }


def main(argv: list[str] | None = None) -> None:
    """Run the commit-check MCP server.

    Defaults to stdio for local MCP clients. ``--transport http`` serves
    stateless Streamable HTTP per the 2026-07-28 MCP specification: every
    tool here is a pure function of its inputs, so no request ever depends
    on an earlier one and any instance behind a plain load balancer can
    answer it. Statelessness is therefore not offered as a toggle — for
    this server it is simply true.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="commit-check-mcp")
    try:
        default_port = int(os.environ.get("MCP_PORT", "8000"))
    except ValueError:
        parser.error(f"MCP_PORT must be an integer, got {os.environ['MCP_PORT']!r}")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="stdio for local clients (default); http for a stateless remote server",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "127.0.0.1"),
        help="bind address for --transport http (default 127.0.0.1; use 0.0.0.0 in containers)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help="port for --transport http (default 8000)",
    )
    args = parser.parse_args(argv)

    # argparse does not check `choices` against env-supplied defaults, and a
    # typo in MCP_TRANSPORT must not silently fall back to stdio inside a
    # container that expects an HTTP listener.
    if args.transport not in ("stdio", "http"):
        parser.error(
            f"argument --transport: invalid choice: {args.transport!r}"
            " (choose from 'stdio', 'http')"
        )

    if args.transport == "http":
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            stateless_http=True,
            json_response=True,
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
