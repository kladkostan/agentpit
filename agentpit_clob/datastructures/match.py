from dataclasses import dataclass

@dataclass(slots=True, init=False)
class Match:
    taker_order_id: str
    maker_order_id: str
    price: int
    trade_size: int

    def __init__(
        self,
        taker_order_id: str,
        maker_order_id: str,
        price: int,
        trade_size: int,
    ) -> None:
        if not isinstance(taker_order_id, str) or not taker_order_id:
            raise ValueError("taker_order_id must be a non-empty string")
        if not isinstance(maker_order_id, str) or not maker_order_id:
            raise ValueError("maker_order_id must be a non-empty string")
        if not isinstance(price, int) or price < 0:
            raise ValueError("price must be a non-negative int")
        if not isinstance(trade_size, int) or trade_size < 0:
            raise ValueError("trade_size must be a non-negative int")
        self.taker_order_id = taker_order_id
        self.maker_order_id = maker_order_id
        self.price = price
        self.trade_size = trade_size
