from dataclasses import dataclass

@dataclass
class Match:
    taker_order_id: str
    maker_order_id: str
    price: int
    trade_size: int
