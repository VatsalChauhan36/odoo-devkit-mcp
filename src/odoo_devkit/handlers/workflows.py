import re
from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import run_rg, to_toon
from .helpers import (
    _build_view_lookup,
    _collect_access_csv_records,
    _collect_action_records,
    _collect_menu_records,
    _collect_record_rules,
    _collect_view_records,
    _enrich_model_matches,
    _find_model_python_files,
    _find_module_for_file,
    _list_related_module_files,
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


def _collect_model_definitions(model: str, roots: list[Path]) -> list[dict[str, Any]]:
    name_pattern = r"_name\s*=\s*['\"]" + re.escape(model) + r"['\"]"
    inherit_pattern = (
        r"_inherit\s*=\s*(?:\[[^\]]*['\"]"
        + re.escape(model)
        + r"['\"][^\]]*\]|['\"]"
        + re.escape(model)
        + r"['\"])"
    )

    direct = run_rg(name_pattern, roots, ["*.py"], limit=500, fixed_strings=False)
    inherited = run_rg(inherit_pattern, roots, ["*.py"], limit=500, fixed_strings=False)

    dedup: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in _enrich_model_matches(direct, "direct", roots) + _enrich_model_matches(
        inherited, "inherit", roots
    ):
        dedup[(row["path"], row["line"], row["kind"])] = row
    return _sort_records(list(dedup.values()))


def _collect_model_fields(model: str, roots: list[Path]) -> tuple[list[dict[str, Any]], list[Path]]:
    field_re = re.compile(r"^\s*(\w+)\s*=\s*(fields\.\w+)\(")
    model_files = _find_model_python_files(model, roots)

    seen_fields: dict[str, dict[str, Any]] = {}
    for py_file in model_files:
        try:
            lines = py_file.read_text(encoding="utf-8", errors="replace").splitlines()
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
            if field_name.startswith("_"):
                continue
            entry = {
                "field": field_name,
                "type": match.group(2),
                "line": line_no,
                "path": str(py_file),
                "module": module_name,
                "scope": scope,
            }
            existing = seen_fields.get(field_name)
            if not existing or (
                existing.get("scope") != "custom" and entry.get("scope") == "custom"
            ):
                seen_fields[field_name] = entry

    ordered = sorted(
        seen_fields.values(),
        key=lambda row: (
            0 if row.get("scope") == "custom" else 1,
            row.get("field") or "",
            row.get("path") or "",
            int(row.get("line") or 0),
        ),
    )
    return ordered, model_files


def _collect_model_methods(model: str, roots: list[Path]) -> list[dict[str, Any]]:
    method_re = re.compile(r"^\s*def\s+([A-Za-z_]\w*)\s*\(")
    rows: list[dict[str, Any]] = []
    for py_file in _find_model_python_files(model, roots):
        try:
            lines = py_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        module_path = _find_module_for_file(py_file)
        module_name = module_path.name if module_path else None
        scope = _scope_for_module(module_path, roots) if module_path else "unknown"

        for line_no, line in enumerate(lines, start=1):
            match = method_re.match(line)
            if not match:
                continue
            method_name = match.group(1)
            if method_name.startswith("__"):
                continue
            rows.append(
                {
                    "method_name": method_name,
                    "line": line_no,
                    "path": str(py_file),
                    "module": module_name,
                    "scope": scope,
                }
            )

    return sorted(
        rows,
        key=lambda row: (
            0 if row.get("scope") == "custom" else 1,
            row.get("method_name") or "",
            row.get("path") or "",
            int(row.get("line") or 0),
        ),
    )


def _menus_for_actions(
    actions: list[dict[str, Any]], roots: list[Path]
) -> list[dict[str, Any]]:
    action_ids = {action.get("xml_id") for action in actions if action.get("xml_id")}
    if not action_ids:
        return []

    menus = []
    for menu in _collect_menu_records(roots):
        if menu.get("action") in action_ids:
            menus.append(menu)
    return _sort_records(menus)


def _rules_for_model(model: str, roots: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    model_token = f"model_{model.replace('.', '_')}"
    access_rows = _collect_access_csv_records(roots)
    access = _sort_records(
        [
            row
            for row in access_rows
            if (row.get("model_id:id") or "") == model_token
            or (row.get("model_id:id") or "").endswith(f".{model_token}")
        ]
    )

    rules = _collect_record_rules(roots)
    matched_rules = _sort_records(
        [
            row
            for row in rules
            if (row.get("model_ref") or "") == model_token
            or (row.get("model_ref") or "").endswith(f".{model_token}")
        ]
    )
    return access, matched_rules


def _view_record_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("path") or ""),
        str(record.get("xml_id") or ""),
        str(record.get("inherit_id") or ""),
    )


