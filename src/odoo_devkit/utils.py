import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import toons

from .constants import DEFAULT_ROOTS


# Short-key map: verbose response key → compact key sent to LLM.
# Keeps field names readable in code but token-efficient on the wire.
_KEY_MAP: dict[str, str] = {
    # ===== Core =====
    "matches": "m",
    "count": "n",
    "total_matches": "tm",

    # ===== File / Location =====
    "path": "p",
    "line": "l",
    "module": "mo",

    # ===== Content =====
    "text": "t",
    "scope": "sc",

    # ===== Fields / Structure =====
    "fields": "f",
    "field_count": "fc",

    # ===== Files =====
    "source_files": "sf",
    "related_files": "rf",
    "total_files": "tf",

    # ===== Errors / Warnings =====
    "errors": "e",
    "warnings": "w",
    "error_count": "ec",
    "warning_count": "wc",

    # ===== Rules / Access =====
    "rules": "rl",
    "access": "ax",
    "rule_count": "rc",
    "access_count": "ac",

    # ===== Execution =====
    "patch": "px",
    "returncode": "rcd",
    "stdout_tail": "out",
    "stderr_tail": "err",
    "truncated": "tr",

    # ===== Directory / Tree =====
    "directories": "ds",
    "chain": "ch",
    "depth": "dp",
    "ancestors": "an",
    "children": "kd",

    # ===== XML / View =====
    "xml_id": "xid",
    "inherit_id": "inh",
    "view_ref": "vr",

    # ===== Naming =====
    "field_name": "fn",
    "method_name": "mn",

    # ===== Status =====
    "success": "ok",
    "valid": "v",

    # ===== Target Paths =====
    "target_xml_path": "txp",
    "target_python_path": "tpp",
    "target_csv_path": "tcp",

    # ===== Rare (keep semi-readable) =====
    "manifest_path": "manifest",
    "init_path": "init",
}

def _compress_keys(data: Any) -> Any:
    if isinstance(data, dict):
        return {_KEY_MAP.get(k, k): _compress_keys(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_compress_keys(item) for item in data]
    return data


def to_toon(data: Any) -> str:
    return toons.dumps(_compress_keys(data))


def load_roots(cli_roots: list[str] | None) -> list[Path]:
    env_roots = os.getenv("ODOO_MCP_ROOTS")
    raw = cli_roots or (
        env_roots.split(os.pathsep) if env_roots else list(DEFAULT_ROOTS)
    )
    roots: list[Path] = []
    for item in raw:
        path = Path(item).expanduser().resolve()
        if path.exists() and path.is_dir():
            roots.append(path)

    unique: list[Path] = []
    seen = set()
    for root in roots:
        value = str(root)
        if value not in seen:
            seen.add(value)
            unique.append(root)

    if not unique:
        raise ValueError("No valid roots found. Use --roots or ODOO_MCP_ROOTS.")
    return unique


def assert_allowed_path(path: Path, roots: list[Path]) -> Path:
    resolved = path.expanduser().resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except ValueError:
            continue
    raise ValueError(f"Path not allowed: {resolved}")


def run_rg(
    pattern: str,
    roots: list[Path],
    globs: list[str],
    limit: int,
    fixed_strings: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    # Fast path: use ripgrep when available.
    if shutil.which("rg"):
        cmd = ["rg", "-n", "--no-heading", "--color", "never"]
        if fixed_strings:
            cmd.append("-F")
        # Only apply glob filters when searching directories; skip for explicit files
        # (rg ignores -g when given a file path directly)
        all_files = all(path.is_file() for path in roots)
        if not all_files:
            for glob in globs:
                cmd.extend(["-g", glob])
        cmd.append(pattern)
        cmd.extend([str(path) for path in roots])

        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode not in (0, 1):
            raise ValueError(proc.stderr.strip() or "ripgrep failed")

        for line in proc.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            rows.append(
                {"path": parts[0], "line": int(parts[1]), "text": parts[2].strip()}
            )
            if len(rows) >= limit:
                break
        return rows

    # Fallback path: pure Python scan when rg is not installed.
    regex = None if fixed_strings else re.compile(pattern)
    for root in roots:
        # Support individual files passed directly (not just directories)
        if root.is_file():
            candidates = [root]
        else:
            candidates = (p for p in root.rglob("*") if p.is_file())
        for file_path in candidates:
            if root.is_dir():
                rel = str(file_path.relative_to(root)).replace("\\", "/")
                if globs and not any(fnmatch.fnmatch(rel, glob) for glob in globs):
                    continue
            try:
                with file_path.open("r", encoding="utf-8", errors="replace") as handle:
                    for idx, line in enumerate(handle, start=1):
                        text = line.rstrip("\n")
                        matched = (
                            pattern in text
                            if fixed_strings
                            else bool(regex.search(text))
                        )
                        if not matched:
                            continue
                        rows.append(
                            {
                                "path": str(file_path),
                                "line": idx,
                                "text": text.strip(),
                            }
                        )
                        if len(rows) >= limit:
                            return rows
            except OSError:
                continue
    return rows
