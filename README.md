# commit-check-mcp

[![PyPI version](https://img.shields.io/pypi/v/commit-check-mcp)](https://pypi.org/project/commit-check-mcp/)
[![Python versions](https://img.shields.io/pypi/pyversions/commit-check-mcp)](https://pypi.org/project/commit-check-mcp/)
[![Build](https://github.com/commit-check/commit-check-mcp/actions/workflows/main.yml/badge.svg)](https://github.com/commit-check/commit-check-mcp/actions/workflows/main.yml)
[![Coverage](https://codecov.io/gh/commit-check/commit-check-mcp/graph/badge.svg)](https://codecov.io/gh/commit-check/commit-check-mcp)
[![MCP server](https://img.shields.io/badge/MCP-server-0A7B83)](https://modelcontextprotocol.io/)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-io.github.commit--check/commit--check--mcp-7B3F00)](https://registry.modelcontextprotocol.io/?q=commit-check-mcp)
[![Glama](https://img.shields.io/badge/Glama-commit--check--mcp-blue)](https://glama.ai/mcp/servers/github/commit-check/commit-check-mcp)

Model Context Protocol (MCP) server for [commit-check](https://github.com/commit-check/commit-check).

`commit-check-mcp` exposes `commit-check` as local MCP tools so an MCP client can validate commit messages, branch names, author info, push safety, and repository state.

## Features

This MCP server exposes commit-check validations as MCP tools:

- `server_health` — returns server/sdk versions
- `validate_commit_message` — validates a commit message
- `validate_branch_name` — validates a branch name or the current repo branch
- `validate_push_safety` — validates that a push is not a force push
- `validate_author_info` — validates author name/email or the repo's git author config
- `validate_commit_context` — runs combined checks in one call
- `validate_repository_state` — validates latest commit, current branch, author state, and optional push safety for a repo
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
      "suggest": "...",
      "fix": "..."
    }
  ]
}
```

`suggest` is the advice a person reads. `fix` is the corrected value itself,
present only when the correction is unambiguous — `Fix: add x` comes back with
`"fix": "fix: add x"` — and an empty string otherwise, so an agent can apply
a non-empty `fix` as it stands and fall back to `suggest` when it is empty.
Populating `fix` needs a commit-check release that carries the field; with an
older commit-check the key is present and always empty.

A call that cannot run at all — an empty `message`, a `repo_path` that does not
exist, a `repo_path` that is not a git repository when the tool has to read git
state (see the `repo_path` note under [Tool Usage](#tool-usage)), a malformed or rejected
commit-check config — is returned as an MCP tool error (`is_error`) whose text
names the problem, for example `repo_path is not a git repository: /path/to/dir`
or `invalid commit-check config: ...`, rather than as a `pass`/`fail` result.

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

With `uvx` (recommended — no install needed):

```bash
# Run once, no pip install required
uvx commit-check-mcp
```

> **Tip**: If `uv` is not installed, get it via `curl -LsSf https://astral.sh/uv/install.sh | sh`.

---

### Claude Desktop

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

### Claude Code CLI

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

Add to your `~/.claude/settings.json` or project-level `.claude/settings.local.json`.

### Cursor

In Cursor, go to **Settings → Cursor Settings → MCP → Add new MCP server** and paste:

| Field | Value |
|---|---|
| **Name** | `commit-check` |
| **Type** | `command` |
| **Command** | `uvx commit-check-mcp` |

Or add to your project's `.cursor/mcp.json`:

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

### Windsurf

Add to your `~/.codeium/windsurf/mcp_config.json`:

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

### Cline (VS Code)

Add a new MCP server in the Cline extension settings:

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

### Continue.dev (VS Code / JetBrains)

Add to your `~/.continue/config.json`:

```json
{
  "experimental": {
    "mcpServers": {
      "commit-check": {
        "command": "uvx",
        "args": ["commit-check-mcp"]
      }
    }
  }
}
```

### Roo Code

Add to your Roo Code MCP settings:

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

### Zed

Add to your `~/.config/zed/settings.json`:

```json
{
  "mcp_servers": {
    "commit-check": {
      "command": "uvx",
      "args": ["commit-check-mcp"]
    }
  }
}
```

### Generic / Any MCP Client

If your client does not support `uvx`, use `pip` and the direct path:

```bash
pip install commit-check-mcp
which commit-check-mcp
```

Then use the absolute path in your config:

```json
{
  "mcpServers": {
    "commit-check": {
      "command": "/path/to/commit-check-mcp"
    }
  }
}
```

## Run Manually

```bash
# If installed via pip
commit-check-mcp

# Or via uvx (no install needed)
uvx commit-check-mcp
```

The server uses stdio transport, which is the recommended MCP default for local tool integrations.

## Tool Usage

After the client starts the server, it will expose these tools:

- `server_health`: returns server, SDK, and dependency versions
- `validate_commit_message(message, config?, repo_path?, config_path?)`
- `validate_branch_name(branch?, config?, repo_path?, config_path?)`
- `validate_push_safety(push_refs?, config?, repo_path?, config_path?)`
- `validate_author_info(author_name?, author_email?, config?, repo_path?, config_path?)`
- `validate_commit_context(message?, branch?, author_name?, author_email?, config?, repo_path?, config_path?)`
- `validate_repository_state(repo_path?, config?, config_path?, include_message?, include_branch?, include_author?, include_push?)`
- `describe_validation_rules(config?, repo_path?, config_path?)`

The common optional arguments are:

- `repo_path`: repository directory to validate against; it must be a git repository when the tool reads git state (branch, author, or push refs omitted, or `validate_repository_state`), and may be a plain directory holding a config file when every value is supplied
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

Validate push safety from git pre-push hook ref metadata (`push_refs` must be non-empty when given; omit it to check the current branch against its upstream):

```json
{
  "repo_path": "/path/to/repo",
  "push_refs": "refs/heads/main abc123 refs/heads/main def456"
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
- Validate the current repository state — the latest commit's message and author, and the current branch — without passing message/branch/author values manually
- Validate push safety using pre-push ref metadata, or check the current branch against its upstream
- Inspect which rules are actually enabled after config merging

Example payload for a repository-wide validation:

```json
{
  "repo_path": "/path/to/repo",
  "include_message": true,
  "include_branch": true,
  "include_author": true,
  "include_push": true
}
```

Config precedence is:

1. `commit-check` built-in defaults
2. repository config loaded from `repo_path`
3. `config_path` when explicitly provided
4. inline `config` overrides passed to the tool

## Published On

| Directory | Link |
|---|---|
| **Official MCP Registry** | [`io.github.commit-check/commit-check-mcp`](https://registry.modelcontextprotocol.io/?q=commit-check-mcp) |
| **Glama.ai** | [`github/commit-check/commit-check-mcp`](https://glama.ai/mcp/servers/github/commit-check/commit-check-mcp) |
| **PyPI** | [`commit-check-mcp`](https://pypi.org/project/commit-check-mcp/) |

---

<!-- Required by MCP Registry for PyPI package ownership validation -->
<!-- https://registry.modelcontextprotocol.io -->
<sub>mcp-name: io.github.commit-check/commit-check-mcp</sub>
