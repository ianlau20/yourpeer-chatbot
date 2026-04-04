"""
Tests for the audit log module — event recording, retrieval,
conversation summaries, stats aggregation, eval results, and
ring buffer behavior.

Run with: python -m pytest tests/test_audit_log.py -v
Or just:  python tests/test_audit_log.py
"""

import os
import json
import time
import tempfile
import threading


from app.services.audit_log import (
    log_conversation_turn,
    log_query_execution,
    log_crisis_detected,
    log_session_reset,
    get_recent_events,
    get_conversation,
    get_conversations_summary,
    get_query_log,
    get_stats,
    set_eval_results,
    get_eval_results,
    load_eval_results_from_file,
    clear_audit_log,
    MAX_EVENTS,
    MAX_CONVERSATIONS,
    _events,
    _conversations,
    _query_log,
)


# -----------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------

def _seed_conversation(session_id="sess-1", turns=3, service_type="food"):
    """Log a multi-turn conversation for testing."""
    for i in range(turns):
        log_conversation_turn(
            session_id=session_id,
            user_message_redacted=f"message {i}",
            bot_response=f"response {i}",
            slots={"service_type": service_type, "location": "Brooklyn"},
            category="service",
            services_count=2 if i == turns - 1 else 0,
        )


# -----------------------------------------------------------------------
# LOG CONVERSATION TURN
# -----------------------------------------------------------------------

def test_log_conversation_turn_basic():
    """A logged turn should appear in events with correct fields."""
    clear_audit_log()
    log_conversation_turn(
        session_id="s1",
        user_message_redacted="I need food in Brooklyn",
        bot_response="I found 3 options.",
        slots={"service_type": "food", "location": "Brooklyn"},
        category="service",
        services_count=3,
        quick_replies=[{"label": "New search", "value": "Start over"}],
        follow_up_needed=False,
    )

    events = get_recent_events()
    assert len(events) == 1

    e = events[0]
    assert e["type"] == "conversation_turn"
    assert e["session_id"] == "s1"
    assert e["user_message"] == "I need food in Brooklyn"
    assert e["bot_response"] == "I found 3 options."
    assert e["category"] == "service"
    assert e["services_count"] == 3
    assert e["follow_up_needed"] is False
    assert "timestamp" in e


def test_log_turn_strips_internal_slots():
    """Internal slot keys (_pending_confirmation, transcript) should be stripped."""
    clear_audit_log()
    log_conversation_turn(
        session_id="s1",
        user_message_redacted="test",
        bot_response="test",
        slots={
            "service_type": "food",
            "location": "Queens",
            "_pending_confirmation": True,
            "transcript": [{"role": "user", "text": "test"}],
            "age": None,
        },
        category="service",
    )

    events = get_recent_events()
    slots = events[0]["slots"]
    assert "service_type" in slots
    assert "location" in slots
    assert "_pending_confirmation" not in slots, "Internal keys should be stripped"
    assert "transcript" not in slots, "Transcript should be stripped"
    assert "age" not in slots, "None-valued slots should be stripped"


def test_log_turn_quick_replies_extracts_labels():
    """Quick replies should be stored as label strings, not full dicts."""
    clear_audit_log()
    log_conversation_turn(
        session_id="s1",
        user_message_redacted="test",
        bot_response="test",
        slots={},
        category="greeting",
        quick_replies=[
            {"label": "🍽️ Food", "value": "I need food"},
            {"label": "🏠 Shelter", "value": "I need shelter"},
        ],
    )

    events = get_recent_events()
    qr = events[0]["quick_replies"]
    assert qr == ["🍽️ Food", "🏠 Shelter"]


def test_log_turn_none_slots():
    """Passing None for slots should not crash."""
    clear_audit_log()
    log_conversation_turn(
        session_id="s1",
        user_message_redacted="hi",
        bot_response="hello",
        slots=None,
        category="greeting",
    )

    events = get_recent_events()
    assert events[0]["slots"] == {}


