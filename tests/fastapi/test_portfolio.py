from fastapi.testclient import TestClient
import pytest
import secrets

from agentpit.fastapi import main
from agentpit.fastapi.agentpit_server import AgentPitServer


@pytest.fixture
def client():
    """Fixture to create a test client with an in-memory database."""
    db_path = ":memory:"
    server = AgentPitServer(db_path=db_path)
    with TestClient(server) as test_client:
        yield test_client
    server.shutdown()


@pytest.fixture
def api_key():
    """Fixture to generate a random API key."""
    return secrets.token_hex(16)


def test_get_portfolio_new_user(client: TestClient, api_key: str):
    """Test that a new user has an empty portfolio."""
    response = client.get(f"/portfolio/{api_key}")
    assert response.status_code == 200
    portfolio = response.json()
    assert portfolio["usdc_balance"] == 0
    assert portfolio["positions"] == []
    assert "eth_address" in portfolio


def test_get_portfolio_with_usdc(client: TestClient, api_key: str):
    """Test portfolio after minting USDC."""
    # Mint some USDC
    mint_payload = {"api_key": api_key, "amount": 500}
    client.post("/mint_usdc", json=mint_payload)

    # Get portfolio
    response = client.get(f"/portfolio/{api_key}")
    assert response.status_code == 200
    portfolio = response.json()
    assert portfolio["usdc_balance"] == 500
    assert portfolio["positions"] == []


def test_get_portfolio_after_split(client: TestClient, api_key: str):
    """Test portfolio after splitting a position."""
    # Mint USDC
    client.post("/mint_usdc", json={"api_key": api_key, "amount": 100})

    # Create a market
    market_payload = {
        "question": "Will it rain tomorrow?",
        "description": "A market about tomorrow's weather.",
        "erc1155_tokens": [["0x1", "Yes"], ["0x2", "No"]],
    }
    market_response = client.post("/markets", json=market_payload)
    market_id = market_response.json()["market_id"]

    # Split position
    split_payload = {"api_key": api_key, "amount": 20}
    client.post(f"/markets/{market_id}/split_position", json=split_payload)

    # Get portfolio
    response = client.get(f"/portfolio/{api_key}")
    assert response.status_code == 200
    portfolio = response.json()

    assert portfolio["usdc_balance"] == 80  # 100 - 20
    assert len(portfolio["positions"]) == 2

    # Sort positions by token_id to have a deterministic order for assertions
    positions = sorted(portfolio["positions"], key=lambda p: p["token_id"])

    assert positions[0]["market_id"] == market_id
    assert positions[0]["question"] == "Will it rain tomorrow?"
    assert positions[0]["token_id"] == "0x1"
    assert positions[0]["outcome_label"] == "Yes"
    assert positions[0]["outcome_index"] == 0
    assert positions[0]["balance"] == 20

    assert positions[1]["market_id"] == market_id
    assert positions[1]["token_id"] == "0x2"
    assert positions[1]["outcome_label"] == "No"
    assert positions[1]["outcome_index"] == 1
    assert positions[1]["balance"] == 20


def test_get_portfolio_after_merge(client: TestClient, api_key: str):
    """Test portfolio after merging a position."""
    # Setup: Mint USDC and split a position
    client.post("/mint_usdc", json={"api_key": api_key, "amount": 100})
    market_payload = {"question": "Q1?", "erc1155_tokens": [["0x1", "A"], ["0x2", "B"]]}
    market_response = client.post("/markets", json=market_payload)
    market_id = market_response.json()["market_id"]
    client.post(f"/markets/{market_id}/split_position", json={"api_key": api_key, "amount": 50})

    # Merge some of the position back
    merge_payload = {"api_key": api_key, "amount": 10}
    client.post(f"/markets/{market_id}/merge_positions", json=merge_payload)

    # Get portfolio
    response = client.get(f"/portfolio/{api_key}")
    assert response.status_code == 200
    portfolio = response.json()

    assert portfolio["usdc_balance"] == 60  # 100 - 50 + 10
    assert len(portfolio["positions"]) == 2
    positions = sorted(portfolio["positions"], key=lambda p: p["token_id"])
    assert positions[0]["balance"] == 40  # 50 - 10
    assert positions[1]["balance"] == 40  # 50 - 10


def test_get_portfolio_after_redeem(client: TestClient, api_key: str):
    """Test portfolio after redeeming a winning position."""
    # Setup: Mint USDC, split, resolve market
    client.post("/mint_usdc", json={"api_key": api_key, "amount": 100})
    market_payload = {"question": "Q1?", "erc1155_tokens": [["0x1", "Win"], ["0x2", "Lose"]]}
    market_response = client.post("/markets", json=market_payload)
    market_id = market_response.json()["market_id"]
    client.post(f"/markets/{market_id}/split_position", json={"api_key": api_key, "amount": 30})
    client.post(f"/markets/{market_id}/resolve", json={"winning_outcome_index": 0})

    # Redeem position
    client.post(f"/markets/{market_id}/redeem_position", json={"api_key": api_key})

    # Get portfolio
    response = client.get(f"/portfolio/{api_key}")
    assert response.status_code == 200
    portfolio = response.json()

    # Initial: 100 USDC. Split: 100-30=70. Redeem: 70 + 30 (winning tokens) = 100
    assert portfolio["usdc_balance"] == 100
    # Positions should be gone after redemption
    assert portfolio["positions"] == []


def test_get_portfolio_multiple_markets(client: TestClient, api_key: str):
    """Test portfolio with positions in multiple markets."""
    client.post("/mint_usdc", json={"api_key": api_key, "amount": 100})

    # Market 1
    market1_payload = {"question": "Q1", "erc1155_tokens": [["0x1", "A"], ["0x2", "B"]]}
    market1_resp = client.post("/markets", json=market1_payload)
    market1_id = market1_resp.json()["market_id"]
    client.post(f"/markets/{market1_id}/split_position", json={"api_key": api_key, "amount": 10})

    # Market 2
    market2_payload = {"question": "Q2", "erc1155_tokens": [["0x3", "C"], ["0x4", "D"]]}
    market2_resp = client.post("/markets", json=market2_payload)
    market2_id = market2_resp.json()["market_id"]
    client.post(f"/markets/{market2_id}/split_position", json={"api_key": api_key, "amount": 20})

    # Get portfolio
    response = client.get(f"/portfolio/{api_key}")
    assert response.status_code == 200
    portfolio = response.json()

    assert portfolio["usdc_balance"] == 70  # 100 - 10 - 20
    assert len(portfolio["positions"]) == 4

    positions = sorted(portfolio["positions"], key=lambda p: p["market_id"])

    market1_positions = [p for p in positions if p["market_id"] == market1_id]
    market2_positions = [p for p in positions if p["market_id"] == market2_id]

    assert len(market1_positions) == 2
    assert market1_positions[0]["balance"] == 10
    assert market1_positions[1]["balance"] == 10

    assert len(market2_positions) == 2
    assert market2_positions[0]["balance"] == 20
    assert market2_positions[1]["balance"] == 20
