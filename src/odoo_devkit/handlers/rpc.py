"""
XML-RPC handler for odoo-devkit.

Provides `execute_rpc` — a general-purpose tool that lets the MCP client
(Claude or any agent) call any Odoo model method over XML-RPC.

Connection parameters are resolved in priority order:
  1. Per-call arguments (url, database, username, password)
  2. Saved dashboard config  (url, database, username, password)
  3. Sensible defaults       (url = http://localhost:8069)
"""

from __future__ import annotations

import json
import xmlrpc.client
from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..config import OdooDevkitConfig
from ..utils import to_toon


def _connect(url: str, db: str, username: str, password: str):
    """Authenticate and return (models_proxy, uid)."""
    common = xmlrpc.client.ServerProxy(f"{url.rstrip('/')}/xmlrpc/2/common")
    uid = common.authenticate(db, username, password, {})
    if not uid:
        raise PermissionError(
            f"Authentication failed for user '{username}' on database '{db}' at {url}"
        )
    models = xmlrpc.client.ServerProxy(f"{url.rstrip('/')}/xmlrpc/2/object")
    return models, uid


def _resolve_params(arguments: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return (url, db, username, password) merging call args with saved config."""
    cfg = OdooDevkitConfig.load()
    url      = arguments.get("url")      or cfg.url      or "http://localhost:8069"
    db       = arguments.get("database") or cfg.database or ""
    username = arguments.get("username") or cfg.username or "admin"
    password = arguments.get("password") or cfg.password or "admin"
    return url, db, username, password


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:

    # ── execute_rpc ───────────────────────────────────────────────────────────
    if name == "execute_rpc":
        model_name  = arguments.get("model", "")
        method      = arguments.get("method", "")
        args_param   = arguments.get("args") or []
        kwargs_param = arguments.get("kwargs") or {}
        limit        = arguments.get("limit")
        max_chars    = int(arguments.get("max_chars") or 50_000)
        # Post-processing filters (applied after RPC call, before truncation)
        search_query = (arguments.get("search") or "").strip()   # free-text search across all string fields
        filter_key   = (arguments.get("filter_key") or "").strip()   # field name to match against
        filter_value = (arguments.get("filter_value") or "").strip()  # value to match (substring, case-insensitive)
        pluck        = arguments.get("pluck") or []              # field names to keep per record

        if not model_name:
            return [TextContent(type="text", text=to_toon({"error": "model is required"}))]
        if not method:
            return [TextContent(type="text", text=to_toon({"error": "method is required"}))]

        # Deserialise args/kwargs if passed as JSON strings
        if isinstance(args_param, str):
            try:
                args_param = json.loads(args_param)
            except json.JSONDecodeError:
                return [TextContent(type="text", text=to_toon({"error": "args must be a JSON array"}))]
        if isinstance(kwargs_param, str):
            try:
                kwargs_param = json.loads(kwargs_param)
            except json.JSONDecodeError:
                return [TextContent(type="text", text=to_toon({"error": "kwargs must be a JSON object"}))]

        # Inject limit into kwargs for search/search_read if not already set
        if limit is not None and method in ("search_read", "search", "read") and "limit" not in kwargs_param:
            kwargs_param = dict(kwargs_param)
            kwargs_param["limit"] = int(limit)

        url = arguments.get("url") or "http://localhost:8069"
        try:
            url, db, username, password = _resolve_params(arguments)
            if not db:
                return [TextContent(type="text", text=to_toon({
                    "error": "database is required. Set it in the dashboard config or pass it as an argument."
                }))]

            models, uid = _connect(url, db, username, password)
            result = models.execute_kw(db, uid, password, model_name, method, args_param, kwargs_param)

            # If the method returned a JSON string, decode it so it's not double-encoded
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except (json.JSONDecodeError, ValueError):
                    pass  # leave as-is if it's not valid JSON

            # Unwrap common wrapper dicts:
            # {"products": [...], "total_count": N, ...} → the list value
            # {"data": [...]} → the list
            # {"result": [...]} → the list
            if isinstance(result, dict):
                # Find the first list value — that's the payload
                list_values = [(k, v) for k, v in result.items() if isinstance(v, list)]
                if len(list_values) == 1:
                    result = list_values[0][1]
                elif list_values:
                    # Multiple lists — pick the one with the most items (likely the data)
                    result = max(list_values, key=lambda kv: len(kv[1]))[1]

            # ── Post-processing filters ───────────────────────────────────
            if isinstance(result, list) and result:

                # 1. filter_key + filter_value — keep records where field matches
                if filter_key and filter_value:
                    fv_lower = filter_value.lower()
                    def _matches_filter(rec: Any) -> bool:
                        if not isinstance(rec, dict):
                            return True
                        val = rec.get(filter_key)
                        if val is None:
                            return False
                        return fv_lower in str(val).lower()
                    result = [r for r in result if _matches_filter(r)]

                # 2. search — free-text search across all string values in each record
                if search_query:
                    sq_lower = search_query.lower()
                    def _matches_search(rec: Any) -> bool:
                        if not isinstance(rec, dict):
                            return sq_lower in str(rec).lower()
                        return any(sq_lower in str(v).lower() for v in rec.values())
                    result = [r for r in result if _matches_search(r)]

                # 3. pluck — keep only specified fields per record
                if pluck:
                    pluck_fields = [p.strip() for p in (pluck if isinstance(pluck, list) else pluck.split(",")) if p.strip()]
                    if pluck_fields:
                        result = [
                            {k: v for k, v in r.items() if k in pluck_fields}
                            if isinstance(r, dict) else r
                            for r in result
                        ]

            # Truncate large results to avoid flooding the context window
            truncated = False
            original_count = len(result) if isinstance(result, list) else None

            if isinstance(result, list):
                # Binary-search for the largest slice that fits in max_chars
                lo, hi = 0, len(result)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if len(json.dumps(result[:mid], default=str)) <= max_chars:
                        lo = mid
                    else:
                        hi = mid - 1
                if lo < len(result):
                    result = result[:lo]
                    truncated = True
                result_payload = result
            else:
                result_str = json.dumps(result, default=str)
                if len(result_str) > max_chars:
                    result_payload = result_str[:max_chars] + "... [truncated]"
                    truncated = True
                else:
                    result_payload = result

            response: dict[str, Any] = {
                "model":    model_name,
                "method":   method,
                "url":      url,
                "database": db,
                "result":   result_payload,
                "truncated": truncated,
            }
            if original_count is not None:
                filtered_count = len(result) if isinstance(result, list) else original_count
                if search_query or filter_key or pluck:
                    response["filtered_count"] = filtered_count
                if truncated:
                    response["total_count"] = original_count
                    response["returned_count"] = len(result_payload) if isinstance(result_payload, list) else None

            return [TextContent(type="text", text=to_toon(response))]

        except PermissionError as exc:
            return [TextContent(type="text", text=to_toon({"error": str(exc)}))]
        except xmlrpc.client.Fault as exc:
            return [TextContent(type="text", text=to_toon({
                "error":      "Odoo RPC fault",
                "fault_code": exc.faultCode,
                "detail":     exc.faultString,
            }))]
        except ConnectionRefusedError:
            return [TextContent(type="text", text=to_toon({
                "error": f"Odoo is not running at {url}",
                "hint":  "Start your Odoo instance and try again.",
            }))]
        except OSError as exc:
            msg = str(exc)
            if "Name or service not known" in msg or "nodename nor servname" in msg:
                return [TextContent(type="text", text=to_toon({
                    "error": f"Cannot resolve host — is Odoo running at {url}?",
                }))]
            return [TextContent(type="text", text=to_toon({
                "error": f"Connection failed: {msg}",
                "hint":  "Check the URL and port.",
            }))]
        except Exception as exc:
            return [TextContent(type="text", text=to_toon({"error": str(exc)}))]

    # ── check_rpc_connection ──────────────────────────────────────────────────
    if name == "check_rpc_connection":
        url = arguments.get("url") or "http://localhost:8069"
        try:
            url, db, username, password = _resolve_params(arguments)
            if not db:
                return [TextContent(type="text", text=to_toon({
                    "error": "database is required. Set it in the dashboard config or pass it as an argument."
                }))]

            common = xmlrpc.client.ServerProxy(f"{url.rstrip('/')}/xmlrpc/2/common")
            version = common.version()
            uid = common.authenticate(db, username, password, {})
            authed = bool(uid)

            return [TextContent(type="text", text=to_toon({
                "url":            url,
                "database":       db,
                "username":       username,
                "authenticated":  authed,
                "uid":            uid if authed else None,
                "server_version": version.get("server_version") if isinstance(version, dict) else str(version),
            }))]

        except ConnectionRefusedError:
            return [TextContent(type="text", text=to_toon({
                "error": f"Odoo is not running at {url}",
                "hint":  "Start your Odoo instance and try again.",
            }))]
        except OSError as exc:
            msg = str(exc)
            if "Name or service not known" in msg or "nodename nor servname" in msg:
                return [TextContent(type="text", text=to_toon({
                    "error": f"Cannot resolve host — is Odoo running at {url}?",
                }))]
            return [TextContent(type="text", text=to_toon({
                "error": f"Connection failed: {msg}",
                "hint":  "Check the URL and port.",
            }))]
        except Exception as exc:
            return [TextContent(type="text", text=to_toon({"error": str(exc)}))]

    return None