def test_log_turn_registers_conversation():
    """Logging a turn should register the session in _conversations."""
    clear_audit_log()
    log_conversation_turn(
        session_id="s1",
        user_message_redacted="test",
        bot_response="test",
        slots={},
        category="service",
    )

    conv = get_conversation("s1")
    assert len(conv) == 1
    assert conv[0]["session_id"] == "s1"


# -----------------------------------------------------------------------
# LOG QUERY EXECUTION
# -----------------------------------------------------------------------

def test_log_query_execution():
    """Query execution events should appear in both events and query log."""
    clear_audit_log()
    log_query_execution(
        session_id="s1",
        template_name="FoodQuery",
        params={"taxonomy_name": "Food", "city": "Brooklyn", "max_results": 10},
        result_count=5,
        relaxed=False,
        execution_ms=42,
    )

    events = get_recent_events()
    assert len(events) == 1
    assert events[0]["type"] == "query_execution"
    assert events[0]["template_name"] == "FoodQuery"
    assert events[0]["result_count"] == 5
    assert events[0]["relaxed"] is False
    assert events[0]["execution_ms"] == 42

    # max_results should be stripped from logged params
    assert "max_results" not in events[0]["params"]
    assert events[0]["params"]["city"] == "Brooklyn"

    # Should also appear in the query log
    queries = get_query_log()
    assert len(queries) == 1
    assert queries[0]["template_name"] == "FoodQuery"


# -----------------------------------------------------------------------
# LOG CRISIS DETECTED
# -----------------------------------------------------------------------

def test_log_crisis_detected():
    """Crisis events should be logged and associated with the session."""
    clear_audit_log()
    log_crisis_detected(
        session_id="s1",
        crisis_category="suicide_self_harm",
        user_message_redacted="I want to [REDACTED]",
    )

    events = get_recent_events()
    assert len(events) == 1
    assert events[0]["type"] == "crisis_detected"
    assert events[0]["crisis_category"] == "suicide_self_harm"

    # Should be associated with the session
    conv = get_conversation("s1")
    assert len(conv) == 1


# -----------------------------------------------------------------------
# LOG SESSION RESET
# -----------------------------------------------------------------------

def test_log_session_reset():
    """Reset events should be logged."""
    clear_audit_log()
    log_session_reset("s1")

    events = get_recent_events()
    assert len(events) == 1
    assert events[0]["type"] == "session_reset"
    assert events[0]["session_id"] == "s1"


# -----------------------------------------------------------------------
# GET RECENT EVENTS
# -----------------------------------------------------------------------

def test_get_recent_events_limit():
    """Should respect the limit parameter."""
    clear_audit_log()
    for i in range(20):
        log_session_reset(f"s-{i}")

    assert len(get_recent_events(limit=5)) == 5
    assert len(get_recent_events(limit=100)) == 20


def test_get_recent_events_filter_by_type():
    """Should filter by event_type when provided."""
    clear_audit_log()
    log_session_reset("s1")
    log_crisis_detected("s1", "violence", "test")
    log_session_reset("s2")

    resets = get_recent_events(event_type="session_reset")
    assert len(resets) == 2
    assert all(e["type"] == "session_reset" for e in resets)

    crises = get_recent_events(event_type="crisis_detected")
    assert len(crises) == 1


def test_get_recent_events_returns_latest():
    """Should return the LATEST events, not the earliest."""
    clear_audit_log()
    for i in range(10):
        log_session_reset(f"s-{i}")

    result = get_recent_events(limit=3)
    assert len(result) == 3
    # The last 3 sessions logged were s-7, s-8, s-9
    session_ids = [e["session_id"] for e in result]
    assert "s-7" in session_ids
    assert "s-8" in session_ids
    assert "s-9" in session_ids


# -----------------------------------------------------------------------
# GET CONVERSATION
# -----------------------------------------------------------------------

