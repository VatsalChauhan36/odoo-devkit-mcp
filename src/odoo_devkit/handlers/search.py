from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..constants import ODOO_DOCS_PATH
from ..utils import assert_allowed_path, to_toon, run_rg
from .helpers import _read_file_lines


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
    if name == "search_odoo_code":
        query = arguments.get("query")
        if not query:
            raise ValueError("query is required")
        glob = str(arguments.get("glob", "*.py"))
        limit = int(arguments.get("limit", 30))
        fixed_strings = bool(arguments.get("fixed_strings", True))
        module_filter = (arguments.get("module_filter") or "").strip()
        search_roots = roots
        if module_filter:
            if module_filter not in modules:
                raise ValueError(f"Unknown module for module_filter: {module_filter}")
            search_roots = [modules[module_filter]]
        matches = run_rg(query, search_roots, [glob], limit=limit, fixed_strings=fixed_strings)
        return [
            TextContent(
                type="text",
                text=to_toon({"query": query, "glob": glob, "module_filter": module_filter or None, "matches": matches}),
            )
        ]

    if name == "read_file_lines":
        rel_or_abs = Path(arguments.get("path", ""))
        if not rel_or_abs:
            raise ValueError("path is required")
        candidate = rel_or_abs if rel_or_abs.is_absolute() else (Path.cwd() / rel_or_abs)
        safe = assert_allowed_path(candidate, roots)
        start = int(arguments.get("start", 1))
        end = int(arguments.get("end", 120))
        max_lines = int(arguments.get("max_lines", 120))
        return [
            TextContent(
                type="text",
                text=to_toon(_read_file_lines(safe, start, end, max_lines)),
            )
        ]

    if name == "search_odoo_docs":
        query = arguments.get("query")
        if not query:
            raise ValueError("query is required")
        limit = int(arguments.get("limit", 20))
        if ODOO_DOCS_PATH is None:
            return [TextContent(type="text", text=to_toon({
                "error": "ODOO_MCP_DOCS_PATH environment variable is not set.",
                "hint": "Clone https://github.com/odoo/documentation and set ODOO_MCP_DOCS_PATH to its path.",
            }))]
        if not ODOO_DOCS_PATH.exists():
            return [TextContent(type="text", text=to_toon({
                "error": f"Docs path does not exist: {ODOO_DOCS_PATH}",
                "hint": "Check that ODOO_MCP_DOCS_PATH points to a valid directory.",
            }))]
        matches = run_rg(query, [ODOO_DOCS_PATH.resolve()], ["*.rst", "*.md"], limit=limit)
        return [TextContent(type="text", text=to_toon({"query": query, "matches": matches}))]

    return None
