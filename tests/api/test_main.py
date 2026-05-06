"""
Main test file - imports all tests from submodules for backward compatibility.
This allows running all tests with: pytest tests/fastapi/test_main.py
"""

# Import all test functions from submodules

from .test_portfolio import *

if __name__ == "__main__":
    # This allows running all tests by executing this file directly
    # pytest will discover and run all tests in this file and imported ones
    pytest.main([__file__])
