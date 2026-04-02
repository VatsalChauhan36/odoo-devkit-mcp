import re
from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import run_rg, to_toon
from .helpers import (
    _enrich_model_matches,
    _find_model_python_files,
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
        limit = int(str(arguments.get("limit", 20)))
        include_related_files = bool(arguments.get("include_related_files", True))
        related_files_limit = int(str(arguments.get("related_files_limit", 60)))

        name_pattern = r"_name\s*=\s*['\"]" + re.escape(model) + r"['\"]"
        inherit_pattern = (
            r"_inherit\s*=\s*(?:\[[^\]]*['\"]"
            + re.escape(model)
            + r"['\"][^\]]*\]|['\"]"
            + re.escape(model)
            + r"['\"])"
        )

        direct = run_rg(name_pattern, roots, ["*.py"], limit=limit, fixed_strings=False)
        inherited = run_rg(
            inherit_pattern, roots, ["*.py"], limit=limit, fixed_strings=False
        )

        direct_enriched = _enrich_model_matches(direct, "direct", roots)
        inherited_enriched = _enrich_model_matches(inherited, "inherit", roots)

        dedup: dict[tuple[str, int, str], dict[str, Any]] = {}
        for row in direct_enriched + inherited_enriched:
            key = (row["path"], row["line"], row["kind"])
            dedup[key] = row
        all_matches = sorted(
            dedup.values(),
            key=lambda row: (
                0 if row.get("scope") == "custom" else 1,
                0 if row.get("kind") == "direct" else 1,
                row.get("module") or "",
                row["path"],
                row["line"],
            ),
        )[: (limit * 2)]

        related_files: list[str] = []
        if include_related_files:
            module_paths = set()
            for row in all_matches:
                module_path = _find_module_for_file(Path(row["path"]))
                if module_path:
                    module_paths.add(module_path)
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
                    {
                        "model": model,
                        "matches": all_matches,
                        "related_files": related_files,
                    }
                ),
            )
        ]

    if name == "get_model_fields":
        model = arguments.get("model")
        if not model:
            raise ValueError("model is required")
        limit = int(str(arguments.get("limit", 200)))

        field_re = re.compile(r"^\s*(\w+)\s*=\s*(fields\.\w+)\(")
        model_files = _find_model_python_files(model, roots)

        seen_fields: dict[str, dict[str, Any]] = {}
        for py_file in model_files:
            try:
                lines = py_file.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except OSError:
                continue
            module_path = _find_module_for_file(py_file)
            module_name = module_path.name if module_path else None
            scope = _scope_for_module(module_path, roots) if module_path else "unknown"

            for line_no, line in enumerate(lines, start=1):
                match = field_re.match(line)
                if not match:
                    continue
                field_name = match.group(1)
                field_type = match.group(2)
                if field_name.startswith("_"):
                    continue
                entry = {
                    "field": field_name,
                    "type": field_type,
                    "line": line_no,
                    "path": str(py_file),
                    "module": module_name,
                    "scope": scope,
                }
                existing = seen_fields.get(field_name)
                if not existing or (
                    existing.get("scope") != "custom" and entry["scope"] == "custom"
                ):
                    seen_fields[field_name] = entry

        results = sorted(seen_fields.values(), key=lambda row: row["field"])[:limit]
        return [
            TextContent(
                type="text",
                text=to_toon(
                    {
                        "model": model,
                        "field_count": len(results),
                        "source_files": [str(path) for path in model_files],
                        "fields": results,
                    }
                ),
            )
        ]

    return None
