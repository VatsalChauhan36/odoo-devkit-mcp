import subprocess
from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import to_toon


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
    if name == "run_module_upgrade":
        module = arguments.get("module")
        if not module:
            raise ValueError("module is required")
        if module not in modules:
            raise ValueError(f"Unknown module: {module}")
        mode = arguments.get("mode", "update")  # "install" or "update"
        odoo_bin = arguments.get("odoo_bin") or ""
        config_file = arguments.get("config_file") or ""

        if not odoo_bin:
            return [TextContent(type="text", text=to_toon({
                "error": "odoo_bin is required. Provide the path to your odoo-bin executable.",
            }))]
        db = arguments.get("database", "")

        odoo_bin_path = Path(odoo_bin)
        if not odoo_bin_path.exists():
            return [TextContent(type="text", text=to_toon({"error": f"odoo-bin not found at: {odoo_bin}"}))]

        flag = "-u" if mode == "update" else "-i"
        cmd = [str(odoo_bin_path), flag, module, "--stop-after-init"]
        if Path(config_file).exists():
            cmd.extend(["-c", config_file])
        if db:
            cmd.extend(["-d", db])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            stdout_tail = proc.stdout[-3000:] if proc.stdout else ""
            stderr_tail = proc.stderr[-3000:] if proc.stderr else ""
            success = proc.returncode == 0
            # Also check for common Odoo error patterns even on returncode 0
            error_patterns = ["ERROR", "Traceback", "raise ", "SyntaxError"]
            has_error = not success or any(p in stderr_tail for p in error_patterns)
            return [
                TextContent(
                    type="text",
                    text=to_toon({
                        "module": module,
                        "mode": mode,
                        "command": " ".join(cmd),
                        "returncode": proc.returncode,
                        "success": not has_error,
                        "stdout_tail": stdout_tail,
                        "stderr_tail": stderr_tail,
                    }),
                )
            ]
        except subprocess.TimeoutExpired:
            return [TextContent(type="text", text=to_toon({"error": "Upgrade timed out after 120s", "module": module}))]
        except OSError as exc:
            return [TextContent(type="text", text=to_toon({"error": str(exc), "module": module}))]

    return None
