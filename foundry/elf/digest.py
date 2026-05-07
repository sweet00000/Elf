"""SHA-256 helper. Mirrors forge/src/lib/digest.ts::sha256Hex."""

from __future__ import annotations

import hashlib


def sha256_hex(data: bytes | str) -> str:
    """Return the lowercase hex SHA-256 digest of `data`.

    Strings are UTF-8 encoded first, matching forge's TextEncoder behavior.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()
