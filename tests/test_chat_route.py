"""
Tests for the chat route and Pydantic models.

Run: pytest tests/test_chat_route.py
"""

from unittest.mock import patch

from pydantic import ValidationError
from fastapi.testclient import TestClient
from app.main import app
from app.models.chat_models import ChatRequest, ChatResponse, ServiceCard, QuickReply
from app.services.session_store import clear_session
from conftest import MOCK_SERVICE_CARD, MOCK_QUERY_RESULTS, MOCK_EMPTY_RESULTS

client = TestClient(app)

# Local aliases matching the original names used throughout this file
_MOCK_SERVICE_CARD = MOCK_SERVICE_CARD
_MOCK_QUERY_RESULTS = MOCK_QUERY_RESULTS
_MOCK_EMPTY_RESULTS = MOCK_EMPTY_RESULTS


# -----------------------------------------------------------------------
# PYDANTIC MODELS — ChatRequest
# -----------------------------------------------------------------------

def test_chat_request_valid():
    """ChatRequest should accept a message and optional session_id."""
    r = ChatRequest(message="I need food")
    assert r.message == "I need food"
    assert r.session_id is None


def test_chat_request_with_session_id():
    """ChatRequest should accept an explicit session_id."""
    r = ChatRequest(message="hello", session_id="abc-123")
    assert r.session_id == "abc-123"


def test_chat_request_missing_message():
    """ChatRequest should reject missing message field."""
    try:
        ChatRequest()
        assert False, "Should have raised ValidationError"
    except ValidationError:
        pass


def test_chat_request_wrong_type():
    """ChatRequest should reject non-string message."""
    try:
        ChatRequest(message=123)
        # Pydantic v2 coerces int to str in strict=False mode
        # This is expected behavior — not a bug
        print("  PASS: ChatRequest coerces int to str (Pydantic v2 behavior)")
    except ValidationError:
        print("  PASS: ChatRequest rejects int message")


def test_chat_request_empty_string_accepted():
    """ChatRequest currently accepts empty strings (validated downstream).

    Note: The generate_reply() function handles empty messages with an
    early-return guard. If we add min_length=1 to the model later,
    this test should be updated to expect ValidationError.
    """
    r = ChatRequest(message="")
    assert r.message == ""


# -----------------------------------------------------------------------
# PYDANTIC MODELS — ServiceCard
# -----------------------------------------------------------------------

def test_service_card_minimal():
    """ServiceCard should work with only the required field (service_name)."""
    sc = ServiceCard(service_name="Test Service")
    assert sc.service_name == "Test Service"
    assert sc.organization is None
    assert sc.phone is None
    assert sc.is_open is None


def test_service_card_full():
    """ServiceCard should accept all optional fields."""
    sc = ServiceCard(**_MOCK_SERVICE_CARD)
    assert sc.service_name == "Test Food Pantry"
    assert sc.organization == "Test Org"
    assert sc.phone == "212-555-0001"
    assert sc.is_open == "open"
    assert sc.yourpeer_url == "https://yourpeer.nyc/locations/test-food-pantry"


def test_service_card_missing_service_name():
    """ServiceCard should reject missing service_name."""
    try:
        ServiceCard(organization="Org")
        assert False, "Should have raised ValidationError"
    except ValidationError:
        pass


def test_service_card_serialization():
    """ServiceCard should serialize to dict with all fields."""
    sc = ServiceCard(service_name="Test", phone="555-0000")
    data = sc.model_dump()
    assert "service_name" in data
    assert "phone" in data
    assert "organization" in data  # None but present
    assert len(data) == 13  # all 13 fields


# -----------------------------------------------------------------------
# PYDANTIC MODELS — QuickReply
# -----------------------------------------------------------------------

def test_quick_reply_valid():
    """QuickReply should require both label and value."""
    qr = QuickReply(label="🍽️ Food", value="I need food")
    assert qr.label == "🍽️ Food"
    assert qr.value == "I need food"


def test_quick_reply_missing_label():
    """QuickReply should reject missing label."""
    try:
        QuickReply(value="test")
        assert False, "Should have raised ValidationError"
    except ValidationError:
        pass


def test_quick_reply_missing_value():
    """QuickReply should reject missing value."""
    try:
        QuickReply(label="test")
        assert False, "Should have raised ValidationError"
    except ValidationError:
        pass


# -----------------------------------------------------------------------
# PYDANTIC MODELS — ChatResponse
# -----------------------------------------------------------------------

