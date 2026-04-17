# commit-check-mcp

Model Context Protocol (MCP) server for [commit-check](https://github.com/commit-check/commit-check).

## Features

This MCP server exposes commit-check validations as MCP tools:

- `server_health` — returns server/sdk versions
- `validate_commit_message` — validates a commit message
- `validate_branch_name` — validates a branch name
- `validate_author_info` — validates author name/email
- `validate_commit_context` — runs combined checks in one call

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
