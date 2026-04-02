from pathlib import Path

# Default roots are intentionally empty — users must supply paths via:
#   --roots CLI argument (repeatable),
#   ODOO_MCP_ROOTS environment variable (colon-separated on Linux/macOS,
#   semicolon-separated on Windows), or
#   the config GUI: odoo-devkit --config
#
# Typical setup:
#   export ODOO_MCP_ROOTS="/path/to/your/addons:/odoo/server/addons:/odoo/server/odoo/addons"
DEFAULT_ROOTS: tuple[()] = ()

# Local Odoo documentation root used by the search_odoo_docs tool.
# Priority: ODOO_MCP_DOCS_PATH env var > saved config (odoo-devkit --config) > None
# If not set, search_odoo_docs will return a clear error message.
import os as _os

def _resolve_docs_path() -> "Path | None":
    env = _os.getenv("ODOO_MCP_DOCS_PATH", "").strip()
    if env:
        return Path(env)
    # Try saved config as fallback (avoids circular import by importing lazily)
    try:
        from odoo_devkit.config import OdooDevkitConfig
        saved = OdooDevkitConfig.load()
        if saved.docs_path:
            return Path(saved.docs_path)
    except Exception:
        pass
    return None

ODOO_DOCS_PATH: "Path | None" = _resolve_docs_path()
