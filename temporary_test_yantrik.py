"""
临时脚本：用 mock 验证 Yantrik 高/低延迟下 ECU score（confidence）是否按预期缩放。
"""
from __future__ import annotations

import io
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
from unittest.mock import MagicMock, patch

from app.adapters.yantrik_adapter import YantrikClusterHealth
from app.schemas.decide import DecideRequest
from app.services import decision_engine


def _fake_tool():
    t = MagicMock()
    t.tool_key = "test_tool"
    t.capabilities = "transcription"
    t.bootstrap_weight = 0.5
    t.enabled = True
    return t


def _baseline_score_no_yantrik() -> float:
    """不调 Yantrik（URL 空）时的 confidence，作为对照。"""
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = [_fake_tool()]
    with patch.object(decision_engine.settings, "YANTRIK_DB_URL", ""):
        with patch.object(decision_engine, "_get_tool_success_rate", return_value=0.5):
            with patch.object(decision_engine, "_get_feedback_count", return_value=0):
                with patch.object(decision_engine, "_create_decision_log"):
                    with patch.object(
                        decision_engine, "_get_success_rate_display", return_value="50%"
                    ):
                        req = DecideRequest(task="Transcribe meeting audio")
                        r = decision_engine.run_decision(req, mock_db)
                        return float(r.confidence)


def _run_with_lag(lag: int) -> float:
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = [_fake_tool()]

    health = YantrikClusterHealth(
        replication_lag_log_entries=lag,
        raw={"replication_lag_log_entries": lag},
    )

    with patch.object(decision_engine.settings, "YANTRIK_DB_URL", "http://yantrik.test"):
        with patch.object(
            decision_engine, "get_cluster_health", return_value=health
        ):
            with patch.object(decision_engine, "_get_tool_success_rate", return_value=0.5):
                with patch.object(decision_engine, "_get_feedback_count", return_value=0):
                    with patch.object(decision_engine, "_create_decision_log"):
                        with patch.object(
                            decision_engine,
                            "_get_success_rate_display",
                            return_value="50%",
                        ):
                            req = DecideRequest(task="Transcribe meeting audio")
                            r = decision_engine.run_decision(req, mock_db)
                            return float(r.confidence)


def main() -> int:
    baseline = _baseline_score_no_yantrik()
    high = _run_with_lag(600)
    low = _run_with_lag(10)

    print("baseline (no YANTRIK_DB_URL):", baseline)
    print("high lag 600:", high, "| ratio vs baseline:", round(high / baseline, 6) if baseline else None)
    print("low lag 10:", low, "| ratio vs baseline:", round(low / baseline, 6) if baseline else None)

    eps = 1e-6
    ok_high = abs(high - baseline * 0.5) < eps
    ok_low = abs(low - baseline) < eps

    print()
    print("断言: 高延迟(600) → score 约为 baseline 的 50%:", "PASS" if ok_high else "FAIL")
    print("断言: 低延迟(10) → score 与 baseline 相同:", "PASS" if ok_low else "FAIL")

    if not ok_high or not ok_low:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
