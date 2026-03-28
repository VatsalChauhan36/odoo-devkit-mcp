from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import to_toon
from .helpers import _collect_access_csv_records, _collect_record_rules, _snake_from_model


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
    if name == "find_security_access_for_model":
        model = arguments.get("model")
        if not model:
            raise ValueError("model is required")
        limit = int(arguments.get("limit", 120))
        target = model.strip()

        csv_rows = _collect_access_csv_records(roots)
        model_token = f"model_{target.replace('.', '_')}"
        access_matches = [
            row for row in csv_rows
            if (row.get("model_id:id") or "") == model_token
            or (row.get("model_id:id") or "").endswith(f".{model_token}")
        ]

        rules = _collect_record_rules(roots)
        rule_matches = [
            row
            for row in rules
            if (row.get("model_ref") or "") == model_token
            or (row.get("model_ref") or "").endswith(f".{model_token}")
        ]

        return [
            TextContent(
                type="text",
                text=to_toon(
                    {
                        "model": target,
                        "access_count": len(access_matches[:limit]),
                        "rule_count": len(rule_matches[:limit]),
                        "access": access_matches[:limit],
                        "rules": rule_matches[:limit],
                    }
                ),
            )
        ]

    return None
