"""
Simulate an Agent: POST /v1/decide → handle audio_transcription ECU → POST /v1/feedback.

Requires a running WisePick API (see README_API.md). No extra deps (stdlib only).

  set WISEPICK_URL=http://localhost:8000
  python examples/agent_audio_transcription_demo.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = os.environ.get("WISEPICK_URL", "http://localhost:8000")
# Task wording biased toward audio_transcription routing (engine may still return others).
DEFAULT_TASK = os.environ.get(
    "WISEPICK_TASK",
    "Transcribe today's team meeting audio recording to text",
)


def _post_json(base: str, path: str, payload: dict) -> dict:
    url = base.rstrip("/") + path
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(err_body)
        except json.JSONDecodeError:
            detail = err_body
        raise RuntimeError(f"HTTP {e.code} {path}: {detail}") from e


def execute_audio_transcription_ecu(decision: dict) -> dict:
    """
    ECU → local execution (simulated). Real agent: map to MCP tool / HTTP client / skill.
    """
    capability_id = decision["capability_id"]
    provider = decision["provider"]
    execution_type = decision.get("execution_type", "api")
    callable_ = decision.get("callable", True)

    if capability_id != "audio_transcription":
        return {
            "simulated": True,
            "skipped": True,
            "reason": f"not audio_transcription (got {capability_id!r})",
        }

    if not callable_:
        return {
            "simulated": True,
            "skipped": True,
            "reason": "callable=false; agent should replan instead of blind invoke",
        }

    # Stand-in for real work: branch by execution_type / provider
    print(
        f"[execute] capability_id={capability_id!r} "
        f"provider={provider!r} execution_type={execution_type!r}"
    )
    return {
        "simulated": True,
        "skipped": False,
        "bytes_written": 0,
        "text_preview": "[simulated transcript]",
    }


def main() -> int:
    base = DEFAULT_BASE
    task = DEFAULT_TASK

    print(f"POST /v1/decide base={base!r} task={task!r}")
    decision = _post_json(base, "/v1/decide", {"task": task})

    decision_id = decision["decision_id"]
    cap = decision["capability_id"]
    print(
        "ECU:",
        json.dumps(
            {
                "decision_id": decision_id,
                "capability_id": cap,
                "provider": decision.get("provider"),
                "execution_type": decision.get("execution_type"),
                "callable": decision.get("callable"),
                "confidence": decision.get("confidence"),
            },
            indent=2,
            ensure_ascii=False,
        ),
    )

    result = execute_audio_transcription_ecu(decision)
    success = bool(result.get("simulated")) and not result.get("skipped")

    fb = _post_json(
        base,
        "/v1/feedback",
        {
            "decision_id": decision_id,
            "success": success,
            "latency_ms": 42,
            "user_note": "examples/agent_audio_transcription_demo.py simulated run",
        },
    )
    print("POST /v1/feedback:", json.dumps(fb, ensure_ascii=False))
    print("local execution summary:", json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as e:
        print(f"Network error (is WisePick up?): {e}", file=sys.stderr)
        raise SystemExit(1)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1)
