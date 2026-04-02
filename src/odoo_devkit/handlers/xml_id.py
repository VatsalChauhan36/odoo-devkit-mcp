import re
from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import run_rg, to_toon
from .helpers import _find_module_for_file, _scope_for_module, _sort_records


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
    if name == "find_xml_id_definition":
        xml_id = arguments.get("xml_id")
        if not xml_id:
            raise ValueError("xml_id is required")
        limit = int(str(arguments.get("limit", 20)))
        raw_id = xml_id.split(".", 1)[1] if "." in xml_id else xml_id
        search_ids = list({xml_id, raw_id})
        all_matches: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, int]] = set()
        for search_id in search_ids:
            pattern = r"id\s*=\s*['\"]" + re.escape(search_id) + r"['\"]"
            for match in run_rg(pattern, roots, ["*.xml"], limit=limit, fixed_strings=False):
                key = (match["path"], match["line"])
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                file_path = Path(match["path"])
                module_path = _find_module_for_file(file_path)
                module_name = module_path.name if module_path else None
                scope = _scope_for_module(module_path, roots) if module_path else "unknown"
                all_matches.append({**match, "module": module_name, "scope": scope})
        matches = _sort_records(all_matches)[:limit]
        return [TextContent(type="text", text=to_toon({"xml_id": xml_id, "matches": matches}))]

    return None
