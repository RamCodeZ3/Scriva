from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from tests.test_export_table_of_contents import _document_fixture


class DocumentSchemaTest(unittest.TestCase):
    def test_generated_tree_matches_v2_schema(self) -> None:
        schema_path = Path(__file__).parents[1] / "document.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)

        errors = sorted(
            validator.iter_errors(_document_fixture().to_node_tree()),
            key=lambda error: list(error.absolute_path),
        )

        self.assertEqual(
            errors,
            [],
            "\n".join(error.message for error in errors),
        )


if __name__ == "__main__":
    unittest.main()
