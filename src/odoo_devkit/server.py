import argparse
from pathlib import Path
from typing import Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .tool_definitions import TOOL_DEFINITIONS
from .tool_handlers import dispatch_tool
from .utils import compact_json, load_roots


async def serve(roots: list[Path]) -> None:
    # The server wires MCP transport to tool metadata and execution handlers.
    server = Server("odoo-devkit")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOL_DEFINITIONS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> Sequence[TextContent]:
        try:
            return dispatch_tool(name=name, arguments=arguments or {}, roots=roots)
        except Exception as exc:
            return [TextContent(type="text", text=compact_json({"error": str(exc)}))]

    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)


def main() -> None:
    # Keep startup simple for MCP clients (CLI args + stdio transport).
    parser = argparse.ArgumentParser(description="Odoo development MCP server")
    parser.add_argument(
        "--roots", action="append", default=[], help="Allowed root directory (repeatable)"
    )
    args = parser.parse_args()
    roots = load_roots(args.roots if args.roots else None)

    import asyncio

    asyncio.run(serve(roots))
