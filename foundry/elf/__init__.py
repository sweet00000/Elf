"""Foundry ELF — Python re-impl of forge's .elf v0.2 builder + inspector.

Goal: produce / parse / verify .elf single-file HTML artifacts that are
byte-compatible with what `forge/src/tools/package.ts::buildSingle()` emits.

Modules:
    spec          — Pydantic models for Manifest + ResourceEntry
    canonicalize  — RFC 8785 JCS port (matches forge/src/lib/canonicalize.ts)
    digest        — sha256_hex helper
    builder       — build_single(): manifest + resource bytes → .elf HTML
    inspector     — inspect(): .elf HTML → parsed manifest + verified resources
    template      — vendored bootstrap.js, binding-ui.html, runtimes from forge

The canonicalize + builder code paths are the load-bearing ones — they must
match forge byte-for-byte so an .elf round-trips through Python and Solid
with the same fingerprint.
"""

from .builder import BuildResult, BuildError, build_single
from .canonicalize import canonicalize
from .digest import sha256_hex
from .inspector import InspectError, InspectResult, inspect
from .spec import Manifest, ResourceEntry, ELF_VERSION

__all__ = [
    "ELF_VERSION",
    "Manifest",
    "ResourceEntry",
    "BuildResult",
    "BuildError",
    "InspectResult",
    "InspectError",
    "build_single",
    "inspect",
    "canonicalize",
    "sha256_hex",
]
