from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import to_toon
from .helpers import (
    _append_manifest_data_entries,
    _append_manifest_data_entry,
    _build_add_file_patch,
    _build_full_replace_patch,
    _build_model_python,
    _class_from_model,
    _default_action_xml_payload,
    _default_views_xml_payload,
    _patch_document,
    _snake_from_model,
)


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
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
                text=to_toon(
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
                text=to_toon(
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
        return [TextContent(type="text", text=to_toon({"module": module, "init_path": str(init_path), "patch": patch}))]

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
        return [TextContent(type="text", text=to_toon({"module": module, "manifest_path": str(manifest_path), "patch": patch}))]

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
        return [TextContent(type="text", text=to_toon({"module": module, "inherit_model": inherit_model, "target_python_path": str(abs_py), "patch": patch}))]

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
        return [TextContent(type="text", text=to_toon({"module": module, "model": model, "target_xml_path": str(abs_xml), "patch": patch}))]

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
        return [TextContent(type="text", text=to_toon({"module": module, "action_id": action_id, "target_xml_path": str(abs_path), "patch": _patch_document([part])}))]

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
        return [TextContent(type="text", text=to_toon({"module": module, "menu_id": menu_id, "target_xml_path": str(abs_path), "patch": _patch_document([part])}))]

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
            lines = new.splitlines(keepends=True)
            if lines and lines[0].startswith("id,name,") and not lines[0].startswith("id,name,model_id:id"):
                # Replace old header format with canonical one
                lines[0] = header
                new = "".join(lines)
            elif not new.startswith("id,name,"):
                new = header + new.lstrip("\n")
            for row in [r for r in new_rows.splitlines() if r.strip()]:
                if row not in new:
                    if not new.endswith("\n"):
                        new += "\n"
                    new += row + "\n"
            part = _build_full_replace_patch(abs_path, old, new)
        else:
            part = _build_add_file_patch(abs_path, header + new_rows)
        return [TextContent(type="text", text=to_toon({"module": module, "model": model, "target_csv_path": str(abs_path), "patch": _patch_document([part])}))]

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
        return [TextContent(type="text", text=to_toon({"module": module, "rule_id": rule_id, "target_xml_path": str(abs_path), "patch": _patch_document([part])}))]

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
        return [TextContent(type="text", text=to_toon({"module": module, "model": model, "patch": _patch_document(parts)}))]

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
        return [TextContent(type="text", text=to_toon({"module": module, "report_id": report_id, "patch": _patch_document(parts)}))]

    return None
