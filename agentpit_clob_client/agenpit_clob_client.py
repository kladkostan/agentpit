from py_clob_client import ClobClient, OrderType

import logging
import plyvel

from py_clob_client.clob_types import PostOrdersArgs
from py_clob_client.utilities import order_to_json




class AgentPitClobClient:
    def __init__(
        self
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db = plyvel.DB('/tmp/x', create_if_missing=True)

    def post_order(self, order, orderType: OrderType, post_only: bool):
        serialized_body = order_to_json(order, self.creds.api_key, orderType, post_only)
        pass

    def post_orders(self, args: list[PostOrdersArgs]):
        pass
