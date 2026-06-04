import sqlite3

from agentpit.datastructures.market_state import MarketState
from agentpit.datastructures.position_wire import PositionWire
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.onchain.admin import OnchainAdmin
from agentpit.polymarket.format import price_to_float, size_to_float


class AccountService:
    """Public-by-address account reads (positions / value / activity)."""

    def __init__(self, db: DbSession, onchain: OnchainAdmin):
        self._db = db
        self._onchain = onchain

    def list_positions(
        self, eth_address: str, market: list[str] | None = None
    ) -> list[PositionWire]:
        with self._db.read() as conn:
            user = TableRead.get_user_by_eth_address(conn, eth_address)
            if user is None:
                return []
            markets, _ = TableRead.list_markets(conn, limit=10000)
        out: list[PositionWire] = []
        for mkt in markets:
            if market and mkt.condition_id.value not in market:
                continue
            tokens = mkt.erc1155_tokens
            for idx, (token_id, label) in enumerate(tokens):
                bal = self._onchain.ctf_balance(eth_address, int(token_id))
                if bal <= 0:
                    continue
                size = bal / 1_000_000
                with self._db.read() as conn:
                    avg_price = self._avg_fill_price(conn, user.api_key, token_id)
                    cur_price = self._cur_price(conn, token_id)
                initial_value = avg_price * size
                current_value = cur_price * size
                cash_pnl = current_value - initial_value
                pct_pnl = (cash_pnl / initial_value * 100) if initial_value else 0.0
                opp_idx = 1 - idx if len(tokens) == 2 else idx
                opp_token, opp_label = (
                    tokens[opp_idx] if len(tokens) == 2 else (token_id, label)
                )
                redeemable = (
                    mkt.market_state == MarketState.RESOLVED
                    and mkt.resolved_outcome == idx
                )
                out.append(
                    PositionWire(
                        proxyWallet=eth_address,
                        asset=token_id,
                        conditionId=mkt.condition_id.value,
                        size=size,
                        avgPrice=avg_price,
                        initialValue=initial_value,
                        currentValue=current_value,
                        cashPnl=cash_pnl,
                        percentPnl=pct_pnl,
                        totalBought=initial_value,
                        curPrice=cur_price,
                        redeemable=redeemable,
                        title=mkt.question,
                        slug=mkt.slug or "",
                        icon=mkt.icon_url or "",
                        outcome=label,
                        outcomeIndex=idx,
                        oppositeOutcome=opp_label,
                        oppositeAsset=opp_token,
                        endDate=str(mkt.end_date) if mkt.end_date else "",
                    )
                )
        return out

    def total_value(self, eth_address: str) -> list[dict]:
        positions = self.list_positions(eth_address)
        total = sum(p.currentValue for p in positions)
        return [{"user": eth_address, "value": total}]

    # --- helpers --------------------------------------------------------

    @staticmethod
    def _avg_fill_price(conn: sqlite3.Connection, api_key: str, token_id: str) -> float:
        """Size-weighted average price of the user's fills on this asset
        (taker or maker), in dollars; 0.0 if none."""
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT PRICE, TRADE_SIZE FROM trades "
            "WHERE ASSET_ID = ? AND STATUS != 'FAILED' "
            "AND (TAKER_API_KEY = ? OR MAKER_API_KEY = ?)",
            (token_id, api_key, api_key),
        ).fetchall()
        num = sum(int(r["PRICE"]) * int(r["TRADE_SIZE"]) for r in rows)
        den = sum(int(r["TRADE_SIZE"]) for r in rows)
        return price_to_float(num // den) if den else 0.0

    @staticmethod
    def _cur_price(conn: sqlite3.Connection, token_id: str) -> float:
        """Book midpoint in dollars; fall back to last trade, else 0.5."""
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT SIDE, PRICE FROM orders WHERE TOKEN_ID = ? AND STATUS = 'live'",
            (token_id,),
        ).fetchall()
        bids = [int(r["PRICE"]) for r in rows if r["SIDE"] == "BUY"]
        asks = [int(r["PRICE"]) for r in rows if r["SIDE"] == "SELL"]
        if bids and asks:
            return price_to_float((max(bids) + min(asks)) // 2)
        last = conn.execute(
            "SELECT PRICE FROM trades WHERE ASSET_ID = ? AND STATUS != 'FAILED' "
            "ORDER BY MATCH_TIME DESC LIMIT 1",
            (token_id,),
        ).fetchone()
        return price_to_float(int(last["PRICE"])) if last else 0.5