def test_get_conversation_multiple_event_types():
    """Should return all event types for a session."""
    clear_audit_log()
    log_conversation_turn("s1", "food in Brooklyn", "searching...", {}, "service")
    log_query_execution("s1", "FoodQuery", {"city": "Brooklyn"}, 3, False, 50)
    log_crisis_detected("s1", "safety_concern", "I don't feel safe")
    log_session_reset("s1")

    # Also log a different session to make sure filtering works
    log_conversation_turn("s2", "shelter", "where?", {}, "service")

    conv = get_conversation("s1")
    assert len(conv) == 4
    types = [e["type"] for e in conv]
    assert "conversation_turn" in types
    assert "query_execution" in types
    assert "crisis_detected" in types
    assert "session_reset" in types


def test_get_conversation_nonexistent():
    """Should return empty list for unknown session."""
    clear_audit_log()
    assert get_conversation("nonexistent") == []


# -----------------------------------------------------------------------
# GET CONVERSATIONS SUMMARY
# -----------------------------------------------------------------------

def test_get_conversations_summary_basic():
    """Summary should aggregate turn count, services, categories."""
    clear_audit_log()
    _seed_conversation("sess-A", turns=3, service_type="food")
    _seed_conversation("sess-B", turns=1, service_type="shelter")

    summaries = get_conversations_summary()
    assert len(summaries) == 2

    # Find sess-A
    a = next(s for s in summaries if s["session_id"] == "sess-A")
    assert a["turn_count"] == 3
    assert a["services_delivered"] == 2  # last turn had services_count=2
    assert "service" in a["categories"]
    assert a["final_slots"]["service_type"] == "food"


def test_get_conversations_summary_crisis_flag():
    """Summary should flag sessions with crisis events."""
    clear_audit_log()
    log_conversation_turn("s1", "test", "test", {}, "service")
    log_crisis_detected("s1", "suicide_self_harm", "test")

    summaries = get_conversations_summary()
    assert len(summaries) == 1
    assert summaries[0]["crisis_detected"] is True


def test_get_conversations_summary_limit():
    """Should respect the limit parameter."""
    clear_audit_log()
    for i in range(10):
        log_conversation_turn(f"s-{i}", "test", "test", {}, "service")

    assert len(get_conversations_summary(limit=3)) == 3


def test_get_conversations_summary_sorted_by_recency():
    """Summaries should be sorted newest first."""
    clear_audit_log()
    log_conversation_turn("s-old", "old msg", "old resp", {}, "service")
    time.sleep(0.01)  # ensure different timestamps
    log_conversation_turn("s-new", "new msg", "new resp", {}, "service")

    summaries = get_conversations_summary()
    assert summaries[0]["session_id"] == "s-new"
    assert summaries[1]["session_id"] == "s-old"


def test_get_conversations_summary_categories_are_lists():
    """Categories should be JSON-serializable lists, not sets."""
    clear_audit_log()
    log_conversation_turn("s1", "hi", "hey", {}, "greeting")
    log_conversation_turn("s1", "food", "where?", {}, "service")

    summaries = get_conversations_summary()
    cats = summaries[0]["categories"]
    assert isinstance(cats, list), f"Expected list, got {type(cats)}"
    assert "greeting" in cats
    assert "service" in cats


# -----------------------------------------------------------------------
# GET QUERY LOG
# -----------------------------------------------------------------------

def test_get_query_log_only_queries():
    """Query log should only contain query_execution events."""
    clear_audit_log()
    log_conversation_turn("s1", "test", "test", {}, "service")
    log_query_execution("s1", "FoodQuery", {}, 5, False, 30)
    log_session_reset("s1")
    log_query_execution("s1", "ShelterQuery", {}, 2, True, 80)

    queries = get_query_log()
    assert len(queries) == 2
    assert all(q["type"] == "query_execution" for q in queries)
    assert queries[0]["template_name"] == "FoodQuery"
    assert queries[1]["template_name"] == "ShelterQuery"


def test_get_query_log_limit():
    """Query log should respect limit."""
    clear_audit_log()
    for i in range(10):
        log_query_execution("s1", f"Query{i}", {}, i, False, 10)

    assert len(get_query_log(limit=3)) == 3


