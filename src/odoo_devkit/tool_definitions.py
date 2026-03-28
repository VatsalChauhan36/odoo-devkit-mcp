from mcp.types import Tool, ToolAnnotations

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    idempotentHint=True,
    destructiveHint=False,
    openWorldHint=False,
)

# Keep tool schemas centralized so API changes are easy to track.
TOOL_DEFINITIONS = [
    # ── Discovery & Navigation ──────────────────────────────────────────
    Tool(
        name="list_modules",
        description="List all Odoo modules; filter by partial name.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="list_custom_modules",
        description="List only custom modules from primary addons root.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="get_module_manifest",
        description="Read module __manifest__.py metadata.",
        inputSchema={
            "type": "object",
            "properties": {"module": {"type": "string"}},
            "required": ["module"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="get_module_structure",
        description="Get full file tree for a module by directory.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "limit": {"type": "integer", "default": 300},
            },
            "required": ["module"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="read_file_lines",
        description="Read lines from a file inside addons roots.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start": {"type": "integer", "default": 1},
                "end": {"type": "integer", "default": 120},
                "max_lines": {"type": "integer", "default": 120},
            },
            "required": ["path"],
        },
        annotations=READ_ONLY,
    ),

    # ── Search ──────────────────────────────────────────────────────────
    Tool(
        name="search_odoo_code",
        description="Regex/text search across Odoo codebase via ripgrep.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "glob": {"type": "string", "default": "*.py"},
                "limit": {"type": "integer", "default": 30},
                "fixed_strings": {"type": "boolean", "default": True},
                "module_filter": {"type": "string"},
            },
            "required": ["query"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="search_odoo_docs",
        description="Search local Odoo RST/Markdown documentation files.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="glob_odoo_files",
        description="Find files by glob pattern across addons roots.",
        inputSchema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "limit": {"type": "integer", "default": 200},
                "module_filter": {"type": "string"},
            },
            "required": ["pattern"],
        },
        annotations=READ_ONLY,
    ),

    # ── Model & Field Analysis ──────────────────────────────────────────
    Tool(
        name="find_model_definition",
        description="Find where a model is defined or inherited (_name/_inherit).",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "include_related_files": {"type": "boolean", "default": True},
                "related_files_limit": {"type": "integer", "default": 60},
            },
            "required": ["model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="get_model_fields",
        description="List all fields declared on a model across modules.",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "limit": {"type": "integer", "default": 200},
            },
            "required": ["model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_method_definition",
        description="Find Python method definitions (def name) in Odoo files.",
        inputSchema={
            "type": "object",
            "properties": {
                "method_name": {"type": "string"},
                "model": {"type": "string"},
                "limit": {"type": "integer", "default": 30},
            },
            "required": ["method_name"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_xml_id_definition",
        description="Find where an XML external ID is defined in data files.",
        inputSchema={
            "type": "object",
            "properties": {
                "xml_id": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["xml_id"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_field_in_views",
        description="Find XML views referencing a field (tags, xpath, domains).",
        inputSchema={
            "type": "object",
            "properties": {
                "field_name": {"type": "string"},
                "model": {"type": "string"},
                "limit": {"type": "integer", "default": 100},
            },
            "required": ["field_name"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_security_access_for_model",
        description="Find access rights and record rules for a model.",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "limit": {"type": "integer", "default": 120},
            },
            "required": ["model"],
        },
        annotations=READ_ONLY,
    ),

    # ── View Navigation ─────────────────────────────────────────────────
    Tool(
        name="find_view_definition",
        description="Find a view by XML ID, name, or model.",
        inputSchema={
            "type": "object",
            "properties": {
                "view_ref": {"type": "string"},
                "limit": {"type": "integer", "default": 40},
            },
            "required": ["view_ref"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_inherited_views",
        description="Find views that inherit/extend a given base view.",
        inputSchema={
            "type": "object",
            "properties": {
                "view_ref": {"type": "string"},
                "limit": {"type": "integer", "default": 60},
            },
            "required": ["view_ref"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_view_by_model",
        description="List all views (form/list/search/kanban) for a model.",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "limit": {"type": "integer", "default": 80},
            },
            "required": ["model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_view_chain",
        description="Resolve full view inheritance chain in priority order.",
        inputSchema={
            "type": "object",
            "properties": {
                "view_ref": {"type": "string"},
                "limit": {"type": "integer", "default": 120},
            },
            "required": ["view_ref"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="validate_view_xml",
        description="Validate XML view syntax and field references.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "xml_path": {"type": "string"},
            },
            "required": ["module", "xml_path"],
        },
        annotations=READ_ONLY,
    ),

    # ── Action & Menu Discovery ─────────────────────────────────────────
    Tool(
        name="find_action_by_model",
        description="Find ir.actions.act_window records for a model.",
        inputSchema={
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "limit": {"type": "integer", "default": 80},
            },
            "required": ["model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_menu_hierarchy",
        description="Find menu items and trace parent/child hierarchy.",
        inputSchema={
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "limit": {"type": "integer", "default": 120},
            },
            "required": ["ref"],
        },
        annotations=READ_ONLY,
    ),

    # ── Code Scaffolding (generates patches, does NOT modify files) ─────
    Tool(
        name="scaffold_model_patch",
        description="Generate patch for a new Odoo model Python file.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "model": {"type": "string"},
                "description": {"type": "string"},
                "base_class": {
                    "type": "string",
                    "enum": ["Model", "TransientModel", "AbstractModel"],
                    "default": "Model",
                },
                "inherit_model": {"type": "string"},
                "field_snippets": {"type": "string"},
                "target_python_path": {"type": "string"},
                "include_init_update": {"type": "boolean", "default": True},
                "include_manifest_update": {"type": "boolean", "default": False},
                "manifest_data_file": {"type": "string"},
                "include_basic_views": {"type": "boolean", "default": False},
                "include_access_csv": {"type": "boolean", "default": False},
            },
            "required": ["module", "model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="scaffold_inherit_model_patch",
        description="Generate patch to extend an existing model via _inherit.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "inherit_model": {"type": "string"},
                "target_python_path": {"type": "string"},
                "field_snippets": {"type": "string"},
                "method_snippets": {"type": "string"},
                "include_init_update": {"type": "boolean", "default": True},
            },
            "required": ["module", "inherit_model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="scaffold_view_inherit_patch",
        description="Generate XPath patch to inherit and modify an existing view.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "model": {"type": "string"},
                "inherit_view_ref": {"type": "string"},
                "new_view_id": {"type": "string"},
                "xpath_expr": {"type": "string", "default": "//sheet"},
                "xpath_position": {
                    "type": "string",
                    "enum": ["inside", "before", "after", "replace", "attributes"],
                    "default": "inside",
                },
                "xml_snippet": {"type": "string"},
                "target_xml_path": {"type": "string"},
            },
            "required": ["module", "model", "inherit_view_ref", "new_view_id", "xml_snippet"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="scaffold_views_patch",
        description="Generate complete view set (form/list/search/kanban) for a model.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "model": {"type": "string"},
                "view_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["form", "list", "search", "kanban", "graph", "pivot"],
                    },
                    "default": ["form", "list", "search"],
                },
                "target_xml_path": {"type": "string"},
                "include_action": {"type": "boolean", "default": False},
                "include_menu": {"type": "boolean", "default": False},
                "parent_menu_ref": {"type": "string"},
            },
            "required": ["module", "model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="scaffold_action_patch",
        description="Generate ir.actions.act_window XML record patch.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "model": {"type": "string"},
                "action_id": {"type": "string"},
                "action_name": {"type": "string"},
                "view_mode": {"type": "string", "default": "tree,form"},
                "context": {"type": "string"},
                "domain": {"type": "string"},
                "target_xml_path": {"type": "string"},
            },
            "required": ["module", "model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="scaffold_menu_patch",
        description="Generate menu item XML record patch.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "menu_id": {"type": "string"},
                "menu_name": {"type": "string"},
                "action_ref": {"type": "string"},
                "parent_menu_ref": {"type": "string"},
                "sequence": {"type": "integer", "default": 10},
                "target_xml_path": {"type": "string"},
            },
            "required": ["module", "menu_id", "menu_name"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="scaffold_security_access_patch",
        description="Generate ir.model.access.csv CRUD permission entries.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "model": {"type": "string"},
                "access_rows_csv": {"type": "string"},
                "target_csv_path": {"type": "string", "default": "security/ir.model.access.csv"},
            },
            "required": ["module", "model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="scaffold_record_rule_patch",
        description="Generate ir.rule XML record for domain-based security.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "model": {"type": "string"},
                "rule_id": {"type": "string"},
                "rule_name": {"type": "string"},
                "domain_force": {"type": "string", "default": "[]"},
                "groups_ref": {"type": "string"},
                "target_xml_path": {"type": "string"},
            },
            "required": ["module", "model", "rule_id", "rule_name"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="scaffold_wizard_patch",
        description="Generate TransientModel wizard with form view patch.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "model": {"type": "string"},
                "description": {"type": "string"},
                "include_action": {"type": "boolean", "default": True},
                "include_menu": {"type": "boolean", "default": False},
            },
            "required": ["module", "model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="scaffold_report_patch",
        description="Generate report model, QWeb template, and action patch.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "model": {"type": "string"},
                "report_id": {"type": "string"},
                "report_name": {"type": "string"},
            },
            "required": ["module", "model", "report_id", "report_name"],
        },
        annotations=READ_ONLY,
    ),

    # ── Module Maintenance ──────────────────────────────────────────────
    Tool(
        name="manifest_update_patch",
        description="Patch __manifest__.py to add data file entries.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "data_files": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["module", "data_files"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="init_update_patch",
        description="Patch __init__.py to add Python import statements.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "init_path": {"type": "string"},
                "imports": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["module", "imports"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="run_module_upgrade",
        description="Run odoo-bin to install or upgrade a module.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["install", "update"],
                    "default": "update",
                },
                "database": {"type": "string"},
                "odoo_bin": {"type": "string"},
                "config_file": {"type": "string"},
            },
            "required": ["module"],
        },
    ),
    # TODO: lint_module — requires odoo-ls binary (https://github.com/odoo-ide/odoo-ls)
    # Planned for v1.1 release once persistent LSP daemon support is added.
]