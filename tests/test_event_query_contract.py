from __future__ import annotations

from copy import deepcopy
import json

from jsonschema import Draft202012Validator
import pytest

from core.event_query import CONTRACT_ROOT, EventQueryError, bind_event_tool_schema, parse_plan, reduce_events


def read(path):
    return json.loads((CONTRACT_ROOT / path).read_text(encoding="utf-8"))


def test_paired_schemas_validate_authored_week_fixture_and_reducer():
    request, result = read("schemas/request.schema.json"), read("schemas/result.schema.json")
    for schema in (request, result):
        Draft202012Validator.check_schema(schema)
    payload = read("examples/week-request.json")
    Draft202012Validator(request).validate(payload)
    fixture = read("fixtures/week-breakfast.json")
    assert fixture["semantic_run_status"] == "not_run"
    assert fixture["request"] == payload
    sources = {f"timeline:tl_{source['id']}": source for source in fixture["sources"]}
    reduced = reduce_events(parse_plan(payload["plan"]), sources)
    assert reduced["aggregate"]["count"] == fixture["expected"]["resolved_groups"]
    assert reduced["aggregate"]["days_without_resolved_events"] == fixture["expected"]["days_without_resolved_events"]
    Draft202012Validator(result).validate(read("examples/result-rejected.json"))
    computed = read("examples/week-result.json")
    Draft202012Validator(result).validate(computed)
    assert computed["aggregate"] == reduced["aggregate"]


@pytest.mark.parametrize("case", ["identity", "bad_time", "missing_anchor", "no_window", "no_resolution", "extra_sql"])
def test_request_schema_and_parser_reject_missing_or_unsupported_semantics(case):
    payload = deepcopy(read("examples/week-request.json"))
    plan, row = payload["plan"], payload["plan"]["rows"][0]
    if case == "identity":
        plan["owner_id"] = "forged"
    elif case == "bad_time":
        row["time"] = {"kind": "instant", "at": "2026-09-08", "source_ref": row["evidence"][0]["source_ref"]}
    elif case == "missing_anchor":
        del row["time"]["source_ref"]
    elif case == "no_window":
        del plan["window"]
    elif case == "no_resolution":
        del row["resolution"]
    else:
        plan["sql"] = "SELECT * FROM timeline"
    assert not Draft202012Validator(read("schemas/request.schema.json")).is_valid(payload)
    with pytest.raises(EventQueryError):
        parse_plan(plan)


def test_real_astrbot_tool_binding_exposes_nested_fields_and_uses_owner_handler():
    from astrbot.core.provider.func_tool_manager import FunctionToolManager
    manager = FunctionToolManager()
    async def handler(event, plan):
        return "unused"
    manager.add_func("memory_companion_events", [{"name": "plan", "type": "object"}], "events", handler)
    tool = manager.get_func("memory_companion_events")
    tool.handler_module_path = "isolated.memory.main"
    assert not bind_event_tool_schema(manager, "another.plugin")
    assert bind_event_tool_schema(manager, "isolated.memory.main")
    Draft202012Validator(tool.parameters).validate(read("examples/week-request.json"))
    properties = tool.parameters["properties"]["plan"]["properties"]["rows"]["items"]["properties"]
    assert "source_version" in properties["evidence"]["items"]["properties"]
    assert "time" in properties and tool.handler is handler
    assert bind_event_tool_schema(manager, "isolated.memory.main")
    assert len([item for item in manager.func_list if item.name == "memory_companion_events"]) == 1


@pytest.mark.parametrize("change", ["computed_without_result", "facts", "complete_coverage"])
def test_result_schema_cannot_claim_persistence_or_complete_history(change):
    value = read("examples/result-rejected.json")
    if change == "computed_without_result":
        value.update(ok=True, status="computed", error="")
    elif change == "facts":
        value["facts"] = [{"atom_id": "invented"}]
    else:
        value["coverage"] = {"event_coverage": "complete"}
    assert not Draft202012Validator(read("schemas/result.schema.json")).is_valid(value)


def test_intersection_of_different_local_days_keeps_interval_precision():
    payload = read("examples/week-request.json")["plan"]
    first = deepcopy(payload["rows"][0])
    second = deepcopy(first)
    second["row_id"] = "alternate-zone"
    first["time"] = {"kind": "date", "date": "2026-09-08", "timezone": "Asia/Shanghai", "source_ref": first["evidence"][0]["source_ref"]}
    second["time"] = {**first["time"], "timezone": "Asia/Tokyo"}
    payload.update(rows=[first, second], operation="list", window=None)
    result = reduce_events(parse_plan(payload), {})
    assert result["events"][0]["time"]["precision"] == "interval"
