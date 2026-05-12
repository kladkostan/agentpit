"""Shared helpers for the live-anvil test suite.

Each test creates its own app + clients so it's isolated from the singleton
app built by tests/conftest.py with on-chain disabled.
"""
import secrets
import uuid

from fastapi.testclient import TestClient

from agentpit.api.app import create_app


def fresh_client() -> TestClient:
    return TestClient(create_app())


def hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def unique_email() -> str:
    return f"e2e-{uuid.uuid4().hex[:10]}@example.com"


def unique_question() -> str:
    return f"Test market {secrets.token_hex(4)}?"


def register(client: TestClient, email: str | None = None) -> dict:
    return client.post(
        "/register",
        json={"email": email or unique_email(), "password": "hunter22hunter22"},
    ).json()


def create_market(client: TestClient, question: str | None = None) -> dict:
    return client.post(
        "/markets",
        json={
            "question": question or unique_question(),
            "description": "test",
            "outcome_labels": ["YES", "NO"],
        },
    ).json()
