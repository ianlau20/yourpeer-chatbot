"""
Tests for the admin API routes — HTTP-level endpoint tests using
FastAPI TestClient.

Covers all admin API endpoints:
    GET /admin/api/stats  — aggregate statistics
    GET /admin/api/conversations       — conversation summaries
    GET /admin/api/conversations/{id}  — single conversation detail
    GET /admin/api/events              — recent events (filterable)
    GET /admin/api/queries             — query execution log
    GET /admin/api/eval                — LLM evaluation results

Run with: python -m pytest tests/test_admin.py -v
Or just:  python tests/test_admin.py
"""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi.testclient import TestClient
from app.main import app
from app.services.audit_log import (
    log_conversation_turn,
    log_query_execution,
    log_crisis_detected,
    log_session_reset,
    set_eval_results,
    clear_audit_log,
)

client = TestClient(app)


# -----------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------

def _seed_data():
    """Populate the audit log with realistic test data."""
    clear_audit_log()

    # Session 1: full service flow
    log_conversation_turn(
        session_id="sess-abc",
        user_message_redacted="I need food in Brooklyn",
        bot_response="I'll search for food in Brooklyn.",
        slots={"service_type": "food", "location": "Brooklyn"},
        category="service",
        services_count=0,
        follow_up_needed=True,
    )
    log_conversation_turn(
        session_id="sess-abc",
        user_message_redacted="Yes, search",
        bot_response="I found 3 options.",
        slots={"service_type": "food", "location": "Brooklyn"},
        category="confirm_yes",
        services_count=3,
    )
    log_query_execution(
        session_id="sess-abc",
        template_name="FoodQuery",
        params={"taxonomy_name": "Food", "city": "Brooklyn", "max_results": 10},
        result_count=3,
        relaxed=False,
        execution_ms=42,
    )

    # Session 2: crisis
    log_conversation_turn(
        session_id="sess-xyz",
        user_message_redacted="I want to [REDACTED]",
        bot_response="I hear you...",
        slots={},
        category="crisis",
    )
    log_crisis_detected(
        session_id="sess-xyz",
        crisis_category="suicide_self_harm",
        user_message_redacted="I want to [REDACTED]",
    )

    # Session 3: reset
    log_session_reset("sess-reset")


# -----------------------------------------------------------------------
# GET /admin/api/stats
# -----------------------------------------------------------------------

def test_stats_empty():
    """Stats on empty log should return zeros."""
    clear_audit_log()
    response = client.get("/admin/api/stats")
    assert response.status_code == 200

    data = response.json()
    assert data["total_events"] == 0
    assert data["total_turns"] == 0
    assert data["total_queries"] == 0
    assert data["total_crises"] == 0
    assert data["total_resets"] == 0
    assert data["unique_sessions"] == 0
    assert data["relaxed_query_rate"] == 0
    print("  PASS: GET /admin/api/stats empty")


def test_stats_with_data():
    """Stats should reflect seeded data correctly."""
    _seed_data()
    response = client.get("/admin/api/stats")
    assert response.status_code == 200

    data = response.json()
    assert data["total_turns"] == 3
    assert data["total_queries"] == 1
    assert data["total_crises"] == 1
    assert data["total_resets"] == 1
    assert data["unique_sessions"] == 3
    assert "service" in data["category_distribution"]
    assert "food" in data["service_type_distribution"]
    print("  PASS: GET /admin/api/stats with data")


# -----------------------------------------------------------------------
# GET /admin/api/conversations
# -----------------------------------------------------------------------

def test_conversations_list():
    """Should return conversation summaries."""
    _seed_data()
    response = client.get("/admin/api/conversations")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 3  # sess-abc, sess-xyz, sess-reset

    # Find sess-abc
    abc = next((c for c in data if c["session_id"] == "sess-abc"), None)
    assert abc is not None
    assert abc["turn_count"] == 2
    assert abc["services_delivered"] >= 3
    print("  PASS: GET /admin/api/conversations list")


def test_conversations_limit():
    """Limit parameter should cap results."""
    _seed_data()
    response = client.get("/admin/api/conversations?limit=1")
    assert response.status_code == 200
    assert len(response.json()) == 1
    print("  PASS: GET /admin/api/conversations?limit=1")


def test_conversations_limit_validation():
    """Limit below 1 or above 200 should be rejected."""
    response = client.get("/admin/api/conversations?limit=0")
    assert response.status_code == 422  # validation error

    response = client.get("/admin/api/conversations?limit=999")
    assert response.status_code == 422
    print("  PASS: GET /admin/api/conversations limit validation")


# -----------------------------------------------------------------------
# GET /admin/api/conversations/{session_id}
# -----------------------------------------------------------------------

def test_conversation_detail():
    """Should return all events for a specific session."""
    _seed_data()
    response = client.get("/admin/api/conversations/sess-abc")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 3  # 2 turns + 1 query
    assert all(e["session_id"] == "sess-abc" for e in data)
    print("  PASS: GET /admin/api/conversations/sess-abc")


def test_conversation_detail_not_found():
    """Should return 404 for unknown session ID."""
    _seed_data()
    response = client.get("/admin/api/conversations/nonexistent-session")
    assert response.status_code == 404
    assert "No conversation found" in response.json()["detail"]
    print("  PASS: GET /admin/api/conversations/nonexistent → 404")


