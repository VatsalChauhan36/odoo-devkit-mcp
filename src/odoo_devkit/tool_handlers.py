import csv
import ast
import re
import subprocess
import xml.etree.ElementTree as ET
from pprint import pformat
from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from .constants import ODOO_DOCS_PATH
from .utils import assert_allowed_path, compact_json, run_rg


def _discover_modules(roots: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for root in roots:
        for child in root.iterdir():
            if not child.is_dir():
                continue
            if (child / "__manifest__.py").exists():
                found.setdefault(child.name, child)
    return found


def _parse_manifest(module_path: Path) -> dict[str, Any]:
    manifest_path = module_path / "__manifest__.py"
    content = manifest_path.read_text(encoding="utf-8")
    payload = ast.literal_eval(content)
    if not isinstance(payload, dict):
        raise ValueError("Manifest must be a Python dict")
    keys = (
        "name",
        "version",
        "summary",
        "depends",
        "data",
        "assets",
        "license",
        "application",
    )
    return {key: payload.get(key) for key in keys if key in payload}


def _read_file_lines(path: Path, start: int, end: int, max_lines: int) -> dict[str, Any]:
    if start < 1:
        raise ValueError("start must be >= 1")
    if end < start:
        raise ValueError("end must be >= start")
    if max_lines < 1:
        raise ValueError("max_lines must be >= 1")

    target_end = min(end, start + max_lines - 1)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for idx, line in enumerate(handle, start=1):
            if idx < start:
                continue
            if idx > target_end:
                break
            rows.append({"line": idx, "text": line.rstrip("\n")})
    return {"path": str(path), "start": start, "end": target_end, "lines": rows}


def _find_module_for_file(file_path: Path) -> Path | None:
    for parent in [file_path.resolve(), *file_path.resolve().parents]:
        if parent.is_dir() and (parent / "__manifest__.py").exists():
            return parent
    return None


def _scope_for_module(module_path: Path, roots: list[Path]) -> str:
    # Convention: first configured root is the custom addons root.
    custom_root = roots[0].resolve() if roots else None
    if custom_root and module_path.parent.resolve() == custom_root:
        return "custom"
    return "standard"


def _list_related_module_files(module_path: Path, limit: int) -> list[str]:
    patterns = [
        "models/**/*.py",
        "views/**/*.xml",
        "security/*",
        "data/**/*.xml",
        "wizard/**/*.py",
        "report/**/*.py",
        "report/**/*.xml",
    ]
    found: list[str] = []
    for pattern in patterns:
        for path in module_path.glob(pattern):
            if path.is_file():
                found.append(str(path))
                if len(found) >= limit:
                    return sorted(set(found))
    return sorted(set(found))


def _enrich_model_matches(
    matches: list[dict[str, Any]], kind: str, roots: list[Path]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for match in matches:
        file_path = Path(match["path"])
        module_path = _find_module_for_file(file_path)
        module_name = module_path.name if module_path else None
        scope = _scope_for_module(module_path, roots) if module_path else "unknown"
        out.append(
            {
                **match,
                "kind": kind,
                "module": module_name,
                "scope": scope,
            }
        )
    return out


def _iter_xml_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend(path for path in root.rglob("*.xml") if path.is_file())
    return files


def _normalize_xml_id(module: str | None, xml_id: str | None) -> str | None:
    if not xml_id:
        return None
    if "." in xml_id:
        return xml_id
    if module:
        return f"{module}.{xml_id}"
    return xml_id


def _collect_view_records(roots: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for xml_file in _iter_xml_files(roots):
        module_path = _find_module_for_file(xml_file)
        module_name = module_path.name if module_path else None
        scope = _scope_for_module(module_path, roots) if module_path else "unknown"
        try:
            tree = ET.parse(xml_file)
        except ET.ParseError:
            continue
        root = tree.getroot()
        for rec in root.iter("record"):
            if rec.get("model") != "ir.ui.view":
                continue
            raw_xml_id = rec.get("id")
            xml_id = _normalize_xml_id(module_name, raw_xml_id)
            fields: dict[str, str] = {}
            for field in rec.findall("field"):
                field_name = field.get("name")
                if not field_name:
                    continue
                ref_val = field.get("ref")
                text_val = (field.text or "").strip()
                fields[field_name] = ref_val if ref_val else text_val
            inherit_id = fields.get("inherit_id")
            inherit_id = _normalize_xml_id(module_name, inherit_id)
            records.append(
                {
                    "path": str(xml_file),
                    "module": module_name,
                    "scope": scope,
                    "xml_id": xml_id,
                    "xml_id_raw": raw_xml_id,
                    "name": fields.get("name"),
                    "model": fields.get("model"),
                    "inherit_id": inherit_id,
                }
            )
    return records


def _match_view_ref(record: dict[str, Any], view_ref: str) -> bool:
    ref = view_ref.strip()
    xml_id = (record.get("xml_id") or "").strip()
    xml_id_raw = (record.get("xml_id_raw") or "").strip()
    name = (record.get("name") or "").strip()
    model = (record.get("model") or "").strip()
    return ref == xml_id or ref == xml_id_raw or ref == name or ref == model


def _targets_from_view_ref(view_ref: str, records: list[dict[str, Any]]) -> set[str]:
    ref = view_ref.strip()
    targets = {ref}
    for rec in records:
        xml_id = rec.get("xml_id")
        xml_id_raw = rec.get("xml_id_raw")
        name = rec.get("name")
        if ref in {xml_id, xml_id_raw, name}:
            if xml_id:
                targets.add(xml_id)
            if xml_id_raw and rec.get("module"):
                targets.add(f"{rec['module']}.{xml_id_raw}")
            if xml_id_raw:
                targets.add(xml_id_raw)
    return targets


def _collect_action_records(roots: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for xml_file in _iter_xml_files(roots):
        module_path = _find_module_for_file(xml_file)
        module_name = module_path.name if module_path else None
        scope = _scope_for_module(module_path, roots) if module_path else "unknown"
        try:
            tree = ET.parse(xml_file)
        except ET.ParseError:
            continue
        for rec in tree.getroot().iter("record"):
            if rec.get("model") != "ir.actions.act_window":
                continue
            raw_xml_id = rec.get("id")
            xml_id = _normalize_xml_id(module_name, raw_xml_id)
            fields: dict[str, str] = {}
            for field in rec.findall("field"):
                fname = field.get("name")
                if not fname:
                    continue
                fields[fname] = field.get("ref") or (field.text or "").strip()
            records.append(
                {
                    "path": str(xml_file),
                    "module": module_name,
                    "scope": scope,
                    "xml_id": xml_id,
                    "xml_id_raw": raw_xml_id,
                    "name": fields.get("name"),
                    "res_model": fields.get("res_model"),
                    "view_id": _normalize_xml_id(module_name, fields.get("view_id")),
                    "view_mode": fields.get("view_mode"),
                }
            )
    return records


def _collect_menu_records(roots: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for xml_file in _iter_xml_files(roots):
        module_path = _find_module_for_file(xml_file)
        module_name = module_path.name if module_path else None
        scope = _scope_for_module(module_path, roots) if module_path else "unknown"
        try:
            tree = ET.parse(xml_file)
        except ET.ParseError:
            continue
        root = tree.getroot()

        # <menuitem ...> style
        for menu in root.iter("menuitem"):
            raw_xml_id = menu.get("id")
            xml_id = _normalize_xml_id(module_name, raw_xml_id)
            action = menu.get("action")
            parent = menu.get("parent")
            records.append(
                {
                    "path": str(xml_file),
                    "module": module_name,
                    "scope": scope,
                    "xml_id": xml_id,
                    "xml_id_raw": raw_xml_id,
                    "name": menu.get("name"),
                    "action": _normalize_xml_id(module_name, action),
                    "parent": _normalize_xml_id(module_name, parent),
                }
            )

        # <record model="ir.ui.menu"> style
        for rec in root.iter("record"):
            if rec.get("model") != "ir.ui.menu":
                continue
            raw_xml_id = rec.get("id")
            xml_id = _normalize_xml_id(module_name, raw_xml_id)
            fields: dict[str, str] = {}
            for field in rec.findall("field"):
                fname = field.get("name")
                if not fname:
                    continue
                fields[fname] = field.get("ref") or (field.text or "").strip()
            records.append(
                {
                    "path": str(xml_file),
                    "module": module_name,
                    "scope": scope,
                    "xml_id": xml_id,
                    "xml_id_raw": raw_xml_id,
                    "name": fields.get("name"),
                    "action": _normalize_xml_id(module_name, fields.get("action")),
                    "parent": _normalize_xml_id(module_name, fields.get("parent_id")),
                }
            )
    return records


def _collect_access_csv_records(roots: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root in roots:
        for csv_path in root.rglob("ir.model.access.csv"):
            module_path = _find_module_for_file(csv_path)
            module_name = module_path.name if module_path else None
            scope = _scope_for_module(module_path, roots) if module_path else "unknown"
            try:
                with csv_path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        rows.append(
                            {
                                "path": str(csv_path),
                                "module": module_name,
                                "scope": scope,
                                "id": row.get("id"),
                                "name": row.get("name"),
                                "model_id:id": row.get("model_id:id"),
                                "group_id:id": row.get("group_id:id"),
                                "perm_read": row.get("perm_read"),
                                "perm_write": row.get("perm_write"),
                                "perm_create": row.get("perm_create"),
                                "perm_unlink": row.get("perm_unlink"),
                            }
                        )
            except OSError:
                continue
    return rows


def _collect_record_rules(roots: list[Path]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for xml_file in _iter_xml_files(roots):
        module_path = _find_module_for_file(xml_file)
        module_name = module_path.name if module_path else None
        scope = _scope_for_module(module_path, roots) if module_path else "unknown"
        try:
            tree = ET.parse(xml_file)
        except ET.ParseError:
            continue
        for rec in tree.getroot().iter("record"):
            if rec.get("model") != "ir.rule":
                continue
            fields: dict[str, str] = {}
            for field in rec.findall("field"):
                fname = field.get("name")
                if not fname:
                    continue
                fields[fname] = field.get("ref") or (field.text or "").strip()
            rules.append(
                {
                    "path": str(xml_file),
                    "module": module_name,
                    "scope": scope,
                    "xml_id": _normalize_xml_id(module_name, rec.get("id")),
                    "name": fields.get("name"),
                    "model_ref": fields.get("model_id"),
                    "domain_force": fields.get("domain_force"),
                    "groups": fields.get("groups"),
                }
            )
    return rules


def _snake_from_model(model: str) -> str:
    return model.replace(".", "_").replace("-", "_")


def _class_from_model(model: str) -> str:
    parts = re.split(r"[._-]+", model.strip())
    return "".join(part.capitalize() for part in parts if part) or "CustomModel"


def _build_model_python(
    model: str,
    description: str,
    base_class: str,
    inherit_model: str | None,
    field_snippets: str | None,
) -> str:
    class_name = _class_from_model(model)
    lines = [
        "from odoo import fields, models",
        "",
        "",
        f"class {class_name}(models.{base_class}):",
    ]
    lines.append(f"    _name = \"{model}\"")
    lines.append(f"    _description = \"{description}\"")
    if inherit_model:
        lines.append(f"    _inherit = \"{inherit_model}\"")
    lines.append("")
    if field_snippets and field_snippets.strip():
        for line in field_snippets.splitlines():
            lines.append(f"    {line.rstrip()}")
    else:
        lines.append("    name = fields.Char(string=\"Name\", required=True)")
    lines.append("")
    return "\n".join(lines)


def _build_full_replace_patch(abs_path: Path, old_content: str, new_content: str) -> str:
    patch = f"*** Update File: {abs_path}\n@@\n"
    for line in old_content.splitlines():
        patch += f"-{line}\n"
    for line in new_content.splitlines():
        patch += f"+{line}\n"
    return patch


def _build_add_file_patch(abs_path: Path, content: str) -> str:
    patch = f"*** Add File: {abs_path}\n"
    for line in content.splitlines():
        patch += f"+{line}\n"
    return patch


def _append_manifest_data_entry(
    manifest_path: Path, data_file: str
) -> str | None:
    if not manifest_path.exists():
        return None
    old_content = manifest_path.read_text(encoding="utf-8", errors="replace")
    payload = ast.literal_eval(old_content)
    if not isinstance(payload, dict):
        return None
    data_list = payload.setdefault("data", [])
    if isinstance(data_list, list) and data_file not in data_list:
        data_list.append(data_file)
    new_content = pformat(payload, width=100, sort_dicts=False) + "\n"
    return _build_full_replace_patch(manifest_path.resolve(), old_content, new_content)


def _append_manifest_data_entries(
    manifest_path: Path, data_files: list[str]
) -> str | None:
    if not manifest_path.exists():
        return None
    old_content = manifest_path.read_text(encoding="utf-8", errors="replace")
    payload = ast.literal_eval(old_content)
    if not isinstance(payload, dict):
        return None
    data_list = payload.setdefault("data", [])
    if not isinstance(data_list, list):
        return None
    for data_file in data_files:
        if data_file not in data_list:
            data_list.append(data_file)
    new_content = pformat(payload, width=100, sort_dicts=False) + "\n"
    return _build_full_replace_patch(manifest_path.resolve(), old_content, new_content)


def _patch_document(parts: list[str]) -> str:
    return (
        "*** Begin Patch\n"
        + "".join(part if part.endswith("\n") else part + "\n" for part in parts)
        + "*** End Patch\n"
    )


def _default_views_xml_payload(module: str, model: str, view_types: list[str]) -> str:
    model_key = _snake_from_model(model)
    chunks: list[str] = [
        "<?xml version='1.0' encoding='utf-8'?>",
        "<odoo>",
        "    <data>",
    ]
    if "form" in view_types:
        chunks.extend(
            [
                f"        <record id=\"{model_key}_view_form\" model=\"ir.ui.view\">",
                f"            <field name=\"name\">{model}.view.form</field>",
                f"            <field name=\"model\">{model}</field>",
                "            <field name=\"arch\" type=\"xml\">",
                "                <form string=\"Record\">",
                "                    <sheet>",
                "                        <group>",
                "                            <field name=\"name\"/>",
                "                        </group>",
                "                    </sheet>",
                "                </form>",
                "            </field>",
                "        </record>",
            ]
        )
    if "list" in view_types:
        chunks.extend(
            [
                f"        <record id=\"{model_key}_view_list\" model=\"ir.ui.view\">",
                f"            <field name=\"name\">{model}.view.list</field>",
                f"            <field name=\"model\">{model}</field>",
                "            <field name=\"arch\" type=\"xml\">",
                "                <list>",
                "                    <field name=\"name\"/>",
                "                </list>",
                "            </field>",
                "        </record>",
            ]
        )
    if "search" in view_types:
        chunks.extend(
            [
                f"        <record id=\"{model_key}_view_search\" model=\"ir.ui.view\">",
                f"            <field name=\"name\">{model}.view.search</field>",
                f"            <field name=\"model\">{model}</field>",
                "            <field name=\"arch\" type=\"xml\">",
                "                <search>",
                "                    <field name=\"name\"/>",
                "                </search>",
                "            </field>",
                "        </record>",
            ]
        )
    if "kanban" in view_types:
        chunks.extend(
            [
                f"        <record id=\"{model_key}_view_kanban\" model=\"ir.ui.view\">",
                f"            <field name=\"name\">{model}.view.kanban</field>",
                f"            <field name=\"model\">{model}</field>",
                "            <field name=\"arch\" type=\"xml\">",
                "                <kanban/>",
                "            </field>",
                "        </record>",
            ]
        )
    if "graph" in view_types:
        chunks.extend(
            [
                f"        <record id=\"{model_key}_view_graph\" model=\"ir.ui.view\">",
                f"            <field name=\"name\">{model}.view.graph</field>",
                f"            <field name=\"model\">{model}</field>",
                "            <field name=\"arch\" type=\"xml\">",
                "                <graph/>",
                "            </field>",
                "        </record>",
            ]
        )
    if "pivot" in view_types:
        chunks.extend(
            [
                f"        <record id=\"{model_key}_view_pivot\" model=\"ir.ui.view\">",
                f"            <field name=\"name\">{model}.view.pivot</field>",
                f"            <field name=\"model\">{model}</field>",
                "            <field name=\"arch\" type=\"xml\">",
                "                <pivot/>",
                "            </field>",
                "        </record>",
            ]
        )
    chunks.extend(["    </data>", "</odoo>", ""])
    return "\n".join(chunks)


def _default_action_xml_payload(
    action_id: str,
    action_name: str,
    model: str,
    view_mode: str = "list,form",
    context: str | None = None,
    domain: str | None = None,
) -> str:
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        "<odoo>",
        "    <data>",
        f"        <record id=\"{action_id}\" model=\"ir.actions.act_window\">",
        f"            <field name=\"name\">{action_name}</field>",
        f"            <field name=\"res_model\">{model}</field>",
        f"            <field name=\"view_mode\">{view_mode}</field>",
    ]
    if context:
        lines.append(f"            <field name=\"context\">{context}</field>")
    if domain:
        lines.append(f"            <field name=\"domain\">{domain}</field>")
    lines.extend(["        </record>", "    </data>", "</odoo>", ""])
    return "\n".join(lines)


def dispatch_tool(
    name: str, arguments: dict[str, Any], roots: list[Path]
) -> Sequence[TextContent]:
    modules = _discover_modules(roots)

    if name in ("list_modules", "list_custom_modules"):
        query = arguments.get("query", "").strip().lower()
        limit = int(arguments.get("limit", 50))
        module_items = modules.items()
        if name == "list_custom_modules":
            # Convention: first configured root is the custom addons root.
            custom_root = roots[0].resolve()
            module_items = [
                (module_name, module_path)
                for module_name, module_path in module_items
                if module_path.resolve().parent == custom_root
            ]
        names = sorted(module_name for module_name, _ in module_items)
        if query:
            names = [module for module in names if query in module.lower()]
        result = {
            "count": len(names[:limit]),
            "total_matches": len(names),
            "modules": names[:limit],
        }
        result["scope"] = "custom" if name == "list_custom_modules" else "all"
        return [TextContent(type="text", text=compact_json(result))]

    if name == "get_module_manifest":
        module = arguments.get("module")
        if not module:
            raise ValueError("module is required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        result = {
            "module": module,
            "path": str(modules[module]),
            "manifest": _parse_manifest(modules[module]),
        }
        return [TextContent(type="text", text=compact_json(result))]

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
                text=compact_json(
                    {"model": model, "matches": all_matches, "related_files": related_files}
                ),
            )
        ]

    if name == "find_xml_id_definition":
        xml_id = arguments.get("xml_id")
        if not xml_id:
            raise ValueError("xml_id is required")
        limit = int(arguments.get("limit", 20))
        pattern = r"id\s*=\s*['\"]" + re.escape(xml_id) + r"['\"]"
        matches = run_rg(pattern, roots, ["*.xml"], limit=limit)
        return [
            TextContent(
                type="text", text=compact_json({"xml_id": xml_id, "matches": matches})
            )
        ]

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

    if name == "find_action_by_model":
        model = arguments.get("model")
        if not model:
            raise ValueError("model is required")
        limit = int(arguments.get("limit", 80))
        target = model.strip()
        actions = _collect_action_records(roots)
        matches = [a for a in actions if (a.get("res_model") or "").strip() == target]
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

    if name == "find_menu_hierarchy":
        ref = arguments.get("ref")
        if not ref:
            raise ValueError("ref is required")
        limit = int(arguments.get("limit", 120))
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

        # Also resolve through matching view -> action.view_id
        for view in views:
            if target in {view.get("xml_id"), view.get("xml_id_raw"), view.get("name")}:
                view_ids = {view.get("xml_id"), view.get("xml_id_raw")}
                for action in actions:
                    if action.get("view_id") in view_ids and action.get("xml_id"):
                        target_action_ids.add(action["xml_id"])

        menu_map = {m.get("xml_id"): m for m in menus if m.get("xml_id")}
        matched_menus = [m for m in menus if m.get("action") in target_action_ids]

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
            result.append(
                {
                    "menu": menu,
                    "ancestors": build_ancestors(menu),
                    "children": [
                        m for m in menus if m.get("parent") == menu.get("xml_id")
                    ][:20],
                }
            )
        return [
            TextContent(
                type="text",
                text=compact_json(
                    {
                        "ref": target,
                        "target_actions": sorted(target_action_ids),
                        "count": len(result),
                        "matches": result,
                    }
                ),
            )
        ]

    if name == "find_field_in_views":
        field_name = arguments.get("field_name")
        if not field_name:
            raise ValueError("field_name is required")
        model = (arguments.get("model") or "").strip()
        limit = int(arguments.get("limit", 100))

        # Match direct field nodes and xpath expressions.
        p1 = r"<field[^>]*name\s*=\s*['\"]" + re.escape(field_name) + r"['\"]"
        p2 = r"@name\s*=\s*['\"]" + re.escape(field_name) + r"['\"]"
        m1 = run_rg(p1, roots, ["*.xml"], limit=limit, fixed_strings=False)
        m2 = run_rg(p2, roots, ["*.xml"], limit=limit, fixed_strings=False)

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

        if model:
            view_paths = {
                rec["path"]
                for rec in _collect_view_records(roots)
                if (rec.get("model") or "").strip() == model
            }
            matches = [m for m in matches if m["path"] in view_paths]

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

    if name == "find_security_access_for_model":
        model = arguments.get("model")
        if not model:
            raise ValueError("model is required")
        limit = int(arguments.get("limit", 120))
        target = model.strip()

        csv_rows = _collect_access_csv_records(roots)
        model_token = f"model_{target.replace('.', '_')}"
        access_matches = [
            row for row in csv_rows
            if (row.get("model_id:id") or "") == model_token
            or (row.get("model_id:id") or "").endswith(f".{model_token}")
        ]

        rules = _collect_record_rules(roots)
        rule_matches = [
            row
            for row in rules
            if (row.get("model_ref") or "") == model_token
            or (row.get("model_ref") or "").endswith(f".{model_token}")
        ]

        return [
            TextContent(
                type="text",
                text=compact_json(
                    {
                        "model": target,
                        "access_count": len(access_matches[:limit]),
                        "rule_count": len(rule_matches[:limit]),
                        "access": access_matches[:limit],
                        "rules": rule_matches[:limit],
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

    if name == "scaffold_view_inherit_patch":
        module = arguments.get("module")
        model = arguments.get("model")
        inherit_view_ref = arguments.get("inherit_view_ref")
        new_view_id = arguments.get("new_view_id")
        xml_snippet = arguments.get("xml_snippet")
        xpath_expr = arguments.get("xpath_expr", "//sheet")
        xpath_position = arguments.get("xpath_position", "inside")
        target_xml_path = arguments.get("target_xml_path")

        if not module:
            raise ValueError("module is required")
        if not model:
            raise ValueError("model is required")
        if not inherit_view_ref:
            raise ValueError("inherit_view_ref is required")
        if not new_view_id:
            raise ValueError("new_view_id is required")
        if not xml_snippet:
            raise ValueError("xml_snippet is required")

        if module not in modules:
            raise ValueError(f"Unknown module: {module}")

        module_path = modules[module]
        if target_xml_path:
            rel = target_xml_path.strip().lstrip("/")
        else:
            rel = f"views/{module}_inherit_views.xml"
        abs_xml = str((module_path / rel).resolve())

        # Normalize indentation of the inserted snippet block.
        snippet_lines = [
            line.rstrip() for line in str(xml_snippet).splitlines() if line.strip()
        ]
        snippet_block = (
            "\n".join([f"                {line}" for line in snippet_lines])
            or "                <!-- TODO: add xml -->"
        )

        xml_payload = (
            "<?xml version='1.0' encoding='utf-8'?>\n"
            "<odoo>\n"
            "    <data>\n"
            f"        <record id=\"{new_view_id}\" model=\"ir.ui.view\">\n"
            f"            <field name=\"name\">{new_view_id}</field>\n"
            f"            <field name=\"model\">{model}</field>\n"
            f"            <field name=\"inherit_id\" ref=\"{inherit_view_ref}\"/>\n"
            "            <field name=\"arch\" type=\"xml\">\n"
            f"                <xpath expr=\"{xpath_expr}\" position=\"{xpath_position}\">\n"
            f"{snippet_block}\n"
            "                </xpath>\n"
            "            </field>\n"
            "        </record>\n"
            "    </data>\n"
            "</odoo>\n"
        )

        patch = (
            "*** Begin Patch\n"
            f"*** Add File: {abs_xml}\n"
            + "".join(f"+{line}\n" for line in xml_payload.splitlines())
            + "*** End Patch\n"
        )
        return [
            TextContent(
                type="text",
                text=compact_json(
                    {
                        "module": module,
                        "target_xml_path": abs_xml,
                        "patch": patch,
                    }
                ),
            )
        ]

    if name == "scaffold_model_patch":
        module = arguments.get("module")
        model = arguments.get("model")
        if not module:
            raise ValueError("module is required")
        if not model:
            raise ValueError("model is required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")

        description = arguments.get("description") or _class_from_model(model)
        base_class = arguments.get("base_class", "Model")
        inherit_model = arguments.get("inherit_model")
        field_snippets = arguments.get("field_snippets")
        target_python_path = arguments.get("target_python_path")
        include_init_update = bool(arguments.get("include_init_update", True))
        include_manifest_update = bool(arguments.get("include_manifest_update", False))
        manifest_data_file = arguments.get("manifest_data_file")
        include_basic_views = bool(arguments.get("include_basic_views", False))
        include_access_csv = bool(arguments.get("include_access_csv", False))

        module_path = modules[module]
        model_stem = _snake_from_model(model)
        rel_py = (
            target_python_path.strip().lstrip("/")
            if target_python_path
            else f"models/{model_stem}.py"
        )
        abs_py = (module_path / rel_py).resolve()

        model_payload = _build_model_python(
            model=model,
            description=description,
            base_class=base_class,
            inherit_model=inherit_model,
            field_snippets=field_snippets,
        )

        patch_parts: list[str] = []
        if abs_py.exists():
            old_py = abs_py.read_text(encoding="utf-8", errors="replace")
            patch_parts.append(_build_full_replace_patch(abs_py, old_py, model_payload))
        else:
            patch_parts.append(_build_add_file_patch(abs_py, model_payload))

        if include_init_update:
            init_path = (module_path / "models" / "__init__.py").resolve()
            import_line = f"from . import {Path(rel_py).stem}"
            if init_path.exists():
                old_init = init_path.read_text(encoding="utf-8", errors="replace")
                if import_line not in old_init.splitlines():
                    new_init = old_init.rstrip("\n")
                    new_init = (
                        new_init + "\n" + import_line + "\n"
                        if new_init
                        else (import_line + "\n")
                    )
                    patch_parts.append(
                        _build_full_replace_patch(init_path, old_init, new_init)
                    )
            else:
                patch_parts.append(_build_add_file_patch(init_path, import_line + "\n"))

        if include_manifest_update and manifest_data_file:
            manifest_path = (module_path / "__manifest__.py").resolve()
            manifest_patch = _append_manifest_data_entry(manifest_path, manifest_data_file)
            if manifest_patch:
                patch_parts.append(manifest_patch)

        manifest_files_for_append: list[str] = []
        if include_basic_views:
            rel_views = f"views/{model_stem}_views.xml"
            abs_views = (module_path / rel_views).resolve()
            views_payload = _default_views_xml_payload(
                module, model, ["form", "list", "search"]
            )
            if abs_views.exists():
                old_views = abs_views.read_text(encoding="utf-8", errors="replace")
                patch_parts.append(
                    _build_full_replace_patch(abs_views, old_views, views_payload)
                )
            else:
                patch_parts.append(_build_add_file_patch(abs_views, views_payload))
            manifest_files_for_append.append(rel_views)

        if include_access_csv:
            rel_access = "security/ir.model.access.csv"
            abs_access = (module_path / rel_access).resolve()
            model_token = f"model_{model_stem}"
            default_row = (
                f"access_{model_stem}_user,access_{model_stem}_user,"
                f"{model_token},base.group_user,1,1,1,1\n"
            )
            if abs_access.exists():
                old_access = abs_access.read_text(encoding="utf-8", errors="replace")
                if "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink" in old_access:
                    if default_row not in old_access:
                        new_access = old_access
                        if not new_access.endswith("\n"):
                            new_access += "\n"
                        new_access += default_row
                        patch_parts.append(
                            _build_full_replace_patch(abs_access, old_access, new_access)
                        )
                else:
                    new_access = (
                        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
                        + default_row
                    )
                    patch_parts.append(
                        _build_full_replace_patch(abs_access, old_access, new_access)
                    )
            else:
                payload = (
                    "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
                    + default_row
                )
                patch_parts.append(_build_add_file_patch(abs_access, payload))
            manifest_files_for_append.append(rel_access)

        if include_manifest_update and manifest_files_for_append:
            manifest_path = (module_path / "__manifest__.py").resolve()
            manifest_patch = _append_manifest_data_entries(
                manifest_path, manifest_files_for_append
            )
            if manifest_patch:
                patch_parts.append(manifest_patch)

        patch = _patch_document(patch_parts)
        return [
            TextContent(
                type="text",
                text=compact_json(
                    {
                        "module": module,
                        "model": model,
                        "target_python_path": str(abs_py),
                        "patch": patch,
                    }
                ),
            )
        ]

    if name == "init_update_patch":
        module = arguments.get("module")
        imports = arguments.get("imports") or []
        init_rel = arguments.get("init_path") or "__init__.py"
        if not module:
            raise ValueError("module is required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        if not isinstance(imports, list) or not imports:
            raise ValueError("imports must be a non-empty list")
        module_path = modules[module]
        init_path = (module_path / init_rel.strip().lstrip("/")).resolve()
        old = init_path.read_text(encoding="utf-8", errors="replace") if init_path.exists() else ""
        lines = old.splitlines()
        changed = False
        for item in imports:
            raw = str(item).strip()
            if not raw:
                continue
            # Support bare module names (e.g. "my_model") or full import lines
            line = raw if raw.startswith("from ") or raw.startswith("import ") else f"from . import {raw}"
            if line not in lines:
                lines.append(line)
                changed = True
        if not changed:
            patch = _patch_document([])
        else:
            new = "\n".join(lines).rstrip("\n") + "\n"
            parts = [_build_full_replace_patch(init_path, old, new)] if init_path.exists() else [_build_add_file_patch(init_path, new)]
            patch = _patch_document(parts)
        return [TextContent(type="text", text=compact_json({"module": module, "init_path": str(init_path), "patch": patch}))]

    if name == "manifest_update_patch":
        module = arguments.get("module")
        data_files = arguments.get("data_files") or []
        if not module:
            raise ValueError("module is required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        if not isinstance(data_files, list) or not data_files:
            raise ValueError("data_files must be a non-empty list")
        manifest_path = (modules[module] / "__manifest__.py").resolve()
        manifest_patch = _append_manifest_data_entries(
            manifest_path, [str(x) for x in data_files]
        )
        patch = _patch_document([manifest_patch] if manifest_patch else [])
        return [TextContent(type="text", text=compact_json({"module": module, "manifest_path": str(manifest_path), "patch": patch}))]

    if name == "scaffold_inherit_model_patch":
        module = arguments.get("module")
        inherit_model = arguments.get("inherit_model")
        target_python_path = arguments.get("target_python_path")
        field_snippets = arguments.get("field_snippets")
        method_snippets = arguments.get("method_snippets")
        include_init_update = bool(arguments.get("include_init_update", True))
        if not module:
            raise ValueError("module is required")
        if not inherit_model:
            raise ValueError("inherit_model is required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        module_path = modules[module]
        model_stem = _snake_from_model(inherit_model)
        if target_python_path:
            rel_py = target_python_path.strip().lstrip("/")
            # Strip leading "<module>/" prefix if caller passed a full module-relative path
            module_prefix = module + "/"
            if rel_py.startswith(module_prefix):
                rel_py = rel_py[len(module_prefix):]
        else:
            rel_py = f"models/{model_stem}_inherit.py"
        abs_py = (module_path / rel_py).resolve()
        class_name = _class_from_model(inherit_model) + "Inherit"
        payload = [
            "from odoo import fields, models",
            "",
            "",
            f"class {class_name}(models.Model):",
            f"    _inherit = \"{inherit_model}\"",
            "",
        ]
        if field_snippets:
            payload.extend([f"    {ln.rstrip()}" for ln in str(field_snippets).splitlines() if ln.strip()])
            payload.append("")
        if method_snippets:
            payload.extend([f"    {ln.rstrip()}" for ln in str(method_snippets).splitlines() if ln.strip()])
            payload.append("")
        if len(payload) <= 6:
            payload.append("    # add fields or methods here")
        model_payload = "\n".join(payload) + "\n"
        parts = [_build_full_replace_patch(abs_py, abs_py.read_text(encoding="utf-8", errors="replace"), model_payload)] if abs_py.exists() else [_build_add_file_patch(abs_py, model_payload)]
        if include_init_update:
            init_path = (module_path / "models" / "__init__.py").resolve()
            import_line = f"from . import {Path(rel_py).stem}"
            old_init = init_path.read_text(encoding="utf-8", errors="replace") if init_path.exists() else ""
            if import_line not in old_init.splitlines():
                new_init = (old_init.rstrip("\n") + "\n" + import_line + "\n").lstrip("\n")
                parts.append(_build_full_replace_patch(init_path, old_init, new_init) if init_path.exists() else _build_add_file_patch(init_path, new_init))
        patch = _patch_document(parts)
        return [TextContent(type="text", text=compact_json({"module": module, "inherit_model": inherit_model, "target_python_path": str(abs_py), "patch": patch}))]

    if name == "scaffold_views_patch":
        module = arguments.get("module")
        model = arguments.get("model")
        view_types = arguments.get("view_types") or ["form", "list", "search"]
        target_xml_path = arguments.get("target_xml_path")
        include_action = bool(arguments.get("include_action", False))
        include_menu = bool(arguments.get("include_menu", False))
        parent_menu_ref = arguments.get("parent_menu_ref")
        if not module:
            raise ValueError("module is required")
        if not model:
            raise ValueError("model is required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        module_path = modules[module]
        model_stem = _snake_from_model(model)
        rel_xml = target_xml_path.strip().lstrip("/") if target_xml_path else f"views/{model_stem}_views.xml"
        abs_xml = (module_path / rel_xml).resolve()
        views_payload = _default_views_xml_payload(module, model, [str(v) for v in view_types])
        parts = [_build_full_replace_patch(abs_xml, abs_xml.read_text(encoding="utf-8", errors="replace"), views_payload)] if abs_xml.exists() else [_build_add_file_patch(abs_xml, views_payload)]
        if include_action:
            action_rel = f"views/{model_stem}_actions.xml"
            action_abs = (module_path / action_rel).resolve()
            action_payload = _default_action_xml_payload(f"action_{model_stem}", _class_from_model(model), model)
            parts.append(_build_full_replace_patch(action_abs, action_abs.read_text(encoding="utf-8", errors="replace"), action_payload) if action_abs.exists() else _build_add_file_patch(action_abs, action_payload))
            if include_menu:
                menu_rel = f"views/{model_stem}_menu.xml"
                menu_abs = (module_path / menu_rel).resolve()
                menu_payload = (
                    "<?xml version='1.0' encoding='utf-8'?>\n<odoo>\n    <data>\n"
                    f"        <menuitem id=\"menu_{model_stem}\" name=\"{_class_from_model(model)}\" "
                    f"action=\"{module}.action_{model_stem}\""
                    + (f" parent=\"{parent_menu_ref}\"" if parent_menu_ref else "")
                    + "/>\n    </data>\n</odoo>\n"
                )
                parts.append(_build_full_replace_patch(menu_abs, menu_abs.read_text(encoding="utf-8", errors="replace"), menu_payload) if menu_abs.exists() else _build_add_file_patch(menu_abs, menu_payload))
        patch = _patch_document(parts)
        return [TextContent(type="text", text=compact_json({"module": module, "model": model, "target_xml_path": str(abs_xml), "patch": patch}))]

    if name == "scaffold_action_patch":
        module = arguments.get("module")
        model = arguments.get("model")
        if not module:
            raise ValueError("module is required")
        if not model:
            raise ValueError("model is required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        action_id = arguments.get("action_id") or f"action_{_snake_from_model(model)}"
        action_name = arguments.get("action_name") or _class_from_model(model)
        view_mode = arguments.get("view_mode", "list,form")
        context = arguments.get("context")
        domain = arguments.get("domain")
        rel = (arguments.get("target_xml_path") or f"views/{_snake_from_model(model)}_actions.xml").strip().lstrip("/")
        abs_path = (modules[module] / rel).resolve()
        payload = _default_action_xml_payload(action_id, action_name, model, view_mode, context, domain)
        part = _build_full_replace_patch(abs_path, abs_path.read_text(encoding="utf-8", errors="replace"), payload) if abs_path.exists() else _build_add_file_patch(abs_path, payload)
        return [TextContent(type="text", text=compact_json({"module": module, "action_id": action_id, "target_xml_path": str(abs_path), "patch": _patch_document([part])}))]

    if name == "scaffold_menu_patch":
        module = arguments.get("module")
        menu_id = arguments.get("menu_id")
        menu_name = arguments.get("menu_name")
        if not module:
            raise ValueError("module is required")
        if not menu_id or not menu_name:
            raise ValueError("menu_id and menu_name are required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        action_ref = arguments.get("action_ref")
        parent_menu_ref = arguments.get("parent_menu_ref")
        sequence = int(arguments.get("sequence", 10))
        rel = (arguments.get("target_xml_path") or f"views/{menu_id}_menu.xml").strip().lstrip("/")
        abs_path = (modules[module] / rel).resolve()
        line = f"        <menuitem id=\"{menu_id}\" name=\"{menu_name}\" sequence=\"{sequence}\""
        if action_ref:
            line += f" action=\"{action_ref}\""
        if parent_menu_ref:
            line += f" parent=\"{parent_menu_ref}\""
        line += "/>"
        payload = f"<?xml version='1.0' encoding='utf-8'?>\n<odoo>\n    <data>\n{line}\n    </data>\n</odoo>\n"
        part = _build_full_replace_patch(abs_path, abs_path.read_text(encoding="utf-8", errors="replace"), payload) if abs_path.exists() else _build_add_file_patch(abs_path, payload)
        return [TextContent(type="text", text=compact_json({"module": module, "menu_id": menu_id, "target_xml_path": str(abs_path), "patch": _patch_document([part])}))]

    if name == "scaffold_security_access_patch":
        module = arguments.get("module")
        model = arguments.get("model")
        if not module:
            raise ValueError("module is required")
        if not model:
            raise ValueError("model is required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        rel = (arguments.get("target_csv_path") or "security/ir.model.access.csv").strip().lstrip("/")
        abs_path = (modules[module] / rel).resolve()
        model_token = f"model_{_snake_from_model(model)}"
        header = "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        access_rows_csv = arguments.get("access_rows_csv")
        default_row = (
            f"access_{_snake_from_model(model)}_user,access_{_snake_from_model(model)}_user,"
            f"{model_token},base.group_user,1,1,1,1\n"
        )
        new_rows = str(access_rows_csv).strip() + ("\n" if str(access_rows_csv).strip() else "") if access_rows_csv else default_row
        if abs_path.exists():
            old = abs_path.read_text(encoding="utf-8", errors="replace")
            new = old
            if not new.startswith("id,name,model_id:id"):
                new = header + new.lstrip("\n")
            for row in [r for r in new_rows.splitlines() if r.strip()]:
                if row not in new:
                    if not new.endswith("\n"):
                        new += "\n"
                    new += row + "\n"
            part = _build_full_replace_patch(abs_path, old, new)
        else:
            part = _build_add_file_patch(abs_path, header + new_rows)
        return [TextContent(type="text", text=compact_json({"module": module, "model": model, "target_csv_path": str(abs_path), "patch": _patch_document([part])}))]

    if name == "scaffold_record_rule_patch":
        module = arguments.get("module")
        model = arguments.get("model")
        rule_id = arguments.get("rule_id")
        rule_name = arguments.get("rule_name")
        if not module:
            raise ValueError("module is required")
        if not model:
            raise ValueError("model is required")
        if not rule_id or not rule_name:
            raise ValueError("rule_id and rule_name are required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        domain_force = arguments.get("domain_force", "[]")
        groups_ref = arguments.get("groups_ref")
        rel = (arguments.get("target_xml_path") or f"security/{_snake_from_model(model)}_rules.xml").strip().lstrip("/")
        abs_path = (modules[module] / rel).resolve()
        group_line = f"\n            <field name=\"groups\" eval=\"[(4, ref('{groups_ref}'))]\"/>" if groups_ref else ""
        payload = (
            "<?xml version='1.0' encoding='utf-8'?>\n<odoo>\n    <data>\n"
            f"        <record id=\"{rule_id}\" model=\"ir.rule\">\n"
            f"            <field name=\"name\">{rule_name}</field>\n"
            f"            <field name=\"model_id\" ref=\"model_{_snake_from_model(model)}\"/>\n"
            f"            <field name=\"domain_force\">{domain_force}</field>{group_line}\n"
            "        </record>\n    </data>\n</odoo>\n"
        )
        part = _build_full_replace_patch(abs_path, abs_path.read_text(encoding="utf-8", errors="replace"), payload) if abs_path.exists() else _build_add_file_patch(abs_path, payload)
        return [TextContent(type="text", text=compact_json({"module": module, "rule_id": rule_id, "target_xml_path": str(abs_path), "patch": _patch_document([part])}))]

    if name == "scaffold_wizard_patch":
        module = arguments.get("module")
        model = arguments.get("model")
        if not module:
            raise ValueError("module is required")
        if not model:
            raise ValueError("model is required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        description = arguments.get("description") or _class_from_model(model)
        include_action = bool(arguments.get("include_action", True))
        include_menu = bool(arguments.get("include_menu", False))
        module_path = modules[module]
        stem = _snake_from_model(model)
        py_path = (module_path / f"wizard/{stem}.py").resolve()
        xml_path = (module_path / f"wizard/{stem}_views.xml").resolve()
        py_payload = _build_model_python(model, description, "TransientModel", None, "name = fields.Char(string=\"Name\")")
        xml_payload = (
            "<?xml version='1.0' encoding='utf-8'?>\n<odoo>\n    <data>\n"
            f"        <record id=\"{stem}_view_form\" model=\"ir.ui.view\">\n"
            f"            <field name=\"name\">{model}.wizard.form</field>\n"
            f"            <field name=\"model\">{model}</field>\n"
            "            <field name=\"arch\" type=\"xml\"><form><group><field name=\"name\"/></group></form></field>\n"
            "        </record>\n"
            "    </data>\n</odoo>\n"
        )
        parts = [
            _build_full_replace_patch(py_path, py_path.read_text(encoding="utf-8", errors="replace"), py_payload) if py_path.exists() else _build_add_file_patch(py_path, py_payload),
            _build_full_replace_patch(xml_path, xml_path.read_text(encoding="utf-8", errors="replace"), xml_payload) if xml_path.exists() else _build_add_file_patch(xml_path, xml_payload),
        ]
        if include_action:
            act_path = (module_path / f"wizard/{stem}_actions.xml").resolve()
            act_payload = _default_action_xml_payload(f"action_{stem}", description, model, "form")
            parts.append(_build_full_replace_patch(act_path, act_path.read_text(encoding="utf-8", errors="replace"), act_payload) if act_path.exists() else _build_add_file_patch(act_path, act_payload))
            if include_menu:
                menu_path = (module_path / f"wizard/{stem}_menu.xml").resolve()
                menu_payload = f"<?xml version='1.0' encoding='utf-8'?>\n<odoo>\n    <data>\n        <menuitem id=\"menu_{stem}\" name=\"{description}\" action=\"{module}.action_{stem}\"/>\n    </data>\n</odoo>\n"
                parts.append(_build_full_replace_patch(menu_path, menu_path.read_text(encoding="utf-8", errors="replace"), menu_payload) if menu_path.exists() else _build_add_file_patch(menu_path, menu_payload))
        return [TextContent(type="text", text=compact_json({"module": module, "model": model, "patch": _patch_document(parts)}))]

    if name == "scaffold_report_patch":
        module = arguments.get("module")
        model = arguments.get("model")
        report_id = arguments.get("report_id")
        report_name = arguments.get("report_name")
        if not module:
            raise ValueError("module is required")
        if not model:
            raise ValueError("model is required")
        if not report_id or not report_name:
            raise ValueError("report_id and report_name are required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        module_path = modules[module]
        stem = _snake_from_model(report_id)
        py_path = (module_path / f"report/{stem}.py").resolve()
        xml_path = (module_path / f"report/{stem}_template.xml").resolve()
        action_path = (module_path / f"report/{stem}_action.xml").resolve()
        py_payload = (
            "from odoo import models\n\n\n"
            f"class Report{_class_from_model(report_id)}(models.AbstractModel):\n"
            f"    _name = 'report.{module}.{report_id}'\n"
            "    _description = 'Report'\n\n"
            "    def _get_report_values(self, docids, data=None):\n"
            f"        docs = self.env['{model}'].browse(docids)\n"
            "        return {'doc_ids': docids, 'doc_model': docs._name, 'docs': docs}\n"
        )
        xml_payload = (
            "<?xml version='1.0' encoding='utf-8'?>\n<odoo>\n    <template id=\""
            + report_id
            + "\">\n        <t t-call=\"web.html_container\"><t t-foreach=\"docs\" t-as=\"o\"><div class=\"page\"><h2>"
            + report_name
            + "</h2></div></t></t>\n    </template>\n</odoo>\n"
        )
        action_payload = (
            "<?xml version='1.0' encoding='utf-8'?>\n<odoo>\n    <data>\n"
            f"        <report id=\"{report_id}_action\" model=\"{model}\" string=\"{report_name}\" "
            f"report_type=\"qweb-pdf\" name=\"{module}.{report_id}\" file=\"{module}.{report_id}\"/>\n"
            "    </data>\n</odoo>\n"
        )
        parts = [
            _build_full_replace_patch(py_path, py_path.read_text(encoding="utf-8", errors="replace"), py_payload) if py_path.exists() else _build_add_file_patch(py_path, py_payload),
            _build_full_replace_patch(xml_path, xml_path.read_text(encoding="utf-8", errors="replace"), xml_payload) if xml_path.exists() else _build_add_file_patch(xml_path, xml_payload),
            _build_full_replace_patch(action_path, action_path.read_text(encoding="utf-8", errors="replace"), action_payload) if action_path.exists() else _build_add_file_patch(action_path, action_payload),
        ]
        return [TextContent(type="text", text=compact_json({"module": module, "report_id": report_id, "patch": _patch_document(parts)}))]

    if name == "search_odoo_code":
        query = arguments.get("query")
        if not query:
            raise ValueError("query is required")
        glob = str(arguments.get("glob", "*.py"))
        limit = int(arguments.get("limit", 30))
        fixed_strings = bool(arguments.get("fixed_strings", True))
        module_filter = (arguments.get("module_filter") or "").strip()
        search_roots = roots
        if module_filter:
            if module_filter not in modules:
                raise ValueError(f"Unknown module for module_filter: {module_filter}")
            search_roots = [modules[module_filter]]
        matches = run_rg(query, search_roots, [glob], limit=limit, fixed_strings=fixed_strings)
        return [
            TextContent(
                type="text",
                text=compact_json({"query": query, "glob": glob, "module_filter": module_filter or None, "matches": matches}),
            )
        ]

    if name == "read_file_lines":
        rel_or_abs = Path(arguments.get("path", ""))
        if not rel_or_abs:
            raise ValueError("path is required")
        candidate = rel_or_abs if rel_or_abs.is_absolute() else (Path.cwd() / rel_or_abs)
        safe = assert_allowed_path(candidate, roots)
        start = int(arguments.get("start", 1))
        end = int(arguments.get("end", 120))
        max_lines = int(arguments.get("max_lines", 120))
        return [
            TextContent(
                type="text",
                text=compact_json(_read_file_lines(safe, start, end, max_lines)),
            )
        ]

    if name == "search_odoo_docs":
        query = arguments.get("query")
        if not query:
            raise ValueError("query is required")
        limit = int(arguments.get("limit", 20))
        if ODOO_DOCS_PATH is None:
            return [TextContent(type="text", text=compact_json({
                "error": "ODOO_MCP_DOCS_PATH environment variable is not set.",
                "hint": "Clone https://github.com/odoo/documentation and set ODOO_MCP_DOCS_PATH to its path.",
            }))]
        if not ODOO_DOCS_PATH.exists():
            return [TextContent(type="text", text=compact_json({
                "error": f"Docs path does not exist: {ODOO_DOCS_PATH}",
                "hint": "Check that ODOO_MCP_DOCS_PATH points to a valid directory.",
            }))]
        matches = run_rg(query, [ODOO_DOCS_PATH.resolve()], ["*.rst", "*.md"], limit=limit)
        return [TextContent(type="text", text=compact_json({"query": query, "matches": matches}))]

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
        field_re = re.compile(r"^\s+(\w+)\s*=\s*(fields\.\w+)\(")
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
                text=compact_json({
                    "model": model,
                    "field_count": len(results),
                    "source_files": sorted(model_files),
                    "fields": results,
                }),
            )
        ]

    if name == "validate_view_xml":
        module = arguments.get("module")
        xml_path_arg = arguments.get("xml_path")
        if not module:
            raise ValueError("module is required")
        if not xml_path_arg:
            raise ValueError("xml_path is required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")

        module_path = modules[module]
        rel = xml_path_arg.strip().lstrip("/")
        # Strip leading module prefix if present
        if rel.startswith(module + "/"):
            rel = rel[len(module) + 1:]
        abs_xml = assert_allowed_path(module_path / rel, roots)

        if not abs_xml.exists():
            return [TextContent(type="text", text=compact_json({"error": f"File not found: {abs_xml}"}))]

        errors: list[str] = []
        warnings: list[str] = []

        # 1. Parse XML
        try:
            tree = ET.parse(abs_xml)
        except ET.ParseError as exc:
            return [TextContent(type="text", text=compact_json({"valid": False, "errors": [f"XML parse error: {exc}"], "warnings": []}))]

        root_el = tree.getroot()

        # 2. Collect all view records and their models
        view_models: dict[str, str] = {}  # xml_id -> model
        for rec in root_el.iter("record"):
            if rec.get("model") != "ir.ui.view":
                continue
            rec_id = rec.get("id", "")
            model_field = next((f for f in rec.findall("field") if f.get("name") == "model"), None)
            if model_field is not None:
                view_models[rec_id] = (model_field.text or "").strip()

        # 3. For each model in the view file, collect known fields from Python
        model_known_fields: dict[str, set[str]] = {}
        for model_name in set(view_models.values()):
            if not model_name:
                continue
            if model_name in model_known_fields:
                continue
            name_pat = re.compile(r"_name\s*=\s*['\"]" + re.escape(model_name) + r"['\"]")
            inherit_pat = re.compile(
                r"_inherit\s*=\s*(?:\[[^\]]*['\"]" + re.escape(model_name) + r"['\"][^\]]*\]|['\"]" + re.escape(model_name) + r"['\"])"
            )
            field_re = re.compile(r"^\s+(\w+)\s*=\s*fields\.")
            known: set[str] = set()
            for root_path in roots:
                for py_file in root_path.rglob("*.py"):
                    try:
                        content = py_file.read_text(encoding="utf-8", errors="replace")
                        if not (name_pat.search(content) or inherit_pat.search(content)):
                            continue
                        for line in content.splitlines():
                            m = field_re.match(line)
                            if m and not m.group(1).startswith("_"):
                                known.add(m.group(1))
                    except OSError:
                        continue
            model_known_fields[model_name] = known

        # 4. Check field tags in view arch against known fields
        for rec in root_el.iter("record"):
            if rec.get("model") != "ir.ui.view":
                continue
            rec_id = rec.get("id", "unknown")
            model_name = view_models.get(rec_id, "")
            if not model_name:
                continue
            known = model_known_fields.get(model_name, set())
            if not known:
                warnings.append(f"[{rec_id}] Could not resolve fields for model '{model_name}' — skipping field validation")
                continue
            arch_field = next((f for f in rec.findall("field") if f.get("name") == "arch"), None)
            if arch_field is None:
                continue
            for field_tag in arch_field.iter("field"):
                fname = field_tag.get("name")
                if fname and fname not in known:
                    errors.append(f"[{rec_id}] Unknown field '{fname}' on model '{model_name}'")

        # 5. Check for deprecated attrs/states usage
        arch_text = abs_xml.read_text(encoding="utf-8", errors="replace")
        if ' attrs="' in arch_text or " attrs='" in arch_text:
            warnings.append("Deprecated 'attrs' attribute found — use inline Python expressions (Odoo 17+)")
        if ' states="' in arch_text or " states='" in arch_text:
            warnings.append("Deprecated 'states' attribute found — use 'invisible' inline expression (Odoo 17+)")

        return [
            TextContent(
                type="text",
                text=compact_json({
                    "valid": len(errors) == 0,
                    "file": str(abs_xml),
                    "error_count": len(errors),
                    "warning_count": len(warnings),
                    "errors": errors,
                    "warnings": warnings,
                }),
            )
        ]

    # TODO: lint_module — requires odoo-ls binary (https://github.com/odoo-ide/odoo-ls)
    # Planned for v1.1 release once persistent LSP daemon support is added.
    # if name == "lint_module":
    #     module = arguments.get("module")
    #     if not module:
    #         raise ValueError("module is required")
    #     if module not in modules:
    #         raise ValueError(f"Unknown module: {module}")
    #
    #     odoo_ls_bin = arguments.get("odoo_ls_bin") or ""
    #     community_path = arguments.get("community_path") or ""
    #     severity_filter = arguments.get("severity_filter", "error")
    #     timeout = int(arguments.get("timeout", 120))
    #     # typeshed stdlib lives at <repo>/server/typeshed/stdlib
    #     # binary is at <repo>/server/target/release/odoo_ls_server
    #     _bin_dir = Path(odoo_ls_bin).parent  # .../target/release
    #     stdlib_path = str(_bin_dir.parent.parent / "typeshed" / "stdlib")  # .../server/typeshed/stdlib
    #
    #     if not odoo_ls_bin:
    #         return [TextContent(type="text", text=compact_json({
    #             "error": "odoo_ls_bin is required. Provide the path to the odoo_ls_server binary.",
    #             "hint": "Build odoo-ls from https://github.com/odoo-ide/odoo-ls and pass the binary path.",
    #         }))]
    #     if not community_path:
    #         return [TextContent(type="text", text=compact_json({
    #             "error": "community_path is required. Provide the path to your Odoo community source root.",
    #         }))]
    #
    #     bin_path = Path(odoo_ls_bin)
    #     if not bin_path.exists():
    #         return [TextContent(type="text", text=compact_json({
    #             "error": f"odoo_ls_server binary not found at: {odoo_ls_bin}",
    #             "hint": "Build odoo-ls from https://github.com/odoo-ide/odoo-ls — run: cargo build --release",
    #         }))]
    #
    #     module_path = modules[module]
    #     module_str = str(module_path)
    #     addons_root = str(module_path.parent)
    #     import tempfile as _tempfile
    #     output_file = Path(_tempfile.gettempdir()) / f"odoo_ls_lint_{module}.json"
    #
    #     # Pass all configured roots as --addons so the linter can resolve all dependencies.
    #     # --community-path alone is not sufficient; explicit --addons for each path is required.
    #     seen_addons: set[str] = set()
    #     addons_args: list[str] = []
    #     for r in [Path(addons_root)] + list(roots):
    #         r_str = str(r.resolve())
    #         if r_str not in seen_addons:
    #             seen_addons.add(r_str)
    #             addons_args.extend(["--addons", r_str])
    #
    #     cmd = [str(bin_path), "--parse"]
    #     cmd.extend(addons_args)
    #     cmd.extend([
    #         "--community-path", community_path,
    #         "--tracked-folders", str(module_path),
    #         "--output", str(output_file),
    #         "--log-level", "error",
    #     ])
    #     if Path(stdlib_path).exists():
    #         cmd.extend(["--stdlib", stdlib_path])
    #
    #     try:
    #         proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    #     except subprocess.TimeoutExpired:
    #         return [TextContent(type="text", text=compact_json({
    #             "error": f"lint_module timed out after {timeout}s",
    #             "module": module,
    #         }))]
    #     except OSError as exc:
    #         return [TextContent(type="text", text=compact_json({"error": str(exc), "module": module}))]
    #
    #     import json as _json
    #     diagnostics: list[dict[str, Any]] = []
    #     if output_file.exists():
    #         try:
    #             raw = _json.loads(output_file.read_text(encoding="utf-8"))
    #             events = raw.get("events", raw) if isinstance(raw, dict) else raw
    #             sev_map = {1: "error", 2: "warning", 3: "info", 4: "hint"}
    #             for event in events:
    #                 if event.get("type") != "diagnostic":
    #                     continue
    #                 uri = event.get("uri", "")
    #                 file_path = uri[len("file://"):] if uri.startswith("file://") else uri
    #                 if not file_path.startswith(module_str):
    #                     continue
    #                 for diag in event.get("diagnostics", []):
    #                     sev_int = diag.get("severity", 1)
    #                     sev_str = sev_map.get(sev_int, "error")
    #                     if severity_filter == "error" and sev_str != "error":
    #                         continue
    #                     if severity_filter == "warning" and sev_str not in ("error", "warning"):
    #                         continue
    #                     rng = diag.get("range", {})
    #                     start = rng.get("start", {})
    #                     rel_path = file_path[len(module_str):].lstrip("/")
    #                     diagnostics.append({
    #                         "severity": sev_str,
    #                         "file": rel_path,
    #                         "line": start.get("line", 0) + 1,
    #                         "col": start.get("character", 0) + 1,
    #                         "code": diag.get("code", ""),
    #                         "message": diag.get("message", ""),
    #                     })
    #         except Exception as exc:
    #             return [TextContent(type="text", text=compact_json({
    #                 "error": f"Failed to parse odoo-ls output: {exc}",
    #                 "module": module,
    #                 "returncode": proc.returncode,
    #             }))]
    #         finally:
    #             try:
    #                 output_file.unlink()
    #             except OSError:
    #                 pass
    #
    #     return [TextContent(type="text", text=compact_json({
    #         "module": module,
    #         "severity_filter": severity_filter,
    #         "diagnostic_count": len(diagnostics),
    #         "diagnostics": diagnostics,
    #         "returncode": proc.returncode,
    #     }))]

    if name == "run_module_upgrade":
        module = arguments.get("module")
        if not module:
            raise ValueError("module is required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        mode = arguments.get("mode", "update")  # "install" or "update"
        odoo_bin = arguments.get("odoo_bin") or ""
        config_file = arguments.get("config_file") or ""

        if not odoo_bin:
            return [TextContent(type="text", text=compact_json({
                "error": "odoo_bin is required. Provide the path to your odoo-bin executable.",
            }))]
        db = arguments.get("database", "")

        odoo_bin_path = Path(odoo_bin)
        if not odoo_bin_path.exists():
            return [TextContent(type="text", text=compact_json({"error": f"odoo-bin not found at: {odoo_bin}"}))]

        flag = "-u" if mode == "update" else "-i"
        cmd = [str(odoo_bin_path), flag, module, "--stop-after-init"]
        if Path(config_file).exists():
            cmd.extend(["-c", config_file])
        if db:
            cmd.extend(["-d", db])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            stdout_tail = proc.stdout[-3000:] if proc.stdout else ""
            stderr_tail = proc.stderr[-3000:] if proc.stderr else ""
            success = proc.returncode == 0
            # Also check for common Odoo error patterns even on returncode 0
            error_patterns = ["ERROR", "Traceback", "raise ", "SyntaxError"]
            has_error = not success or any(p in stderr_tail for p in error_patterns)
            return [
                TextContent(
                    type="text",
                    text=compact_json({
                        "module": module,
                        "mode": mode,
                        "command": " ".join(cmd),
                        "returncode": proc.returncode,
                        "success": not has_error,
                        "stdout_tail": stdout_tail,
                        "stderr_tail": stderr_tail,
                    }),
                )
            ]
        except subprocess.TimeoutExpired:
            return [TextContent(type="text", text=compact_json({"error": "Upgrade timed out after 120s", "module": module}))]
        except OSError as exc:
            return [TextContent(type="text", text=compact_json({"error": str(exc), "module": module}))]

    raise ValueError(f"Unknown tool: {name}")
