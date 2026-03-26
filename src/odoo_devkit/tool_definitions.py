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
        description=(
            "List all Odoo modules (addons) discovered across all configured roots. "
            "Use this as a starting point to explore what modules exist, "
            "or to find a module by partial name (e.g. query='sale' finds sale, sale_subscription, etc.). "
            "Returns module name, path, and scope (custom vs standard)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional substring to filter module names (e.g. 'sale', 'stock', 'hr').",
                },
                "limit": {"type": "integer", "default": 50},
            },
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="list_custom_modules",
        description=(
            "List only YOUR custom modules (from the first configured addons root). "
            "Use this when the user asks about 'my modules', 'our modules', or 'custom modules'. "
            "Excludes Odoo standard/community modules."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional substring to filter module names.",
                },
                "limit": {"type": "integer", "default": 50},
            },
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="get_module_manifest",
        description=(
            "Read an Odoo module's __manifest__.py and return its key metadata: "
            "name, version, summary, depends, data files, assets, license, and application flag. "
            "Use this to understand a module's dependencies, what data/view files it loads, "
            "or whether it's an application."
        ),
        inputSchema={
            "type": "object",
            "properties": {"module": {"type": "string"}},
            "required": ["module"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="get_module_structure",
        description=(
            "Get a complete file tree for an Odoo module — lists all Python, XML, CSV, "
            "and other files organized by directory (models/, views/, security/, data/, "
            "wizard/, report/, static/, etc.). "
            "This should be the FIRST tool to call when exploring an unfamiliar module. "
            "Prefer this over glob_odoo_files when you already know the module name "
            "and want to understand its full layout before reading or editing files."
        ),
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
        description=(
            "Read lines from any file inside the configured Odoo addons roots. "
            "Use this to read Python source code, XML views, CSV security files, or any other file. "
            "Specify start/end line numbers to read a specific section of a large file."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file.",
                },
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
        description=(
            "Search for any text or regex pattern across the entire Odoo codebase using ripgrep. "
            "This is the PRIMARY general-purpose search tool — use it whenever you need to find "
            "method calls, field references, imports, string literals, error messages, "
            "class definitions, or any code pattern. "
            "Supports glob filters (e.g. '*.xml' for XML only, '*.py' for Python only). "
            "Use module_filter to restrict to a single module. "
            "NOTE: For finding method DEFINITIONS specifically, prefer find_method_definition. "
            "For finding FILES by name/path pattern, prefer glob_odoo_files."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text or regex pattern to search for.",
                },
                "glob": {
                    "type": "string",
                    "default": "*.py",
                    "description": "File type filter: '*.py' (default), '*.xml', '*.csv', '*.js', or '*' for all files.",
                },
                "limit": {"type": "integer", "default": 30},
                "fixed_strings": {
                    "type": "boolean",
                    "default": True,
                    "description": "If true, treat query as literal text. Set to false to use regex.",
                },
                "module_filter": {
                    "type": "string",
                    "description": "Optional module name to restrict the search scope (e.g. 'sale', 'point_of_sale').",
                },
            },
            "required": ["query"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="search_odoo_docs",
        description=(
            "Search the local Odoo documentation (RST/Markdown files) for a topic. "
            "Use this when the user asks about Odoo APIs, ORM methods, view architecture, "
            "QWeb syntax, or other framework concepts. "
            "Requires the ODOO_MCP_DOCS_PATH environment variable to point to a cloned "
            "https://github.com/odoo/documentation repository."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Topic or keyword to search in the docs (e.g. 'compute field', 'onchange', 'QWeb').",
                },
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="glob_odoo_files",
        description=(
            "Find files by glob pattern across all Odoo addons roots. "
            "Use this to locate files by extension or directory convention, e.g.: "
            "'**/models/*.py' (all model files), '**/views/*.xml' (all view files), "
            "'**/__manifest__.py' (all manifests), '**/static/src/**/*.js' (all JS files). "
            "For searching file CONTENTS, use search_odoo_code instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern, e.g. '**/*.py', '**/models/*.py', '**/views/*.xml'.",
                },
                "limit": {"type": "integer", "default": 200},
                "module_filter": {
                    "type": "string",
                    "description": "Optional module name to restrict search scope.",
                },
            },
            "required": ["pattern"],
        },
        annotations=READ_ONLY,
    ),

    # ── Model & Field Analysis ──────────────────────────────────────────
    Tool(
        name="find_model_definition",
        description=(
            "Find where an Odoo model is defined (_name = '...') and extended (_inherit = '...'). "
            "This should be the FIRST tool to call when the user asks about a specific model "
            "like 'sale.order', 'res.partner', etc. "
            "Returns the file paths, line numbers, and which module defines or inherits the model, "
            "plus a list of related files (views, security, data) in those modules. "
            "For listing a model's fields, use get_model_fields instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Odoo model technical name, e.g. 'sale.order', 'res.partner', 'account.move'.",
                },
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
        description=(
            "List all fields declared on an Odoo model across all modules that define or inherit it. "
            "Returns each field's name, type (Char, Many2one, etc.), the file and line where it's declared, "
            "and which module it belongs to. "
            "Use this to understand a model's data structure, check if a field exists, "
            "or find where a specific field is defined."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Odoo model technical name, e.g. 'sale.order', 'res.partner'.",
                },
                "limit": {"type": "integer", "default": 200},
            },
            "required": ["model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_method_definition",
        description=(
            "Find where a Python method is defined across Odoo modules. "
            "Use this when looking for a specific method like '_compute_amount_total', "
            "'action_confirm', 'write', 'create', or to find all overrides of a method. "
            "Searches for 'def method_name' patterns in Python files. "
            "Optionally filter by model name to narrow results to files that define/inherit that model. "
            "Prefer this over search_odoo_code when specifically looking for method definitions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "method_name": {
                    "type": "string",
                    "description": "Method name to find, e.g. '_compute_amount_total', 'action_confirm', 'write'.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional Odoo model name to narrow search to files defining/inheriting this model.",
                },
                "limit": {"type": "integer", "default": 30},
            },
            "required": ["method_name"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_xml_id_definition",
        description=(
            "Find where an XML external ID (e.g. 'sale.view_order_form', 'base.group_user') "
            "is defined in XML data files. "
            "Use this to locate a specific record definition by its XML ID — views, actions, menus, "
            "security groups, record rules, or any data record."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "xml_id": {
                    "type": "string",
                    "description": "The external ID to search for, e.g. 'sale.view_order_form', 'base.group_user'.",
                },
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["xml_id"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_field_in_views",
        description=(
            "Find all XML views that reference a specific field — in <field> tags, "
            "xpath expressions, domains, or attrs. "
            "Use this before renaming or removing a field to check its view-level usage, "
            "or to understand where a field appears in the UI."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "field_name": {
                    "type": "string",
                    "description": "The field name, e.g. 'partner_id', 'amount_total', 'state'.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model name to narrow results to views of that model.",
                },
                "limit": {"type": "integer", "default": 100},
            },
            "required": ["field_name"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_security_access_for_model",
        description=(
            "Find all security rules for a model: both ir.model.access.csv entries (CRUD permissions) "
            "and ir.rule records (domain-based record rules). "
            "Use this to audit who can read/write/create/delete records of a model, "
            "or to check what record rules apply."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Odoo model technical name, e.g. 'sale.order'.",
                },
                "limit": {"type": "integer", "default": 120},
            },
            "required": ["model"],
        },
        annotations=READ_ONLY,
    ),

    # ── View Navigation ─────────────────────────────────────────────────
    Tool(
        name="find_view_definition",
        description=(
            "Find an Odoo view (ir.ui.view) by its XML ID, view name, or model name. "
            "Use this to locate a specific view when you know its identifier, "
            "e.g. 'sale.view_order_form' or 'sale.order'. "
            "Returns the view's XML ID, model, inherit_id, file path, and module. "
            "For listing ALL views of a model, prefer find_view_by_model. "
            "For tracing inheritance, prefer find_view_chain."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "view_ref": {
                    "type": "string",
                    "description": "XML ID (e.g. 'sale.view_order_form'), view name, or model name.",
                },
                "limit": {"type": "integer", "default": 40},
            },
            "required": ["view_ref"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_inherited_views",
        description=(
            "Find all views that inherit from (extend) a given view. "
            "Use this to see which modules modify a base view — e.g. what modules add fields "
            "to the sale order form, or who overrides a list view."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "view_ref": {
                    "type": "string",
                    "description": "The base view XML ID to find inheritors for, e.g. 'sale.view_order_form'.",
                },
                "limit": {"type": "integer", "default": 60},
            },
            "required": ["view_ref"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_view_by_model",
        description=(
            "Find ALL views registered for a specific model — form, list, search, kanban, etc. "
            "Use this to get an overview of all UI representations for a model "
            "(e.g. all views for 'product.template')."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Odoo model technical name, e.g. 'sale.order', 'product.template'.",
                },
                "limit": {"type": "integer", "default": 80},
            },
            "required": ["model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_view_chain",
        description=(
            "Resolve the full inheritance chain for a view — from the base view through all "
            "inherited layers in priority order. "
            "Use this to understand the final composed view or to debug view inheritance issues."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "view_ref": {
                    "type": "string",
                    "description": "The view XML ID to resolve the chain for.",
                },
                "limit": {"type": "integer", "default": 120},
            },
            "required": ["view_ref"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="validate_view_xml",
        description=(
            "Validate an XML view file for correctness: checks XML syntax, verifies that "
            "field names used in the view actually exist on the model, and warns about "
            "deprecated Odoo 16+ patterns (attrs, states attributes). "
            "Use this after editing a view XML file to catch errors before upgrading the module."
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

    # ── Action & Menu Discovery ─────────────────────────────────────────
    Tool(
        name="find_action_by_model",
        description=(
            "Find window actions (ir.actions.act_window) for a model. "
            "Use this to find how a model is opened in the UI — what action launches "
            "the list/form view, what view_mode is used, and which module defines the action."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Odoo model technical name, e.g. 'sale.order'.",
                },
                "limit": {"type": "integer", "default": 80},
            },
            "required": ["model"],
        },
        annotations=READ_ONLY,
    ),
    Tool(
        name="find_menu_hierarchy",
        description=(
            "Find menu items linked to an action, view, or model and trace the full "
            "parent menu chain and children. "
            "Use this to understand navigation: where in the Odoo menu tree a model/action appears."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Menu XML ID, action XML ID, or model name to search for.",
                },
                "limit": {"type": "integer", "default": 120},
            },
            "required": ["ref"],
        },
        annotations=READ_ONLY,
    ),

    # ── Code Scaffolding (generates patches, does NOT modify files) ─────
    Tool(
        name="scaffold_model_patch",
        description=(
            "Generate a ready-to-apply patch for a NEW Odoo model. "
            "Creates the Python file with model class, and optionally updates "
            "models/__init__.py and __manifest__.py. "
            "Can also include basic views and an ir.model.access.csv entry. "
            "Output is a unified diff patch — no files are modified."
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
            "Generate a patch to EXTEND an existing Odoo model (via _inherit). "
            "Use this when adding fields or methods to a model defined in another module. "
            "Output is a unified diff patch — no files are modified."
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
        name="scaffold_view_inherit_patch",
        description=(
            "Generate a patch to INHERIT and modify an existing view using XPath. "
            "Use this when you need to add fields to or modify another module's form/list/search view. "
            "Output is a unified diff patch — no files are modified."
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
        name="scaffold_views_patch",
        description=(
            "Generate a complete set of views (form, list, search, kanban, graph, pivot) "
            "for a model with optional action and menu item. "
            "Use this when creating a new model that needs a full UI. "
            "Output is a unified diff patch — no files are modified."
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
        description=(
            "Generate an ir.actions.act_window XML record for a model. "
            "Output is a unified diff patch — no files are modified."
        ),
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
        description=(
            "Generate a menu item XML record with optional parent and action binding. "
            "Output is a unified diff patch — no files are modified."
        ),
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
        description=(
            "Generate ir.model.access.csv entries (CRUD permissions) for a model. "
            "Output is a unified diff patch — no files are modified."
        ),
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
        description=(
            "Generate an ir.rule XML record for domain-based record-level security. "
            "Output is a unified diff patch — no files are modified."
        ),
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
        description=(
            "Generate a TransientModel (wizard) with form view and optional action/menu. "
            "Use this for creating popup wizards. "
            "Output is a unified diff patch — no files are modified."
        ),
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
        description=(
            "Generate a report: Python model, QWeb template, and report action. "
            "Output is a unified diff patch — no files are modified."
        ),
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
        description=(
            "Generate a patch to add data file entries (e.g. 'views/sale_view.xml') "
            "to a module's __manifest__.py 'data' list. Idempotent — skips files already listed. "
            "Output is a unified diff patch — no files are modified."
        ),
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
        description=(
            "Generate a patch to add Python import statements to a module's __init__.py. "
            "Idempotent — skips imports already present. "
            "Output is a unified diff patch — no files are modified."
        ),
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
        description=(
            "Run odoo-bin to install or upgrade an Odoo module (with --stop-after-init). "
            "Use this after making changes to test that the module installs/upgrades cleanly. "
            "Returns the tail of stdout/stderr and a success/failure status. "
            "Requires odoo-bin to be accessible on the server."
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
    # TODO: lint_module — requires odoo-ls binary (https://github.com/odoo-ide/odoo-ls)
    # Planned for v1.1 release once persistent LSP daemon support is added.
]
