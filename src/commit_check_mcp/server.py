"""MCP server for commit-check validations."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
import inspect
import os
import subprocess
from typing import Annotated, Any, TypeVar

from commit_check import __version__ as commit_check_version
from commit_check.config_merger import deep_merge, get_default_config, load_toml_config
from commit_check.engine import (
    CheckOutcome,
    ValidationContext,
    ValidationEngine,
    count_warnings,
    overall_status,
)
from commit_check.rule_builder import RuleBuilder, ValidationRule
from commit_check.rules_catalog import BRANCH_RULES, COMMIT_RULES, PUSH_RULES
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__

INSTRUCTIONS = (
    "commit-check-mcp validates commit messages, branch names, author metadata and push safety "
    "against commit-check rules. Every tool leaves your working tree and commits untouched; the "
    "two push checks may run git fetch to resolve SHAs.\n"
    "Workflow: (1) validate FIRST, before you commit or push, with the matching validate_* tool "
    "(pass repo_path so the repository's own cchk.toml/commit-check.toml is used). "
    "(2) Read the top-level status: only 'fail' is a rejection; 'skip' means nothing was validated "
    "(do not treat it as approval); 'warn' checks are reported but do not fail the run. "
    "(3) On 'fail', for each check with status 'fail': if its fix is non-empty, apply fix "
    "verbatim; otherwise rewrite the value following suggest (rule_id and docs_url point at the "
    "rule's docs). "
    "(4) Validate AGAIN with the corrected value and repeat until status is 'pass'. "
    "Use describe_validation_rules to see which rules are enabled before guessing at a format."
)

mcp = MCPServer("commit-check-mcp", instructions=INSTRUCTIONS, version=__version__)

# The result every validate_* tool returns, described once and spliced into each
# tool description where its docstring says ``{result_shape}``.
RESULT_SHAPE = (
    "Returns {status, warnings, checks[]}. status is 'pass', 'fail' or 'skip': only 'fail' is a "
    "rejection; 'skip' means every check skipped, so nothing was validated and the result is not "
    "approval. warnings is the number of checks with status 'warn'. Each check has: rule_id "
    "(stable rule id, e.g. 'CC001'); check (rule name, e.g. 'message'); status 'pass' | 'fail' | "
    "'warn' | 'skip' ('warn' = the config lists the check under warn, so the finding is reported "
    "without failing the run; 'skip' = the rule did not run, e.g. the author is in ignore_authors "
    "or there was nothing to check); value (what was checked); error (why it failed); suggest "
    "(advice for a person); fix (the corrected value when the correction is unambiguous, else ''); "
    "docs_url (documentation for the rule). On 'fail', apply a non-empty fix verbatim; when fix is "
    "'', rewrite following suggest; then validate again."
)

_F = TypeVar("_F", bound=Callable[..., Any])


def _tool(title: str, *, fetches: bool = False) -> Callable[[_F], _F]:
    """Register a commit-check tool with the hints every one of them shares.

    No tool changes the working tree or the commits, and repeating a call has
    no further effect, so every tool is idempotent and none is destructive.
    ``fetches`` marks the two that run the force-push check: to resolve a SHA it
    does not know locally it may run ``git fetch``, which reaches the network
    and updates FETCH_HEAD and remote-tracking refs, so those two are neither
    read-only nor closed-world. The function docstring becomes the tool
    description, with ``{result_shape}`` replaced by :data:`RESULT_SHAPE`.
    """
    annotations = ToolAnnotations(
        readOnlyHint=not fetches,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=fetches,
    )

    def register(fn: _F) -> _F:
        description = inspect.cleandoc(fn.__doc__ or "").replace("{result_shape}", RESULT_SHAPE)
        return mcp.tool(title=title, description=description, annotations=annotations)(fn)

    return register


# Parameter types shared by the tools; the Field description reaches the tool's
# JSON schema, which is what an MCP client shows the model.
ConfigParam = Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            "Inline commit-check config overrides as a JSON object, merged on top of the built-in "
            'defaults and any config file, e.g. {"warn": ["message"]} or '
            '{"commit": {"require_body": true}}.'
        )
    ),
]
RepoPathParam = Annotated[
    str | None,
    Field(
        description=(
            "Path to the git repository to validate against. Its cchk.toml or commit-check.toml "
            "(also looked up under .github/) is loaded, and a relative config_path is resolved "
            "from it. Omit to use the server's working directory."
        )
    ),
]
ConfigPathParam = Annotated[
    str | None,
    Field(
        description=(
            "Path to a commit-check TOML config file, used instead of the repository's own "
            "cchk.toml/commit-check.toml; a relative path is resolved from repo_path."
        )
    ),
]
MessageParam = Annotated[
    str,
    Field(
        description=(
            "Full commit message text to validate: subject line, optional blank line, body "
            "(and trailers such as Signed-off-by). Must be non-empty."
        )
    ),
]
OptionalMessageParam = Annotated[
    str | None,
    Field(
        description=(
            "Commit message text to validate: subject line, optional blank line, body. Omit to "
            "skip the message checks. Must be non-empty when provided."
        )
    ),
]
BranchParam = Annotated[
    str | None,
    Field(
        description=(
            "Branch name to validate, e.g. 'feature/login'. Omit to validate the branch currently "
            "checked out in repo_path, which must then be a git repository. Must be non-empty when "
            "provided."
        )
    ),
]
AuthorNameParam = Annotated[
    str | None,
    Field(
        description=(
            "Author name to validate, e.g. 'Alice Example'. Omit to read it from repo_path "
            "(git config user.name, falling back to the latest commit's author). Must be "
            "non-empty when provided."
        )
    ),
]
AuthorEmailParam = Annotated[
    str | None,
    Field(
        description=(
            "Author email to validate, e.g. 'alice@example.com'. Omit to read it from repo_path "
            "(git config user.email, falling back to the latest commit's author). Must be "
            "non-empty when provided."
        )
    ),
]
PushRefsParam = Annotated[
    str | None,
    Field(
        description=(
            "Refs about to be pushed, in git pre-push hook stdin format, one ref per line: "
            "'<local_ref> <local_sha> <remote_ref> <remote_sha>', e.g. "
            "'refs/heads/main 1a2b3c... refs/heads/main 9f8e7d...'. A remote_sha of 40 zeros "
            "means a new branch (never a force push). Every other SHA must resolve to a commit in "
            "repo_path (the check runs git merge-base and may fetch the remote ref first); a SHA "
            "that still cannot be resolved is a tool error, not a pass, so fetch it first. Omit to "
            "check the current branch of repo_path against its upstream instead. Must be non-empty "
            "when provided."
        )
    ),
]


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
    return _summarize([o.to_dict() for o in outcomes])


def _summarize(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap per-check results in the shape every validation tool returns.

    The overall ``status`` comes from commit-check's own reducer, so a run in
    which every check skipped is reported as ``"skip"`` rather than ``"pass"``:
    nothing was validated, and an agent must not read that as approval. A
    ``"warn"`` is a finding the config asked to report without enforcing; it
    leaves ``status`` at ``"pass"`` and is counted in ``warnings``.
    """
    statuses = [c["status"] for c in checks]
    return {
        "status": overall_status(statuses),
        "warnings": count_warnings(statuses),
        "checks": checks,
    }


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


