"""The server as an MCP client launches it: a subprocess speaking stdio.

The other tests call the tools in-process, through the server object. This
one starts the server the way a client does and checks the whole exchange
over its stdin and stdout: the handshake, the tool list, structured results
for a pass and a fail, a tool error flagged as an error, and no line the
client could not parse.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def _talk_to_the_server(cwd: Path) -> dict[str, object]:
    transport_errors: list[Exception] = []

    async def on_message(message: object) -> None:
        if isinstance(message, Exception):
            transport_errors.append(message)

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "commit_check_mcp.server"], cwd=str(cwd)
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write, message_handler=on_message) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        return {
            "tools": {tool.name for tool in tools.tools},
            "pass": await session.call_tool(
                "validate_commit_message", {"message": "feat: add a stdio test"}
            ),
            "fail": await session.call_tool(
                "validate_commit_message", {"message": "added a stdio test"}
            ),
            "error": await session.call_tool("validate_commit_message", {"message": "   "}),
            "transport_errors": transport_errors,
        }


def test_a_client_lists_and_calls_the_tools_over_stdio(tmp_path: Path) -> None:
    replies = asyncio.run(asyncio.wait_for(_talk_to_the_server(tmp_path), timeout=60))

    assert replies["transport_errors"] == []
    assert "validate_commit_message" in replies["tools"]
    assert len(replies["tools"]) == 8

    passed = replies["pass"]
    assert passed.is_error is False
    assert passed.structured_content["status"] == "pass"

    failed = replies["fail"]
    assert failed.is_error is False
    assert failed.structured_content["status"] == "fail"
    assert any(c["status"] == "fail" for c in failed.structured_content["checks"])

    error = replies["error"]
    assert error.is_error is True
    assert "message must be a non-empty string" in error.content[0].text
