<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/commit-check/.github/main/branding/banner-dark.png">
  <img src="https://raw.githubusercontent.com/commit-check/.github/main/branding/banner-light.png" alt="Commit Check">
</picture>

**Catch bad commits before they merge — inside your AI agent.**

[![PyPI](https://img.shields.io/pypi/v/commit-check-mcp?labelColor=0b1620&logo=pypi&logoColor=white&color=2c9ccd)](https://pypi.org/project/commit-check-mcp/)
[![CI](https://img.shields.io/github/actions/workflow/status/commit-check/commit-check-mcp/main.yml?branch=main&labelColor=0b1620&label=CI)](https://github.com/commit-check/commit-check-mcp/actions/workflows/main.yml)
[![Coverage](https://img.shields.io/codecov/c/github/commit-check/commit-check-mcp?labelColor=0b1620&color=2c9ccd&label=coverage)](https://codecov.io/gh/commit-check/commit-check-mcp)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-listed-2c9ccd?labelColor=0b1620)](https://registry.modelcontextprotocol.io/?q=commit-check-mcp)
[![Glama](https://img.shields.io/badge/Glama-listed-2c9ccd?labelColor=0b1620)](https://glama.ai/mcp/servers/commit-check/commit-check-mcp)

[Docs](https://commit-check.com/guides/mcp/) ·
[Rules](https://commit-check.com/rules/) ·
[CLI](https://github.com/commit-check/commit-check) ·
[GitHub Action](https://github.com/commit-check/commit-check-action) ·
[GitHub App](https://github.com/apps/commit-check)

</div>

The [Model Context Protocol](https://modelcontextprotocol.io/) server for
[Commit Check](https://github.com/commit-check/commit-check). It gives your
coding agent the rules your CI enforces: the agent validates its commit
message, branch name and author before it commits or pushes, and when a
correction is unambiguous it gets the fix to apply.

## Quick start

```bash
claude mcp add commit-check -- uvx commit-check-mcp
```

Every other client launches the same command. This is the object to register:

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

No `uv` yet? `curl -LsSf https://astral.sh/uv/install.sh | sh` — or use
`pip install commit-check-mcp`, as in the last row below.

### Where each client keeps it

| Client | Where it goes | Notes |
|---|---|---|
| Claude Code | `claude mcp add commit-check -- uvx commit-check-mcp` | Add `--scope project` to write a shareable `.mcp.json` at the repo root (`--scope user` makes it available in all your projects). You can also commit a `.mcp.json` containing the block above; `"type": "stdio"` may be added inside the server object. MCP servers are **not** configured in `~/.claude/settings.json`. |
| Claude Desktop | macOS `~/Library/Application Support/Claude/claude_desktop_config.json`; Windows `%APPDATA%\Claude\claude_desktop_config.json` | Block above as-is; restart Claude Desktop. |
| Cursor | project `.cursor/mcp.json` or global `~/.cursor/mcp.json` | Block above as-is (or **Settings → Cursor Settings → MCP → Add new MCP server** with command `uvx commit-check-mcp`). |
| VS Code (Copilot agent mode) | `.vscode/mcp.json` | **Different key**: `{"servers": {"commit-check": {"type": "stdio", "command": "uvx", "args": ["commit-check-mcp"]}}}` |
| Cline | MCP Servers panel → Configure → `cline_mcp_settings.json` (check your client's docs) | Block above as-is. |
| Roo Code | project `.roo/mcp.json` or global `mcp_settings.json` (**Edit Global MCP**) | Block above as-is; optional `"alwaysAllow": [...]`. |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` (check your client's docs) | Block above as-is. |
| Continue | `config.yaml` (or a file in `.continue/mcpServers/`) | **YAML list** under `mcpServers:`, see below. Continue also picks up the JSON block above when dropped into `.continue/mcpServers/`. |
| Zed | `~/.config/zed/settings.json` | **Different key**: `{"context_servers": {"commit-check": {"command": "uvx", "args": ["commit-check-mcp"]}}}` |
| Anything else | your client's MCP config | If the client cannot run `uvx`: `pip install commit-check-mcp`, then set `"command"` to the absolute path of the installed binary and drop `args`. Find it with `which commit-check-mcp` (macOS/Linux), `where commit-check-mcp` (Windows cmd) or `Get-Command commit-check-mcp \| Select-Object -ExpandProperty Source` (PowerShell). |

Continue's `config.yaml` entry in full (`name`, `version` and `schema` are required by Continue; drop them if you are adding only the `mcpServers` fragment to an existing file, or save this as a standalone file in `.continue/mcpServers/`):

```yaml
name: commit-check
version: 0.0.1
schema: v1
mcpServers:
  - name: commit-check
    command: uvx
    args: ["commit-check-mcp"]
```

## Tools

| Tool | What it checks | Arguments |
|---|---|---|
| `validate_commit_message` | A commit message: Conventional Commits, subject length and case, body, sign-off, WIP and fixup markers, AI attribution | `message` |
| `validate_branch_name` | A branch name, or the checked-out one, and its rebase target when configured | `branch?` |
| `validate_author_info` | Author name and email; read from the repository's git config when omitted | `author_name?` `author_email?` |
| `validate_commit_context` | Message, branch and author in one call, for whichever you pass | `message?` `branch?` `author_name?` `author_email?` |
| `validate_push_safety` | That a push is not a force push (CC301) | `push_refs?` — pre-push lines; omit to compare the branch with its upstream |
| `validate_repository_state` | The latest commit's message and author, the checked-out branch and, optionally, the push | `include_message` `include_branch` `include_author` (default `true`), `include_push` (default `false`) |
| `describe_validation_rules` | Nothing: returns the merged config and the rules it enables | — |
| `server_health` | Nothing: returns the server, commit-check and MCP SDK versions | — |

Every tool but `server_health` also takes:

- `repo_path` — the repository whose `cchk.toml` / `commit-check.toml` applies.
  It must be a git repository when the tool reads git state; a plain directory
  holding a config file is enough when you pass every value yourself.
- `config_path` — a config file to use instead of the repository's own;
  relative paths resolve from `repo_path`.
- `config` — inline overrides merged on top, e.g. `{"commit": {"require_body": true}}`.

No tool changes the working tree or the commits. `validate_push_safety` and
`validate_repository_state` may run `git fetch` to resolve a SHA, so only they
are annotated as not read-only; a client that gates on MCP tool hints can
auto-approve the other six.

<details>
<summary><b>Example arguments</b></summary>

Validate a message with the repository's rules:

```json
{
  "message": "feat(api): add MCP validation tool",
  "repo_path": "/path/to/repo"
}
```

Check the repository as it stands, including the push:

```json
{
  "repo_path": "/path/to/repo",
  "include_push": true
}
```

Validate push safety from git pre-push ref metadata (`<local_ref> <local_sha> <remote_ref> <remote_sha>`):

```json
{
  "repo_path": "/path/to/repo",
  "push_refs": "refs/heads/main abc123 refs/heads/main def456"
}
```

See which rules apply once an override is merged in:

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

</details>

## Results

Every `validate_*` tool returns the shape `commit-check --format json` prints:

```json
{
  "status": "pass|fail|skip",
  "warnings": 0,
  "checks": [
    {
      "rule_id": "CC001",
      "check": "message",
      "status": "pass|fail|warn|skip",
      "value": "...",
      "error": "...",
      "suggest": "...",
      "fix": "...",
      "docs_url": "https://commit-check.com/rules/#cc001"
    }
  ]
}
```

- Only `fail` is a rejection. `skip` means nothing was validated — never read
  it as approval — and `warn` is reported without failing the run.
- On `fail`, apply a non-empty `fix` verbatim, otherwise follow `suggest`,
  then validate again. The server's instructions teach the agent this loop.
- A call that cannot run at all — an empty `message`, a `repo_path` that does
  not exist or is not a git repository where one is needed, an invalid config, a `push_refs` SHA
  that cannot be resolved — comes back as an MCP tool error that names the
  problem, never as a pass.

## Development

```bash
pip install -e .[dev]
python -m pytest
```

The server speaks stdio, so an MCP client launches it; run `uvx commit-check-mcp`
by hand only to see that it starts.

---

<!-- Required by MCP Registry for PyPI package ownership validation -->
<!-- https://registry.modelcontextprotocol.io -->
<sub>mcp-name: io.github.commit-check/commit-check-mcp</sub>
