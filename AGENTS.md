# AGENTS.md — AI Coding Agent Instructions

> This file tells AI coding agents (Claude Code, Cursor, Copilot, etc.) how to use
> `commit-check-mcp` effectively when validating commits in this repository.

## What commit-check-mcp does for you

`commit-check-mcp` is an MCP server that exposes structured commit validation tools. As
an AI agent, you can call these tools to validate:

- **Commit messages** — Conventional Commits format, subject length, imperative mood, etc.
- **Branch names** — Naming conventions (feature/, bugfix/, hotfix/, etc.)
- **Author info** — Name and email format validation
- **Push safety** — Force-push detection for pre-push hooks
- **Repository state** — Combined validation of all the above in one call
- **Validation rules** — Inspect the effective config (defaults + repo config + overrides)

## Installing in your MCP client

```json
{
  "mcpServers": {
    "commit-check": {
      "command": "commit-check-mcp"
    }
  }
}
```

Or with `uvx` (no install needed):

```json
{
  "mcpServers": {
    "commit-check": {
      "command": "uvx",
      "args": ["commit-check-mcp"]
    }
  }
}
```

## When to call each tool

### Before creating a commit → `validate_commit_message`

Always call this **before** writing a commit message. Pass the message you intend to use:

```
Tool: validate_commit_message
Args: { "message": "feat(api): add user authentication endpoint" }
```

If it returns `"status": "fail"`, read the `checks[].suggest` field and fix the message
before committing. Never commit a message that fails validation.

### Before creating a branch → `validate_branch_name`

When you need to create a new branch, validate the name first:

```
Tool: validate_branch_name
Args: { "branch": "feature/user-auth" }
```

### After switching to a repo → `describe_validation_rules`

On first entering a repository, inspect what rules are enforced:

```
Tool: describe_validation_rules
Args: { "repo_path": "/path/to/repo" }
```

This tells you which checks are active so you can comply from the start.

### Before pushing → `validate_push_safety`

If the repo has pre-push hooks configured, validate push safety:

```
Tool: validate_push_safety
Args: { "repo_path": "/path/to/repo" }
```

### Full state check → `validate_repository_state`

For a comprehensive check of the current repo state:

```
Tool: validate_repository_state
Args: { "repo_path": "/path/to/repo" }
```

## Understanding responses

All validation tools return this shape:

```json
{
  "status": "pass|fail",
  "checks": [
    {
      "check": "message",
      "status": "pass|fail",
      "value": "the input that was checked",
      "error": "reason for failure (only on fail)",
      "suggest": "how to fix it (only on fail)"
    }
  ]
}
```

### When a check fails

1. Read `error` to understand what went wrong
2. Read `suggest` for the recommended fix
3. Apply the fix and re-validate
4. Only proceed when `status` is `"pass"`

### Config precedence

When both `repo_path` and `config` are provided:

1. commit-check built-in defaults
2. `cchk.toml` / `commit-check.toml` from the repo
3. Explicit `config_path` if given
4. Inline `config` overrides (highest priority)

## Best practices for AI agents

1. **Validate early, validate often** — check commit messages before writing them, not after
2. **Don't bypass failures** — if a check fails, fix it; never force-push or skip hooks
3. **Use the suggest field** — it contains the exact fix needed
4. **Check rules first** — call `describe_validation_rules` when entering a new repo
5. **Prefer `validate_repository_state`** for a comprehensive check in one call
