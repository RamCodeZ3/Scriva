from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from domain.exceptions import DocumentBuildError
from jsonschema import Draft202012Validator


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema_path = Path(__file__).parents[3] / "document.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_document_tree(node_tree: dict[str, Any]) -> None:
    """Reject a non-v2 tree before it crosses a persistence/export boundary."""
    errors = sorted(
        _validator().iter_errors(node_tree),
        key=lambda error: list(error.absolute_path),
    )
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(part) for part in first.absolute_path)
    suffix = f" at '{location}'" if location else ""
    raise DocumentBuildError(
        f"Document tree does not match schema v2{suffix}: {first.message}"
    )
