from mcp.types import Tool, ToolAnnotations

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    idempotentHint=True,
    destructiveHint=False,
    openWorldHint=False,
)

# Keep tool schemas centralized so API changes are easy to track.
TOOL_DEFINITIONS = [
    Tool(
        name="list_modules",
        description="List modules from all configured roots with optional name filter.",
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
        description=(
            "List modules only from your custom addons root "
            "(first configured root) with optional name filter."
        ),
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
        description="Get selected keys from module __manifest__.py.",
        inputSchema={
            "type": "object",
            "properties": {"module": {"type": "string"}},
            "required": ["module"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_model_definition",
        description=(
            "Find Odoo model definitions and extensions across custom and standard addons. "
            "Includes _name matches, _inherit matches, and related module files."
        ),
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
        name="find_xml_id_definition",
        description="Find XML external id definitions (id=\"...\") across xml files.",
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
        name="find_view_definition",
        description=(
            "Find ir.ui.view records across custom and standard addons. "
            "Matches by xml id (module.view_id or view_id), view name, or model name."
        ),
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
        description=(
            "Find ir.ui.view records that inherit a target view "
            "(via field name='inherit_id')."
        ),
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
        description=(
            "Find ir.ui.view records for a specific model "
            "(e.g. 'res.partner') across custom and standard addons."
        ),
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
        name="find_action_by_model",
        description=(
            "Find ir.actions.act_window records for a model "
            "(from XML data files, custom + standard addons)."
        ),
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
        description=(
            "Find menus linked to an action/view/model and return parent chain + children."
        ),
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
    Tool(
        name="find_field_in_views",
        description=(
            "Find where a field is used in view XML (field tags and xpath expressions)."
        ),
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
        description=(
            "Find model security from ir.model.access.csv and ir.rule XML records."
        ),
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
    Tool(
        name="find_view_chain",
        description=(
            "Resolve a view chain from base view to inherited layers in order."
        ),
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
        name="scaffold_view_inherit_patch",
        description=(
            "Generate a unified diff patch to add an inherited ir.ui.view XML record "
            "for a module (no files are modified by this tool)."
        ),
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
                "xml_snippet": {
                    "type": "string",
                    "description": "XML snippet inserted inside the xpath node.",
                },
                "target_xml_path": {
                    "type": "string",
                    "description": "Optional target file path relative to module root.",
                },
            },
            "required": [
                "module",
                "model",
                "inherit_view_ref",
                "new_view_id",
                "xml_snippet",
            ],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="scaffold_model_patch",
        description=(
            "Generate a unified diff patch to scaffold an Odoo model file "
            "and optional updates to models/__init__.py and __manifest__.py "
            "(no files are modified by this tool)."
        ),
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
                "field_snippets": {
                    "type": "string",
                    "description": "Optional multiline field declarations.",
                },
                "target_python_path": {
                    "type": "string",
                    "description": "Optional target path relative to module root.",
                },
                "include_init_update": {"type": "boolean", "default": True},
                "include_manifest_update": {"type": "boolean", "default": False},
                "manifest_data_file": {
                    "type": "string",
                    "description": "Optional data file to append in manifest data list.",
                },
                "include_basic_views": {"type": "boolean", "default": False},
                "include_access_csv": {"type": "boolean", "default": False},
            },
            "required": ["module", "model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="scaffold_inherit_model_patch",
        description=(
            "Generate a patch for an inherited model class with optional field/method snippets."
        ),
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
        name="scaffold_views_patch",
        description=(
            "Generate patch for model views (form/list/search/kanban/graph/pivot) and optional action/menu."
        ),
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
        description="Generate ir.actions.act_window XML patch for a model.",
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
        description="Generate menu XML patch with optional parent/action binding.",
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
        description="Generate/append ir.model.access.csv entries for a model.",
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "model": {"type": "string"},
                "access_rows_csv": {
                    "type": "string",
                    "description": "Optional CSV rows without header; default full-access user row.",
                },
                "target_csv_path": {"type": "string", "default": "security/ir.model.access.csv"},
            },
            "required": ["module", "model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="scaffold_record_rule_patch",
        description="Generate ir.rule XML patch for a model.",
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
        name="manifest_update_patch",
        description="Generate patch to idempotently append data files into __manifest__.py data list.",
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
        description="Generate patch to idempotently append python imports into __init__.py.",
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
        name="scaffold_wizard_patch",
        description="Generate TransientModel + wizard view patch and optional action/menu.",
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
        description="Generate report python + qweb + report action patches.",
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
    Tool(
        name="search_odoo_code",
        description="Token-bounded code search using ripgrep. Use module_filter to restrict search to a single module.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "glob": {"type": "string", "default": "*.py"},
                "limit": {"type": "integer", "default": 30},
                "fixed_strings": {"type": "boolean", "default": True},
                "module_filter": {
                    "type": "string",
                    "description": "Optional module name to restrict the search scope (e.g. 'point_of_sale').",
                },
            },
            "required": ["query"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="read_file_lines",
        description="Read only a bounded line range from an allowed file.",
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
    Tool(
        name="search_odoo_docs",
        description="Search local Odoo documentation. Requires ODOO_MCP_DOCS_PATH environment variable to be set.",
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
        name="get_model_fields",
        description=(
            "List all fields declared on an Odoo model by scanning Python source files. "
            "Returns field name, type, file location, and module scope for each field."
        ),
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
        name="validate_view_xml",
        description=(
            "Validate a view XML file: checks XML syntax, verifies field names exist on the model, "
            "and warns about deprecated Odoo 16 syntax (attrs/states)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "xml_path": {
                    "type": "string",
                    "description": "Path to the XML file, relative to module root (e.g. 'views/my_view.xml').",
                },
            },
            "required": ["module", "xml_path"],
        },
        annotations=READ_ONLY,
    ),
    # TODO: lint_module — requires odoo-ls binary (https://github.com/odoo-ide/odoo-ls)
    # Planned for v1.1 release once persistent LSP daemon support is added.
    # Tool(
    #     name="lint_module",
    #     description=(
    #         "Run odoo-ls static analysis (--parse mode) on a module and return semantic diagnostics. "
    #         "Catches field name errors, missing XML IDs, broken view references, domain expression issues, "
    #         "and Python type errors. Requires odoo_ls_server binary to be built. "
    #         "Slower than validate_view_xml (~30-60s) but semantically deeper."
    #     ),
    #     inputSchema={
    #         "type": "object",
    #         "properties": {
    #             "module": {"type": "string"},
    #             "odoo_ls_bin": {
    #                 "type": "string",
    #                 "description": "Path to the odoo_ls_server binary (from https://github.com/odoo-ide/odoo-ls).",
    #             },
    #             "community_path": {
    #                 "type": "string",
    #                 "description": "Path to Odoo community source root (e.g. /opt/odoo/server).",
    #             },
    #             "severity_filter": {
    #                 "type": "string",
    #                 "enum": ["error", "warning", "all"],
    #                 "default": "error",
    #                 "description": "Filter diagnostics by severity.",
    #             },
    #             "stdlib_path": {
    #                 "type": "string",
    #                 "description": "Path to typeshed stdlib stubs. Auto-detected from binary location if omitted.",
    #             },
    #             "timeout": {
    #                 "type": "integer",
    #                 "default": 120,
    #                 "description": "Timeout in seconds for the lint run.",
    #             },
    #         },
    #         "required": ["module"],
    #     },
    #     annotations=READ_ONLY,
    # ),
    Tool(
        name="run_module_upgrade",
        description=(
            "Run odoo-bin to install or update a module with --stop-after-init. "
            "Returns stdout/stderr tail and success status. "
            "Requires odoo-bin accessible on the server."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["install", "update"],
                    "default": "update",
                    "description": "Use 'install' for new modules, 'update' for existing ones.",
                },
                "database": {
                    "type": "string",
                    "description": "Odoo database name. If omitted, relies on config file default.",
                },
                "odoo_bin": {
                    "type": "string",
                    "description": "Path to the odoo-bin executable (e.g. /opt/odoo/server/odoo-bin).",
                },
                "config_file": {
                    "type": "string",
                    "description": "Path to Odoo config file (e.g. /etc/odoo/odoo.conf).",
                },
            },
            "required": ["module"],
        },
    ),
]
