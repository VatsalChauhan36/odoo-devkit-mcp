# odoo-devkit

A token-efficient [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for Odoo 17/18/19 development. Gives AI assistants (Claude, Cursor, etc.) fast, structured access to your Odoo codebase — module discovery, model analysis, view navigation, XML validation, and code scaffolding — without loading entire files into context.

## Features

- **Module & model discovery** — find models, fields, views, actions, menus, security rules
- **View navigation** — trace inheritance chains, find all views for a model
- **Code scaffolding** — generate ready-to-apply unified diff patches for models, views, wizards, reports, menus, security
- **XML validation** — validate view XML syntax and field names against model definitions
- **Read-only by default** — safe to use in automated workflows; no writes to your codebase

---

## Requirements

Before installing, make sure you have:

| Requirement | Version | Install |
|---|---|---|
| Python | 3.10+ | [python.org](https://www.python.org/downloads/) |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| ripgrep | any | `sudo apt install ripgrep` / `brew install ripgrep` |
| Git | any | [git-scm.com](https://git-scm.com/) |

> **Windows users:** ripgrep can be installed via `winget install BurntSushi.ripgrep.MSVC`

---

## Installation

### Step 1 — Clone the repository

```bash
git clone https://github.com/VatsalChauhan36/odoo-devkit.git
cd odoo-devkit
```

### Step 2 — Install dependencies

```bash
uv sync
```

This creates a virtual environment and installs all dependencies automatically.

### Step 3 — Verify it works

```bash
uv run odoo-devkit --help
```

You should see the CLI help output. If you get a `No valid roots found` error, that's expected — you need to configure your addons paths in the next step.

---

## Configuration

The server needs to know where your Odoo addons directories are.

### What paths to provide

A typical Odoo 18 setup has three roots:

| Path | What it contains |
|---|---|
| `/path/to/your/custom-addons` | Your own modules (put this **first**) |
| `/path/to/odoo/server/addons` | Odoo community modules |
| `/path/to/odoo/server/odoo/addons` | Odoo base modules |

> **Order matters** — the first root is treated as your custom addons directory (used by `list_custom_modules`).

### Option A — Environment variable (recommended)

**Linux / macOS:**
```bash
export ODOO_MCP_ROOTS="/path/to/your/addons:/path/to/odoo/server/addons:/path/to/odoo/server/odoo/addons"
```

**Windows (PowerShell):**
```powershell
$env:ODOO_MCP_ROOTS = "C:\your\addons;C:\odoo\server\addons;C:\odoo\server\odoo\addons"
```

> Use `:` as separator on Linux/macOS, `;` on Windows.

### Option B — CLI flags

```bash
uv run odoo-devkit \
  --roots /path/to/your/addons \
  --roots /path/to/odoo/server/addons \
  --roots /path/to/odoo/server/odoo/addons
```

### Optional — Odoo docs search

Set `ODOO_MCP_DOCS_PATH` to enable the `search_odoo_docs` tool. This should point to a locally cloned copy of the [Odoo documentation](https://github.com/odoo/documentation) repository.

```bash
# Clone the docs (one time)
git clone https://github.com/odoo/documentation.git /path/to/odoo/documentation

# Set the env var
export ODOO_MCP_DOCS_PATH="/path/to/odoo/documentation"
```

**Windows (PowerShell):**
```powershell
$env:ODOO_MCP_DOCS_PATH = "C:\odoo\documentation"
```

---

## MCP Client Setup

### Claude Code

Add to your `.claude/settings.json`:

```json
{
  "mcpServers": {
    "odoo-devkit": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/odoo-devkit",
        "odoo-devkit",
        "--roots", "/path/to/your/addons",
        "--roots", "/path/to/odoo/server/addons",
        "--roots", "/path/to/odoo/server/odoo/addons"
      ]
    }
  }
}
```

Or using the environment variable:

```json
{
  "mcpServers": {
    "odoo-devkit": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/odoo-devkit", "odoo-devkit"],
      "env": {
        "ODOO_MCP_ROOTS": "/path/to/your/addons:/path/to/odoo/server/addons:/path/to/odoo/server/odoo/addons",
        "ODOO_MCP_DOCS_PATH": "/path/to/odoo/documentation"
      }
    }
  }
}
```

### Cursor

Add to your Cursor MCP config (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "odoo-devkit": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/odoo-devkit",
        "odoo-devkit",
        "--roots", "/path/to/your/addons",
        "--roots", "/path/to/odoo/server/addons",
        "--roots", "/path/to/odoo/server/odoo/addons"
      ]
    }
  }
}
```

### Other MCP clients

Use `command: "uv"` with the args pattern above. Refer to your client's MCP documentation for the exact config file location.

---

## Verifying the Setup

Once your MCP client is running, you can ask your AI assistant:

- *"List all custom Odoo modules"* → calls `list_custom_modules`
- *"Find the definition of sale.order model"* → calls `find_model_definition`
- *"Show me all views for product.template"* → calls `find_view_by_model`

---

## Tools Reference

### Discovery

| Tool | Description |
|------|-------------|
| `list_modules` | List all modules across all configured roots |
| `list_custom_modules` | List modules from your custom addons root only |
| `get_module_manifest` | Parse `__manifest__.py` fields for a module |
| `read_file_lines` | Read a bounded line range from any allowed file |
| `search_odoo_code` | Token-bounded ripgrep search across all roots |
| `search_odoo_docs` | Search local Odoo documentation (requires `ODOO_MCP_DOCS_PATH`) |

### Model & Field Analysis

| Tool | Description |
|------|-------------|
| `find_model_definition` | Find files defining a model by `_name` or `_inherit` |
| `get_model_fields` | List all field declarations for a model |
| `find_xml_id_definition` | Find XML records by external ID |
| `find_security_access_for_model` | Find `ir.model.access` and `ir.rule` records for a model |

### View Navigation

| Tool | Description |
|------|-------------|
| `find_view_definition` | Find a view by XML ID, name, or model |
| `find_inherited_views` | Find all views that inherit from a given view |
| `find_view_by_model` | Find all views registered for a model |
| `find_view_chain` | Resolve the full inheritance chain for a view |
| `find_field_in_views` | Find which views reference a specific field |
| `validate_view_xml` | Validate view XML syntax and field names |

### Action & Menu Discovery

| Tool | Description |
|------|-------------|
| `find_action_by_model` | Find `ir.actions.act_window` records for a model |
| `find_menu_hierarchy` | Find menu items and their parent/child chains |

### Code Scaffolding (generate unified diff patches)

| Tool | Description |
|------|-------------|
| `scaffold_model_patch` | New model with optional views and security access |
| `scaffold_inherit_model_patch` | Extend an existing model with fields/methods |
| `scaffold_view_inherit_patch` | Inherit and modify an existing view with XPath |
| `scaffold_views_patch` | Full set of views (form/list/search/kanban) for a model |
| `scaffold_action_patch` | `ir.actions.act_window` XML |
| `scaffold_menu_patch` | Menu item XML linked to an action |
| `scaffold_security_access_patch` | `ir.model.access.csv` entries |
| `scaffold_record_rule_patch` | `ir.rule` XML for record-level security |
| `scaffold_wizard_patch` | `TransientModel` + wizard view |
| `scaffold_report_patch` | Report Python model + QWeb template + action |

### Module Maintenance

| Tool | Description |
|------|-------------|
| `manifest_update_patch` | Add data file entries to `__manifest__.py` |
| `init_update_patch` | Add import statements to `__init__.py` |
| `run_module_upgrade` | Run `odoo-bin -u <module> --stop-after-init` (requires `odoo_bin` path) |

---

## Troubleshooting

**`No valid roots found` error**
→ You haven't configured any roots. Set `ODOO_MCP_ROOTS` or use `--roots` flags.

**`rg: command not found`**
→ Install ripgrep: `sudo apt install ripgrep` (Ubuntu) / `brew install ripgrep` (macOS)

**MCP server not connecting in Claude Code**
→ Check the `--directory` path in your config points to where you cloned the repo.
→ Run `uv sync` again inside the repo directory.

**`uv: command not found`**
→ Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh` then restart your terminal.

→ On Ubuntu/Linux, uv installs to `~/.local/bin` which may not be in your `PATH`. Fix it by creating a symlink:
```bash
sudo ln -s ~/.local/bin/uv /usr/local/bin/uv
```
Then verify with `uv --version`. If you prefer not to use sudo, add `~/.local/bin` to your PATH instead:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

---

## License

MIT — see [LICENSE](LICENSE)
