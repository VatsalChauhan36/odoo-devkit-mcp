from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import compact_json
from .helpers import _discover_modules, _parse_manifest


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
    if name in ("list_modules", "list_custom_modules"):
        query = arguments.get("query", "").strip().lower()
        limit = int(arguments.get("limit", 50))
        module_items = modules.items()
        if name == "list_custom_modules":
            # Convention: first configured root is the custom addons root.
            custom_root = roots[0].resolve()
            module_items = [
                (module_name, module_path)
                for module_name, module_path in module_items
                if module_path.resolve().parent == custom_root
            ]
        names = sorted(module_name for module_name, _ in module_items)
        if query:
            names = [module for module in names if query in module.lower()]
        result = {
            "count": len(names[:limit]),
            "total_matches": len(names),
            "modules": names[:limit],
        }
        result["scope"] = "custom" if name == "list_custom_modules" else "all"
        return [TextContent(type="text", text=compact_json(result))]

    if name == "get_module_manifest":
        module = arguments.get("module")
        if not module:
            raise ValueError("module is required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        result = {
            "module": module,
            "path": str(modules[module]),
            "manifest": _parse_manifest(modules[module]),
        }
        return [TextContent(type="text", text=compact_json(result))]

    return None
