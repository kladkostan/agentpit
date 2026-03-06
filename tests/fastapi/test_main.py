"""
Main test file - imports all tests from submodules for backward compatibility.
This allows running all tests with: pytest tests/fastapi/test_main.py
"""

import pytest

# Import all test functions from submodules
from .test_basic import *
from .test_markets import *

from .test_basic import *
from .test_history import *
from .test_lifecycle import *
from .test_markets import *
from .test_polymarket_sync import *
from .test_portfolio import *
from .test_positions import *
from .test_resolution import *
from .test_usdc import *


if __name__ == "__main__":
    # This allows running all tests by executing this file directly
    # pytest will discover and run all tests in this file and imported ones
    pytest.main([__file__])
