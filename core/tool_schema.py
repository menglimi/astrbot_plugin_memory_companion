"""Provider-safe function-calling parameters derived from review contracts.

Contract files under ``docs/contracts`` are JSON Schema 2020-12 documents: they
are validated with ``jsonschema`` and may therefore use ``const``, omit
``items`` on arrays, and keep ``null`` or empty-array members inside ``enum``.

Those forms are valid for request validation but are not portable to function
calling, where strict providers reject the whole request.  Google Gemini, for
example, turns ``{"const": ""}`` into ``"enum": [""]`` and answers with
``GenerateContentRequest.tools[0].function_declarations[N].parameters
.properties[source_ref].enum[0]: cannot be empty``.

The contracts stay untouched; only the outgoing tool parameters are normalised.
Request validation keeps using the original contract, so pattern/const
semantics are unchanged for callers.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


def _clean(node: Any) -> Any:
    if isinstance(node, list):
        return [_clean(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {key: _clean(value) for key, value in node.items()}
    if "const" in out:
        const_value = out.pop("const")
        if isinstance(const_value, str) and not const_value:
            # An empty const has no enum form that providers accept; express it
            # with the equivalent pattern instead of an empty enum member.
            out.setdefault("type", "string")
            out["pattern"] = "^$"
        else:
            out["enum"] = [const_value]
    enum_values = out.get("enum")
    if isinstance(enum_values, list):
        kept = [value for value in enum_values if value is not None and value != []]
        if not kept:
            out.pop("enum", None)
            out.setdefault("type", "string")
        else:
            out["enum"] = kept
            if "type" not in out:
                item_types = {type(value).__name__ for value in kept}
                if item_types == {"str"}:
                    out["type"] = "string"
                elif item_types <= {"int", "float"}:
                    out["type"] = "number"
                elif item_types == {"bool"}:
                    out["type"] = "boolean"
    node_type = out.get("type")
    if node_type == "array" or (isinstance(node_type, list) and "array" in node_type):
        if not isinstance(out.get("items"), dict):
            out["items"] = {"type": "string"}
    return out


def tool_parameters_from_contract(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep, provider-safe copy of a contract schema."""

    return _clean(deepcopy(dict(schema)))
