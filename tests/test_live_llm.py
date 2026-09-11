"""Opt-in regression set that calls a real model.

The rest of the suite stubs the LLM, which proves the deterministic layers but
not that the model extracts intent correctly. This file is the guard against a
prompt edit quietly breaking that. It needs API keys and costs tokens, so it is
skipped unless RUN_LIVE_LLM=1.

    RUN_LIVE_LLM=1 uv run pytest tests/test_live_llm.py -v
"""
import json
import os
from pathlib import Path

import pytest

from src.service import parse_message

from tests.conftest import FACETS

CASES = json.loads((Path(__file__).parent / "fixtures" / "chat_cases.json").read_text())

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM") != "1", reason="set RUN_LIVE_LLM=1 to call a real model"
)


@pytest.mark.parametrize("case", CASES, ids=[c["message"] for c in CASES])
def test_live_case(case):
    result = parse_message(case["message"], "oneway", FACETS)

    expected_status = case.get("expect_status", "applied")
    assert result["status"] == expected_status, result

    if "expect_message" in case:
        assert result["message"] == case["expect_message"]

    for field, value in (case.get("expect") or {}).items():
        assert result["filter"][field] == value, f"{field}: {result['filter'][field]!r}"
