"""Verify the MCP tool layer works: write a file and run pytest through MCP.

    python scripts/check_mcp.py

This spawns the workspace MCP server, writes a tiny module and test through
the MCP client, runs pytest via MCP, and prints the result.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.mcp_client import workspace_tools

MODULE = "def add(a, b):\n    return a + b\n"
TEST = "from adder import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


async def main() -> None:
    """Exercise the MCP server end to end."""
    async with workspace_tools() as tools:
        print(await tools.write_file("mcp-check/adder.py", MODULE))
        print(await tools.write_file("mcp-check/test_adder.py", TEST))
        readback = await tools.read_file("mcp-check/adder.py")
        print(f"read_file OK: {len(readback)} chars")
        output = await tools.run_pytest("mcp-check")
        print("--- pytest via MCP ---")
        print(output)

    if "1 passed" in output:
        print("VERDICT: MCP tool layer works.")
    else:
        print("VERDICT: MCP ran but the test did not pass as expected.")


if __name__ == "__main__":
    asyncio.run(main())
