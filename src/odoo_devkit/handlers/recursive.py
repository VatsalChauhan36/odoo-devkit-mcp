import re
from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import to_toon, run_rg
from .helpers import _discover_modules, _find_module_for_file, _scope_for_module


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
    if name == "glob_odoo_files":
        return _glob_odoo_files(arguments, roots, modules)

    if name == "get_module_structure":
        return _get_module_structure(arguments, roots, modules)

    if name == "find_method_definition":
        return _find_method_definition(arguments, roots, modules)

    return None


def _glob_odoo_files(
    arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent]:
    pattern = arguments.get("pattern")
    if not pattern:
        raise ValueError("pattern is required")
    limit = int(arguments.get("limit", 200))
    module_filter = (arguments.get("module_filter") or "").strip()

    search_roots = roots
    if module_filter:
        if module_filter not in modules:
            raise ValueError(f"Unknown module for module_filter: {module_filter}")
        search_roots = [modules[module_filter]]

    results = []
    seen: set[Path] = set()
    for root in search_roots:
        for match in sorted(root.rglob(pattern)):
            if match in seen or not match.is_file():
                continue
            seen.add(match)
            if len(results) >= limit:
                break
            rel = str(match.relative_to(root))
            module_name = _find_module_for_file(match)
            scope = (
                _scope_for_module(modules.get(module_name, match.parent), roots)
                if module_name
                else None
            )
            results.append({
                "path": str(match),
                "rel_path": rel,
                "module": module_name,
                "scope": scope,
            })
        if len(results) >= limit:
            break

    return [
        TextContent(
            type="text",
            text=to_toon({
                "pattern": pattern,
                "module_filter": module_filter or None,
                "count": len(results),
                "truncated": len(results) == limit,
                "files": results,
            }),
        )
    ]


def _get_module_structure(
    arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent]:
    module_name = arguments.get("module")
    if not module_name:
        raise ValueError("module is required")
    if module_name not in modules:
        raise ValueError(f"Unknown module: {module_name}")
    limit = int(arguments.get("limit", 300))

    module_path = modules[module_name]
    scope = _scope_for_module(module_path, roots)

    # Collect all files grouped by directory
    dirs: dict[str, list[str]] = {}
    count = 0
    for path in sorted(module_path.rglob("*")):
        if not path.is_file():
            continue
        # Skip __pycache__ and hidden directories
        rel = path.relative_to(module_path)
        parts = rel.parts
        if any(p.startswith(".") or p == "__pycache__" for p in parts):
            continue
        count += 1
        if count > limit:
            break
        dir_key = str(rel.parent) if len(parts) > 1 else "."
        dirs.setdefault(dir_key, []).append(str(rel))

    return [
        TextContent(
            type="text",
            text=to_toon({
                "module": module_name,
                "path": str(module_path),
                "scope": scope,
                "total_files": min(count, limit),
                "truncated": count > limit,
                "directories": dirs,
            }),
        )
    ]


def _find_method_definition(
    arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent]:
    method_name = arguments.get("method_name")
    if not method_name:
        raise ValueError("method_name is required")
    model_filter = (arguments.get("model") or "").strip()
    limit = int(arguments.get("limit", 30))

    # Search for 'def method_name(' pattern
    pattern = r"def\s+" + re.escape(method_name) + r"\s*\("

    if model_filter:
        # First find files that define/inherit this model, then search within them
        name_pat = r"_name\s*=\s*['\"]" + re.escape(model_filter) + r"['\"]"
        inherit_pat = (
            r"_inherit\s*=\s*(?:\[[^\]]*['\"]"
            + re.escape(model_filter)
            + r"['\"][^\]]*\]|['\"]"
            + re.escape(model_filter)
            + r"['\"])"
        )
        # Get files that reference this model
        name_matches = run_rg(name_pat, roots, ["*.py"], limit=500, fixed_strings=False)
        inherit_matches = run_rg(inherit_pat, roots, ["*.py"], limit=500, fixed_strings=False)
        model_files = {m["path"] for m in name_matches} | {m["path"] for m in inherit_matches}

        if not model_files:
            return [
                TextContent(
                    type="text",
                    text=to_toon({
                        "method_name": method_name,
                        "model": model_filter,
                        "count": 0,
                        "matches": [],
                        "note": f"No files found defining or inheriting model '{model_filter}'.",
                    }),
                )
            ]

        # Search for method def in those files only
        all_matches = run_rg(pattern, roots, ["*.py"], limit=500, fixed_strings=False)
        matches = [m for m in all_matches if m["path"] in model_files][:limit]
    else:
        matches = run_rg(pattern, roots, ["*.py"], limit=limit, fixed_strings=False)

    # Enrich with module info
    enriched = []
    for m in matches:
        file_path = Path(m["path"])
        mod_path = _find_module_for_file(file_path)
        mod_name = mod_path.name if mod_path else None
        scope = _scope_for_module(mod_path, roots) if mod_path else "unknown"
        enriched.append({
            **m,
            "module": mod_name,
            "scope": scope,
        })

    return [
        TextContent(
            type="text",
            text=to_toon({
                "method_name": method_name,
                "model": model_filter or None,
                "count": len(enriched),
                "matches": enriched,
            }),
        )
    ]
