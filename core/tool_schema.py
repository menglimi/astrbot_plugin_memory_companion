"""Project validation schemas into the smaller function-tool schema subset."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


_SIMPLE_KEYS = {
    "additionalProperties",
    "default",
    "description",
    "format",
    "maximum",
    "maxItems",
    "maxLength",
    "minimum",
    "minItems",
    "minLength",
    "pattern",
}
_TYPE_PRIORITY = {
    "boolean": 1,
    "string": 2,
    "number": 3,
    "integer": 3,
    "array": 4,
    "object": 5,
}


def _types(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [item for item in values if isinstance(item, str) and item != "null"]


def _enum_values(value: Any) -> list[Any]:
    values = value if isinstance(value, list) else [value]
    return [item for item in values if item is not None and item != "" and item != []]


def _merge_type(target: dict[str, Any], value: Any) -> None:
    values = _types(value)
    if not values:
        return
    candidate = max(values, key=lambda item: _TYPE_PRIORITY.get(item, 0))
    current = target.get("type")
    if current is None or _TYPE_PRIORITY.get(candidate, 0) > _TYPE_PRIORITY.get(current, 0):
        target["type"] = candidate


def _append_unique(target: list[Any], values: list[Any]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _merge_schema(target: dict[str, Any], source: dict[str, Any], *, branch: bool = False) -> None:
    _merge_type(target, source.get("type"))
    for key in _SIMPLE_KEYS:
        if key in source and key not in target:
            value = source[key]
            if key == "additionalProperties" and not isinstance(value, bool):
                continue
            target[key] = value

    if not branch and isinstance(source.get("required"), list):
        target["required"] = list(dict.fromkeys(
            item for item in source["required"] if isinstance(item, str)
        ))

    values = []
    if "enum" in source:
        values.extend(_enum_values(source["enum"]))
    if "const" in source:
        values.extend(_enum_values(source["const"]))
    if values:
        merged = _enum_values(target.get("enum", []))
        _append_unique(merged, values)
        target["enum"] = merged

    properties = source.get("properties")
    if isinstance(properties, dict):
        target_properties = target.setdefault("properties", {})
        for name, child in properties.items():
            if not isinstance(name, str) or not isinstance(child, dict):
                continue
            projected = target_properties.setdefault(name, {})
            _merge_schema(projected, child, branch=branch)

    if isinstance(source.get("items"), dict):
        projected_items = target.setdefault("items", {})
        _merge_schema(projected_items, source["items"], branch=branch)

    for key in ("allOf", "anyOf", "oneOf"):
        branches = source.get(key)
        if not isinstance(branches, list):
            continue
        for item in branches:
            if isinstance(item, dict):
                _merge_schema(target, item, branch=True)


def _finalize_schema(schema: dict[str, Any]) -> None:
    if schema.get("type") == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            schema["items"] = {"type": "string"}
        else:
            _finalize_schema(items)
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for child in properties.values():
            if isinstance(child, dict):
                _finalize_schema(child)


def project_tool_schema(schema: Any) -> dict[str, Any]:
    """Flatten schema unions and omit constraints unsupported by tool providers.

    Runtime validators still enforce the full contract. This projection keeps
    the model-facing shape useful while avoiding empty enums, const constraints,
    nullable unions, and arrays without an item schema.
    """
    result: dict[str, Any] = {}
    if isinstance(schema, dict):
        _merge_schema(result, schema)
    _finalize_schema(result)
    return result


# Keep the structure-preserving normalizer for existing contract consumers.
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
