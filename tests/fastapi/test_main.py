"""
Main test file - imports all tests from submodules for backward compatibility.
This allows running all tests with: pytest tests/fastapi/test_main.py
"""

import pytest

# Import all test functions from submodules
from .test_basic import *
from .test_markets import *
from .test_usdc import *
from .test_positions import *
from .test_resolution import *
from .test_lifecycle import *


def test_all():
    """
    This function is a placeholder to confirm that all imported tests are being run.
    Pytest discovers and runs all functions starting with 'test_'.
    By running this file, all imported tests will be executed.
    """
    print("Running all tests...")
    assert True


if __name__ == "__main__":
    # This allows running all tests by executing this file directly
    # pytest will discover and run all tests in this file and imported ones
    pytest.main([__file__])