# -----------------------------------------------------------------------
# GET STATS
# -----------------------------------------------------------------------

def test_get_stats_counts():
    """Stats should count each event type correctly."""
    clear_audit_log()
    log_conversation_turn("s1", "test", "test", {}, "service")
    log_conversation_turn("s1", "test2", "test2", {}, "service")
    log_query_execution("s1", "FoodQuery", {}, 3, False, 40)
    log_crisis_detected("s2", "violence", "test")
    log_session_reset("s3")
    log_conversation_turn("s2", "test", "test", {}, "greeting")

    stats = get_stats()
    assert stats["total_events"] == 6
    assert stats["total_turns"] == 3
    assert stats["total_queries"] == 1
    assert stats["total_crises"] == 1
    assert stats["total_resets"] == 1
    assert stats["unique_sessions"] == 3


def test_get_stats_category_distribution():
    """Stats should track category distribution."""
    clear_audit_log()
    log_conversation_turn("s1", "t", "t", {}, "service")
    log_conversation_turn("s1", "t", "t", {}, "service")
    log_conversation_turn("s2", "t", "t", {}, "greeting")

    stats = get_stats()
    assert stats["category_distribution"]["service"] == 2
    assert stats["category_distribution"]["greeting"] == 1


def test_get_stats_service_type_distribution():
    """Stats should track service type distribution from slot data."""
    clear_audit_log()
    log_conversation_turn("s1", "t", "t", {"service_type": "food"}, "service")
    log_conversation_turn("s1", "t", "t", {"service_type": "food"}, "service")
    log_conversation_turn("s2", "t", "t", {"service_type": "shelter"}, "service")

    stats = get_stats()
    assert stats["service_type_distribution"]["food"] == 2
    assert stats["service_type_distribution"]["shelter"] == 1


def test_get_stats_relaxed_query_rate():
    """Stats should compute relaxed query rate correctly."""
    clear_audit_log()
    log_query_execution("s1", "Q1", {}, 5, False, 30)
    log_query_execution("s1", "Q2", {}, 0, True, 60)
    log_query_execution("s1", "Q3", {}, 3, False, 20)
    log_query_execution("s1", "Q4", {}, 1, True, 90)

    stats = get_stats()
    # 2 relaxed out of 4 total = 0.5
    assert stats["relaxed_query_rate"] == 0.5


def test_get_stats_empty():
    """Stats on empty log should return zeros."""
    clear_audit_log()
    stats = get_stats()
    assert stats["total_events"] == 0
    assert stats["total_turns"] == 0
    assert stats["unique_sessions"] == 0
    assert stats["relaxed_query_rate"] == 0


# -----------------------------------------------------------------------
# EVAL RESULTS
# -----------------------------------------------------------------------

def test_eval_results_set_and_get():
    """Should store and retrieve eval results."""
    clear_audit_log()
    data = {"score": 0.85, "scenarios": [{"name": "test"}]}
    set_eval_results(data)

    result = get_eval_results()
    assert result == data


def test_eval_results_deep_copy():
    """Returned eval results should be a deep copy (no mutation leaks)."""
    clear_audit_log()
    data = {"scores": [1, 2, 3]}
    set_eval_results(data)

    result = get_eval_results()
    result["scores"].append(4)

    original = get_eval_results()
    assert len(original["scores"]) == 3, "Mutation should not leak"


def test_eval_results_none_when_not_set():
    """Should return None when no eval results are stored."""
    clear_audit_log()
    assert get_eval_results() is None


def test_load_eval_results_from_file():
    """Should load eval results from a JSON file."""
    clear_audit_log()
    data = {"test": True, "score": 0.9}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        tmp_path = f.name

    try:
        result = load_eval_results_from_file(tmp_path)
        assert result is True
        assert get_eval_results() == data
    finally:
        os.unlink(tmp_path)


