import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import assert_allowed_path, compact_json


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
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

    return None
