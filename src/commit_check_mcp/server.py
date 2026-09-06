"""MCP server for commit-check validations."""

from __future__ import annotations

from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
import os
import subprocess
from typing import Any

from commit_check import __version__ as commit_check_version
from commit_check.config_merger import deep_merge, get_default_config, load_toml_config
from commit_check.engine import ValidationContext, ValidationEngine, CheckOutcome
from commit_check.rule_builder import RuleBuilder, ValidationRule
from commit_check.rules_catalog import BRANCH_RULES, COMMIT_RULES, PUSH_RULES
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

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
        raise ToolError("config must be an object/dictionary when provided")
    return config


def _normalize_repo_path(repo_path: str | None) -> Path | None:
    """Normalize and validate an optional repository path."""
    if repo_path is None:
        return None
    if not isinstance(repo_path, str):
        raise ToolError("repo_path must be a string when provided")
    normalized = repo_path.strip()
    if not normalized:
        raise ToolError("repo_path cannot be empty when provided")

    path = Path(normalized).expanduser().resolve()
    if not path.exists():
        raise ToolError(f"repo_path does not exist: {path}")
    if not path.is_dir():
        raise ToolError(f"repo_path must be a directory: {path}")
    return path


def _require_git_repo(repo_path: Path | None) -> None:
    """Fail when the directory a git-backed check would run in is not a git work tree.

    commit-check reads the branch, author, HEAD message, and upstream through
    ``git``; outside a repository those reads come back empty and every rule
    passes vacuously, so tools that will consult git call this first.
    """
    directory = repo_path if repo_path is not None else Path.cwd()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        raise ToolError(f"git is not available to inspect repo_path {directory}: {e}") from e
    if result.returncode != 0:
        raise ToolError(f"repo_path is not a git repository: {directory}")


def _normalize_config_path(config_path: str | None, repo_path: Path | None) -> str | None:
    """Normalize and validate an optional config path."""
    if config_path is None:
        return None
    if not isinstance(config_path, str):
        raise ToolError("config_path must be a string when provided")
    normalized = config_path.strip()
    if not normalized:
        raise ToolError("config_path cannot be empty when provided")

    path = Path(normalized).expanduser()
    if not path.is_absolute() and repo_path is not None:
        path = repo_path / path

    resolved = path.resolve()
    if not resolved.exists():
        raise ToolError(f"config_path does not exist: {resolved}")
    if not resolved.is_file():
        raise ToolError(f"config_path must be a file: {resolved}")
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
    try:
        with _working_directory(repo_path):
            loaded_config = load_toml_config(config_path or "")
        if loaded_config:
            deep_merge(merged, loaded_config)
        if config:
            deep_merge(merged, config)
    except ValueError as e:
        # tomllib/tomli TOMLDecodeError subclasses ValueError, so this covers a
        # malformed config file as well as a value commit-check rejects.
        raise ToolError(f"invalid commit-check config: {e}") from e
    return merged


def _build_rules(config: dict[str, Any]) -> list[ValidationRule]:
    """Build commit-check rules, reporting a rejected config as a tool error."""
    try:
        return RuleBuilder(config).build_all_rules()
    except ValueError as e:
        raise ToolError(f"invalid commit-check config: {e}") from e


