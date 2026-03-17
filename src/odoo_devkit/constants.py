from pathlib import Path

# Default roots are intentionally empty — users must supply paths via:
#   --roots CLI argument (repeatable), or
#   ODOO_MCP_ROOTS environment variable (colon-separated on Linux/macOS,
#   semicolon-separated on Windows)
#
# Typical setup:
#   export ODOO_MCP_ROOTS="/path/to/your/addons:/odoo/server/addons:/odoo/server/odoo/addons"
DEFAULT_ROOTS: tuple[()] = ()

# Local Odoo documentation root used by the search_odoo_docs tool.
# Set ODOO_MCP_DOCS_PATH environment variable to enable this tool.
# If not set, search_odoo_docs will return a clear error message.
import os as _os
_docs_env = _os.getenv("ODOO_MCP_DOCS_PATH", "").strip()
ODOO_DOCS_PATH: Path | None = Path(_docs_env) if _docs_env else None
