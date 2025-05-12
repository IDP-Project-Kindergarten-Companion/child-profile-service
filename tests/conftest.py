# tests/conftest.py
import pytest
import os
import requests

@pytest.fixture(scope="session")
def auth_service_url():
    """Fixture for the Auth Service URL."""
    return os.environ.get("AUTH_SERVICE_URL", "http://localhost:8081") # Adjust port if needed

@pytest.fixture(scope="session")
def child_profile_url():
    """Fixture for the Child Profile Service URL."""
    # Adjust port based on your docker-compose mapping for child-profile-service
    return os.environ.get("CHILD_PROFILE_URL", "http://localhost:5002")

@pytest.fixture(scope="session")
def http_session():
    """Provides a requests session for making HTTP calls."""
    with requests.Session() as session:
        session.headers.update({"Content-Type": "application/json"})
        yield session