def test_conversation_detail_crisis_session():
    """Crisis session should include both turn and crisis events."""
    _seed_data()
    response = client.get("/admin/api/conversations/sess-xyz")
    assert response.status_code == 200

    data = response.json()
    types = [e["type"] for e in data]
    assert "conversation_turn" in types
    assert "crisis_detected" in types
    print("  PASS: GET /admin/api/conversations/sess-xyz (crisis)")


# -----------------------------------------------------------------------
# GET /admin/api/events
# -----------------------------------------------------------------------

def test_events_all():
    """Should return all events with default parameters."""
    _seed_data()
    response = client.get("/admin/api/events")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 6  # 3 turns + 1 query + 1 crisis + 1 reset
    print("  PASS: GET /admin/api/events all")


def test_events_filter_by_type():
    """Should filter events by type."""
    _seed_data()

    response = client.get("/admin/api/events?event_type=crisis_detected")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["type"] == "crisis_detected"

    response = client.get("/admin/api/events?event_type=session_reset")
    data = response.json()
    assert len(data) == 1
    assert data[0]["type"] == "session_reset"
    print("  PASS: GET /admin/api/events?event_type=...")


def test_events_invalid_type_rejected():
    """Invalid event_type should be rejected by the regex validator."""
    response = client.get("/admin/api/events?event_type=invalid_type")
    assert response.status_code == 422
    print("  PASS: GET /admin/api/events?event_type=invalid → 422")


def test_events_limit():
    """Limit parameter should cap results."""
    _seed_data()
    response = client.get("/admin/api/events?limit=2")
    assert response.status_code == 200
    assert len(response.json()) == 2
    print("  PASS: GET /admin/api/events?limit=2")


def test_events_limit_validation():
    """Limit below 1 or above 500 should be rejected."""
    response = client.get("/admin/api/events?limit=0")
    assert response.status_code == 422

    response = client.get("/admin/api/events?limit=999")
    assert response.status_code == 422
    print("  PASS: GET /admin/api/events limit validation")


# -----------------------------------------------------------------------
# GET /admin/api/queries
# -----------------------------------------------------------------------

def test_queries_list():
    """Should return query execution log."""
    _seed_data()
    response = client.get("/admin/api/queries")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["template_name"] == "FoodQuery"
    assert data[0]["result_count"] == 3
    assert "max_results" not in data[0]["params"]
    print("  PASS: GET /admin/api/queries")


def test_queries_limit():
    """Limit parameter should cap results."""
    clear_audit_log()
    for i in range(10):
        log_query_execution("s1", f"Q{i}", {}, i, False, 10)

    response = client.get("/admin/api/queries?limit=3")
    assert response.status_code == 200
    assert len(response.json()) == 3
    print("  PASS: GET /admin/api/queries?limit=3")


# -----------------------------------------------------------------------
# GET /admin/api/eval
# -----------------------------------------------------------------------

def test_eval_no_results():
    """Should return 200 with null results when no eval results exist."""
    clear_audit_log()
    response = client.get("/admin/api/eval")
    assert response.status_code == 200
    data = response.json()
    assert data["results"] is None
    assert "No evaluation results" in data["detail"]
    print("  PASS: GET /admin/api/eval → 200 with null results when empty")


def test_eval_with_results():
    """Should return eval results when set."""
    clear_audit_log()
    eval_data = {
        "timestamp": "2025-01-01T00:00:00Z",
        "scenarios_run": 10,
        "average_score": 4.2,
        "results": [{"scenario": "basic_food", "score": 5}],
    }
    set_eval_results(eval_data)

    response = client.get("/admin/api/eval")
    assert response.status_code == 200

    data = response.json()
    assert data["scenarios_run"] == 10
    assert data["average_score"] == 4.2
    print("  PASS: GET /admin/api/eval with results")


# -----------------------------------------------------------------------
# HEALTH CHECK (sanity — not admin but confirms app is wired)
# -----------------------------------------------------------------------

def test_health_endpoint():
    """GET /api/health should return ok."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    print("  PASS: GET /api/health")


# -----------------------------------------------------------------------
# RUNNER
# -----------------------------------------------------------------------

if __name__ == "__main__":
    print("\nAdmin Route Tests\n" + "=" * 50)

    print("\n--- Stats Endpoint ---")
    test_stats_empty()
    test_stats_with_data()

    print("\n--- Conversations List ---")
    test_conversations_list()
    test_conversations_limit()
    test_conversations_limit_validation()

    print("\n--- Conversation Detail ---")
    test_conversation_detail()
    test_conversation_detail_not_found()
    test_conversation_detail_crisis_session()

    print("\n--- Events ---")
    test_events_all()
    test_events_filter_by_type()
    test_events_invalid_type_rejected()
    test_events_limit()
    test_events_limit_validation()

    print("\n--- Queries ---")
    test_queries_list()
    test_queries_limit()

    print("\n--- Eval ---")
    test_eval_no_results()
    test_eval_with_results()

    print("\n--- Health ---")
    test_health_endpoint()

    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
