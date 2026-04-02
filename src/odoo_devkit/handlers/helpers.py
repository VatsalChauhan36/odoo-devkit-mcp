import csv
import ast
import re
import xml.etree.ElementTree as ET
from pprint import pformat
from pathlib import Path
from typing import Any

from ..utils import run_rg


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


def _sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(record: dict[str, Any]) -> tuple[Any, ...]:
        scope = record.get("scope")
        scope_rank = 0 if scope == "custom" else 1 if scope == "standard" else 2
        kind = record.get("kind")
        kind_rank = 0 if kind == "direct" else 1 if kind == "inherit" else 2
        return (
            scope_rank,
            kind_rank,
            str(record.get("module") or ""),
            str(record.get("xml_id") or record.get("xml_id_raw") or record.get("name") or record.get("path") or ""),
            int(record.get("line") or 0),
        )

    return sorted(records, key=key)


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


def _find_model_python_files(model: str, roots: list[Path]) -> list[Path]:
    name_pattern = r"_name\s*=\s*['\"]" + re.escape(model) + r"['\"]"
    inherit_pattern = (
        r"_inherit\s*=\s*(?:\[[^\]]*['\"]"
        + re.escape(model)
        + r"['\"][^\]]*\]|['\"]"
        + re.escape(model)
        + r"['\"])"
    )
    name_matches = run_rg(name_pattern, roots, ["*.py"], limit=500, fixed_strings=False)
    inherit_matches = run_rg(inherit_pattern, roots, ["*.py"], limit=500, fixed_strings=False)
    files = {Path(row["path"]).resolve() for row in name_matches + inherit_matches}
    return sorted(files)


def _collect_known_fields_for_model(model: str, roots: list[Path]) -> set[str]:
    field_re = re.compile(r"^\s*(\w+)\s*=\s*fields\.")
    known: set[str] = set()
    for py_file in _find_model_python_files(model, roots):
        try:
            for line in py_file.read_text(encoding="utf-8", errors="replace").splitlines():
                match = field_re.match(line)
                if match and not match.group(1).startswith("_"):
                    known.add(match.group(1))
        except OSError:
            continue
    return known


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


def _build_view_lookup(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for record in records:
        xml_id = record.get("xml_id")
        raw_xml_id = record.get("xml_id_raw")
        if xml_id and xml_id not in lookup:
            lookup[xml_id] = record
        if raw_xml_id and raw_xml_id not in lookup:
            lookup[raw_xml_id] = record
    return lookup


def _resolve_view_model(
    record: dict[str, Any],
    view_lookup: dict[str, dict[str, Any]],
    cache: dict[str, str | None],
    stack: set[str] | None = None,
) -> str | None:
    cache_key = str(record.get("xml_id") or record.get("xml_id_raw") or record.get("path") or id(record))
    if cache_key in cache:
        return cache[cache_key]

    if stack is None:
        stack = set()
    if cache_key in stack:
        return None
    stack.add(cache_key)

    model = (record.get("model") or "").strip()
    if model:
        cache[cache_key] = model
        stack.remove(cache_key)
        return model

    inherit_id = (record.get("inherit_id") or "").strip()
    if not inherit_id:
        cache[cache_key] = None
        stack.remove(cache_key)
        return None

    parent = view_lookup.get(inherit_id)
    if parent is None and "." in inherit_id:
        parent = view_lookup.get(inherit_id.split(".", 1)[1])

    resolved = (
        _resolve_view_model(parent, view_lookup, cache, stack)
        if parent is not None
        else None
    )
    cache[cache_key] = resolved
    stack.remove(cache_key)
    return resolved


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
