"""End-to-end build → inspect round-trip.

Acceptance criterion from PLAN.md Phase 2:
    `foundry inspect golden.elf` prints metadata; the recomputed fingerprint
    matches what the builder declared.

These tests don't depend on Playwright or any network.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pytest

from foundry.elf import (
    BuildError,
    Manifest,
    ResourceEntry,
    build_single,
    canonicalize,
    inspect,
    sha256_hex,
)


def _resource(rid: str, body: bytes, role: str = "document",
              media_type: str = "text/plain") -> ResourceEntry:
    return ResourceEntry(
        id=rid,
        media_type=media_type,
        size=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        role=role,
        behavioral=False,
        canonical_content=True,
    )


def _minimal_manifest(resources: list[ResourceEntry]) -> Manifest:
    return Manifest(
        elf_version="0.2",
        id="urn:uuid:test-12345",
        title="Round-trip Test ELF",
        created="2026-05-07T00:00:00Z",
        resources=resources,
        interaction={"kind": "chat", "operations": ["generate-text"]},
        fulfillments={
            "generate-text": [{"id": "host", "kind": "host-capability"}],
        },
    )


def test_build_round_trip_fingerprint_matches(tmp_path: Path):
    body = b"This is a small document body for the round-trip test."
    r = _resource("res:doc.demo", body)
    manifest = _minimal_manifest([r])
    result = build_single(manifest, {"res:doc.demo": body})

    elf_path = tmp_path / "demo.elf.html"
    result.write(elf_path)
    assert elf_path.exists()
    assert result.byte_size == len(elf_path.read_text(encoding="utf-8").encode("utf-8"))

    inspected = inspect(elf_path)
    assert inspected.ok, inspected.errors
    assert inspected.declared_fingerprint == result.fingerprint
    assert inspected.actual_fingerprint == result.fingerprint
    assert inspected.elf_version == "0.2"
    assert inspected.title == "Round-trip Test ELF"
    assert len(inspected.resource_checks) == 1
    rc = inspected.resource_checks[0]
    assert rc.id == "res:doc.demo"
    assert rc.sha_ok
    assert rc.size_ok
    assert rc.actual_sha256 == r.sha256


def test_build_rejects_size_mismatch():
    body = b"hello world"
    r = ResourceEntry(
        id="res:doc.bad",
        media_type="text/plain",
        size=999,  # lying about the size
        sha256=hashlib.sha256(body).hexdigest(),
        role="document",
        behavioral=False,
        canonical_content=True,
    )
    manifest = _minimal_manifest([r])
    with pytest.raises(BuildError) as excinfo:
        build_single(manifest, {"res:doc.bad": body})
    assert any("size" in p.path for p in excinfo.value.problems)


def test_build_rejects_sha_mismatch():
    body = b"hello world"
    r = ResourceEntry(
        id="res:doc.bad",
        media_type="text/plain",
        size=len(body),
        sha256="0" * 63 + "1",  # wrong but right shape
        role="document",
        behavioral=False,
        canonical_content=True,
    )
    manifest = _minimal_manifest([r])
    with pytest.raises(BuildError) as excinfo:
        build_single(manifest, {"res:doc.bad": body})
    assert any("sha256" in p.path for p in excinfo.value.problems)


def test_build_allows_reference_only_resource():
    """A resource with placeholder sha + fetch_urls is allowed (model file
    fetched at runtime, not packaged)."""
    r = ResourceEntry(
        id="res:model.qwen3",
        media_type="application/x-gguf",
        size=0,
        sha256="0" * 64,
        role="model",
        behavioral=True,
        canonical_content=False,
        fetch_urls=["https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/blob/main/qwen3-0.6b-q4.gguf"],
    )
    manifest = _minimal_manifest([r])
    result = build_single(manifest, {})
    assert result.fingerprint
    assert result.byte_size > 0


def test_canonicalize_is_deterministic_across_key_order():
    """Two dicts with the same logical content must canonicalize identically
    regardless of key insertion order — the foundation of the fingerprint."""
    a = {"id": "x", "title": "y", "created": "z"}
    b = {"created": "z", "title": "y", "id": "x"}
    assert canonicalize(a) == canonicalize(b)
    assert sha256_hex(canonicalize(a)) == sha256_hex(canonicalize(b))


def test_inspect_detects_missing_manifest(tmp_path: Path):
    p = tmp_path / "broken.elf.html"
    p.write_text("<html><body>no manifest here</body></html>", encoding="utf-8")
    from foundry.elf import InspectError
    with pytest.raises(InspectError):
        inspect(p)