def _candidate_views_for_model(
    model: str,
    records: list[dict[str, Any]],
    view_lookup: dict[str, dict[str, Any]],
    model_cache: dict[str, str | None],
) -> list[dict[str, Any]]:
    matches = []
    for record in records:
        if _resolve_view_model(record, view_lookup, model_cache) != model:
            continue
        matches.append(_with_effective_model(record, view_lookup, model_cache))
    return _sort_records(matches)


def _candidate_views_for_ref(
    view_ref: str,
    records: list[dict[str, Any]],
    view_lookup: dict[str, dict[str, Any]],
    model_cache: dict[str, str | None],
) -> list[dict[str, Any]]:
    targets = _targets_from_view_ref(view_ref, records)
    by_inherit: dict[str, list[dict[str, Any]]] = {}
    by_xml_id = {
        record.get("xml_id"): record for record in records if record.get("xml_id")
    }

    for record in records:
        inherit_id = record.get("inherit_id")
        if inherit_id:
            by_inherit.setdefault(inherit_id, []).append(record)

    selected: dict[tuple[str, str, str], dict[str, Any]] = {}
    queue: list[tuple[int, dict[str, Any]]] = []

    for record in records:
        if any(
            target in {record.get("xml_id"), record.get("xml_id_raw"), record.get("name")}
            for target in targets
        ):
            queue.append((0, record))

            current = record
            depth = 0
            seen_ancestors: set[str] = set()
            while current.get("inherit_id"):
                inherit_id = current["inherit_id"]
                if inherit_id in seen_ancestors:
                    break
                seen_ancestors.add(inherit_id)
                parent = by_xml_id.get(inherit_id)
                if parent is None:
                    break
                depth -= 1
                enriched_parent = _with_effective_model(parent, view_lookup, model_cache)
                parent_key = _view_record_key(enriched_parent)
                previous = selected.get(parent_key)
                if previous is None or depth < int(previous.get("depth", 0)):
                    selected[parent_key] = {"depth": depth, **enriched_parent}
                current = parent

    seen_descendants: set[tuple[str, str, int]] = set()
    while queue:
        depth, record = queue.pop(0)
        enriched = _with_effective_model(record, view_lookup, model_cache)
        key = _view_record_key(enriched)
        previous = selected.get(key)
        if previous is None or depth < int(previous.get("depth", 0)):
            selected[key] = {"depth": depth, **enriched}

        xml_id = enriched.get("xml_id")
        if not xml_id:
            continue
        marker = (str(enriched.get("path") or ""), xml_id, depth)
        if marker in seen_descendants:
            continue
        seen_descendants.add(marker)

        for child in _sort_records(by_inherit.get(xml_id, [])):
            queue.append((depth + 1, child))

    return sorted(
        selected.values(),
        key=lambda row: (
            int(row.get("depth") or 0),
            0 if row.get("scope") == "custom" else 1,
            row.get("module") or "",
            row.get("xml_id") or row.get("name") or "",
        ),
    )


