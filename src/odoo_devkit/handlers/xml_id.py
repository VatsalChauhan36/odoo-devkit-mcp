import re
from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import to_toon, run_rg


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
    if name == "find_xml_id_definition":
        xml_id = arguments.get("xml_id")
        if not xml_id:
            raise ValueError("xml_id is required")
        limit = int(arguments.get("limit", 20))
        # Search for both full xml_id (e.g. "sale.view_order_form") and raw id (e.g. "view_order_form")
        # XML files store the raw id without module prefix, so we must strip it.
        raw_id = xml_id.split(".", 1)[1] if "." in xml_id else xml_id
        search_ids = list({xml_id, raw_id})
        all_matches: list[dict] = []
        seen_keys: set[tuple] = set()
        for sid in search_ids:
            pattern = r"id\s*=\s*['\"]" + re.escape(sid) + r"['\"]"
            for m in run_rg(pattern, roots, ["*.xml"], limit=limit, fixed_strings=False):
                key = (m["path"], m["line"])
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_matches.append(m)
        return [
            TextContent(
                type="text", text=to_toon({"xml_id": xml_id, "matches": all_matches[:limit]})
            )
        ]

    return None
