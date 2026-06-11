"""Download and track external data sources used by local ETL scripts."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_RAW_DIR = Path("data") / "raw"
DEFAULT_MANIFEST_PATH = Path("data") / "source_manifest.json"
DEFAULT_TIMEOUT_SECONDS = 120
SUPPORTED_SOURCE_FORMATS = ("csv", "xlsx", "zip", "parquet")


@dataclass(frozen=True)
class SourceReference:
    """Reference to a downloadable dataset or API endpoint."""

    key: str
    name: str
    url: str
    expected_format: str | None = None
    vintage: str | None = None


INSEE_SOURCE_REGISTRY: dict[str, SourceReference] = {}


@dataclass(frozen=True)
class SourceManifestEntry:
    """Metadata persisted for one downloaded source file."""

    source_key: str
    name: str
    source_url: str
    downloaded_at: str
    vintage: str | None
    local_filename: str
    sha256: str


class SourceDownloadError(RuntimeError):
    """Raised when a source cannot be downloaded."""


class UnknownDataSourceError(RuntimeError):
    """Raised when a named source is not registered."""


def register_insee_source(reference: SourceReference) -> None:
    """Register a named INSEE source for later lookup."""
    if (
        reference.expected_format
        and reference.expected_format not in SUPPORTED_SOURCE_FORMATS
    ):
        supported = ", ".join(SUPPORTED_SOURCE_FORMATS)
        raise ValueError(
            f"Unsupported source format: {reference.expected_format}. Use {supported}."
        )
    INSEE_SOURCE_REGISTRY[reference.key] = reference


def get_insee_source(key: str) -> SourceReference:
    """Return a registered INSEE source by key."""
    try:
        return INSEE_SOURCE_REGISTRY[key]
    except KeyError as exc:
        raise UnknownDataSourceError(f"Unknown INSEE data source: {key}") from exc


def list_insee_sources() -> list[SourceReference]:
    """Return registered INSEE sources sorted by key."""
    return [INSEE_SOURCE_REGISTRY[key] for key in sorted(INSEE_SOURCE_REGISTRY)]


def source_from_url(
    key: str,
    name: str,
    url: str,
    expected_format: str | None = None,
    vintage: str | None = None,
) -> SourceReference:
    """Build a source reference from CLI-provided values."""
    return SourceReference(
        key=key,
        name=name,
        url=url,
        expected_format=expected_format or detect_format_from_url(url),
        vintage=vintage or detect_vintage(url),
    )


def download_source(
    reference: SourceReference,
    raw_dir: Path = DEFAULT_RAW_DIR,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    force_refresh: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Path:
    """Download a source file into raw_dir and update the manifest."""
    if not is_remote_url(reference.url):
        local_path = Path(reference.url)
        if not local_path.exists():
            raise FileNotFoundError(f"Source file not found: {local_path}")
        return local_path

    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)
    local_filename = build_local_filename(reference)
    local_path = raw_dir / local_filename

    if local_path.exists() and not force_refresh:
        logger.info("Using existing raw source file %s.", local_path)
        entry = build_manifest_entry(reference, local_path)
        save_manifest_entry(manifest_path, manifest, entry)
        return local_path

    logger.info("Downloading %s to %s.", reference.url, local_path)
    try:
        response = requests.get(reference.url, timeout=timeout_seconds)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SourceDownloadError(f"Unable to download {reference.url}: {exc}") from exc

    local_path.write_bytes(response.content)
    entry = build_manifest_entry(reference, local_path)
    save_manifest_entry(manifest_path, manifest, entry)
    return local_path


def download_sources(
    references: list[SourceReference],
    raw_dir: Path = DEFAULT_RAW_DIR,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    force_refresh: bool = False,
) -> dict[str, Path]:
    """Download several sources and return local paths by source key."""
    paths: dict[str, Path] = {}
    for reference in references:
        paths[reference.key] = download_source(
            reference,
            raw_dir=raw_dir,
            manifest_path=manifest_path,
            force_refresh=force_refresh,
        )
    return paths


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, dict[str, Any]]:
    """Load the source manifest as a dictionary keyed by source URL."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid source manifest: {path}")
    sources = payload.get("sources", {})
    if not isinstance(sources, dict):
        raise ValueError(f"Invalid source manifest sources object: {path}")
    return {
        str(key): value for key, value in sources.items() if isinstance(value, dict)
    }


def save_manifest_entry(
    path: Path,
    manifest: dict[str, dict[str, Any]],
    entry: SourceManifestEntry,
) -> None:
    """Upsert one manifest entry keyed by source URL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest[entry.source_key] = asdict(entry)
    path.write_text(
        json.dumps({"sources": manifest}, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def build_manifest_entry(
    reference: SourceReference,
    local_path: Path,
) -> SourceManifestEntry:
    """Create manifest metadata for a local source file."""
    return SourceManifestEntry(
        source_key=reference.key,
        name=reference.name,
        source_url=reference.url,
        downloaded_at=datetime.now(timezone.utc).isoformat(),
        vintage=(
            reference.vintage
            or detect_vintage(reference.url)
            or detect_vintage(local_path.name)
        ),
        local_filename=local_path.name,
        sha256=sha256_file(local_path),
    )


def sha256_file(path: Path) -> str:
    """Return the SHA256 hash of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_local_filename(reference: SourceReference) -> str:
    """Build a stable, readable filename for a source."""
    parsed = urlparse(reference.url)
    raw_name = unquote(Path(parsed.path).name) if parsed.path else ""
    suffix = Path(raw_name).suffix
    if not suffix and reference.expected_format:
        suffix = f".{reference.expected_format}"
    if not suffix:
        suffix = ".data"

    stem_parts = [slugify(reference.key)]
    vintage = reference.vintage or detect_vintage(reference.url)
    if vintage:
        stem_parts.append(vintage)
    return "_".join(stem_parts) + suffix.lower()


def detect_format_from_url(url: str) -> str | None:
    """Infer source format from a URL path extension."""
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    return suffix if suffix in SUPPORTED_SOURCE_FORMATS else None


def detect_vintage(value: str) -> str | None:
    """Detect a plausible INSEE vintage year in a URL or filename."""
    matches = re.findall(r"(?<!\d)(20\d{2})(?!\d)", value)
    return matches[-1] if matches else None


def is_remote_url(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "source"
