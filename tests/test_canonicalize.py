"""RFC 8785 JCS port — vectors mirror the canonicalize.ts behavior in forge.

These tests deliberately use values that match what an .elf manifest carries
(strings, integers, arrays, nested objects, escaped chars) so that a Python-
built artifact's fingerprint matches a forge-built artifact's fingerprint
byte-for-byte.
"""

from __future__ import annotations

import pytest

from foundry.elf.canonicalize import canonicalize


def test_primitives():
    assert canonicalize(None) == "null"
    assert canonicalize(True) == "true"
    assert canonicalize(False) == "false"
    assert canonicalize(0) == "0"
    assert canonicalize(42) == "42"
    assert canonicalize(-7) == "-7"
    assert canonicalize("") == '""'
    assert canonicalize("hello") == '"hello"'


def test_string_escapes():
    # Only the JCS-mandated escapes are emitted.
    assert canonicalize('say "hi"') == '"say \\"hi\\""'
    assert canonicalize("a\\b") == '"a\\\\b"'
    assert canonicalize("tab\there") == '"tab\\there"'
    assert canonicalize("nl\nhere") == '"nl\\nhere"'
    # U+0001 → 
    assert canonicalize("a\x01b") == '"a\\u0001b"'
    # Non-ASCII passes through verbatim (UTF-8 emitted by repr, but here in str).
    assert canonicalize("café") == '"café"'


def test_arrays():
    assert canonicalize([]) == "[]"
    assert canonicalize([1, 2, 3]) == "[1,2,3]"
    assert canonicalize([1, "two", None, True]) == '[1,"two",null,true]'


def test_objects_sort_keys_lexicographically():
    assert canonicalize({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert canonicalize({"z": 0, "A": 0, "a": 0}) == '{"A":0,"a":0,"z":0}'


def test_nested():
    obj = {
        "elf_version": "0.2",
        "id": "urn:uuid:abc",
        "resources": [{"id": "r1", "size": 10}],
    }
    out = canonicalize(obj)
    # All keys sorted at every level; arrays preserve order.
    assert out == (
        '{"elf_version":"0.2","id":"urn:uuid:abc","resources":[{"id":"r1","size":10}]}'
    )


def test_drops_undefined_via_missing_sentinel():
    from foundry.elf.canonicalize import MISSING

    assert canonicalize({"a": 1, "b": MISSING, "c": 2}) == '{"a":1,"c":2}'


def test_non_finite_float_raises():
    with pytest.raises(ValueError):
        canonicalize(float("inf"))
    with pytest.raises(ValueError):
        canonicalize(float("nan"))


def test_integer_floats_render_as_ints():
    # Manifests don't carry floats but if a 1.0 sneaks in, it should match
    # ECMAScript Number.toString (which prints "1", not "1.0").
    assert canonicalize(1.0) == "1"
    assert canonicalize(-0.0) == "0"
