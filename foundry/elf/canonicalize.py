"""RFC 8785 — JSON Canonicalization Scheme (JCS).

Python port of `forge/src/lib/canonicalize.ts`. Produces byte-identical output
to the forge implementation for the manifest shapes the .elf format uses
(objects, arrays, strings, integers, booleans, null).

Implements the I-JSON subset used by forge:
    - objects: keys sorted by UTF-16 code units (= code points for the BMP),
      undefined values dropped.
    - arrays: serialize each element; undefined → null.
    - strings: minimal JSON escapes (", \\, U+0000..U+001F); UTF-8 passthrough.
    - numbers: integers via str(); finite floats via the shortest round-trip
      ECMAScript-compatible form. Non-finite raises.

Forge's manifests do not contain floats, so the float path is best-effort —
matching ECMAScript Number.toString for arbitrary doubles is non-trivial and
deliberately punted.

Reference: https://www.rfc-editor.org/rfc/rfc8785
"""

from __future__ import annotations

from typing import Any


def canonicalize(value: Any) -> str:
    """Return the RFC 8785 canonical JSON serialization of `value`."""
    return _serialize(value)


def _serialize(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return _serialize_int(v)
    if isinstance(v, float):
        return _serialize_float(v)
    if isinstance(v, str):
        return _serialize_string(v)
    if isinstance(v, (list, tuple)):
        parts = [_serialize(x if x is not None else None) for x in v]
        return "[" + ",".join(parts) + "]"
    if isinstance(v, dict):
        # RFC 8785 §3.2.3: sort keys by UTF-16 code units. For BMP code points
        # this matches Python's default string ordering. Drop any explicit
        # undefined-equivalents (None values are kept; only values that round
        # to "undefined" are dropped — which we represent here as MISSING).
        keys = sorted(k for k, val in v.items() if val is not _MISSING)
        parts = []
        for k in keys:
            if not isinstance(k, str):
                k_str = str(k)
            else:
                k_str = k
            parts.append(f"{_serialize_string(k_str)}:{_serialize(v[k])}")
        return "{" + ",".join(parts) + "}"
    # Functions / symbols / unsupported → null at top level (matches JS
    # behavior of dropping undefined / non-serializable values).
    return "null"


# Sentinel used to drop keys explicitly. Python dicts can't carry "undefined";
# callers can pass _MISSING as a value to omit a key from the canonical output.
class _Missing:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover
        return "MISSING"


_MISSING = _Missing()
MISSING = _MISSING


def _serialize_int(n: int) -> str:
    # I-JSON range: integers up to 2^53. We don't enforce — all real manifests
    # stay well inside it. str(int) is unambiguous in Python.
    return str(n)


def _serialize_float(n: float) -> str:
    if n != n or n in (float("inf"), float("-inf")):
        raise ValueError(f"JCS: non-finite number not permitted ({n})")
    if n == 0.0:
        return "0"
    # Best-effort ECMAScript Number.toString. Python's `repr(float)` produces
    # the shortest round-trip representation, which matches ECMAScript for
    # most finite doubles but not all (e.g. exponent format thresholds).
    # Manifests in this project should not contain floats; if they do and a
    # round-trip mismatch surfaces, swap this for a dedicated impl.
    if n.is_integer() and abs(n) < 2**53:
        return str(int(n))
    return repr(n)


def _serialize_string(s: str) -> str:
    out = ['"']
    for ch in s:
        c = ord(ch)
        if c == 0x22:
            out.append('\\"')
        elif c == 0x5C:
            out.append("\\\\")
        elif c == 0x08:
            out.append("\\b")
        elif c == 0x09:
            out.append("\\t")
        elif c == 0x0A:
            out.append("\\n")
        elif c == 0x0C:
            out.append("\\f")
        elif c == 0x0D:
            out.append("\\r")
        elif c < 0x20:
            out.append(f"\\u{c:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)
