# commit-check-mcp

Model Context Protocol (MCP) server for [commit-check](https://github.com/commit-check/commit-check).

## Features

This MCP server exposes commit-check validations as MCP tools:

- `server_health` — returns server/sdk versions
- `validate_commit_message` — validates a commit message
- `validate_branch_name` — validates a branch name or the current repo branch
- `validate_author_info` — validates author name/email or the repo's git author config
- `validate_commit_context` — runs combined checks in one call
- `validate_repository_state` — validates latest commit, current branch, and author state for a repo
- `describe_validation_rules` — returns the effective config and enabled rules after merging defaults and repo config

All validation tools return the same structured commit-check result shape:

```json
{
  "status": "pass|fail",
  "checks": [
    {
      "check": "message",
      "status": "pass|fail",
      "value": "...",
      "error": "...",
      "suggest": "..."
    }
  ]
}
```

## Install

```bash
pip install -e .
```

## Run

```bash
commit-check-mcp
```

The server runs over stdio transport (recommended MCP default for local tool integrations).

## Repository-Aware Validation

`commit-check` is most useful when it runs against a real git repository and its `cchk.toml` or `commit-check.toml` file. This MCP server now supports that directly:

- `repo_path` — run git-based validations against a specific repository
- `config_path` — point to an explicit TOML config file; relative paths are resolved from `repo_path`
- `config` — apply ad-hoc overrides on top of defaults and repo config

Typical patterns:

- Validate an explicit message with a repository's rules
- Validate the current repository state without passing message/branch/author values manually
- Inspect which rules are actually enabled after config merging

Example payload for a repository-wide validation:

```json
{
  "repo_path": "/path/to/repo",
  "include_message": true,
  "include_branch": true,
  "include_author": true
}
```
