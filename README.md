# commit-check-mcp

[![PyPI version](https://img.shields.io/pypi/v/commit-check-mcp)](https://pypi.org/project/commit-check-mcp/)
[![Python versions](https://img.shields.io/pypi/pyversions/commit-check-mcp)](https://pypi.org/project/commit-check-mcp/)
[![Build](https://github.com/commit-check/commit-check-mcp/actions/workflows/main.yml/badge.svg)](https://github.com/commit-check/commit-check-mcp/actions/workflows/main.yml)
[![Coverage](https://codecov.io/gh/commit-check/commit-check-mcp/graph/badge.svg)](https://codecov.io/gh/commit-check/commit-check-mcp)
[![MCP server](https://img.shields.io/badge/MCP-server-0A7B83)](https://modelcontextprotocol.io/)

Model Context Protocol (MCP) server for [commit-check](https://github.com/commit-check/commit-check).

`commit-check-mcp` exposes `commit-check` as local MCP tools so an MCP client can validate commit messages, branch names, author info, and repository state.

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

## Installation

```bash
pip install commit-check-mcp
```

This installs the `commit-check-mcp` CLI entrypoint.

For local development from this repository:

```bash
pip install -e .
```

## Use With An MCP Client

This server runs over stdio, so it is meant to be launched by an MCP client rather than used as a long-running HTTP service.

Generic MCP client config:

```json
{
  "mcpServers": {
    "commit-check": {
      "command": "commit-check-mcp"
    }
  }
}
```

If the client needs the full path to the executable, first locate it:

```bash
which commit-check-mcp
```

Then use that absolute path in the client config.

Example using an absolute path:

```json
{
  "mcpServers": {
    "commit-check": {
      "command": "/absolute/path/to/commit-check-mcp"
    }
  }
}
```

For local development from this repository, that absolute path may point to something like `.venv/bin/commit-check-mcp`.

## Run Manually

```bash
commit-check-mcp
```

The server uses stdio transport, which is the recommended MCP default for local tool integrations.

## Tool Usage

After the client starts the server, it will expose these tools:

- `server_health`: returns server, SDK, and dependency versions
- `validate_commit_message(message, config?, repo_path?, config_path?)`
- `validate_branch_name(branch?, config?, repo_path?, config_path?)`
- `validate_author_info(author_name?, author_email?, config?, repo_path?, config_path?)`
- `validate_commit_context(message?, branch?, author_name?, author_email?, config?, repo_path?, config_path?)`
- `validate_repository_state(repo_path?, config?, config_path?, include_message?, include_branch?, include_author?)`
- `describe_validation_rules(config?, repo_path?, config_path?)`

The common optional arguments are:

- `repo_path`: repository directory to validate against
- `config_path`: explicit TOML config file; relative paths resolve from `repo_path`
- `config`: ad-hoc config overrides merged on top of defaults and repo config

## Common Examples

Validate a commit message using repo-local rules:

```json
{
  "message": "feat(api): add MCP validation tool",
  "repo_path": "/path/to/repo"
}
```

Validate the current repository branch using an explicit config file:

```json
{
  "repo_path": "/path/to/repo",
  "config_path": ".github/commit-check.toml"
}
```

Validate the full repository state:

```json
{
  "repo_path": "/path/to/repo",
  "include_message": true,
  "include_branch": true,
  "include_author": true
}
```

Inspect the final merged rules that will be applied:

```json
{
  "repo_path": "/path/to/repo",
  "config": {
    "commit": {
      "require_body": true
    }
  }
}
```

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

Config precedence is:

1. `commit-check` built-in defaults
2. repository config loaded from `repo_path`
3. `config_path` when explicitly provided
4. inline `config` overrides passed to the tool