def test_load_eval_results_missing_file():
    """Should return False for missing files without crashing."""
    clear_audit_log()
    result = load_eval_results_from_file("/nonexistent/path.json")
    assert result is False


# -----------------------------------------------------------------------
# CLEAR
# -----------------------------------------------------------------------

def test_clear_audit_log():
    """Clear should wipe everything."""
    log_conversation_turn("s1", "t", "t", {}, "service")
    log_query_execution("s1", "Q", {}, 1, False, 10)
    log_crisis_detected("s1", "test", "t")
    set_eval_results({"test": True})

    clear_audit_log()

    assert get_recent_events() == []
    assert get_query_log() == []
    assert get_conversation("s1") == []
    assert get_eval_results() is None
    stats = get_stats()
    assert stats["total_events"] == 0


# -----------------------------------------------------------------------
# RING BUFFER BEHAVIOR
# -----------------------------------------------------------------------

def test_ring_buffer_caps_events():
    """Events deque should not exceed MAX_EVENTS."""
    clear_audit_log()

    # Log more than MAX_EVENTS
    for i in range(MAX_EVENTS + 50):
        log_session_reset(f"s-{i}")

    events = get_recent_events(limit=MAX_EVENTS + 100)
    assert len(events) == MAX_EVENTS, \
        f"Expected {MAX_EVENTS} events, got {len(events)}"
    print(f"  PASS: ring buffer caps at {MAX_EVENTS}")


def test_ring_buffer_evicts_oldest():
    """Oldest events should be evicted when buffer is full."""
    clear_audit_log()

    for i in range(MAX_EVENTS + 10):
        log_session_reset(f"s-{i}")

    events = get_recent_events(limit=MAX_EVENTS)
    # The first 10 sessions should have been evicted
    session_ids = {e["session_id"] for e in events}
    assert "s-0" not in session_ids, "s-0 should have been evicted"
    assert "s-9" not in session_ids, "s-9 should have been evicted"
    assert f"s-{MAX_EVENTS + 9}" in session_ids, "Latest should be present"


def test_conversation_limit_eviction():
    """Should evict oldest conversations when MAX_CONVERSATIONS is exceeded."""
    clear_audit_log()

    for i in range(MAX_CONVERSATIONS + 10):
        log_conversation_turn(f"s-{i}", "t", "t", {}, "service")

    # The oldest conversations should have been evicted from the index
    # (the events are still in the ring buffer, but the conversation
    # index no longer tracks them)
    from app.services.audit_log import _conversations, _lock
    with _lock:
        assert len(_conversations) <= MAX_CONVERSATIONS
    print(f"  PASS: conversation index stays within {MAX_CONVERSATIONS}")


# -----------------------------------------------------------------------
# THREAD SAFETY
# -----------------------------------------------------------------------

def test_concurrent_logging():
    """Multiple threads logging simultaneously should not crash."""
    clear_audit_log()
    errors = []
    num_threads = 8
    ops = 50

    def log_turns(thread_id):
        try:
            for i in range(ops):
                log_conversation_turn(f"t{thread_id}", f"msg{i}", f"resp{i}", {}, "service")
        except Exception as e:
            errors.append(f"Turn logger {thread_id}: {e}")

    def log_queries(thread_id):
        try:
            for i in range(ops):
                log_query_execution(f"t{thread_id}", "Q", {}, i, False, 10)
        except Exception as e:
            errors.append(f"Query logger {thread_id}: {e}")

    def read_stats():
        try:
            for _ in range(ops):
                get_stats()
                get_recent_events(limit=10)
                get_conversations_summary(limit=5)
        except Exception as e:
            errors.append(f"Reader: {e}")

    threads = []
    for t in range(num_threads):
        threads.append(threading.Thread(target=log_turns, args=(t,)))
        threads.append(threading.Thread(target=log_queries, args=(t,)))
    threads.append(threading.Thread(target=read_stats))

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert len(errors) == 0, f"Thread safety errors: {errors}"
    print(f"  PASS: {len(threads)} concurrent threads, no errors")


# -----------------------------------------------------------------------
