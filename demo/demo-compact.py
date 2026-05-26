#!/usr/bin/env python3
"""Compact terminal demo optimized for GIF recording."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from commit_check_mcp.server import (
    _validate_message,
    _validate_branch,
    _validate_author,
    _validate_push,
    _validate_all,
    server_health,
)

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"


def heading(text: str) -> None:
    print(f"\n{BOLD}{CYAN}{text}{RESET}")


def show(result: dict) -> None:
    s = f"{GREEN}PASS{RESET}" if result["status"] == "pass" else f"{RED}FAIL{RESET}"
    print(f"  [{s}]", end="")
    for c in result["checks"]:
        mark = f"{GREEN}✓{RESET}" if c["status"] == "pass" else f"{RED}✗{RESET}"
        print(f" {mark}{c['check']}", end="")
        if c["status"] == "fail" and c.get("suggest"):
            print(f"\n    {YELLOW}→ {c['suggest'][:80]}{RESET}", end="")
    print()


# Header
print(f"{BOLD}commit-check-mcp  —  AI Agent-Friendly Commit Validation{RESET}")
print(f"{DIM}https://github.com/commit-check/commit-check-mcp{RESET}")

heading("Server Health")
health = server_health()
print(f"  {health['server']} v{health['server_version']} | commit-check v{health['commit_check_version']}")

heading("1. Commit Message")
show(_validate_message("feat(api): add user auth endpoint"))
show(_validate_message("add user auth"))

heading("2. Branch Name")
show(_validate_branch("feature/user-auth"))
show(_validate_branch("my_branch"))

heading("3. Author Info")
show(_validate_author("Xianpeng Shen", "xianpeng.shen@gmail.com"))
show(_validate_author("", "bad-email"))

heading("4. Push Safety")
show(_validate_push("refs/heads/main abc123 refs/heads/main def456"))

heading("5. Combined Context")
show(_validate_all(
    message="chore(deps): bump requests",
    branch="chore/update-deps",
    author_name="Xianpeng Shen",
    author_email="xianpeng.shen@gmail.com",
))

print(f"\n{BOLD}{GREEN}8 MCP tools for AI agents — install: pip install commit-check-mcp{RESET}")
