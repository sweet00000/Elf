"""inspect() — parse a .elf single-file HTML, recompute fingerprint, verify
each packaged resource's sha256.

This is the read side of the v0.2 builder: given an .elf, return its parsed
manifest, its declared fingerprint, the recomputed fingerprint, and per-
resource verification results.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .canonicalize import canonicalize
from .digest import sha256_hex
from .spec import Manifest


# ── HTML extraction (regex — fine for the strict envelope our builder emits) ─


_MANIFEST_RE = re.compile(
    r'<script\s+type="application/elf-manifest">\s*(.+?)\s*</script>',
    re.DOTALL | re.IGNORECASE,
)
_FINGERPRINT_META_RE = re.compile(
    r'<meta\s+name="elf-fingerprint"\s+content="sha256:([0-9a-f]{64})"\s*/?>',
    re.IGNORECASE,
)
_VERSION_META_RE = re.compile(
    r'<meta\s+name="elf-version"\s+content="([^"]+)"\s*/?>',
    re.IGNORECASE,
)
_RESOURCE_RE = re.compile(
    r'<script\s+type="application/elf-resource"'
    r'\s+data-id="([^"]+)"'
    r'\s+data-encoding="([^"]+)"'
    r'\s+data-sha256="([0-9a-f]{64})"'
    r'\s+data-media-type="([^"]+)"\s*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


# ── Result types ────────────────────────────────────────────────────────────


@dataclass
class ResourceCheck:
    id: str
    declared_sha256: str
    actual_sha256: str
    declared_size: int
    actual_size: int
    media_type: str
    role: str
    sha_ok: bool
    size_ok: bool


@dataclass
class InspectResult:
    path: str
    elf_version: str | None
    declared_fingerprint: str | None
    actual_fingerprint: str
    fingerprint_ok: bool
    canonical_byte_count: int
    title: str
    id: str
    manifest: dict[str, Any]
    resource_checks: list[ResourceCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.fingerprint_ok
            and not self.errors
            and all(r.sha_ok and r.size_ok for r in self.resource_checks)
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ok"] = self.ok
        return d


class InspectError(RuntimeError):
    pass


# ── Public API ──────────────────────────────────────────────────────────────


def inspect(path: str | Path) -> InspectResult:
    """Parse `path` (a .elf HTML file) and verify its integrity."""
    p = Path(path)
    if not p.exists():
        raise InspectError(f"file not found: {path}")
    html = p.read_text(encoding="utf-8")

    # 1. Find the manifest script.
    m = _MANIFEST_RE.search(html)
    if not m:
        raise InspectError("no <script type=\"application/elf-manifest\"> found")
    raw_manifest = m.group(1).strip()
    try:
        manifest_dict = json.loads(raw_manifest)
    except json.JSONDecodeError as e:
        raise InspectError(f"manifest is not valid JSON: {e}") from e

    # 2. Validate against the spec model (loose — extra fields allowed).
    try:
        manifest = Manifest.model_validate(manifest_dict)
    except Exception as e:
        raise InspectError(f"manifest fails spec validation: {e}") from e

    # 3. Extract declared fingerprint from <meta>, if present.
    fp_meta = _FINGERPRINT_META_RE.search(html)
    declared_fp = fp_meta.group(1) if fp_meta else None
    version_meta = _VERSION_META_RE.search(html)
    elf_version = version_meta.group(1) if version_meta else manifest_dict.get("elf_version")

    # 4. Recompute fingerprint from canonical manifest (signatures cleared).
    fp_dict = dict(manifest_dict)
    fp_dict["signatures"] = []
    canonical = canonicalize(fp_dict)
    actual_fp = sha256_hex(canonical)

    # 5. Walk packaged resources, recomputing sha256 + size.
    resource_checks: list[ResourceCheck] = []
    declared_resources = {r.id: r for r in manifest.resources}

    for match in _RESOURCE_RE.finditer(html):
        rid, encoding, declared_sha, media_type, b64_payload = match.groups()
        if encoding != "base64":
            resource_checks.append(ResourceCheck(
                id=rid,
                declared_sha256=declared_sha,
                actual_sha256="",
                declared_size=declared_resources.get(rid).size if rid in declared_resources else 0,
                actual_size=0,
                media_type=media_type,
                role=declared_resources[rid].role if rid in declared_resources else "?",
                sha_ok=False,
                size_ok=False,
            ))
            continue
        payload = re.sub(r"\s+", "", b64_payload)
        try:
            data = base64.b64decode(payload, validate=True)
        except (ValueError, base64.binascii.Error) as e:  # type: ignore[attr-defined]
            raise InspectError(f"resource {rid}: invalid base64 ({e})") from e
        actual_sha = sha256_hex(data)
        spec_entry = declared_resources.get(rid)
        declared_size = spec_entry.size if spec_entry else 0
        role = spec_entry.role if spec_entry else "?"
        resource_checks.append(ResourceCheck(
            id=rid,
            declared_sha256=declared_sha,
            actual_sha256=actual_sha,
            declared_size=declared_size,
            actual_size=len(data),
            media_type=media_type,
            role=role,
            sha_ok=actual_sha == declared_sha,
            size_ok=spec_entry is None or len(data) == declared_size,
        ))

    # 6. Cross-check: every manifest-declared resource (with non-placeholder
    #    sha) should have an inline payload OR fetch_urls.
    warnings: list[str] = []
    inline_ids = {r.id for r in resource_checks}
    for r in manifest.resources:
        if r.sha256 == "0" * 64:
            continue
        if r.id not in inline_ids and not r.fetch_urls:
            warnings.append(
                f"resource {r.id!r} declared but no inline payload and no fetch_urls"
            )

    return InspectResult(
        path=str(p),
        elf_version=elf_version,
        declared_fingerprint=declared_fp,
        actual_fingerprint=actual_fp,
        fingerprint_ok=(declared_fp is None) or (declared_fp == actual_fp),
        canonical_byte_count=len(canonical),
        title=manifest.title,
        id=manifest.id,
        manifest=manifest_dict,
        resource_checks=resource_checks,
        warnings=warnings,
        errors=[],
    )
