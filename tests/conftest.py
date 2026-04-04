# Copyright (c) 2024 Streetlives, Inc.
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""
Shared test fixtures for the YourPeer chatbot test suite.

This file is automatically loaded by pytest before any test module.
It provides:
    - sys.path setup (so `from app.services.chatbot import ...` works)
    - Shared mock data fixtures (MOCK_QUERY_RESULTS, etc.)
    - Session management helpers

To run all tests:    pytest
To run one file:     pytest tests/test_chatbot.py
To run with print:   pytest -s
"""

import sys
import os

import pytest

# ---------------------------------------------------------------------------
# COLLECTION CONFIGURATION
# ---------------------------------------------------------------------------
# eval_llm_judge.py is not a unit test — it's an evaluation runner invoked
# separately via the admin panel or CLI. Exclude from pytest collection.

collect_ignore = ["eval_llm_judge.py"]


# ---------------------------------------------------------------------------
# PATH SETUP
# ---------------------------------------------------------------------------
# pyproject.toml sets pythonpath = ["backend"], but this ensures
# compatibility when running individual test files directly too.

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


# ---------------------------------------------------------------------------
# MOCK SERVICE DATA
# ---------------------------------------------------------------------------
# Shared across test_chatbot.py, test_chat_route.py, and any new test
# files that need a realistic query_services() return value.
# Update this in ONE place when the service card schema changes.


MOCK_SERVICE_CARD = {
    "service_name": "Test Food Pantry",
    "organization": "Test Org",
    "description": "Free meals every weekday",
    "address": "123 Test St, Brooklyn, NY 11201",
    "city": "Brooklyn",
    "phone": "212-555-0001",
    "email": "info@testpantry.org",
    "website": "https://testpantry.org",
    "fees": "Free",
    "additional_info": None,
    "yourpeer_url": "https://yourpeer.nyc/locations/test-food-pantry",
    "hours_today": "9:00 AM – 5:00 PM",
    "is_open": "open",
    "service_id": "svc-001",
    "requires_membership": False,
}

MOCK_QUERY_RESULTS = {
    "services": [MOCK_SERVICE_CARD],
    "result_count": 1,
    "template_used": "FoodQuery",
    "params_applied": {"taxonomy_name": "Food", "city": "Brooklyn"},
    "relaxed": False,
    "execution_ms": 50,
}

MOCK_EMPTY_RESULTS = {
    "services": [],
    "result_count": 0,
    "template_used": "FoodQuery",
    "params_applied": {},
    "relaxed": False,
    "execution_ms": 10,
}

MOCK_RELAXED_RESULTS = {
    "services": [MOCK_SERVICE_CARD],
    "result_count": 1,
    "template_used": "FoodQuery",
    "params_applied": {"taxonomy_name": "Food"},
    "relaxed": True,
    "execution_ms": 75,
}


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_service_card():
    """A single realistic service card dict."""
    return dict(MOCK_SERVICE_CARD)


@pytest.fixture
def mock_query_results():
    """A query_services() return value with one result."""
    return dict(MOCK_QUERY_RESULTS)


@pytest.fixture
def mock_empty_results():
    """A query_services() return value with zero results."""
    return dict(MOCK_EMPTY_RESULTS)


@pytest.fixture
def fresh_session():
    """Provide a unique session ID and clean it up after the test."""
    import uuid
    from app.services.session_store import clear_session

    sid = f"test-{uuid.uuid4().hex[:8]}"
    clear_session(sid)
    yield sid
    clear_session(sid)
