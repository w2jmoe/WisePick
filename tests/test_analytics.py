"""Tests for read-only usage analytics endpoints and service."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.analytics import (
    AnalyticsDashboardResponse,
    AnalyticsSummaryResponse,
    AnalyticsTimelineResponse,
)
from app.services import analytics_service


def _mock_db(*, fetchone_results=None, fetchall_results=None) -> MagicMock:
    db = MagicMock()
    fetchone_iter = iter(fetchone_results or [])
    fetchall_iter = iter(fetchall_results or [])

    def execute(*_args, **_kwargs):
        result = MagicMock()
        try:
            result.fetchone.return_value = next(fetchone_iter)
        except StopIteration:
            result.fetchone.return_value = None
        try:
            result.fetchall.return_value = next(fetchall_iter)
        except StopIteration:
            result.fetchall.return_value = []
        return result

    db.execute = execute
    return db


def test_summary_empty_database() -> None:
    db = _mock_db(
        fetchone_results=[
            (0,),
            (0,),
            (0,),
            (None, None, None, None),
            None,
        ]
    )
    summary = analytics_service.get_analytics_summary(db)
    assert summary.decisions_total == 0
    assert summary.feedback_total == 0
    assert summary.closure_rate == 0.0
    assert summary.active_providers == 0
    assert summary.avg_success_rate is None
    assert summary.top_provider is None
    assert summary.top_provider_decisions == 0


def test_providers_empty_database() -> None:
    db = _mock_db(fetchall_results=[[]])
    providers = analytics_service.get_provider_stats(db)
    assert providers == []


def test_timeline_empty_database() -> None:
    db = _mock_db(fetchall_results=[[], []])
    timeline = analytics_service.get_analytics_timeline(db)
    assert timeline.days == []


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "app.routers.analytics.get_analytics_summary",
        lambda _db: AnalyticsSummaryResponse(
            decisions_total=0,
            feedback_total=0,
            closure_rate=0.0,
            active_providers=0,
        ),
    )
    monkeypatch.setattr(
        "app.routers.analytics.get_provider_stats",
        lambda _db: [],
    )
    monkeypatch.setattr(
        "app.routers.analytics.get_analytics_timeline",
        lambda _db: AnalyticsTimelineResponse(days=[]),
    )
    monkeypatch.setattr(
        "app.routers.analytics.get_analytics_dashboard",
        lambda _db: AnalyticsDashboardResponse(
            decisions_total=0,
            feedback_total=0,
            closure_rate=0.0,
            active_providers=0,
            decisions_last_7d=0,
            feedback_last_7d=0,
        ),
    )
    return TestClient(app)


def test_summary_endpoint_returns_200(client: TestClient) -> None:
    response = client.get("/v1/analytics/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["decisions_total"] == 0
    assert body["closure_rate"] == 0.0


def test_providers_endpoint_returns_200(client: TestClient) -> None:
    response = client.get("/v1/analytics/providers")
    assert response.status_code == 200
    assert response.json() == []


def test_timeline_endpoint_returns_200(client: TestClient) -> None:
    response = client.get("/v1/analytics/timeline")
    assert response.status_code == 200
    assert response.json() == {"days": []}


def test_dashboard_endpoint_returns_200(client: TestClient) -> None:
    response = client.get("/v1/analytics/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["decisions_total"] == 0
    assert body["decisions_last_7d"] == 0
    assert body["feedback_last_7d"] == 0


def test_dashboard_empty_database() -> None:
    db = _mock_db(
        fetchone_results=[
            (0,),
            (0,),
            (0,),
            (None, None, None, None),
            None,
            (0,),
            (0,),
        ]
    )
    dashboard = analytics_service.get_analytics_dashboard(db)
    assert dashboard.decisions_total == 0
    assert dashboard.feedback_total == 0
    assert dashboard.decisions_last_7d == 0
    assert dashboard.feedback_last_7d == 0


def test_dashboard_with_sample_data() -> None:
    db = _mock_db(
        fetchone_results=[
            (12,),
            (9,),
            (3,),
            (0.8889, 450.5, 1200.25, 0.91),
            ("feishu_minutes", 7, 6),
            (5,),
            (4,),
        ]
    )
    dashboard = analytics_service.get_analytics_dashboard(db)
    assert dashboard.decisions_total == 12
    assert dashboard.feedback_total == 9
    assert dashboard.closure_rate == 0.75
    assert dashboard.top_provider == "feishu_minutes"
    assert dashboard.decisions_last_7d == 5
    assert dashboard.feedback_last_7d == 4


def test_summary_with_sample_data() -> None:
    db = _mock_db(
        fetchone_results=[
            (12,),
            (9,),
            (3,),
            (0.8889, 450.5, 1200.25, 0.91),
            ("feishu_minutes", 7, 6),
        ]
    )
    summary = analytics_service.get_analytics_summary(db)
    assert summary.decisions_total == 12
    assert summary.feedback_total == 9
    assert summary.closure_rate == 0.75
    assert summary.top_provider == "feishu_minutes"
    assert summary.top_provider_decisions == 7


def test_providers_maps_tool_stats_rows() -> None:
    last_at = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    db = _mock_db(
        fetchall_results=[
            [
                (
                    "feishu_minutes",
                    "Feishu Minutes",
                    7,
                    6,
                    0.8333,
                    420.5,
                    1100.0,
                    0.9,
                    last_at,
                )
            ]
        ]
    )
    providers = analytics_service.get_provider_stats(db)
    assert len(providers) == 1
    row = providers[0]
    assert row.tool_key == "feishu_minutes"
    assert row.decision_count == 7
    assert row.success_rate == 0.8333
    assert row.last_feedback_at == last_at


def test_timeline_merges_decisions_and_feedback() -> None:
    db = _mock_db(
        fetchall_results=[
            [(date(2026, 6, 1), 5), (date(2026, 6, 2), 2)],
            [(date(2026, 6, 1), 4), (date(2026, 6, 3), 1)],
        ]
    )
    timeline = analytics_service.get_analytics_timeline(db)
    assert len(timeline.days) == 3
    assert timeline.days[0].date == date(2026, 6, 1)
    assert timeline.days[0].decisions == 5
    assert timeline.days[0].feedback == 4
    assert timeline.days[1].decisions == 2
    assert timeline.days[1].feedback == 0
    assert timeline.days[2].decisions == 0
    assert timeline.days[2].feedback == 1
