"""ELF v0.2 manifest spec — Pydantic models matching forge's `types.ts::Manifest`.

These models drive validation in the builder and inspector. They serialize to
the same JSON shape forge emits, so a manifest can round-trip Python ↔ Solid.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ELF_VERSION: Literal["0.2"] = "0.2"


# A free-form role string, but recognized canonical values are listed below.
# Custom roles must be prefixed `x-` (matches forge ResourceRole template type).
ResourceRole = str

CANONICAL_ROLES = frozenset({
    "document", "segment-set", "embedding-set", "index", "model", "template",
    "binding-ui", "binding-runtime", "asset", "license-text", "provenance",
})


class ResourceEntry(BaseModel):
    """A single packaged resource in an .elf manifest.

    Matches `forge/src/types.ts::ResourceEntry`. Field names are forge-canonical
    and must serialize exactly that way (no aliases, no rewrites).
    """

    model_config = ConfigDict(extra="allow")

    id: str
    media_type: str
    size: int
    sha256: str
    role: ResourceRole
    behavioral: bool = False
    canonical_content: bool = True
    path: str | None = None
    derived_from: list[str] | None = None
    fetch_urls: list[str] | None = None


class InteractionBlock(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: Literal["chat", "search", "qa", "summarize", "translate", "agent", "blank"] = "chat"
    operations: list[str] = Field(default_factory=list)


class FulfillmentEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    kind: str


class ProvenanceBlock(BaseModel):
    model_config = ConfigDict(extra="allow")

    builder: str | None = None
    built_at: str | None = None
    source_documents: list[dict[str, Any]] | None = None
    reproducible_seed: str | None = None


class SignatureEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    algorithm: str
    artifact_digest: str
    public_key: str
    signature: str
    identity_hint: str | None = None


class Manifest(BaseModel):
    """The full .elf v0.2 manifest. Identity = sha256 of canonicalized JSON
    after `signatures` is reset to `[]`."""

    model_config = ConfigDict(extra="allow")

    elf_version: Literal["0.2"] = ELF_VERSION
    id: str
    title: str
    description: str | None = None
    created: str
    locales: list[str] | None = None
    resources: list[ResourceEntry] = Field(default_factory=list)
    knowledge: dict[str, Any] | None = None
    interaction: InteractionBlock = Field(default_factory=InteractionBlock)
    fulfillments: dict[str, list[FulfillmentEntry]] = Field(default_factory=dict)
    bindings: list[dict[str, Any]] | None = None
    requirements: list[str] | None = None
    permissions: dict[str, Any] | None = None
    extensions: list[dict[str, Any]] | None = None
    licenses: list[dict[str, Any]] | None = None
    provenance: ProvenanceBlock | None = None
    signatures: list[SignatureEntry] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for canonicalize().

        Drops fields whose value is None to match forge's `obj[k] !== undefined`
        filter in canonicalize.ts. Keeps empty arrays / dicts.
        """
        return _drop_none(self.model_dump(mode="json"))


def _drop_none(value: Any) -> Any:
    """Recursively drop `None` values from dicts (mirrors JCS undefined-skip)."""
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(v) for v in value]
    return value


# Validation problem reporting (matches package.ts::ValidationProblem shape).


class ValidationProblem(BaseModel):
    path: str
    message: str

    def __str__(self) -> str:  # pragma: no cover
        return f"  • {self.path}: {self.message}"


def validate_manifest(m: Manifest) -> list[ValidationProblem]:
    """Replicate the validation in package.ts::validateManifest."""
    out: list[ValidationProblem] = []

    if m.elf_version != "0.2":
        out.append(ValidationProblem(
            path="elf_version",
            message=f'must be "0.2", got "{m.elf_version}"',
        ))
    if not m.id:
        out.append(ValidationProblem(path="id", message="required"))
    if not m.title:
        out.append(ValidationProblem(path="title", message="required"))
    if not m.created:
        out.append(ValidationProblem(path="created", message="required"))
    if not isinstance(m.resources, list):
        out.append(ValidationProblem(path="resources", message="must be array"))
    if not m.interaction:
        out.append(ValidationProblem(path="interaction", message="required"))
    elif not m.interaction.kind:
        out.append(ValidationProblem(path="interaction.kind", message="required"))

    # fulfillments must cover every declared operation
    for op in (m.interaction.operations if m.interaction else []):
        entries = m.fulfillments.get(op)
        if not entries:
            out.append(ValidationProblem(
                path=f"fulfillments.{op}",
                message="no fulfillment for declared operation",
            ))

    # cross-reference derived_from
    ids = {r.id for r in m.resources}
    for r in m.resources:
        for ref in r.derived_from or []:
            if ref not in ids:
                out.append(ValidationProblem(
                    path=f"resources.{r.id}.derived_from",
                    message=f'references unknown resource "{ref}"',
                ))

    return out
