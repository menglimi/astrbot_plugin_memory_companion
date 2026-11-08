"""Contract schemas must reach providers in a function-calling safe form.

The request contracts are JSON Schema 2020-12 documents used for validation.
Strict function-calling providers reject some of the forms they use, most
notably ``const`` with an empty string (turned into an empty ``enum`` member by
Google Gemini) and arrays without ``items``.  These tests pin the outgoing form.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from core.tool_schema import tool_parameters_from_contract
from .test_source_query import ctx, service  # noqa: F401 - pytest fixtures reused here


CONTRACTS = Path(__file__).parents[1] / "docs/contracts"
REQUEST_SCHEMAS = sorted(CONTRACTS.glob("**/schemas/request.schema.json"))


def provider_problems(node, path=""):
    """Return every construct a strict function-calling provider rejects."""

    found = []
    if isinstance(node, dict):
        if "const" in node:
            found.append(f"{path}.const={node['const']!r}")
        enum = node.get("enum")
        if isinstance(enum, list) and (not enum or any(value in (None, []) or value == "" for value in enum)):
            found.append(f"{path}.enum={enum}")
        if node.get("type") == "array" and not isinstance(node.get("items"), dict):
            found.append(f"{path}: type array without items")
        for key, value in node.items():
            found += provider_problems(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += provider_problems(value, f"{path}[{index}]")
    return found


@pytest.mark.parametrize("path", REQUEST_SCHEMAS, ids=lambda item: str(item.relative_to(CONTRACTS)))
def test_cleaned_contract_is_provider_safe_while_contract_stays_valid(path):
    contract = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(contract)

    cleaned = tool_parameters_from_contract(contract)

    assert provider_problems(cleaned) == []
    # The contract itself is untouched: validation keeps its original semantics.
    assert json.loads(path.read_text(encoding="utf-8")) == contract
    if "required" in contract:
        assert cleaned.get("required") == contract["required"]


def test_empty_const_becomes_empty_string_pattern():
    cleaned = tool_parameters_from_contract({"properties": {"source_ref": {"const": ""}}})

    assert cleaned["properties"]["source_ref"] == {"type": "string", "pattern": "^$"}


def test_non_empty_const_becomes_single_value_enum():
    cleaned = tool_parameters_from_contract({"properties": {"action": {"const": "search"}}})

    assert cleaned["properties"]["action"] == {"enum": ["search"], "type": "string"}


def test_array_without_items_gets_string_items():
    cleaned = tool_parameters_from_contract({"properties": {"terms": {"type": "array"}}})

    assert cleaned["properties"]["terms"] == {"type": "array", "items": {"type": "string"}}


def test_enum_dropping_null_and_empty_array():
    cleaned = tool_parameters_from_contract({"properties": {"flag": {"enum": [None, [], "on"]}}})

    assert cleaned["properties"]["flag"] == {"enum": ["on"], "type": "string"}


def test_cleaning_is_idempotent():
    contract = json.loads((CONTRACTS / "source-query/v1/schemas/request.schema.json").read_text(encoding="utf-8"))
    once = tool_parameters_from_contract(contract)

    assert tool_parameters_from_contract(once) == once


def test_bound_sources_tool_parameters_are_provider_safe():
    from .test_source_query_v2 import tools_for_batch

    tools, _ = tools_for_batch()
    source = next(tool for tool in tools.tools if tool.name == "memory_companion_sources")

    assert provider_problems(source.parameters) == []


def test_v1_source_fallback_keeps_provider_safe_parameters():
    from core.query_session import TOOL_NAME, bind_query_tool_schema, bind_source_query_v2_schema

    query = SimpleNamespace(handler_module_path="test.module", parameters={})
    source = SimpleNamespace(
        handler_module_path="test.module",
        parameters={
            "type": "object",
            "properties": {
                "query_note": {"type": "string"},
                "mode": {"const": ""},
                "terms": {"type": "array"},
            },
            "required": ["query_note"],
        },
    )
    tools = {TOOL_NAME: query, "memory_companion_sources": source}
    manager = SimpleNamespace(get_func=tools.get)

    assert bind_query_tool_schema(manager, "test.module")
    assert not bind_source_query_v2_schema(manager, "test.module")
    assert provider_problems(source.parameters) == []
    assert "query_note" not in source.parameters["properties"]
    assert source.parameters["required"] == []


@pytest.mark.asyncio
async def test_request_projection_parameters_are_provider_safe(service, ctx):
    from types import SimpleNamespace

    from core.query_session import offer_query_tool

    from .test_source_query_v2 import tools_for_batch

    service.config.raw.setdefault("memory_tools", {})["enable_source_query_v2"] = True
    tools, _ = tools_for_batch()
    event = SimpleNamespace()
    offer_query_tool(service, SimpleNamespace(func_tool=tools), ctx, event)

    assert provider_problems(tools.tools) == []