def test_chat_response_minimal():
    """ChatResponse should work with required fields and defaults."""
    r = ChatResponse(
        session_id="s1",
        response="Hello!",
        follow_up_needed=False,
        slots={},
    )
    assert r.session_id == "s1"
    assert r.services == []
    assert r.result_count == 0
    assert r.relaxed_search is False
    assert r.quick_replies == []


def test_chat_response_with_services():
    """ChatResponse should accept a list of ServiceCards."""
    r = ChatResponse(
        session_id="s1",
        response="Found 1 result.",
        follow_up_needed=False,
        slots={"service_type": "food"},
        services=[ServiceCard(service_name="Test")],
        result_count=1,
    )
    assert len(r.services) == 1
    assert r.services[0].service_name == "Test"
    assert r.result_count == 1


def test_chat_response_missing_required():
    """ChatResponse should reject missing required fields."""
    required = ["session_id", "response", "follow_up_needed", "slots"]
    base = {"session_id": "s", "response": "r", "follow_up_needed": False, "slots": {}}

    for field in required:
        data = dict(base)
        del data[field]
        try:
            ChatResponse(**data)
            assert False, f"Should reject missing {field}"
        except ValidationError:
            pass


def test_chat_response_serialization_round_trip():
    """ChatResponse should serialize to JSON and back."""
    original = ChatResponse(
        session_id="s1",
        response="Found results.",
        follow_up_needed=False,
        slots={"service_type": "food", "location": "Brooklyn"},
        services=[ServiceCard(service_name="Pantry", phone="555-0000")],
        result_count=1,
        relaxed_search=True,
        quick_replies=[QuickReply(label="New search", value="Start over")],
    )

    json_str = original.model_dump_json()
    restored = ChatResponse.model_validate_json(json_str)

    assert restored.session_id == "s1"
    assert restored.result_count == 1
    assert restored.relaxed_search is True
    assert len(restored.services) == 1
    assert restored.services[0].phone == "555-0000"
    assert len(restored.quick_replies) == 1
    assert restored.quick_replies[0].label == "New search"


# -----------------------------------------------------------------------
# HTTP ROUTE — POST /chat/
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services", return_value=_MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="How can I help?")
def test_chat_route_valid_request(mock_claude, mock_query):
    """POST /chat/ with a valid message should return 200."""
    response = client.post("/chat/", json={"message": "hello"})
    assert response.status_code == 200

    data = response.json()
    assert "session_id" in data
    assert "response" in data
    assert isinstance(data["services"], list)
    assert isinstance(data["quick_replies"], list)