def _search_patterns_for_target(
    target: str, target_type: str
) -> tuple[str, list[tuple[str, str, bool]]]:
    if target_type == "field":
        return (
            "field",
            [
                ("field", r"<field[^>]*name\s*=\s*['\"]" + re.escape(target) + r"['\"]", False),
                ("field", r"@name\s*=\s*['\"]" + re.escape(target) + r"['\"]", False),
            ],
        )
    if target_type == "button":
        return (
            "button",
            [
                ("button", r"<button[^>]*name\s*=\s*['\"]" + re.escape(target) + r"['\"]", False),
                ("button", r"@name\s*=\s*['\"]" + re.escape(target) + r"['\"]", False),
            ],
        )
    if target_type == "xml_id":
        return ("xml_id", [("xml_id", r"id\s*=\s*['\"]" + re.escape(target) + r"['\"]", False)])
    if target_type == "text":
        return ("text", [("text", target, True)])

    return (
        "auto",
        [
            ("field", r"<field[^>]*name\s*=\s*['\"]" + re.escape(target) + r"['\"]", False),
            ("button", r"<button[^>]*name\s*=\s*['\"]" + re.escape(target) + r"['\"]", False),
            ("xml_id", r"id\s*=\s*['\"]" + re.escape(target) + r"['\"]", False),
            ("text", target, True),
        ],
    )


def _search_view_target(
    candidate_views: list[dict[str, Any]],
    target: str,
    target_type: str,
    limit: int,
    context_lines: int,
    roots: list[Path],
) -> tuple[str, list[dict[str, Any]]]:
    files = [Path(record["path"]) for record in candidate_views if record.get("path")]
    if not files:
        return target_type, []

    file_view_refs: dict[str, list[str]] = {}
    for record in candidate_views:
        path = str(record.get("path") or "")
        if not path:
            continue
        ref = record.get("xml_id") or record.get("xml_id_raw") or record.get("name")
        if ref:
            file_view_refs.setdefault(path, [])
            if ref not in file_view_refs[path]:
                file_view_refs[path].append(ref)

    normalized_type, patterns = _search_patterns_for_target(target, target_type)
    all_matches: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()

    for kind, pattern, fixed_strings in patterns:
        matches = run_rg(
            pattern,
            files,
            ["*.xml"],
            limit=max(limit * 3, 30),
            fixed_strings=fixed_strings,
            context_lines=context_lines,
        )
        for row in matches:
            key = (row["path"], int(row["line"]), kind)
            if key in seen:
                continue
            seen.add(key)
            file_path = Path(row["path"])
            module_path = _find_module_for_file(file_path)
            module_name = module_path.name if module_path else None
            scope = _scope_for_module(module_path, roots) if module_path else "unknown"
            all_matches.append(
                {
                    **row,
                    "kind": kind,
                    "module": module_name,
                    "scope": scope,
                    "views": file_view_refs.get(row["path"], [])[:5],
                }
            )

        if normalized_type == "auto" and kind != "text" and all_matches:
            return kind, _sort_records(all_matches)[:limit]

    return normalized_type, _sort_records(all_matches)[:limit]


