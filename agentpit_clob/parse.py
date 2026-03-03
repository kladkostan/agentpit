"""Small parsing helpers used across the server implementation."""

from __future__ import annotations

from typing import cast

from eth_typing import HexStr
from web3 import Web3


def parse_32b_hex_private_key(value: object) -> bytes | None:
    """Parse a 32-byte hex-encoded private key.

    Accepts strings with or without a 0x prefix. Returns the raw 32 bytes if valid,
    otherwise returns None.
    """

    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if not s.startswith(("0x", "0X")):
        s = "0x" + s
    try:
        b = Web3.to_bytes(hexstr=cast(HexStr, s))
    except (TypeError, ValueError):
        return None
    return b if len(b) == 32 else None


def normalize_eth_address(addr: str) -> str | None:
    if not isinstance(addr, str):
        return None
    a = addr.strip().lower()
    if not a:
        return None
    if not a.startswith("0x"):
        a = "0x" + a
    # Strict: 20-byte address => 40 hex chars after 0x
    if len(a) != 42:
        return None
    try:
        int(a[2:], 16)
    except ValueError:
        return None
    return a


def hex_u256_to_int(value: object) -> int:
    if not isinstance(value, str):
        raise TypeError(f"Expected hex string, got {type(value)}")
    s = value.strip().lower()
    if not s:
        raise ValueError("Empty hex string")
    if not s.startswith("0x"):
        s = "0x" + s
    n = int(s, 16)
    if n < 0 or n >= (1 << 256):
        raise ValueError("Value out of u256 range")
    return n
