from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

try:
    from .package_bootstrap import bootstrap_package
except ImportError:
    from package_bootstrap import bootstrap_package

ROOT = bootstrap_package()

from astrbot_plugin_memory_companion.core.tool_schema import project_tool_schema


def assert_provider_schema(test: unittest.TestCase, schema: dict) -> None:
    test.assertFalse(set(schema) & {"const", "allOf", "anyOf", "oneOf", "$ref"})
    schema_type = schema.get("type")
    test.assertFalse(isinstance(schema_type, list), schema)
    if schema_type == "array":
        items = schema.get("items")
        test.assertIsInstance(items, dict, schema)
        test.assertNotEqual("null", items.get("type"), schema)
        assert_provider_schema(test, items)
    for values in schema.get("properties", {}).values():
        assert_provider_schema(test, values)
    enum = schema.get("enum")
    if enum is not None:
        test.assertTrue(enum, schema)
        test.assertNotIn(None, enum, schema)
        test.assertNotIn("", enum, schema)
        test.assertTrue(all(isinstance(value, str) for value in enum), schema)


class ToolSchemaProjectionTests(unittest.TestCase):
    def test_contract_request_schemas_project_without_provider_invalid_fields(self) -> None:
        contracts = ROOT / "docs" / "contracts"
        request_schemas = sorted(contracts.rglob("request.schema.json"))
        self.assertGreaterEqual(len(request_schemas), 5)

        for path in request_schemas:
            with self.subTest(path=path.relative_to(ROOT)):
                raw = json.loads(path.read_text(encoding="utf-8"))
                projected = project_tool_schema(raw)
                assert_provider_schema(self, projected)

    def test_unions_keep_model_facing_properties_and_nonempty_constants(self) -> None:
        projected = project_tool_schema({
            "type": "object",
            "oneOf": [
                {
                    "properties": {
                        "action": {"const": "search"},
                        "terms": {"type": "array", "minItems": 1},
                    },
                },
                {
                    "properties": {
                        "action": {"const": "read"},
                        "source_ref": {"type": "string", "const": ""},
                    },
                },
            ],
        })

        self.assertEqual(["search", "read"], projected["properties"]["action"]["enum"])
        self.assertEqual({"type": "string"}, projected["properties"]["terms"]["items"])
        self.assertNotIn("enum", projected["properties"]["source_ref"])
        assert_provider_schema(self, projected)

    def test_numeric_branch_constants_do_not_restrict_other_branches(self) -> None:
        projected = project_tool_schema({
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0},
            },
            "oneOf": [
                {"properties": {"action": {"const": "batch"}, "offset": {"const": 0}}},
                {"properties": {"action": {"const": "read"}, "offset": {"minimum": 0}}},
            ],
        })

        self.assertEqual(["batch", "read"], projected["properties"]["action"]["enum"])
        self.assertNotIn("enum", projected["properties"]["offset"])
        self.assertTrue(Draft202012Validator(projected).is_valid({"action": "read", "offset": 42}))
        assert_provider_schema(self, projected)

    def test_boolean_and_numeric_enums_are_omitted_from_provider_projection(self) -> None:
        projected = project_tool_schema({
            "type": "object",
            "properties": {
                "flag": {"type": "boolean", "enum": [True, False]},
                "limit": {"type": "integer", "enum": [0, 1]},
                "kind": {"type": "string", "enum": ["search", "read"]},
                "untyped_kind": {"enum": ["search", "read"]},
            },
        })

        self.assertNotIn("enum", projected["properties"]["flag"])
        self.assertNotIn("enum", projected["properties"]["limit"])
        self.assertEqual(["search", "read"], projected["properties"]["kind"]["enum"])
        self.assertEqual("string", projected["properties"]["untyped_kind"]["type"])
        assert_provider_schema(self, projected)


if __name__ == "__main__":
    unittest.main()
