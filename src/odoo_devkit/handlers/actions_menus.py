from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import to_toon
from .helpers import (
    _collect_action_records,
    _collect_menu_records,
    _collect_view_records,
    _sort_records,
)


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
    if name == "find_action_by_model":
        model = arguments.get("model")
        if not model:
            raise ValueError("model is required")
        limit = int(str(arguments.get("limit", 80)))
        target = model.strip()
        actions = _collect_action_records(roots)
        matches = _sort_records(
            [action for action in actions if (action.get("res_model") or "").strip() == target]
        )[:limit]
        return [
            TextContent(
                type="text",
                text=to_toon(
                    {
                        "model": target,
                        "count": len(matches),
                        "matches": matches,
                    }
                ),
            )
        ]

    if name == "find_menu_hierarchy":
        ref = arguments.get("ref")
        if not ref:
            raise ValueError("ref is required")
        limit = int(str(arguments.get("limit", 120)))
        target = ref.strip()
        actions = _collect_action_records(roots)
        menus = _collect_menu_records(roots)
        views = _collect_view_records(roots)

        target_action_ids = set()
        for action in actions:
            if target in {
                action.get("xml_id"),
                action.get("xml_id_raw"),
                action.get("name"),
                action.get("res_model"),
                action.get("view_id"),
            }:
                if action.get("xml_id"):
                    target_action_ids.add(action["xml_id"])
                if action.get("xml_id_raw") and action.get("module"):
                    target_action_ids.add(f"{action['module']}.{action['xml_id_raw']}")

        for view in views:
            if target in {view.get("xml_id"), view.get("xml_id_raw"), view.get("name")}:
                view_ids = {view.get("xml_id"), view.get("xml_id_raw")}
                for action in actions:
                    if action.get("view_id") in view_ids and action.get("xml_id"):
                        target_action_ids.add(action["xml_id"])

        menu_map = {menu.get("xml_id"): menu for menu in menus if menu.get("xml_id")}
        matched_menus = _sort_records(
            [
                menu
                for menu in menus
                if menu.get("action") in target_action_ids
                or target in {menu.get("xml_id"), menu.get("xml_id_raw"), menu.get("name")}
            ]
        )

        def build_ancestors(menu: dict[str, Any]) -> list[dict[str, Any]]:
            chain: list[dict[str, Any]] = []
            seen = set()
            current = menu
            while current.get("parent") and current["parent"] not in seen:
                seen.add(current["parent"])
                parent = menu_map.get(current["parent"])
                if not parent:
                    break
                chain.append(parent)
                current = parent
            return list(reversed(chain))

        result = []
        for menu in matched_menus[:limit]:
            children = _sort_records(
                [child for child in menus if child.get("parent") == menu.get("xml_id")]
            )[:20]
            result.append(
                {
                    "menu": menu,
                    "ancestors": build_ancestors(menu),
                    "children": children,
                }
            )
        return [
            TextContent(
                type="text",
                text=to_toon(
                    {
                        "ref": target,
                        "target_actions": sorted(target_action_ids),
                        "count": len(result),
                        "matches": result,
                    }
                ),
            )
        ]

    return None