ZERO_SHA = "0" * 40


def _require_push_shas_resolvable(push_refs: str) -> None:
    """Fail when a pushed SHA is not a commit in the current working directory.

    The force-push rule asks ``git merge-base`` whether the remote SHA is an
    ancestor of the local one. When either SHA is unknown, git exits 128 and,
    after commit-check's own attempt to fetch the remote ref, the rule falls
    through to PASS. Nothing was judged in that case, so the pass must not
    reach the caller. This runs after the rule, so a SHA the rule's fetch
    brought in counts as resolved. The 40-zero placeholder for a new branch is
    not a commit and is skipped.
    """
    for line in push_refs.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        for sha in (parts[1], parts[3]):
            if sha == ZERO_SHA:
                continue
            try:
                result = subprocess.run(
                    ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except OSError as e:
                raise ToolError(f"git is not available to inspect push_refs: {e}") from e
            if result.returncode != 0:
                raise ToolError(
                    f"push_refs: {sha} is not a commit in the repository; fetch it first, "
                    "the force-push check cannot be judged"
                )


def _validate_push(
    push_refs: str | None = None,
    *,
    config: dict[str, Any] | None = None,
    repo_path: Path | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Validate push ref updates against commit-check force-push protection.

    With explicit ``push_refs``, a pass is only returned once every SHA in
    them has been confirmed to be a commit in the repository; the
    upstream-fallback path (``push_refs`` is ``None``) reads HEAD and the
    upstream ref, which always resolve.
    """
    cfg = _merge_config(config, repo_path=repo_path, config_path=config_path)
    cfg.setdefault("push", {})["allow_force_push"] = False
    with _working_directory(repo_path):
        result = _run_checks(
            ["no_force_push"],
            ValidationContext(
                stdin_text=push_refs,
                config=cfg,
                push_upstream_fallback=push_refs is None,
            ),
            cfg,
        )
        if push_refs and result["status"] != "fail":
            _require_push_shas_resolvable(push_refs)
    return result


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
            return _summarize(name_result["checks"] + email_result["checks"])

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

    return _summarize(checks)


@_tool("Server health")
def server_health() -> dict[str, str]:
    """Return server and dependency versions. Read-only, no side effects.

    Returns {server, server_version, commit_check_version, mcp_sdk_version}. Useful as a first call
    to verify the server is running and to check version compatibility.
    """
    return {
        "server": "commit-check-mcp",
        "server_version": __version__,
        "commit_check_version": commit_check_version,
        "mcp_sdk_version": version("mcp"),
    }


@_tool("Validate commit message")
def validate_commit_message(
    message: MessageParam,
    config: ConfigParam = None,
    repo_path: RepoPathParam = None,
    config_path: ConfigPathParam = None,
) -> dict[str, Any]:
    """Validate a commit message against commit-check rules (Conventional Commits type and format,
    subject length and case, body, sign-off, WIP/fixup markers, AI attribution: whatever the
    effective config enables). Read-only; touches no git state.

    {result_shape}

    Use this when you have one commit message string to check before committing. To check message,
    branch and author in one call use validate_commit_context; to check the latest commit already
    in a repository use validate_repository_state.
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


@_tool("Validate branch name")
def validate_branch_name(
    branch: BranchParam = None,
    config: ConfigParam = None,
    repo_path: RepoPathParam = None,
    config_path: ConfigPathParam = None,
) -> dict[str, Any]:
    """Validate a branch name against the configured naming convention (e.g. feature/*, bugfix/*)
    and, when configured, that the branch is based on the required merge base. Read-only.

    {result_shape}

    Use this before creating or pushing a branch. Omit branch to check the branch currently checked
    out in repo_path. For combined message+branch+author validation use validate_commit_context.
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


@_tool("Validate author info")
def validate_author_info(
    author_name: AuthorNameParam = None,
    author_email: AuthorEmailParam = None,
    config: ConfigParam = None,
    repo_path: RepoPathParam = None,
    config_path: ConfigPathParam = None,
) -> dict[str, Any]:
    """Validate a commit author's name and/or email against the configured rules (e.g. allowed
    email domains, name patterns). Read-only.

    {result_shape}

    Use this to check author metadata before committing. Only the values you pass are checked; if
    neither is given, both are read from repo_path's git config (falling back to the latest commit)
    and repo_path must be a git repository. For combined validation use validate_commit_context.
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


@_tool("Validate push safety", fetches=True)
def validate_push_safety(
    push_refs: PushRefsParam = None,
    config: ConfigParam = None,
    repo_path: RepoPathParam = None,
    config_path: ConfigPathParam = None,
) -> dict[str, Any]:
    """Check that a pending push is not a force push (rule CC301, no_force_push): fails when a
    remote_sha is not an ancestor of its local_sha, i.e. the push would rewrite remote history.
    Leaves your working tree and commits untouched, but may run `git fetch <remote> <ref>` to
    resolve SHAs, which updates FETCH_HEAD and remote-tracking refs. A SHA that cannot be resolved
    even then is a tool error, never a pass. Force pushes are always rejected by this tool;
    push.allow_force_push in config cannot re-enable them here.

    {result_shape}

    Call this before `git push`. Only the no_force_push rule runs. When it fails there is no
    automatic fix (fix is ''): follow suggest, i.e. push without --force/--force-with-lease or
    rebase onto the remote first, then validate again.
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


@_tool("Validate commit context")
def validate_commit_context(
    message: OptionalMessageParam = None,
    branch: BranchParam = None,
    author_name: AuthorNameParam = None,
    author_email: AuthorEmailParam = None,
    config: ConfigParam = None,
    repo_path: RepoPathParam = None,
    config_path: ConfigPathParam = None,
) -> dict[str, Any]:
    """Run the commit message, branch name and author checks together in one call, for whichever of
    message, branch, author_name and author_email you pass. Read-only.

    {result_shape}

    Use this to validate several aspects of a commit you are about to make with a single call. At
    least one of message, branch, author_name or author_email is required; omitted aspects are not
    checked. For one aspect use validate_commit_message, validate_branch_name or
    validate_author_info; for the commit already at HEAD use validate_repository_state.
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


@_tool("Validate repository state", fetches=True)
def validate_repository_state(
    repo_path: Annotated[
        str | None,
        Field(
            description=(
                "Path to the git repository to inspect; its cchk.toml or commit-check.toml is "
                "loaded and a relative config_path is resolved from it. Omit to use the server's "
                "working directory, which must then be a git repository."
            )
        ),
    ] = None,
    config: ConfigParam = None,
    config_path: ConfigPathParam = None,
    include_message: Annotated[
        bool,
        Field(description="Validate the message of the latest commit (HEAD). Default true."),
    ] = True,
    include_branch: Annotated[
        bool,
        Field(description="Validate the name of the currently checked-out branch. Default true."),
    ] = True,
    include_author: Annotated[
        bool,
        Field(
            description=(
                "Validate the author name and email of the latest commit (falling back to git "
                "config user.name/user.email). Default true."
            )
        ),
    ] = True,
    include_push: Annotated[
        bool,
        Field(
            description=(
                "Also check that pushing the current branch to its upstream would not be a "
                "force push; may run git fetch (updating FETCH_HEAD), and passes when the branch "
                "has no upstream. Default false."
            )
        ),
    ] = False,
) -> dict[str, Any]:
    """Validate what is already in a local git repository: the latest commit's message and author,
    the checked-out branch name and, optionally, whether pushing that branch to its upstream would
    be a force push. Leaves the working tree and commits untouched; the push check may run
    `git fetch`, which updates FETCH_HEAD and remote-tracking refs.

    {result_shape}

    Use this to check a repository's current state in one call, e.g. after committing and before
    pushing, or in a hook. The include_* flags select the checks; at least one must be true. To
    validate values that are not yet committed use validate_commit_context or the single-aspect
    tools.
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

    return _summarize(checks)


@_tool("Describe validation rules")
def describe_validation_rules(
    config: ConfigParam = None,
    repo_path: RepoPathParam = None,
    config_path: ConfigPathParam = None,
) -> dict[str, Any]:
    """Return the commit-check rules that are in effect after merging the built-in defaults, the
    repository's config file (or config_path) and the inline config overrides. Read-only, no side
    effects.

    Returns {commit_check_version, config (the merged config), supported_checks (every check name
    commit-check knows), enabled_rules[]} where each enabled rule carries its check name, config
    and pattern details.

    Use this before writing a commit message or branch name to learn the expected format instead
    of guessing, and to debug why a validation failed or was skipped.
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
