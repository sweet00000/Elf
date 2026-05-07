"""build_single() — Python re-impl of forge/src/tools/package.ts::buildSingle.

Takes a Manifest plus a mapping of {resource_id → bytes} and emits a single
self-contained .elf HTML file byte-compatible with what forge produces.

The HTML envelope (head/body, script tags, comments) matches forge's emitter
character-for-character so two implementations produce the same fingerprint
when given the same manifest + bytes.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import time
from dataclasses import dataclass
from pathlib import Path

from .canonicalize import canonicalize
from .digest import sha256_hex
from .spec import Manifest, ResourceEntry, ValidationProblem, validate_manifest


PLACEHOLDER_SHA = "0" * 64


# Templates vendored from forge: bootstrap.js + binding-ui.html. Read once
# from disk; cached for subsequent builds.

_TEMPLATE_DIR = Path(__file__).parent / "template"
_BOOTSTRAP_PATH = _TEMPLATE_DIR / "bootstrap.js"
_DEFAULT_UI_HTML = '<div id="elf-app"></div>'


def _load_bootstrap() -> str:
    if not _BOOTSTRAP_PATH.exists():
        raise BuildError([ValidationProblem(
            path="template.bootstrap",
            message=f"bootstrap.js missing at {_BOOTSTRAP_PATH}",
        )])
    return _BOOTSTRAP_PATH.read_text(encoding="utf-8")


@dataclass
class BuildResult:
    build_id: str
    fingerprint: str
    byte_size: int
    manifest: dict
    html: str

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.html, encoding="utf-8")
        return path

    def summary(self) -> dict:
        return {
            "build_id": self.build_id,
            "fingerprint": self.fingerprint,
            "byte_size": self.byte_size,
            "title": self.manifest.get("title"),
            "id": self.manifest.get("id"),
            "resources": len(self.manifest.get("resources", [])),
        }


class BuildError(RuntimeError):
    """Raised when the manifest fails validation or resource bytes don't match.

    Mirrors forge's BuildError — carries a list of `ValidationProblem`s.
    """

    def __init__(self, problems: list[ValidationProblem]) -> None:
        self.problems = problems
        plural = "" if len(problems) == 1 else "s"
        msg = f"build failed ({len(problems)} problem{plural}):\n" + "\n".join(
            f"  • {p.path}: {p.message}" for p in problems
        )
        super().__init__(msg)


def build_single(
    manifest: Manifest,
    resource_bytes: dict[str, bytes],
    *,
    builder: str = "foundry/0.1",
    built_at: str | None = None,
) -> BuildResult:
    """Package a manifest + resource bytes into a single .elf HTML.

    `resource_bytes` is keyed by resource id. Resources whose `sha256` is the
    placeholder, or whose entry only carries `fetch_urls`, may be omitted —
    they'll be packaged as reference-only.
    """
    t0 = time.perf_counter()

    # Defensive deep copy of the manifest so we can mutate provenance / clear
    # signatures without affecting the caller's instance.
    m_copy = Manifest.model_validate(manifest.model_dump(mode="json"))
    m_copy.signatures = []
    if m_copy.provenance is None:
        from .spec import ProvenanceBlock
        m_copy.provenance = ProvenanceBlock(builder=builder)
    else:
        m_copy.provenance.builder = builder
    m_copy.provenance.built_at = built_at or dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")

    # 1. Validate.
    problems = validate_manifest(m_copy)
    if problems:
        raise BuildError(problems)

    # 2-3. Walk resources, gather bytes, verify sha256.
    encoded: dict[str, str] = {}
    verify_problems: list[ValidationProblem] = []
    ui_html: str | None = None

    for r in m_copy.resources:
        bytes_blob = resource_bytes.get(r.id)
        if r.sha256 == PLACEHOLDER_SHA:
            if not r.fetch_urls:
                verify_problems.append(ValidationProblem(
                    path=f"resources.{r.id}",
                    message="has placeholder sha256 but no fetch_urls — cannot package",
                ))
            continue

        if bytes_blob is None:
            if r.fetch_urls:
                continue  # reference-only is allowed
            verify_problems.append(ValidationProblem(
                path=f"resources.{r.id}",
                message="bytes missing and no fetch_urls fallback",
            ))
            continue

        actual_sha = sha256_hex(bytes_blob)
        if actual_sha != r.sha256:
            verify_problems.append(ValidationProblem(
                path=f"resources.{r.id}.sha256",
                message=f"bytes hash to {actual_sha}, expected {r.sha256}",
            ))
            continue
        if len(bytes_blob) != r.size:
            verify_problems.append(ValidationProblem(
                path=f"resources.{r.id}.size",
                message=f"bytes are {len(bytes_blob)} long, manifest says {r.size}",
            ))
            continue

        encoded[r.id] = base64.b64encode(bytes_blob).decode("ascii")

        if r.role == "binding-ui":
            try:
                ui_html = bytes_blob.decode("utf-8")
            except UnicodeDecodeError:
                verify_problems.append(ValidationProblem(
                    path=f"resources.{r.id}",
                    message="binding-ui resource is not valid UTF-8",
                ))

    if verify_problems:
        raise BuildError(verify_problems)

    if ui_html is None:
        ui_html = _DEFAULT_UI_HTML

    # 4. Canonicalize + fingerprint.
    canonical = canonicalize(m_copy.to_dict())
    fingerprint = sha256_hex(canonical)

    # 5. Manifest JSON for the inert <script> — pretty-printed exactly as forge
    #    does (`JSON.stringify(manifest, null, 2)`).
    manifest_json = _stringify_pretty(m_copy.to_dict(), indent=2)

    # 6. Emit the HTML envelope. Lines and indentation mirror package.ts.
    safe_title = (m_copy.title or ".elf artifact").replace("<", "").replace(">", "")
    head: list[str] = []
    head.append("<!DOCTYPE html>")
    head.append('<html lang="en">')
    head.append("<head>")
    head.append('  <meta charset="utf-8">')
    head.append('  <meta name="viewport" content="width=device-width, initial-scale=1">')
    head.append('  <meta name="elf-version" content="0.2">')
    head.append(f'  <meta name="elf-fingerprint" content="sha256:{fingerprint}">')
    head.append(f"  <title>{safe_title}</title>")
    head.append(
        f'  <script type="application/elf-manifest">\n{manifest_json}\n  </script>'
    )
    head.append("  <!--")
    head.append(f"    artifact identity: sha256:{fingerprint}")
    head.append(f"    canonical bytes: {len(canonical)} chars (RFC 8785)")
    head.append("  -->")

    for r in m_copy.resources:
        b64 = encoded.get(r.id)
        if b64 is None:
            continue  # reference-only
        head.append(
            '  <script type="application/elf-resource"'
            f' data-id="{r.id}"'
            f' data-encoding="base64"'
            f' data-sha256="{r.sha256}"'
            f' data-media-type="{r.media_type}"'
            f">{b64}</script>"
        )
    head.append("</head>")

    bootstrap_js = _load_bootstrap()
    body: list[str] = [
        "<body>",
        ui_html,
        '<script type="module">',
        bootstrap_js,
        "</script>",
        "</body>",
        "</html>",
    ]

    html = "\n".join(head) + "\n" + "\n".join(body) + "\n"
    byte_size = len(html.encode("utf-8"))
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    timestamp_short = format(int(time.time() * 1000), "x")
    build_id = f"build.{timestamp_short}.{fingerprint[:8]}"

    return BuildResult(
        build_id=build_id,
        fingerprint=fingerprint,
        byte_size=byte_size,
        manifest=m_copy.to_dict(),
        html=html,
    )


def _stringify_pretty(value, indent: int = 2) -> str:
    """JSON.stringify(value, null, 2) equivalent — matches forge's pretty form.

    `json.dumps` with `indent=2` and `separators=(',', ': ')` produces a
    formatting close to JS but with one difference: JS adds no trailing
    newline. Match that.
    """
    return json.dumps(value, indent=indent, ensure_ascii=False, separators=(",", ": "))
