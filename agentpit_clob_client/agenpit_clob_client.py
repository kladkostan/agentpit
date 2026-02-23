from py_clob_client import ClobClient, OrderType

import logging
import json
import time
from typing import Optional

from py_builder_signing_sdk.config import BuilderConfig

from py_clob_client.clob_types import PostOrdersArgs


class AgentPitClobClient:
    def __init__(
        self
    ):
        self.logger = logging.getLogger(self.__class__.__name__)


    def post_order(self, order, orderType: OrderType, post_only: bool):
        pass

    def post_orders(self, args: list[PostOrdersArgs]):
        pass




