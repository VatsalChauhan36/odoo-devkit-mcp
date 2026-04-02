import re
from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import run_rg, to_toon
from .helpers import _find_module_for_file, _scope_for_module, _sort_records


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
    limit = int(str(arguments.get("limit", 200)))
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
            module_path = _find_module_for_file(match)
            module_name = module_path.name if module_path else None
            scope = _scope_for_module(module_path, roots) if module_path else "unknown"
            results.append(
                {
                    "path": str(match),
                    "rel_path": rel,
                    "module": module_name,
                    "scope": scope,
                }
            )
        if len(results) >= limit:
            break

    results = _sort_records(results)[:limit]
    return [
        TextContent(
            type="text",
            text=to_toon(
                {
                    "pattern": pattern,
                    "module_filter": module_filter or None,
                    "count": len(results),
                    "truncated": len(results) == limit,
                    "files": results,
                }
            ),
        )
    ]


def _resolve_module_names(raw: Any) -> list[str]:
    if isinstance(raw, list):
        names = []
        for item in raw:
            names.extend(name.strip() for name in str(item).split(",") if name.strip())
        return names
    if isinstance(raw, str):
        return [name.strip() for name in raw.split(",") if name.strip()]
    return []


def _get_module_structure(
    arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent]:
    raw = arguments.get("module") or arguments.get("module_name")
    if not raw:
        raise ValueError("module is required")
    module_names = _resolve_module_names(raw)
    if not module_names:
        raise ValueError("module is required")

    unknown = [module_name for module_name in module_names if module_name not in modules]
    if unknown:
        raise ValueError(f"Unknown module(s): {', '.join(unknown)}")

    limit = int(str(arguments.get("limit", 300)))
    results = []

    for module_name in module_names:
        module_path = modules[module_name]
        scope = _scope_for_module(module_path, roots)

        directories: dict[str, list[str]] = {}
        count = 0
        for path in sorted(module_path.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(module_path)
            parts = rel.parts
            if any(part.startswith(".") or part == "__pycache__" for part in parts):
                continue
            count += 1
            if count > limit:
                break
            dir_key = str(rel.parent) if len(parts) > 1 else "."
            directories.setdefault(dir_key, []).append(str(rel))

        results.append(
            {
                "module": module_name,
                "path": str(module_path),
                "scope": scope,
                "total_files": min(count, limit),
                "truncated": count > limit,
                "directories": directories,
            }
        )

    output = results[0] if len(results) == 1 else {"modules": results, "count": len(results)}
    return [TextContent(type="text", text=to_toon(output))]


def _find_method_definition(
    arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent]:
    method_name = arguments.get("method_name")
    if not method_name:
        raise ValueError("method_name is required")
    model_filter = (arguments.get("model") or "").strip()
    limit = int(str(arguments.get("limit", 30)))
    context_lines = int(str(arguments.get("context_lines", 0)))

    pattern = r"def\s+" + re.escape(method_name) + r"\s*\("

    if model_filter:
        name_pat = r"_name\s*=\s*['\"]" + re.escape(model_filter) + r"['\"]"
        inherit_pat = (
            r"_inherit\s*=\s*(?:\[[^\]]*['\"]"
            + re.escape(model_filter)
            + r"['\"][^\]]*\]|['\"]"
            + re.escape(model_filter)
            + r"['\"])"
        )
        name_matches = run_rg(name_pat, roots, ["*.py"], limit=500, fixed_strings=False)
        inherit_matches = run_rg(inherit_pat, roots, ["*.py"], limit=500, fixed_strings=False)
        model_files = {match["path"] for match in name_matches} | {
            match["path"] for match in inherit_matches
        }

        if not model_files:
            return [
                TextContent(
                    type="text",
                    text=to_toon(
                        {
                            "method_name": method_name,
                            "model": model_filter,
                            "count": 0,
                            "matches": [],
                            "note": f"No files found defining or inheriting model '{model_filter}'.",
                        }
                    ),
                )
            ]

        raw_matches = run_rg(
            pattern,
            roots,
            ["*.py"],
            limit=500,
            fixed_strings=False,
            context_lines=context_lines,
        )
        matches = [match for match in raw_matches if match["path"] in model_files]
    else:
        matches = run_rg(
            pattern,
            roots,
            ["*.py"],
            limit=limit,
            fixed_strings=False,
            context_lines=context_lines,
        )

    enriched = []
    for match in matches:
        file_path = Path(match["path"])
        module_path = _find_module_for_file(file_path)
        module_name = module_path.name if module_path else None
        scope = _scope_for_module(module_path, roots) if module_path else "unknown"
        enriched.append({**match, "module": module_name, "scope": scope})

    enriched = _sort_records(enriched)[:limit]
    return [
        TextContent(
            type="text",
            text=to_toon(
                {
                    "method_name": method_name,
                    "model": model_filter or None,
                    "count": len(enriched),
                    "matches": enriched,
                }
            ),
        )
    ]