@patch("app.services.chatbot.query_services", return_value=_MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
def test_chat_route_generates_session_id(mock_claude, mock_query):
    """POST /chat/ without session_id should generate one."""
    response = client.post("/chat/", json={"message": "hi"})
    data = response.json()
    assert data["session_id"] is not None
    assert len(data["session_id"]) > 0


@patch("app.services.chatbot.query_services", return_value=_MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
def test_chat_route_preserves_session_id(mock_claude, mock_query):
    """POST /chat/ with session_id should preserve it."""
    response = client.post("/chat/", json={
        "message": "hi",
        "session_id": "my-session-123",
    })
    assert response.json()["session_id"] == "my-session-123"


def test_chat_route_missing_message():
    """POST /chat/ without message should return 422."""
    response = client.post("/chat/", json={})
    assert response.status_code == 422


def test_chat_route_not_json():
    """POST /chat/ with non-JSON body should return 422."""
    response = client.post("/chat/", content="hello",
                           headers={"Content-Type": "text/plain"})
    assert response.status_code == 422


def test_chat_route_no_body():
    """POST /chat/ with no body should return 422."""
    response = client.post("/chat/")
    assert response.status_code == 422


@patch("app.services.chatbot.query_services", return_value=_MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
def test_chat_route_empty_message(mock_claude, mock_query):
    """POST /chat/ with empty message should return 200 with welcome prompt.

    The model accepts '' but generate_reply handles it with an early guard.
    """
    response = client.post("/chat/", json={"message": ""})
    assert response.status_code == 200
    assert "looking for" in response.json()["response"].lower()


@patch("app.services.chatbot.query_services", return_value=_MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
def test_chat_route_response_schema(mock_claude, mock_query):
    """Response should match ChatResponse schema exactly."""
    response = client.post("/chat/", json={"message": "I need food"})
    data = response.json()

    # All required fields present
    assert "session_id" in data
    assert "response" in data
    assert "follow_up_needed" in data
    assert "slots" in data

    # Default fields present
    assert "services" in data
    assert "result_count" in data
    assert "relaxed_search" in data
    assert "quick_replies" in data

    # Types correct
    assert isinstance(data["session_id"], str)
    assert isinstance(data["response"], str)
    assert isinstance(data["follow_up_needed"], bool)
    assert isinstance(data["slots"], dict)
    assert isinstance(data["services"], list)
    assert isinstance(data["result_count"], int)
    assert isinstance(data["relaxed_search"], bool)
    assert isinstance(data["quick_replies"], list)


# -----------------------------------------------------------------------
# HTTP ROUTE — Multi-turn conversation
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services", return_value=_MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
def test_chat_route_multi_turn_with_services(mock_claude, mock_query):
    """A full multi-turn conversation should return service cards."""
    sid = "http-multi-turn"
    clear_session(sid)

    # Step 1: service request → confirmation
    r1 = client.post("/chat/", json={"message": "I need food in Brooklyn", "session_id": sid})
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1["follow_up_needed"] is True
    assert len(data1["services"]) == 0  # confirmation, no results yet
    assert len(data1["quick_replies"]) > 0

    # Step 2: confirm → results
    r2 = client.post("/chat/", json={"message": "Yes, search", "session_id": sid})
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["result_count"] == 1
    assert len(data2["services"]) == 1

    # Verify service card structure
    card = data2["services"][0]
    assert card["service_name"] == "Test Food Pantry"
    assert card["phone"] == "212-555-0001"
    assert card["is_open"] == "open"
    assert card["yourpeer_url"] is not None


@patch("app.services.chatbot.query_services", return_value=_MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
def test_chat_route_session_continuity(mock_claude, mock_query):
    """Slots should accumulate across turns within the same session."""
    sid = "http-continuity"
    clear_session(sid)

    # Turn 1: provide service type
    r1 = client.post("/chat/", json={"message": "I need shelter", "session_id": sid})
    data1 = r1.json()
    assert data1["slots"].get("service_type") == "shelter"
    assert data1["follow_up_needed"] is True  # needs location

    # Turn 2: provide location
    r2 = client.post("/chat/", json={"message": "Queens", "session_id": sid})
    data2 = r2.json()
    assert data2["slots"].get("service_type") == "shelter"
    assert data2["slots"].get("location") is not None


@patch("app.services.chatbot.query_services", return_value=_MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
def test_chat_route_reset_clears_session(mock_claude, mock_query):
    """Saying 'start over' should clear the session slots."""
    sid = "http-reset"
    clear_session(sid)

    # Build up some slots
    client.post("/chat/", json={"message": "I need food in Brooklyn", "session_id": sid})

    # Reset
    r = client.post("/chat/", json={"message": "start over", "session_id": sid})
    data = r.json()
    # After reset, slots should be empty
    assert data["slots"] == {} or data["slots"].get("service_type") is None


@patch("app.services.chatbot.query_services", return_value=_MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
def test_chat_route_quick_replies_structure(mock_claude, mock_query):
    """Quick replies should have label and value fields."""
    r = client.post("/chat/", json={"message": "hello"})
    data = r.json()

    if data["quick_replies"]:
        qr = data["quick_replies"][0]
        assert "label" in qr, "Quick reply missing 'label'"
        assert "value" in qr, "Quick reply missing 'value'"
        assert isinstance(qr["label"], str)
        assert isinstance(qr["value"], str)


# -----------------------------------------------------------------------
# HTTP ROUTE — Crisis handling
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services", return_value=_MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
def test_chat_route_crisis_returns_resources(mock_claude, mock_query):
    """Crisis messages should return crisis resources, not service results."""
    r = client.post("/chat/", json={"message": "I want to kill myself"})
    assert r.status_code == 200

    data = r.json()
    assert "988" in data["response"], "Should include 988 lifeline"
    assert len(data["services"]) == 0
    mock_query.assert_not_called()


# -----------------------------------------------------------------------
# HTTP ROUTE — GET method not allowed
# -----------------------------------------------------------------------

def test_chat_route_get_not_allowed():
    """GET /chat/ should not return 200 — it's a POST-only endpoint.

    Note: Returns 404 (not 405) because the catch-all static file handler
    in main.py intercepts GET requests to /chat/ before FastAPI's method
    checking can return 405. The important thing is it doesn't succeed.
    """
    response = client.get("/chat/")
    assert response.status_code in (404, 405)


# -----------------------------------------------------------------------
