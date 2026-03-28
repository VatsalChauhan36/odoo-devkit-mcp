import re
from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import to_toon, run_rg
from .helpers import (
    _enrich_model_matches,
    _find_module_for_file,
    _list_related_module_files,
    _scope_for_module,
)


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
    if name == "find_model_definition":
        model = arguments.get("model")
        if not model:
            raise ValueError("model is required")
        limit = int(arguments.get("limit", 20))
        include_related_files = bool(arguments.get("include_related_files", True))
        related_files_limit = int(arguments.get("related_files_limit", 60))

        name_pattern = r"_name\s*=\s*['\"]" + re.escape(model) + r"['\"]"
        inherit_pattern = (
            r"_inherit\s*=\s*(?:\[[^\]]*['\"]"
            + re.escape(model)
            + r"['\"][^\]]*\]|['\"]"
            + re.escape(model)
            + r"['\"])"
        )

        direct = run_rg(name_pattern, roots, ["*.py"], limit=limit)
        inherited = run_rg(inherit_pattern, roots, ["*.py"], limit=limit)

        direct_enriched = _enrich_model_matches(direct, "direct", roots)
        inherited_enriched = _enrich_model_matches(inherited, "inherit", roots)

        dedup: dict[tuple[str, int, str], dict[str, Any]] = {}
        for row in direct_enriched + inherited_enriched:
            key = (row["path"], row["line"], row["kind"])
            dedup[key] = row
        all_matches = list(dedup.values())[: (limit * 2)]

        related_files: list[str] = []
        if include_related_files:
            module_paths = set()
            for row in all_matches:
                module = _find_module_for_file(Path(row["path"]))
                if module:
                    module_paths.add(module)
            for module_path in sorted(module_paths):
                related_files.extend(
                    _list_related_module_files(module_path, related_files_limit)
                )
                if len(related_files) >= related_files_limit:
                    break
            related_files = sorted(set(related_files))[:related_files_limit]

        return [
            TextContent(
                type="text",
                text=to_toon(
                    {"model": model, "matches": all_matches, "related_files": related_files}
                ),
            )
        ]

    if name == "get_model_fields":
        model = arguments.get("model")
        if not model:
            raise ValueError("model is required")
        limit = int(arguments.get("limit", 200))

        # Search for field declarations in Python files across all roots
        field_pattern = r"^\s+\w+\s*=\s*fields\."
        raw_matches = run_rg(field_pattern, roots, ["*.py"], limit=limit * 5, fixed_strings=False)

        # Filter to only files that define or inherit the model
        name_pat = re.compile(r"_name\s*=\s*['\"]" + re.escape(model) + r"['\"]")
        inherit_pat = re.compile(
            r"_inherit\s*=\s*(?:\[[^\]]*['\"]" + re.escape(model) + r"['\"][^\]]*\]|['\"]" + re.escape(model) + r"['\"])"
        )

        # Collect files that define/inherit the model
        model_files: set[str] = set()
        for root_path in roots:
            for py_file in root_path.rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8", errors="replace")
                    if name_pat.search(content) or inherit_pat.search(content):
                        model_files.add(str(py_file))
                except OSError:
                    continue

        # Only keep field matches from model files
        # Note: run_rg strips leading whitespace from text, so don't anchor with ^\s+
        field_re = re.compile(r"^(\w+)\s*=\s*(fields\.\w+)\(")
        results: list[dict[str, Any]] = []
        seen_fields: dict[str, dict[str, Any]] = {}
        for row in raw_matches:
            if row["path"] not in model_files:
                continue
            m = field_re.match(row["text"])
            if not m:
                continue
            field_name = m.group(1)
            field_type = m.group(2)
            if field_name.startswith("_"):
                continue
            file_path = Path(row["path"])
            mod = _find_module_for_file(file_path)
            entry = {
                "field": field_name,
                "type": field_type,
                "line": row["line"],
                "path": row["path"],
                "module": mod.name if mod else None,
                "scope": _scope_for_module(mod, roots) if mod else "unknown",
            }
            # Prefer custom scope over standard for duplicates
            existing = seen_fields.get(field_name)
            if not existing or (existing["scope"] != "custom" and entry["scope"] == "custom"):
                seen_fields[field_name] = entry

        results = sorted(seen_fields.values(), key=lambda x: x["field"])[:limit]
        return [
            TextContent(
                type="text",
                text=to_toon({
                    "model": model,
                    "field_count": len(results),
                    "source_files": sorted(model_files),
                    "fields": results,
                }),
            )
        ]

    return None
