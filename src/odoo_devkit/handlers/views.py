from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import compact_json, run_rg
from .helpers import (
    _collect_view_records,
    _find_module_for_file,
    _match_view_ref,
    _scope_for_module,
    _targets_from_view_ref,
)


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
    if name == "find_view_definition":
        view_ref = arguments.get("view_ref")
        if not view_ref:
            raise ValueError("view_ref is required")
        limit = int(arguments.get("limit", 40))
        records = _collect_view_records(roots)
        matches = [rec for rec in records if _match_view_ref(rec, view_ref)]
        return [
            TextContent(
                type="text",
                text=compact_json(
                    {
                        "view_ref": view_ref,
                        "count": len(matches[:limit]),
                        "matches": matches[:limit],
                    }
                ),
            )
        ]

    if name == "find_inherited_views":
        view_ref = arguments.get("view_ref")
        if not view_ref:
            raise ValueError("view_ref is required")
        limit = int(arguments.get("limit", 60))
        records = _collect_view_records(roots)
        targets = _targets_from_view_ref(view_ref, records)
        matches = [
            rec
            for rec in records
            if rec.get("inherit_id") and rec["inherit_id"] in targets
        ]
        return [
            TextContent(
                type="text",
                text=compact_json(
                    {
                        "view_ref": view_ref,
                        "targets": sorted(targets),
                        "count": len(matches[:limit]),
                        "matches": matches[:limit],
                    }
                ),
            )
        ]

    if name == "find_view_by_model":
        model = arguments.get("model")
        if not model:
            raise ValueError("model is required")
        limit = int(arguments.get("limit", 80))
        records = _collect_view_records(roots)
        target = model.strip()
        matches = [rec for rec in records if (rec.get("model") or "").strip() == target]
        # Stable output ordering helps deterministic tool responses.
        matches = sorted(
            matches,
            key=lambda rec: (
                rec.get("scope", ""),
                rec.get("module", "") or "",
                rec.get("xml_id", "") or "",
                rec.get("path", ""),
            ),
        )
        return [
            TextContent(
                type="text",
                text=compact_json(
                    {
                        "model": target,
                        "count": len(matches[:limit]),
                        "matches": matches[:limit],
                    }
                ),
            )
        ]

    if name == "find_view_chain":
        view_ref = arguments.get("view_ref")
        if not view_ref:
            raise ValueError("view_ref is required")
        limit = int(arguments.get("limit", 120))
        views = _collect_view_records(roots)
        targets = _targets_from_view_ref(view_ref, views)
        seeds = [
            view
            for view in views
            if any(
                target in {view.get("xml_id"), view.get("xml_id_raw"), view.get("name")}
                for target in targets
            )
        ]
        if not seeds:
            return [
                TextContent(
                    type="text",
                    text=compact_json({"view_ref": view_ref, "chain": []}),
                )
            ]

        by_inherit: dict[str, list[dict[str, Any]]] = {}
        for view in views:
            inh = view.get("inherit_id")
            if inh:
                by_inherit.setdefault(inh, []).append(view)

        out: list[dict[str, Any]] = []
        queue: list[tuple[int, dict[str, Any]]] = [(0, seed) for seed in seeds]
        seen = set()
        while queue and len(out) < limit:
            depth, node = queue.pop(0)
            key = (node.get("path"), node.get("xml_id"), depth)
            if key in seen:
                continue
            seen.add(key)
            out.append({"depth": depth, **node})
            for child in by_inherit.get(node.get("xml_id"), []):
                queue.append((depth + 1, child))
        return [
            TextContent(
                type="text",
                text=compact_json(
                    {"view_ref": view_ref, "count": len(out), "chain": out}
                ),
            )
        ]

    if name == "find_field_in_views":
        import re

        field_name = arguments.get("field_name")
        if not field_name:
            raise ValueError("field_name is required")
        model = (arguments.get("model") or "").strip()
        limit = int(arguments.get("limit", 100))

        # When model is given, collect view_paths first and search only those files.
        # This avoids ripgrep hitting the global limit before reaching model-specific files
        # (common fields like 'state' appear in thousands of XML files across all modules).
        search_roots = list(roots)
        if model:
            all_view_records = _collect_view_records(roots)
            direct_view_paths = {
                rec["path"]
                for rec in all_view_records
                if (rec.get("model") or "").strip() == model
            }
            base_xml_ids = {
                rec.get("xml_id")
                for rec in all_view_records
                if (rec.get("model") or "").strip() == model and rec.get("xml_id")
            }
            inherited_view_paths = {
                rec["path"]
                for rec in all_view_records
                if rec.get("inherit_id") in base_xml_ids
            }
            view_paths = direct_view_paths | inherited_view_paths
            # Replace roots with the specific view files so ripgrep only scans those
            search_roots = [Path(p) for p in sorted(view_paths) if Path(p).is_file()]

        # Match direct field nodes and xpath expressions.
        p1 = r"<field[^>]*name\s*=\s*['\"]" + re.escape(field_name) + r"['\"]"
        p2 = r"@name\s*=\s*['\"]" + re.escape(field_name) + r"['\"]"
        m1 = run_rg(p1, search_roots, ["*.xml"], limit=limit, fixed_strings=False)
        m2 = run_rg(p2, search_roots, ["*.xml"], limit=limit, fixed_strings=False)

        seen = set()
        matches: list[dict[str, Any]] = []
        for row in m1 + m2:
            key = (row["path"], row["line"])
            if key in seen:
                continue
            seen.add(key)
            fpath = Path(row["path"])
            mod = _find_module_for_file(fpath)
            row["module"] = mod.name if mod else None
            row["scope"] = _scope_for_module(mod, roots) if mod else "unknown"
            matches.append(row)

        return [
            TextContent(
                type="text",
                text=compact_json(
                    {
                        "field_name": field_name,
                        "model": model or None,
                        "count": len(matches[:limit]),
                        "matches": matches[:limit],
                    }
                ),
            )
        ]

    return None
