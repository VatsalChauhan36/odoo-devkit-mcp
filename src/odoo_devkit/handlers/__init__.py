from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from .helpers import _discover_modules
from . import (
    actions_menus,
    model,
    modules,
    recursive,
    scaffold,
    search,
    security,
    upgrade,
    validate,
    views,
    xml_id,
)

_HANDLERS = [
    modules,
    model,
    xml_id,
    views,
    actions_menus,
    security,
    scaffold,
    search,
    recursive,
    validate,
    upgrade,
]


def dispatch_tool(
    name: str, arguments: dict[str, Any], roots: list[Path]
) -> Sequence[TextContent]:
    discovered_modules = _discover_modules(roots)

    for handler in _HANDLERS:
        result = handler.handle(name, arguments, roots, discovered_modules)
        if result is not None:
            return result

    raise ValueError(f"Unknown tool: {name}")
