from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import run_rg, to_toon
from .helpers import (
    _build_view_lookup,
    _collect_view_records,
    _find_module_for_file,
    _match_view_ref,
    _resolve_view_model,
    _scope_for_module,
    _sort_records,
    _targets_from_view_ref,
)


def _with_effective_model(
    record: dict[str, Any],
    view_lookup: dict[str, dict[str, Any]],
    model_cache: dict[str, str | None],
) -> dict[str, Any]:
    resolved_model = _resolve_view_model(record, view_lookup, model_cache)
    if resolved_model and not (record.get("model") or "").strip():
        return {**record, "model": resolved_model}
    return record


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
    records = _collect_view_records(roots)
    view_lookup = _build_view_lookup(records)
    model_cache: dict[str, str | None] = {}

    if name == "find_view_definition":
        view_ref = arguments.get("view_ref")
        if not view_ref:
            raise ValueError("view_ref is required")
        limit = int(str(arguments.get("limit", 40)))
        matches = [
            _with_effective_model(record, view_lookup, model_cache)
            for record in records
            if _match_view_ref(record, view_ref)
        ]
        matches = _sort_records(matches)[:limit]
        return [
            TextContent(
                type="text",
                text=to_toon(
                    {
                        "view_ref": view_ref,
                        "count": len(matches),
                        "matches": matches,
                    }
                ),
            )
        ]

    if name == "find_inherited_views":
        view_ref = arguments.get("view_ref")
        if not view_ref:
            raise ValueError("view_ref is required")
        limit = int(str(arguments.get("limit", 60)))
        targets = _targets_from_view_ref(view_ref, records)
        matches = [
            _with_effective_model(record, view_lookup, model_cache)
            for record in records
            if record.get("inherit_id") and record["inherit_id"] in targets
        ]
        matches = _sort_records(matches)[:limit]
        return [
            TextContent(
                type="text",
                text=to_toon(
                    {
                        "view_ref": view_ref,
                        "targets": sorted(targets),
                        "count": len(matches),
                        "matches": matches,
                    }
                ),
            )
        ]

    if name == "find_view_by_model":
        model = arguments.get("model")
        if not model:
            raise ValueError("model is required")
        limit = int(str(arguments.get("limit", 80)))
        target = model.strip()
        matches = []
        for record in records:
            effective_model = _resolve_view_model(record, view_lookup, model_cache)
            if effective_model != target:
                continue
            matches.append(_with_effective_model(record, view_lookup, model_cache))
        matches = _sort_records(matches)[:limit]
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

    if name == "find_view_chain":
        view_ref = arguments.get("view_ref")
        if not view_ref:
            raise ValueError("view_ref is required")
        limit = int(str(arguments.get("limit", 120)))
        targets = _targets_from_view_ref(view_ref, records)
        seeds = [
            _with_effective_model(view, view_lookup, model_cache)
            for view in records
            if any(
                target in {view.get("xml_id"), view.get("xml_id_raw"), view.get("name")}
                for target in targets
            )
        ]
        if not seeds:
            return [TextContent(type="text", text=to_toon({"view_ref": view_ref, "chain": []}))]

        by_inherit: dict[str, list[dict[str, Any]]] = {}
        for view in records:
            inherit_id = view.get("inherit_id")
            if inherit_id:
                by_inherit.setdefault(inherit_id, []).append(
                    _with_effective_model(view, view_lookup, model_cache)
                )
        for inherit_id, children in by_inherit.items():
            by_inherit[inherit_id] = _sort_records(children)

        out: list[dict[str, Any]] = []
        queue: list[tuple[int, dict[str, Any]]] = [(0, seed) for seed in _sort_records(seeds)]
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
                text=to_toon({"view_ref": view_ref, "count": len(out), "chain": out}),
            )
        ]

    if name == "find_field_in_views":
        import re

        field_name = arguments.get("field_name")
        if not field_name:
            raise ValueError("field_name is required")
        model = (arguments.get("model") or "").strip()
        limit = int(str(arguments.get("limit", 100)))

        search_roots = list(roots)
        if model:
            view_paths = {
                record["path"]
                for record in records
                if _resolve_view_model(record, view_lookup, model_cache) == model
            }
            search_roots = [Path(path) for path in sorted(view_paths) if Path(path).is_file()]

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
            file_path = Path(row["path"])
            module_path = _find_module_for_file(file_path)
            row["module"] = module_path.name if module_path else None
            row["scope"] = _scope_for_module(module_path, roots) if module_path else "unknown"
            matches.append(row)

        matches = _sort_records(matches)[:limit]
        return [
            TextContent(
                type="text",
                text=to_toon(
                    {
                        "field_name": field_name,
                        "model": model or None,
                        "count": len(matches),
                        "matches": matches,
                    }
                ),
            )
        ]

    return None
