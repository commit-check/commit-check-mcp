#!/usr/bin/env python3
"""Terminal demo for commit-check-mcp — exercises all validation tools."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add local src to path so demo works from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from commit_check_mcp.server import (
    _validate_message,
    _validate_branch,
    _validate_author,
    _validate_push,
    _validate_all,
    _merge_config,
    server_health,
)
from commit_check import __version__ as cc_version


GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"


def heading(text: str) -> None:
    print(f"\n{BOLD}{CYAN}━━━ {text} ━━━{RESET}\n")


def ok(text: str) -> None:
    print(f"  {GREEN}✓{RESET} {text}")


def fail(text: str) -> None:
    print(f"  {RED}✗{RESET} {text}")


def info(text: str) -> None:
    print(f"  {DIM}{text}{RESET}")


def show_result(result: dict) -> None:
    status = result["status"]
    icon = f"{GREEN}PASS{RESET}" if status == "pass" else f"{RED}FAIL{RESET}"
    print(f"  Status: [{icon}]")
    for check in result["checks"]:
        cstatus = check["status"]
        mark = f"{GREEN}✓{RESET}" if cstatus == "pass" else f"{RED}✗{RESET}"
        line = f"    {mark} {check['check']}"
        if check.get("value"):
            line += f"  {DIM}(input: {check['value'][:40]}){RESET}"
        print(line)
        if cstatus == "fail":
            if check.get("error"):
                print(f"      {RED}error:{RESET} {check['error']}")
            if check.get("suggest"):
                print(f"      {YELLOW}suggest:{RESET} {check['suggest']}")
    print()


def main() -> None:
    print(f"{BOLD}{CYAN}")
    print("  ╔══════════════════════════════════════════╗")
    print("  ║     commit-check-mcp  —  Demo Tour       ║")
    print("  ║   AI Agent-Friendly Commit Validation    ║")
    print("  ╚══════════════════════════════════════════╝")
    print(f"{RESET}")

    # ---- Server Health ----
    heading("1. Server Health")
    health = server_health()
    print(f"  Server:          {health['server']} v{health['server_version']}")
    print(f"  commit-check:    v{health['commit_check_version']}")
    print(f"  MCP SDK:         v{health['mcp_sdk_version']}")
    ok("Server healthy")

    # ---- Commit Message Validation ----
    heading("2. Commit Message Validation")

    # Good message
    info("Validating: 'feat(api): add user authentication endpoint'")
    result = _validate_message("feat(api): add user authentication endpoint")
    show_result(result)

    # Bad message - missing type
    info("Validating: 'add user auth' (missing type)")
    result = _validate_message("add user auth")
    show_result(result)

    # Bad message - too long subject
    info("Validating: 'feat: ' + 73 chars...")
    result = _validate_message("feat: " + "x" * 73)
    show_result(result)

    # ---- Branch Name Validation ----
    heading("3. Branch Name Validation")

    # Good branch
    info("Validating branch: 'feature/user-auth'")
    result = _validate_branch("feature/user-auth")
    show_result(result)

    # Bad branch
    info("Validating branch: 'my_branch' (no prefix)")
    result = _validate_branch("my_branch")
    show_result(result)

    # ---- Author Validation ----
    heading("4. Author Name/Email Validation")

    info("Validating: name='Xianpeng Shen', email='xianpeng.shen@gmail.com'")
    result = _validate_author("Xianpeng Shen", "xianpeng.shen@gmail.com")
    show_result(result)

    info("Validating: name='', email='not-an-email'")
    result = _validate_author("", "not-an-email")
    show_result(result)

    # ---- Push Safety ----
    heading("5. Push Safety Validation")

    info("Simulating normal push (no force-push refs)")
    result = _validate_push("refs/heads/main abc123 refs/heads/main def456")
    show_result(result)

    # ---- Commit Context (combined) ----
    heading("6. Combined Commit Context Validation")

    info("Validating message + branch + author together")
    result = _validate_all(
        message="chore(deps): bump requests to 2.32.0",
        branch="chore/update-deps",
        author_name="Xianpeng Shen",
        author_email="xianpeng.shen@gmail.com",
    )
    show_result(result)

    # ---- Config Inspection ----
    heading("7. Validation Rules Inspection (describe_validation_rules)")

    merged = _merge_config(None)
    commit_rules = [k for k in merged.get("commit", {})]
    branch_rules = [k for k in merged.get("branch", {})]
    print(f"  Active commit rules:  {YELLOW}{', '.join(sorted(commit_rules))}{RESET}")
    print(f"  Active branch rules:  {YELLOW}{', '.join(sorted(branch_rules))}{RESET}")
    print()

    # ---- Summary ----
    heading("Summary")
    print(f"  {BOLD}commit-check-mcp{RESET} provides {CYAN}8 MCP tools{RESET} for")
    print(f"  AI agents to validate commits, branches, authors,")
    print(f"  push safety, and repository state.")
    print()
    print(f"  {DIM}Install: pip install commit-check-mcp{RESET}")
    print(f"  {DIM}MCP config: {{ 'command': 'commit-check-mcp' }}{RESET}")
    print(f"  {DIM}GitHub: https://github.com/commit-check/commit-check-mcp{RESET}")
    print()


if __name__ == "__main__":
    main()
