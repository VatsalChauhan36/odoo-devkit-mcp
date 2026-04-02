from pathlib import Path
from typing import Any, Sequence

from mcp.types import TextContent

from ..utils import to_toon
from .helpers import _collect_access_csv_records, _collect_record_rules, _sort_records


def handle(
    name: str, arguments: dict[str, Any], roots: list[Path], modules: dict[str, Path]
) -> Sequence[TextContent] | None:
    if name == "find_security_access_for_model":
        model = arguments.get("model")
        if not model:
            raise ValueError("model is required")
        limit = int(str(arguments.get("limit", 120)))
        target = model.strip()

        csv_rows = _collect_access_csv_records(roots)
        model_token = f"model_{target.replace('.', '_')}"
        access_matches = _sort_records(
            [
                row
                for row in csv_rows
                if (row.get("model_id:id") or "") == model_token
                or (row.get("model_id:id") or "").endswith(f".{model_token}")
            ]
        )[:limit]

        rules = _collect_record_rules(roots)
        rule_matches = _sort_records(
            [
                row
                for row in rules
                if (row.get("model_ref") or "") == model_token
                or (row.get("model_ref") or "").endswith(f".{model_token}")
            ]
        )[:limit]

        return [
            TextContent(
                type="text",
                text=to_toon(
                    {
                        "model": target,
                        "access_count": len(access_matches),
                        "rule_count": len(rule_matches),
                        "access": access_matches,
                        "rules": rule_matches,
                    }
                ),
            )
        ]

    return None
