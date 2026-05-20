"""Thin REST wrapper over the AgentPit API.

The runner instantiates one of these and shares it across bots — auth
tokens are per-bot and passed per-call rather than stored on the client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class _ResponseLike(Protocol):
    status_code: int
    text: str

    def json(self) -> Any: ...


class _SessionLike(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _ResponseLike: ...


@dataclass(frozen=True)
class BotCredentials:
    token: str
    eth_address: str


class AgentpitClient:
    def __init__(
        self,
        *,
        base_url: str,
        session: _SessionLike,
        admin_token: str = "",
        timeout: float = 15.0,
    ):
        self._base = base_url.rstrip("/")
        self._session = session
        self._admin_token = admin_token
        self._timeout = timeout

    # --- auth -----------------------------------------------------------

    def register(self, *, email: str, password: str) -> BotCredentials:
        body = self._post("/register", body={"email": email, "password": password})
        return BotCredentials(
            token=body["access_token"],
            eth_address=body["user"]["eth_address"],
        )

    # --- orders ---------------------------------------------------------

    def place_order(
        self,
        *,
        token: str,
        market_id: int,
        outcome: str,
        side: str,
        price: str,
        size: int,
    ) -> dict[str, Any]:
        return self._post(
            "/orders",
            body={
                "market_id": market_id,
                "outcome": outcome,
                "side": side,
                "price": price,
                "size": size,
                "order_type": "GTC",
                "expiration": 0,
            },
            token=token,
        )

    def list_my_orders(self, *, token: str) -> list[dict[str, Any]]:
        return self._get("/orders/mine", token=token)["orders"]

    def cancel_order(self, *, token: str, order_id: str) -> dict[str, Any]:
        return self._delete(f"/orders/{order_id}", token=token)

    def get_orderbook(self, *, market_id: int, outcome: str) -> dict[str, Any]:
        return self._get(f"/orderbook/{market_id}/{outcome}")

    # --- markets --------------------------------------------------------

    def get_markets(self) -> list[dict[str, Any]]:
        # /markets returns ListMarketsResponse: {"markets": [...]}
        return self._get("/markets")["markets"]

    def get_portfolio(
        self, *, token: str, market_id: int | None = None
    ) -> dict[str, Any]:
        path = "/portfolio"
        if market_id is not None:
            path += f"?market_id={market_id}"
        return self._get(path, token=token)

    def split_position(
        self, *, token: str, market_id: int, amount: int
    ) -> dict[str, Any]:
        return self._post(
            f"/markets/{market_id}/split_position",
            body={"amount": amount},
            token=token,
        )

    def merge_positions(
        self, *, token: str, market_id: int, amount: int
    ) -> dict[str, Any]:
        return self._post(
            f"/markets/{market_id}/merge_positions",
            body={"amount": amount},
            token=token,
        )

    # --- admin ----------------------------------------------------------

    def mark_bot(self, *, eth_address: str) -> dict[str, Any]:
        if not self._admin_token:
            raise RuntimeError("AgentpitClient: admin_token not configured")
        return self._post(
            "/admin/mark_bot",
            body={"eth_address": eth_address},
            extra_headers={"X-Admin-Token": self._admin_token},
        )

    # --- low-level ------------------------------------------------------

    def _post(self, path, *, body=None, token=None, extra_headers=None):
        return self._call(
            "POST", path, body=body, token=token, extra_headers=extra_headers
        )

    def _get(self, path, *, token=None):
        return self._call("GET", path, token=token)

    def _delete(self, path, *, token=None):
        return self._call("DELETE", path, token=token)

    def _call(self, method, path, *, body=None, token=None, extra_headers=None):
        headers: dict[str, str] = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if extra_headers:
            headers.update(extra_headers)
        resp = self._session.request(
            method,
            self._base + path,
            json=body,
            headers=headers,
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"{method} {path} → HTTP {resp.status_code}: {resp.text}"
            )
        return resp.json()