def _run_checks(
    check_names: list[str],
    context: ValidationContext,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Run commit-check rules and return structured per-check results.

    Uses ValidationEngine.validate_all_detailed() which internally
    suppresses terminal output and collects structured failure details.
    """
    rules = _build_rules(config)
    filtered: list[ValidationRule] = [r for r in rules if r.check in check_names]

    engine = ValidationEngine(filtered)
    outcomes: list[CheckOutcome] = engine.validate_all_detailed(context)
    checks = [o.to_dict() for o in outcomes]
    # commit-check names the corrected value in "fix" when a failure has an
    # unambiguous one. Older engines have no such field; give the key a
    # stable presence so an agent can always test it instead of probing for it.
    for check in checks:
        check.setdefault("fix", "")

    overall = "fail" if any(c["status"] == "fail" for c in checks) else "pass"
    return {"status": overall, "checks": checks}


def _validate_message(
    message: str | None,
    *,
    config: dict[str, Any] | None = None,
    repo_path: Path | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Validate message using commit-check engine internals.

    A ``None`` message makes commit-check read the latest commit (``git log -1``)
    in the working directory, as the CLI does when no message is supplied.
    """
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
    """Validate a commit message against commit-check rules. Read-only validation. Returns a structured result with overall status ('pass'/'fail') and a list of per-check results. Each check includes the check name, status, value, error message (on failure), suggestion (on failure), and fix: the corrected value when the correction is unambiguous (a type's case, a missing colon, a WIP marker, a missing sign-off), otherwise an empty string. Apply a non-empty fix as it stands; when fix is empty, rewrite from the suggestion.

    Use this tool when you have a specific commit message string to validate. For batch validation of message, branch, and author together, use validate_commit_context instead.

    Parameters:
    - message (required): The commit message text to validate.
    - config (optional): Inline JSON config overrides on top of any loaded config file.
    - repo_path (optional): Path to the git repository for repo-relative config loading.
    - config_path (optional): Path to a custom commit-check TOML config file.
    """
    if not isinstance(message, str) or not message.strip():
        raise ToolError("message must be a non-empty string")
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
    """Validate branch naming conventions with commit-check. Read-only validation. Returns a structured result with overall status ('pass'/'fail') and per-check results (check name, status, value, error, suggest, and fix: the corrected value when unambiguous, else empty).

    Use this when you need to verify a branch name follows configured convention rules (e.g., feature/*, bugfix/*). For combined message+branch+author validation, use validate_commit_context.

    Parameters:
    - branch (optional): The branch name to validate. If omitted, detected from the current repo.
    - config (optional): Inline JSON config overrides.
    - repo_path (optional): Path to the git repository.
    - config_path (optional): Path to a custom commit-check TOML config file.
    """
    normalized_branch = branch.strip() if isinstance(branch, str) else None
    if isinstance(branch, str) and not normalized_branch:
        raise ToolError("branch cannot be empty when provided")
    normalized_repo_path = _normalize_repo_path(repo_path)
    if normalized_branch is None:
        _require_git_repo(normalized_repo_path)
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
    """Validate commit author name and/or email with commit-check. Read-only validation. Returns a structured result with overall status and per-check results (check name, status, value, error, suggest, and fix: the corrected value when unambiguous, else empty).

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
        raise ToolError("author_name cannot be empty when provided")
    if isinstance(author_email, str) and not normalized_email:
        raise ToolError("author_email cannot be empty when provided")
    normalized_repo_path = _normalize_repo_path(repo_path)
    if normalized_name is None and normalized_email is None:
        _require_git_repo(normalized_repo_path)

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
    """Validate that a push is not a force push. Read-only validation. Returns a structured result with overall status and per-check results (check name, status, value, error, suggest, and fix: the corrected value when unambiguous, else empty). By default, force push is rejected; configure via 'push.allow_force_push' in config.

    Use this before performing a git push to ensure force-push protection rules are satisfied. Only validates the no_force_push rule. Use validate_commit_context for combined checks.

    Parameters:
    - push_refs (optional): The push ref specification to validate. If omitted, checks upstream fallback state. Must be non-empty when provided.
    - config (optional): Inline JSON config overrides.
    - repo_path (optional): Path to the git repository.
    - config_path (optional): Path to a custom commit-check TOML config file.
    """
    normalized_push_refs = push_refs.strip() if isinstance(push_refs, str) else None
    if isinstance(push_refs, str) and not normalized_push_refs:
        raise ToolError("push_refs cannot be empty when provided")
    normalized_repo_path = _normalize_repo_path(repo_path)
    if normalized_push_refs is None:
        _require_git_repo(normalized_repo_path)
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
    """Run combined commit-check validations for message, branch, and/or author in one call. Read-only validation. Returns a structured result with overall status and a unified list of per-check results (check name, status, value, error, suggest, and fix: the corrected value when unambiguous, else empty).

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
        raise ToolError("message cannot be empty when provided")
    if isinstance(branch, str) and not normalized_branch:
        raise ToolError("branch cannot be empty when provided")
    if isinstance(author_name, str) and not normalized_name:
        raise ToolError("author_name cannot be empty when provided")
    if isinstance(author_email, str) and not normalized_email:
        raise ToolError("author_email cannot be empty when provided")

    if not any([normalized_message, normalized_branch, normalized_name, normalized_email]):
        raise ToolError(
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
        raise ToolError("At least one validation target must be enabled")

    normalized_repo_path = _normalize_repo_path(repo_path)
    _require_git_repo(normalized_repo_path)
    normalized_config = _normalize_config(config)
    normalized_config_path = _normalize_config_path(config_path, normalized_repo_path)

    checks: list[dict[str, Any]] = []
    if include_message:
        checks.extend(
            _validate_message(
                None,
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
    rules = [rule.to_dict() for rule in _build_rules(merged_config)]

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


def main() -> None:
    """Run commit-check MCP server via stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
