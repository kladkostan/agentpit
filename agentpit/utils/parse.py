"""Small parsing helpers used across the server implementation."""

from __future__ import annotations

from typing import cast

from eth_typing import HexStr
from web3 import Web3


def parse_32b_hex_private_key(value: object) -> bytes:
    """Parse a 32-byte hex-encoded private key.

    Accepts strings with or without a 0x prefix.
    Returns the raw 32 bytes if valid, otherwise raises.
    """
    if not isinstance(value, str):
        raise TypeError(f"Expected hex string for private key, got {type(value)}")
    s = value.strip()
    if not s:
        raise ValueError("Empty private key string")
    if not s.startswith(("0x", "0X")):
        s = "0x" + s
    try:
        b = Web3.to_bytes(hexstr=cast(HexStr, s))
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid hex private key: {value!r}") from e
    if len(b) != 32:
        raise ValueError(f"Private key must be 32 bytes, got {len(b)} bytes")
    return b


def normalize_eth_address(addr: str) -> str:
    if not isinstance(addr, str):
        raise TypeError(f"Expected string for ETH address, got {type(addr)}")
    a = addr.strip().lower()
    if not a:
        raise ValueError("Empty ETH address string")
    if not a.startswith("0x"):
        a = "0x" + a
    # Strict: 20-byte address => 40 hex chars after 0x
    if len(a) != 42:
        raise ValueError(f"ETH address must be 42 chars including 0x, got {len(a)}")
    try:
        int(a[2:], 16)
    except ValueError as e:
        raise ValueError(f"ETH address contains non-hex characters: {addr!r}") from e
    return a


def hex_u256_to_int(value: object) -> int:
    if not isinstance(value, str):
        raise TypeError(f"Expected hex string, got {type(value)}")
    s = value.strip().lower()
    if not s:
        raise ValueError("Empty hex string")
    if not s.startswith("0x"):
        s = "0x" + s
    try:
        n = int(s, 16)
    except ValueError as e:
        raise ValueError(f"Invalid hex literal for u256: {value!r}") from e
    if n < 0 or n >= (1 << 256):
        raise ValueError("Value out of u256 range")
    return n


def is_hex256(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    token_hex = value[2:] if value.lower().startswith("0x") else value
    return len(token_hex) == 64 and all(c in "0123456789abcdefABCDEF" for c in token_hex)
