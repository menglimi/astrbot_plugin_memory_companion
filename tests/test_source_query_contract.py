from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest


ROOT = Path(__file__).parents[1] / "docs/contracts/source-query/v1"


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_paired_local_profile_schemas_and_examples():
    request = read("schemas/request.schema.json")
    result = read("schemas/result.schema.json")
    for schema in (request, result):
        Draft202012Validator.check_schema(schema)
    for example in read("examples/requests.json"):
        Draft202012Validator(request).validate(example["request"])
    for name in ("result-page", "result-rejected"):
        Draft202012Validator(result).validate(read(f"examples/{name}.json"))


@pytest.mark.parametrize("payload", [
    {"terms": ["早餐"], "bot_id": "caller-cannot-assign-owner"},
    {"cursor": "src_example", "terms": ["changed-query"]},
    {"action": "range", "start_at": "2026-09-08", "end_at": "2026-09-09"},
    {"action": "aggregate", "terms": ["早餐"]},
    {"action": "read", "source_ref": "timeline:tl_example", "terms": ["changed-query"]},
    {"terms": ["早餐"], "limit": True},
])
def test_request_contract_rejects_unsupported_or_mixed_inputs(payload):
    assert not Draft202012Validator(read("schemas/request.schema.json")).is_valid(payload)


@pytest.mark.parametrize("case", ["fact", "coverage", "missing_excerpt_state", "rejected_with_sources"])
def test_result_contract_does_not_mislabel_evidence(case):
    result = deepcopy(read("examples/result-page.json"))
    if case == "fact":
        result["sources"][0]["source_kind"] = "fact"
    elif case == "coverage":
        result["coverage"]["event_coverage"] = "complete"
    elif case == "missing_excerpt_state":
        del result["sources"][0]["excerpt_truncated"]
    else:
        result.update(ok=False, status="rejected", error="source_unavailable")
    assert not Draft202012Validator(read("schemas/result.schema.json")).is_valid(result)
