import argparse
from pathlib import Path
from typing import Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .tool_definitions import TOOL_DEFINITIONS
from .tool_handlers import dispatch_tool
from .utils import load_roots, to_toon


async def serve(roots: list[Path], defaults: dict | None = None, open_browser: bool = True) -> None:
    # Start the config dashboard in a background thread (like Serena's pattern)
    from .dashboard import run_in_thread as _start_dashboard
    _start_dashboard(open_browser=open_browser)

    # The server wires MCP transport to tool metadata and execution handlers.
    server = Server("odoo-devkit")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOL_DEFINITIONS

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict) -> Sequence[TextContent]:
        try:
            args = dict(arguments or {})
            # Inject saved defaults for upgrade tool when not provided by the caller
            if name == "run_module_upgrade" and defaults:
                for key in ("odoo_bin", "config_file", "database"):
                    config_key = "odoo_config" if key == "config_file" else key
                    if not args.get(key) and defaults.get(config_key):
                        args[key] = defaults[config_key]
            return dispatch_tool(name=name, arguments=args, roots=roots)
        except Exception as exc:
            return [TextContent(type="text", text=to_toon({"error": str(exc)}))]

    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)


def main() -> None:
    parser = argparse.ArgumentParser(description="Odoo development MCP server")
    parser.add_argument(
        "--roots", action="append", default=[], help="Allowed root directory (repeatable)"
    )
    parser.add_argument(
        "--config", action="store_true", help="Open the configuration GUI and exit"
    )
    args = parser.parse_args()

    # --config: launch the web dashboard and exit (no MCP server started)
    if args.config:
        try:
            from .dashboard import run_dashboard
            run_dashboard()
        except Exception as exc:
            print(f"Could not open config dashboard: {exc}", flush=True)
        return

    roots = load_roots(args.roots if args.roots else None)

    # Load saved config for defaults (odoo_bin, odoo_config, database, open_browser)
    from .config import OdooDevkitConfig
    saved_cfg = OdooDevkitConfig.load()
    defaults = {
        "odoo_bin": saved_cfg.odoo_bin,
        "odoo_config": saved_cfg.odoo_config,
        "database": saved_cfg.database,
    }

    import asyncio
    asyncio.run(serve(roots, defaults=defaults, open_browser=saved_cfg.open_browser))
