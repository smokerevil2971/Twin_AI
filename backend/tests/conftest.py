import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from fastapi.testclient import TestClient
from main import app
from core.config import settings

@pytest.fixture
def client():
    # Force settings for tests if needed
    # We will let the test modify settings using monkeypatch or just directly
    return TestClient(app)
