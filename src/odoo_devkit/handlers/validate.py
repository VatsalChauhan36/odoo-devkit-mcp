import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import assert_allowed_path, to_toon
from .helpers import (
    _build_view_lookup,
    _collect_known_fields_for_model,
    _collect_view_records,
    _resolve_view_model,
)


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
        if rel.startswith(module + "/"):
            rel = rel[len(module) + 1 :]
        abs_xml = assert_allowed_path(module_path / rel, roots)

        if not abs_xml.exists():
            return [TextContent(type="text", text=to_toon({"error": f"File not found: {abs_xml}"}))]

        errors: list[str] = []
        warnings: list[str] = []

        try:
            tree = ET.parse(abs_xml)
        except ET.ParseError as exc:
            return [
                TextContent(
                    type="text",
                    text=to_toon(
                        {
                            "valid": False,
                            "errors": [f"XML parse error: {exc}"],
                            "warnings": [],
                        }
                    ),
                )
            ]

        root_el = tree.getroot()

        all_view_records = _collect_view_records(roots)
        view_lookup = _build_view_lookup(all_view_records)
        model_cache: dict[str, str | None] = {}
        view_models: dict[str, str] = {}
        for record in all_view_records:
            if record.get("path") != str(abs_xml):
                continue
            raw_xml_id = record.get("xml_id_raw")
            if not raw_xml_id:
                continue
            resolved_model = _resolve_view_model(record, view_lookup, model_cache)
            if resolved_model:
                view_models[raw_xml_id] = resolved_model

        model_known_fields: dict[str, set[str]] = {}

        for rec in root_el.iter("record"):
            if rec.get("model") != "ir.ui.view":
                continue
            rec_id = rec.get("id", "unknown")
            model_name = view_models.get(rec_id, "")
            if not model_name:
                warnings.append(
                    f"[{rec_id}] Could not resolve model from this view record or its inherit_id chain"
                )
                continue

            known = model_known_fields.get(model_name)
            if known is None:
                known = _collect_known_fields_for_model(model_name, roots)
                model_known_fields[model_name] = known

            if not known:
                warnings.append(
                    f"[{rec_id}] Could not resolve fields for model '{model_name}' - skipping field validation"
                )
                continue

            arch_field = next((field for field in rec.findall("field") if field.get("name") == "arch"), None)
            if arch_field is None:
                continue
            for field_tag in arch_field.iter("field"):
                field_name = field_tag.get("name")
                if field_name and field_name not in known:
                    errors.append(f"[{rec_id}] Unknown field '{field_name}' on model '{model_name}'")

        arch_text = abs_xml.read_text(encoding="utf-8", errors="replace")
        if ' attrs="' in arch_text or " attrs='" in arch_text:
            warnings.append("Deprecated 'attrs' attribute found - use inline Python expressions (Odoo 17+)")
        if ' states="' in arch_text or " states='" in arch_text:
            warnings.append("Deprecated 'states' attribute found - use 'invisible' inline expression (Odoo 17+)")

        return [
            TextContent(
                type="text",
                text=to_toon(
                    {
                        "valid": len(errors) == 0,
                        "file": str(abs_xml),
                        "error_count": len(errors),
                        "warning_count": len(warnings),
                        "errors": errors,
                        "warnings": warnings,
                    }
                ),
            )
        ]

    return None
