"""Unit tests for ``routing.wisepick_tool_router`` (client-side ECU parsing)."""

from __future__ import annotations

import json
import os
from unittest import mock

from routing.wisepick_tool_router import (
    extract_hermes_tool_name_from_decide_payload,
    fetch_wisepick_tool_key,
    wisepick_routing_enabled,
)


def test_wisepick_routing_enabled_default() -> None:
    cleaned = {k: v for k, v in os.environ.items() if k != "HERMES_WISEPICK_ROUTING"}
    with mock.patch.dict(os.environ, cleaned, clear=True):
        assert wisepick_routing_enabled() is True
    for val, expected in (("1", True), ("0", False), ("false", False), ("off", False)):
        with mock.patch.dict(os.environ, {"HERMES_WISEPICK_ROUTING": val}):
            assert wisepick_routing_enabled() is expected


def test_extract_flat_capability() -> None:
    key, meta = extract_hermes_tool_name_from_decide_payload(
        {"capability_id": "image_generation", "callable": True, "provider": "openai"}
    )
    assert key == "image_generation"
    assert meta["source"] == "ecu_flat"
    assert meta["provider"] == "openai"


def test_extract_callable_false() -> None:
    key, meta = extract_hermes_tool_name_from_decide_payload(
        {"capability_id": "x", "callable": False}
    )
    assert key is None
    assert meta.get("callable") is False


def test_extract_nested_ecu() -> None:
    payload = {"ecu": {"capability_id": "tts", "callable": True}}
    key, meta = extract_hermes_tool_name_from_decide_payload(payload)
    assert key == "tts"
    assert meta["source"] == "ecu_nested"


def test_extract_legacy_tool_key() -> None:
    key, meta = extract_hermes_tool_name_from_decide_payload(
        {"tool_call": {"tool_key": "legacy_tool"}}
    )
    assert key == "legacy_tool"
    assert meta["source"] == "tool_call.tool_key"


def test_extract_agent_ready_envelope() -> None:
    key, meta = extract_hermes_tool_name_from_decide_payload(
        {
            "agent_ready_output": {
                "primary_choice": {"capability_id": "web_search", "callable": True}
            }
        }
    )
    assert key == "web_search"
    assert "primary_choice" in meta["source"]


def test_fetch_force_tool_short_circuit() -> None:
    with mock.patch.dict(os.environ, {"HERMES_WISEPICK_FORCE_TOOL": "forced_name"}):
        assert fetch_wisepick_tool_key("any task") == "forced_name"


def test_fetch_decide_success() -> None:
    body = json.dumps({"capability_id": "code_execution", "callable": True}).encode("utf-8")

    class FakeResp:
        def __enter__(self) -> FakeResp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return body

    with mock.patch.dict(os.environ, {"HERMES_WISEPICK_FORCE_TOOL": ""}):
        with mock.patch(
            "routing.wisepick_tool_router.urllib.request.urlopen",
            return_value=FakeResp(),
        ):
            assert fetch_wisepick_tool_key("run code") == "code_execution"