def _hint_for_override(
    candidate_views: list[dict[str, Any]], matches: list[dict[str, Any]]
) -> str:
    if any(match.get("scope") == "custom" for match in matches):
        return "Target already appears in custom XML. Start by editing those custom view files."
    if any(view.get("scope") == "custom" for view in candidate_views):
        return (
            "No existing custom view match was found. Extend one of the custom inherited views "
            "returned below."
        )
    return (
        "No custom inherited view was found for this target. Create a new inherited view against "
        "one of the base views returned below."
    )


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
    if name == "inspect_model_surface":
        model = (arguments.get("model") or "").strip()
        if not model:
            raise ValueError("model is required")

        limit = int(str(arguments.get("limit", 8)))
        include_methods = bool(arguments.get("include_methods", True))
        include_related_files = bool(arguments.get("include_related_files", True))
        related_files_limit = int(str(arguments.get("related_files_limit", 40)))

        definitions = _collect_model_definitions(model, roots)
        fields, model_files = _collect_model_fields(model, roots)
        methods = _collect_model_methods(model, roots) if include_methods else []

        view_records = _collect_view_records(roots)
        view_lookup = _build_view_lookup(view_records)
        model_cache: dict[str, str | None] = {}
        views = _candidate_views_for_model(model, view_records, view_lookup, model_cache)

        actions = _sort_records(
            [
                action
                for action in _collect_action_records(roots)
                if (action.get("res_model") or "").strip() == model
            ]
        )
        menus = _menus_for_actions(actions, roots)
        access, rules = _rules_for_model(model, roots)

        related_files: list[str] = []
        if include_related_files:
            module_paths = {
                _find_module_for_file(Path(row["path"]))
                for row in definitions + fields + methods + views + actions + menus + access + rules
                if row.get("path")
            }
            module_paths.update(_find_module_for_file(path) for path in model_files)
            for module_path in sorted(path for path in module_paths if path is not None):
                related_files.extend(_list_related_module_files(module_path, related_files_limit))
                if len(related_files) >= related_files_limit:
                    break
            related_files = sorted(set(related_files))[:related_files_limit]

        payload = {
            "model": model,
            "summary": {
                "definitions": len(definitions),
                "fields": len(fields),
                "methods": len(methods),
                "views": len(views),
                "actions": len(actions),
                "menus": len(menus),
                "access": len(access),
                "rules": len(rules),
                "related_files": len(related_files),
            },
            "definitions": definitions[:limit],
            "fields": fields[:limit],
            "views": views[:limit],
            "actions": actions[:limit],
            "menus": menus[:limit],
            "access": access[:limit],
            "rules": rules[:limit],
            "related_files": related_files,
        }
        if include_methods:
            payload["methods"] = methods[:limit]
        return [TextContent(type="text", text=to_toon(payload))]

    if name == "locate_view_override":
        target = (
            arguments.get("target")
            or arguments.get("field_name")
            or arguments.get("button_name")
            or arguments.get("text")
            or ""
        ).strip()
        model = (arguments.get("model") or "").strip()
        view_ref = (arguments.get("view_ref") or arguments.get("view") or "").strip()
        if not target:
            raise ValueError("target is required")
        if not model and not view_ref:
            raise ValueError("Either model or view_ref is required")

        target_type = str(arguments.get("target_type", "auto")).strip() or "auto"
        limit = int(str(arguments.get("limit", 12)))
        context_lines = int(str(arguments.get("context_lines", 0)))

        view_records = _collect_view_records(roots)
        view_lookup = _build_view_lookup(view_records)
        model_cache: dict[str, str | None] = {}

        candidate_views = (
            _candidate_views_for_ref(view_ref, view_records, view_lookup, model_cache)
            if view_ref
            else _candidate_views_for_model(model, view_records, view_lookup, model_cache)
        )
        if model:
            candidate_views = [
                record
                for record in candidate_views
                if (record.get("model") or "").strip() == model
            ]

        resolved_target_type, matches = _search_view_target(
            candidate_views=candidate_views,
            target=target,
            target_type=target_type,
            limit=limit,
            context_lines=context_lines,
            roots=roots,
        )

        payload = {
            "target": target,
            "target_type": resolved_target_type,
            "model": model or None,
            "view_ref": view_ref or None,
            "summary": {
                "candidate_views": len(candidate_views),
                "matches": len(matches),
                "custom_views": len(
                    [record for record in candidate_views if record.get("scope") == "custom"]
                ),
            },
            "hint": _hint_for_override(candidate_views, matches),
            "candidate_views": candidate_views[:limit],
            "matches": matches,
        }
        return [TextContent(type="text", text=to_toon(payload))]

    return None
