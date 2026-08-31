#!/usr/bin/env python3
"""Build a deterministic offline RAG source package from canonical-content JSON.

The builder validates every canonical input with the bundled JSON Schema
validator and performs the semantic structural checks required by the canonical
contract.  It never calls a model, network service, tokenizer, embedding API, or
vector database.

``rag-package.json`` is the schema-valid control object.  Each document's
``manifest.json`` inventories immutable payload files but deliberately excludes
itself and the control object, avoiding a false or self-referential checksum.
The control object carries the independently verifiable checksum of each
document manifest.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote
import xml.etree.ElementTree as ET
import zlib


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from validate_records import (  # noqa: E402
    InternalSchemaValidator,
    ValidationToolError,
    load_json_bytes,
)


TOOL_NAME = "thien-rag-package-builder"
TOOL_VERSION = "1.0.0"
SKILL_ID = "thien-skill-document-evidence"
SKILL_ROOT = SCRIPT_DIRECTORY.parent
SCHEMA_ROOT = SKILL_ROOT / "schemas"
CANONICAL_SCHEMA = SCHEMA_ROOT / "common" / "canonical-content.schema.json"
RAG_SCHEMA = SCHEMA_ROOT / "common" / "rag-package.schema.json"
TEMPLATE_ROOT = SKILL_ROOT / "assets" / "templates"
METADATA_TEMPLATE = TEMPLATE_ROOT / "rag-metadata.json"
MANIFEST_TEMPLATE = TEMPLATE_ROOT / "rag-manifest.json"
RELEASE_VERSION_FILE = SKILL_ROOT / "VERSION"

MAX_CANONICAL_BYTES = 64 * 1024 * 1024
MAX_CONFIG_BYTES = 1024 * 1024
MAX_ASSET_BYTES = 256 * 1024 * 1024
MAX_SVG_BYTES = 10 * 1024 * 1024
MAX_PNG_PIXELS = 100_000_000
MAX_PNG_SCANLINES = 1_000_000
MAX_PNG_DECODED_BYTES = 256 * 1024 * 1024
MAX_PACKAGE_BYTES = 512 * 1024 * 1024
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
ASSET_MEDIA_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/svg+xml",
}
ASSET_EXTENSIONS = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/webp": {".webp"},
    "image/svg+xml": {".svg"},
}
RESERVED_ROOT_PATHS = {"rag-package.json", "collection-manifest.json"}
RESERVED_DOCUMENT_PATHS = {
    "document.md",
    "metadata.json",
    "manifest.json",
    "chunks.jsonl",
}
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
SVG_ALLOWED_ELEMENTS = {
    "svg",
    "g",
    "defs",
    "symbol",
    "use",
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "text",
    "tspan",
    "title",
    "desc",
    "clippath",
    "mask",
    "lineargradient",
    "radialgradient",
    "stop",
    "pattern",
    "marker",
}
SVG_PROHIBITED_ELEMENTS = {
    "script",
    "foreignobject",
    "iframe",
    "object",
    "embed",
    "style",
    "a",
    "image",
    "audio",
    "video",
    "canvas",
}
SVG_ALLOWED_ATTRIBUTES = {
    "id",
    "class",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "dx",
    "dy",
    "width",
    "height",
    "viewbox",
    "preserveaspectratio",
    "version",
    "d",
    "points",
    "transform",
    "fill",
    "fill-opacity",
    "fill-rule",
    "stroke",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-dasharray",
    "stroke-dashoffset",
    "stroke-opacity",
    "opacity",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "text-anchor",
    "dominant-baseline",
    "offset",
    "stop-color",
    "stop-opacity",
    "clip-path",
    "mask",
    "marker-start",
    "marker-mid",
    "marker-end",
    "gradientunits",
    "gradienttransform",
    "spreadmethod",
    "patternunits",
    "patterncontentunits",
    "patterntransform",
    "href",
    "style",
    "role",
    "aria-label",
    "aria-labelledby",
    "space",
}
CHUNK_REQUIRED_FIELDS = {"document_id", "block_ids", "source_locators"}
CHUNK_AVAILABLE_FIELDS = {
    "chunk_id",
    "document_id",
    "sequence",
    "block_ids",
    "source_locators",
    "heading_path",
    "character_count",
    "count_method",
    "classification",
}


class RagBuildError(ValueError):
    """Raised for invalid inputs, unsafe paths, or failed publication."""


@dataclass(frozen=True)
class CanonicalSource:
    path: Path
    source_reference: str
    raw_bytes: bytes
    payload: dict[str, Any]
    document_id: str
    directory: str
    assets_root: Path


@dataclass(frozen=True)
class ChunkingRequest:
    target_id: str
    config: dict[str, Any]
    raw_bytes: bytes
    checksum: str


@dataclass(frozen=True)
class BuildResult:
    files: dict[str, bytes]
    control: dict[str, Any]
    package_id: str
    package_kind: str


def canonical_json_bytes(value: object, *, pretty: bool = True) -> bytes:
    if pretty:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    else:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return (rendered + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checksum_object(data: bytes) -> dict[str, str]:
    return {
        "algorithm": "SHA-256",
        "digest": sha256_bytes(data),
        "computed_at": "UNKNOWN",
        "object_role": "DERIVATIVE",
    }


def _absolute_without_resolution(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def resolve_root(raw_root: str | Path, *, label: str) -> Path:
    supplied = Path(raw_root).expanduser()
    if supplied.is_symlink():
        raise RagBuildError(f"{label} must not be a symlink: {supplied}")
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise RagBuildError(f"cannot resolve {label} {supplied}: {exc}") from exc
    if not root.is_dir():
        raise RagBuildError(f"{label} is not a directory: {supplied}")
    if root == Path(root.anchor):
        raise RagBuildError(f"{label} must not be a filesystem root")
    return root


def ensure_below_root(root: Path, path: Path, *, label: str) -> Path:
    lexical = _absolute_without_resolution(path)
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise RagBuildError(f"{label} escapes authorized root: {path}") from exc
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RagBuildError(f"{label} must not traverse a symlink: {relative}")
    return lexical


def resolve_regular_file(root: Path, raw_path: str | Path, *, label: str) -> Path:
    supplied = Path(raw_path).expanduser()
    candidate = supplied if supplied.is_absolute() else root / supplied
    lexical = ensure_below_root(root, candidate, label=label)
    if not lexical.is_file():
        raise RagBuildError(f"{label} is not a regular file: {raw_path}")
    return lexical


def resolve_directory_below_root(
    root: Path, raw_path: str | Path, *, label: str
) -> Path:
    supplied = Path(raw_path).expanduser()
    candidate = supplied if supplied.is_absolute() else root / supplied
    candidate = _absolute_without_resolution(candidate)
    alias_root: Path | None = None
    for ancestor in (candidate, *candidate.parents):
        try:
            if ancestor.resolve(strict=True) == root:
                alias_root = ancestor
                break
        except OSError:
            continue
    if alias_root is None:
        raise RagBuildError(f"{label} escapes authorized root: {raw_path}")
    relative = candidate.relative_to(alias_root)
    cursor = alias_root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RagBuildError(f"{label} must not traverse a symlink: {relative}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RagBuildError(f"{label} escapes authorized root: {raw_path}") from exc
    if not resolved.is_dir():
        raise RagBuildError(f"{label} is not a directory: {raw_path}")
    return resolved


def resolve_output_directory(root: Path, raw_path: str | Path) -> Path:
    supplied = Path(raw_path).expanduser()
    candidate = supplied if supplied.is_absolute() else root / supplied
    lexical = _absolute_without_resolution(candidate)
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise RagBuildError(f"output escapes authorized root: {raw_path}") from exc
    if lexical == root:
        raise RagBuildError("output must not replace the authorized root")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RagBuildError(f"output must not traverse a symlink: {relative}")
    if not lexical.parent.is_dir() or lexical.parent.is_symlink():
        raise RagBuildError(
            f"output parent must be an existing real directory: {lexical.parent}"
        )
    return lexical


def read_regular_nofollow(path: Path, *, label: str, max_bytes: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RagBuildError(f"{label} is not a regular file: {path}")
        if before.st_size > max_bytes:
            raise RagBuildError(
                f"{label} exceeds the {max_bytes}-byte safety limit: {path}"
            )
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            data = handle.read(max_bytes + 1)
            after = os.fstat(handle.fileno())
        if len(data) > max_bytes:
            raise RagBuildError(
                f"{label} exceeds the {max_bytes}-byte safety limit: {path}"
            )
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise RagBuildError(f"{label} changed while being read: {path}")
        return data
    except OSError as exc:
        raise RagBuildError(f"cannot safely read {label} {path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load_json(data: bytes, *, label: str) -> object:
    try:
        return load_json_bytes(data, label=label)
    except ValidationToolError as exc:
        raise RagBuildError(str(exc)) from exc


def safe_relative_path(raw_path: str, *, label: str) -> PurePosixPath:
    if not isinstance(raw_path, str) or not raw_path:
        raise RagBuildError(f"{label} must be a non-empty relative POSIX path")
    if raw_path != unicodedata.normalize("NFC", raw_path):
        raise RagBuildError(f"{label} must use NFC-normalized Unicode: {raw_path!r}")
    if raw_path.startswith("/") or raw_path.startswith("./") or "//" in raw_path:
        raise RagBuildError(f"unsafe {label}: {raw_path!r}")
    if "\\" in raw_path or ":" in raw_path:
        raise RagBuildError(f"unsafe {label}: {raw_path!r}")
    if any(ord(character) < 32 for character in raw_path):
        raise RagBuildError(f"unsafe {label}: {raw_path!r}")
    path = PurePosixPath(raw_path)
    if str(path) != raw_path or path.is_absolute():
        raise RagBuildError(f"unsafe {label}: {raw_path!r}")
    for part in path.parts:
        if part in {"", ".", ".."}:
            raise RagBuildError(f"unsafe {label}: {raw_path!r}")
        if len(part.encode("utf-8")) > 200:
            raise RagBuildError(f"{label} segment is too long: {part!r}")
        if part.endswith((".", " ")) or any(
            character in '<>"|?*' for character in part
        ):
            raise RagBuildError(f"unsafe {label}: {raw_path!r}")
        if part.split(".", 1)[0].casefold() in WINDOWS_RESERVED:
            raise RagBuildError(f"unsafe reserved {label}: {raw_path!r}")
    if len(raw_path.encode("utf-8")) > 800:
        raise RagBuildError(f"{label} is too long")
    return path


def normalized_path_key(raw_path: str, *, label: str) -> tuple[str, ...]:
    path = safe_relative_path(raw_path, label=label)
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in path.parts)


def assert_path_set_has_no_collisions(
    raw_paths: Sequence[str],
    *,
    label: str,
    allow_identical_duplicates: bool = False,
) -> None:
    observed: list[tuple[str, tuple[str, ...]]] = []
    for raw_path in raw_paths:
        key = normalized_path_key(raw_path, label=label)
        for previous_raw, previous_key in observed:
            if key == previous_key:
                if allow_identical_duplicates and raw_path == previous_raw:
                    break
                raise RagBuildError(
                    f"{label} exact or case-insensitive path collision: "
                    f"{previous_raw!r} and {raw_path!r}"
                )
            shared = min(len(key), len(previous_key))
            if key[:shared] == previous_key[:shared]:
                raise RagBuildError(
                    f"{label} file/directory-prefix collision: "
                    f"{previous_raw!r} and {raw_path!r}"
                )
        else:
            observed.append((raw_path, key))


def validate_asset_references(blocks: Sequence[Mapping[str, Any]]) -> None:
    references: list[str] = []
    for block in blocks:
        if block["block_type"] != "IMAGE":
            continue
        reference = block["asset_reference"]
        path = safe_relative_path(reference, label="asset_reference")
        if path.parts[0].casefold() in {
            value.casefold() for value in RESERVED_DOCUMENT_PATHS
        }:
            raise RagBuildError(
                f"asset_reference collides with reserved generated path: {reference!r}"
            )
        if len(path.parts) < 2 or path.parts[0] != "assets":
            raise RagBuildError(
                f"asset_reference must be below the reserved assets/ directory: {reference!r}"
            )
        media_type = block["media_type"]
        expected_extensions = ASSET_EXTENSIONS.get(media_type)
        if expected_extensions is None:
            raise RagBuildError(f"unsupported asset media type: {media_type}")
        suffix = PurePosixPath(reference).suffix.casefold()
        if suffix not in expected_extensions:
            raise RagBuildError(
                f"asset extension {suffix or '<none>'!r} does not match declared "
                f"media_type {media_type!r}: {reference}"
            )
        references.append(reference)
    assert_path_set_has_no_collisions(
        references,
        label="asset_reference",
        allow_identical_duplicates=True,
    )


def stable_directory(document_id: str) -> str:
    candidate = document_id.replace(":", "-")
    if candidate != document_id:
        candidate = f"{candidate}-{sha256_bytes(document_id.encode('utf-8'))[:8]}"
    try:
        safe_relative_path(candidate, label="document directory")
    except RagBuildError:
        candidate = f"document-{sha256_bytes(document_id.encode('utf-8'))[:20]}"
        safe_relative_path(candidate, label="document directory")
    if candidate.casefold() in {value.casefold() for value in RESERVED_ROOT_PATHS}:
        raise RagBuildError(
            f"document directory collides with reserved control path: {candidate!r}"
        )
    return candidate


def format_schema_errors(errors: Sequence[Mapping[str, str]], *, label: str) -> str:
    preview = "; ".join(
        f"{error.get('path', '$')}: {error.get('message', 'invalid')}"
        for error in errors[:8]
    )
    suffix = "" if len(errors) <= 8 else f"; and {len(errors) - 8} more"
    return f"{label} failed schema validation: {preview}{suffix}"


def semantic_canonical_errors(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        return ["blocks must be an array"]

    block_ids: list[str] = []
    reading_orders: list[int] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            errors.append(f"blocks[{index}] must be an object")
            continue
        block_id = block.get("block_id")
        order = block.get("reading_order")
        if isinstance(block_id, str):
            block_ids.append(block_id)
        if isinstance(order, int) and not isinstance(order, bool):
            reading_orders.append(order)

    if len(block_ids) != len(set(block_ids)):
        errors.append("block_id values must be unique")
    if len(reading_orders) != len(set(reading_orders)):
        errors.append("reading_order values must be unique")
    if len(reading_orders) == len(blocks) and any(
        left >= right for left, right in zip(reading_orders, reading_orders[1:])
    ):
        errors.append("reading_order must be strictly increasing in array order")

    known_ids = set(block_ids)
    parents: dict[str, str | None] = {}
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("block_id"), str):
            parent = block.get("parent_block_id")
            parents[block["block_id"]] = parent if isinstance(parent, str) else None
    for block_id, parent_id in parents.items():
        if parent_id is not None and parent_id not in known_ids:
            errors.append(f"dangling parent_block_id {parent_id!r} for {block_id!r}")
            continue
        visited = {block_id}
        cursor = parent_id
        while cursor is not None:
            if cursor in visited:
                errors.append(f"cyclic parent_block_id chain for {block_id!r}")
                break
            visited.add(cursor)
            cursor = parents.get(cursor)

    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_id = block.get("block_id", "UNKNOWN")
        if block.get("block_type") == "CAPTION":
            target = block.get("target_block_id")
            if target not in known_ids:
                errors.append(f"dangling caption target {target!r} for {block_id!r}")
        if block.get("block_type") == "TABLE":
            columns = block.get("columns")
            rows = block.get("rows")
            if isinstance(columns, list) and isinstance(rows, list):
                for row_index, row in enumerate(rows):
                    if not isinstance(row, list) or len(row) != len(columns):
                        errors.append(
                            f"table row width mismatch for {block_id!r} row {row_index}"
                        )
        provenance = block.get("provenance")
        if not isinstance(provenance, dict):
            continue
        box = provenance.get("bounding_box")
        if isinstance(box, dict):
            numeric_keys = ("x", "y", "width", "height", "page_width", "page_height")
            if all(
                isinstance(box.get(key), (int, float))
                and not isinstance(box.get(key), bool)
                for key in numeric_keys
            ):
                if box["x"] + box["width"] > box["page_width"]:
                    errors.append(f"horizontal bounding-box overflow for {block_id!r}")
                if box["y"] + box["height"] > box["page_height"]:
                    errors.append(f"vertical bounding-box overflow for {block_id!r}")
    return errors


def validate_canonical(payload: object, *, source_reference: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RagBuildError(f"canonical input must be a JSON object: {source_reference}")
    try:
        validator = InternalSchemaValidator(CANONICAL_SCHEMA, SCHEMA_ROOT)
        schema_errors = validator.validate(payload)
    except ValidationToolError as exc:
        raise RagBuildError(f"cannot run bundled canonical validator: {exc}") from exc
    if schema_errors:
        raise RagBuildError(
            format_schema_errors(schema_errors, label=f"canonical input {source_reference}")
        )
    semantic_errors = semantic_canonical_errors(payload)
    if semantic_errors:
        raise RagBuildError(
            f"canonical input {source_reference} failed semantic structural validation: "
            + "; ".join(semantic_errors[:12])
        )
    if payload.get("structural_validation_status") in {
        "FAIL",
        "HUMAN_REVIEW_REQUIRED",
    }:
        raise RagBuildError(
            f"canonical input {source_reference} declares structural_validation_status "
            f"{payload['structural_validation_status']!r}; refusing a PASS RAG package"
        )
    return payload


def load_template(path: Path, *, expected_artifact: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink():
        raise RagBuildError(f"bundled template must not be a symlink: {path}")
    data = read_regular_nofollow(path, label="bundled template", max_bytes=MAX_CONFIG_BYTES)
    value = load_json(data, label=f"template {path.name}")
    if not isinstance(value, dict) or value.get("artifact_name") != expected_artifact:
        raise RagBuildError(f"invalid bundled template contract: {path.name}")
    if value.get("template_version") != "1.0.0":
        raise RagBuildError(f"unsupported bundled template version: {path.name}")
    return value, data


def load_runtime_release_version() -> str:
    if RELEASE_VERSION_FILE.is_symlink():
        raise RagBuildError(
            f"bundled release version file must not be a symlink: {RELEASE_VERSION_FILE}"
        )
    data = read_regular_nofollow(
        RELEASE_VERSION_FILE,
        label="bundled release version",
        max_bytes=256,
    )
    try:
        value = data.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise RagBuildError("bundled release version must be UTF-8") from exc
    if not SEMVER_PATTERN.fullmatch(value):
        raise RagBuildError(f"invalid bundled release version: {value!r}")
    return value


def load_sources(
    root: Path,
    raw_inputs: Sequence[str],
    *,
    explicit_assets_root: Path | None,
) -> list[CanonicalSource]:
    sources: list[CanonicalSource] = []
    document_ids: set[str] = set()
    directory_keys: set[str] = set()
    inode_keys: set[tuple[int, int]] = set()
    for raw_input in raw_inputs:
        path = resolve_regular_file(root, raw_input, label="canonical input")
        source_stat = path.stat(follow_symlinks=False)
        inode_key = (source_stat.st_dev, source_stat.st_ino)
        if inode_key in inode_keys:
            raise RagBuildError("canonical inputs must not be duplicate paths or hardlink aliases")
        inode_keys.add(inode_key)
        raw_bytes = read_regular_nofollow(
            path,
            label="canonical input",
            max_bytes=MAX_CANONICAL_BYTES,
        )
        source_reference = path.relative_to(root).as_posix()
        payload = validate_canonical(
            load_json(raw_bytes, label=f"canonical input {source_reference}"),
            source_reference=source_reference,
        )
        document_id = payload["document_id"]
        if not isinstance(document_id, str) or not IDENTIFIER_PATTERN.fullmatch(document_id):
            raise RagBuildError(f"invalid canonical document_id: {document_id!r}")
        if document_id in document_ids:
            raise RagBuildError(f"duplicate document_id: {document_id}")
        document_ids.add(document_id)
        directory = stable_directory(document_id)
        directory_key = unicodedata.normalize("NFC", directory).casefold()
        if directory_key in directory_keys:
            raise RagBuildError(f"case-insensitive document-directory collision: {directory}")
        directory_keys.add(directory_key)
        assets_root = explicit_assets_root or path.parent
        sources.append(
            CanonicalSource(
                path=path,
                source_reference=source_reference,
                raw_bytes=raw_bytes,
                payload=payload,
                document_id=document_id,
                directory=directory,
                assets_root=assets_root,
            )
        )
    return sorted(sources, key=lambda item: item.document_id)


def validate_chunk_config(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RagBuildError("chunk config must be a JSON object")
    required = {
        "config_version",
        "strategy",
        "unit",
        "max_blocks_per_chunk",
        "overlap_blocks",
        "heading_handling",
        "table_handling",
        "language_basis",
        "tokenizer_basis",
        "required_metadata_fields",
    }
    unknown = set(value) - required
    missing = required - set(value)
    if unknown or missing:
        raise RagBuildError(
            f"chunk config keys mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    if not isinstance(value["config_version"], str) or not SEMVER_PATTERN.fullmatch(
        value["config_version"]
    ):
        raise RagBuildError("chunk config config_version must be semantic version")
    expected_constants = {
        "strategy": "CANONICAL_BLOCK_GROUPS",
        "unit": "BLOCK",
        "heading_handling": "TRACK_HEADING_PATH",
        "table_handling": "KEEP_BLOCK_WHOLE",
        "tokenizer_basis": "NOT_APPLICABLE",
    }
    for key, expected in expected_constants.items():
        if value.get(key) != expected:
            raise RagBuildError(f"unsupported chunk config {key}; expected {expected!r}")
    maximum = value["max_blocks_per_chunk"]
    overlap = value["overlap_blocks"]
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 1000:
        raise RagBuildError("max_blocks_per_chunk must be an integer from 1 to 1000")
    if (
        not isinstance(overlap, int)
        or isinstance(overlap, bool)
        or overlap < 0
        or overlap >= maximum
    ):
        raise RagBuildError("overlap_blocks must be an integer below max_blocks_per_chunk")
    if not isinstance(value["language_basis"], str) or not value["language_basis"].strip():
        raise RagBuildError("language_basis must be a non-empty explicit string")
    fields = value["required_metadata_fields"]
    if (
        not isinstance(fields, list)
        or any(not isinstance(field, str) for field in fields)
        or len(fields) != len(set(fields))
    ):
        raise RagBuildError("required_metadata_fields must be a unique string array")
    field_set = set(fields)
    if not CHUNK_REQUIRED_FIELDS.issubset(field_set):
        raise RagBuildError(
            "required_metadata_fields must include document_id, block_ids, and source_locators"
        )
    unsupported = field_set - CHUNK_AVAILABLE_FIELDS
    if unsupported:
        raise RagBuildError(f"unsupported required chunk metadata fields: {sorted(unsupported)}")
    return value


def load_chunking_request(
    root: Path,
    *,
    target_id: str | None,
    raw_config: str | None,
) -> tuple[ChunkingRequest | None, Path | None]:
    if (target_id is None) != (raw_config is None):
        raise RagBuildError("--target-id and --chunk-config must be supplied together")
    if target_id is None:
        return None, None
    if not target_id.strip() or any(ord(character) < 32 for character in target_id):
        raise RagBuildError("--target-id must be a non-empty control-free string")
    config_path = resolve_regular_file(root, raw_config or "", label="chunk config")
    raw_bytes = read_regular_nofollow(
        config_path,
        label="chunk config",
        max_bytes=MAX_CONFIG_BYTES,
    )
    config = validate_chunk_config(load_json(raw_bytes, label="chunk config"))
    return (
        ChunkingRequest(
            target_id=target_id,
            config=config,
            raw_bytes=raw_bytes,
            checksum=sha256_bytes(raw_bytes),
        ),
        config_path,
    )


def escape_markdown(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    escaped = re.sub(r"([`*_{}\[\]()#+.!<>|])", r"\\\1", escaped)
    return escaped


def escape_table_cell(value: str | None) -> str:
    if value is None:
        return "⟦CANONICAL_NULL⟧"
    return escape_markdown(value).replace("\r\n", " ↵ ").replace("\n", " ↵ ").replace("\r", " ↵ ")


def source_locator(block: Mapping[str, Any], document_id: str) -> str:
    provenance = block["provenance"]
    page = provenance["source_page"]
    region = provenance["source_region"]
    return (
        f"> **Generated source locator:** document `{escape_markdown(document_id)}`; "
        f"block `{escape_markdown(block['block_id'])}`; page `{escape_markdown(str(page))}`; "
        f"region `{escape_markdown(region)}`"
    )


def render_markdown(source: CanonicalSource) -> bytes:
    lines = [
        "> **Generated package note:** The text and tables below are a structural derivative; "
        "source locators are generated annotations, not source text.",
        "",
    ]
    for block in source.payload["blocks"]:
        lines.append(source_locator(block, source.document_id))
        lines.append("")
        block_type = block["block_type"]
        if block_type == "HEADING":
            lines.append(f"{'#' * block['level']} {escape_markdown(block['text'])}")
        elif block_type == "PARAGRAPH":
            lines.append(escape_markdown(block["text"]))
        elif block_type == "TABLE":
            columns = [escape_table_cell(value) for value in block["columns"]]
            lines.append("| " + " | ".join(columns) + " |")
            lines.append("| " + " | ".join("---" for _ in columns) + " |")
            for row in block["rows"]:
                lines.append("| " + " | ".join(escape_table_cell(value) for value in row) + " |")
        elif block_type == "IMAGE":
            alt = block["alt_text"] if block["alt_text"] is not None else "Image"
            encoded_path = quote(block["asset_reference"], safe="/._-")
            lines.append(f"![{escape_markdown(alt)}]({encoded_path})")
        elif block_type == "CAPTION":
            lines.append(
                f"*Caption for `{escape_markdown(block['target_block_id'])}`: "
                f"{escape_markdown(block['text'])}*"
            )
        else:
            raise RagBuildError(f"unsupported canonical block type: {block_type!r}")
        lines.extend(("", ""))
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def plain_block_text(block: Mapping[str, Any]) -> str:
    block_type = block["block_type"]
    if block_type in {"HEADING", "PARAGRAPH", "CAPTION"}:
        return block["text"]
    if block_type == "TABLE":
        lines = [" | ".join(block["columns"])]
        lines.extend(" | ".join("" if value is None else value for value in row) for row in block["rows"])
        return "\n".join(lines)
    if block_type == "IMAGE":
        return block["alt_text"] or ""
    raise RagBuildError(f"unsupported canonical block type: {block_type!r}")


def heading_path_before(blocks: Sequence[Mapping[str, Any]], index: int) -> list[str]:
    levels: list[str] = []
    for block in blocks[: index + 1]:
        if block["block_type"] != "HEADING":
            continue
        level = block["level"]
        levels = levels[: level - 1]
        while len(levels) < level - 1:
            levels.append("UNKNOWN")
        levels.append(block["text"])
    return levels


def render_chunks(
    source: CanonicalSource,
    request: ChunkingRequest,
    *,
    classification: list[str],
) -> bytes:
    blocks = source.payload["blocks"]
    maximum = request.config["max_blocks_per_chunk"]
    overlap = request.config["overlap_blocks"]
    step = maximum - overlap
    records: list[dict[str, Any]] = []
    sequence = 1
    for start in range(0, len(blocks), step):
        group = blocks[start : start + maximum]
        if not group:
            break
        block_ids = [block["block_id"] for block in group]
        text = "\n\n".join(plain_block_text(block) for block in group)
        identity = canonical_json_bytes(
            {
                "document_id": source.document_id,
                "target_id": request.target_id,
                "config_checksum": request.checksum,
                "sequence": sequence,
                "block_ids": block_ids,
                "text_checksum": sha256_bytes(text.encode("utf-8")),
            },
            pretty=False,
        )
        records.append(
            {
                "block_ids": block_ids,
                "character_count": len(text),
                "chunk_id": f"chunk-{sha256_bytes(identity)[:24]}",
                "classification": classification,
                "count_method": "PYTHON_UNICODE_CODE_POINTS",
                "document_id": source.document_id,
                "heading_path": heading_path_before(blocks, start),
                "sequence": sequence,
                "source_locators": [
                    {
                        "block_id": block["block_id"],
                        "source_page": block["provenance"]["source_page"],
                        "source_region": block["provenance"]["source_region"],
                    }
                    for block in group
                ],
                "split_warnings": [],
                "text": text,
                "token_count": None,
                "tokenizer_basis": request.config["tokenizer_basis"],
            }
        )
        sequence += 1
        if start + maximum >= len(blocks):
            break
    return b"".join(canonical_json_bytes(record, pretty=False) for record in records)


def png_pass_layout(
    width: int,
    height: int,
    *,
    channels: int,
    bit_depth: int,
    interlace: int,
) -> tuple[list[tuple[int, int]], int]:
    if width * height > MAX_PNG_PIXELS:
        raise RagBuildError("PNG pixel count exceeds the bounded validation limit")
    if interlace == 0:
        dimensions = [(width, height)]
    else:
        dimensions = []
        for x_start, y_start, x_step, y_step in (
            (0, 0, 8, 8),
            (4, 0, 8, 8),
            (0, 4, 4, 8),
            (2, 0, 4, 4),
            (0, 2, 2, 4),
            (1, 0, 2, 2),
            (0, 1, 1, 2),
        ):
            pass_width = 0 if width <= x_start else (width - x_start + x_step - 1) // x_step
            pass_height = 0 if height <= y_start else (height - y_start + y_step - 1) // y_step
            if pass_width and pass_height:
                dimensions.append((pass_width, pass_height))
    scanline_count = sum(pass_height for _, pass_height in dimensions)
    if scanline_count > MAX_PNG_SCANLINES:
        raise RagBuildError("PNG scanline count exceeds the bounded validation limit")
    expected = 0
    for pass_width, pass_height in dimensions:
        row_bytes = (pass_width * channels * bit_depth + 7) // 8
        expected += pass_height * (1 + row_bytes)
    if expected > MAX_PNG_DECODED_BYTES:
        raise RagBuildError("PNG decoded scanlines exceed the bounded validation limit")
    return dimensions, expected


def decompress_png_idat(
    parts: Sequence[bytes],
    *,
    expected_size: int,
    reference: str,
) -> bytes:
    decompressor = zlib.decompressobj()
    decoded = bytearray()
    try:
        for part in parts:
            pending = part
            while pending:
                maximum = expected_size - len(decoded) + 1
                produced = decompressor.decompress(pending, max(1, maximum))
                decoded.extend(produced)
                if len(decoded) > expected_size:
                    raise RagBuildError(
                        f"PNG IDAT expands beyond the declared scanline size: {reference}"
                    )
                next_pending = decompressor.unconsumed_tail
                if next_pending and len(next_pending) == len(pending) and not produced:
                    raise RagBuildError(f"PNG IDAT decompressor made no progress: {reference}")
                pending = next_pending
                if decompressor.unused_data:
                    raise RagBuildError(
                        f"PNG IDAT contains trailing or multiple zlib streams: {reference}"
                    )
        maximum = expected_size - len(decoded) + 1
        decoded.extend(decompressor.flush(max(1, maximum)))
    except zlib.error as exc:
        raise RagBuildError(f"PNG IDAT zlib stream is invalid: {reference}") from exc
    if len(decoded) > expected_size:
        raise RagBuildError(
            f"PNG IDAT expands beyond the declared scanline size: {reference}"
        )
    if not decompressor.eof:
        raise RagBuildError(f"PNG IDAT zlib stream is truncated: {reference}")
    if decompressor.unused_data or decompressor.unconsumed_tail:
        raise RagBuildError(f"PNG IDAT has unconsumed compressed data: {reference}")
    if len(decoded) != expected_size:
        raise RagBuildError(
            f"PNG decoded scanline size does not match IHDR dimensions: {reference}"
        )
    return bytes(decoded)


def validate_png_asset(data: bytes, *, reference: str) -> None:
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise RagBuildError(f"PNG signature mismatch: {reference}")
    position = len(signature)
    chunk_index = 0
    seen_ihdr = False
    seen_idat = False
    seen_iend = False
    seen_plte = False
    idat_closed = False
    idat_parts: list[bytes] = []
    width = height = bit_depth = color_type = interlace = 0
    while position < len(data):
        if len(data) - position < 12:
            raise RagBuildError(f"truncated PNG chunk structure: {reference}")
        length = int.from_bytes(data[position : position + 4], "big")
        chunk_type = data[position + 4 : position + 8]
        if not re.fullmatch(rb"[A-Za-z]{4}", chunk_type):
            raise RagBuildError(f"invalid PNG chunk type: {reference}")
        end = position + 12 + length
        if end > len(data):
            raise RagBuildError(f"truncated PNG chunk payload: {reference}")
        payload = data[position + 8 : position + 8 + length]
        declared_crc = int.from_bytes(data[position + 8 + length : end], "big")
        actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        if declared_crc != actual_crc:
            raise RagBuildError(f"PNG chunk CRC mismatch: {reference}")
        if chunk_index == 0 and chunk_type != b"IHDR":
            raise RagBuildError(f"PNG IHDR must be the first chunk: {reference}")
        if chunk_type == b"IHDR":
            if seen_ihdr or length != 13:
                raise RagBuildError(f"invalid or duplicate PNG IHDR: {reference}")
            seen_ihdr = True
            width = int.from_bytes(payload[0:4], "big")
            height = int.from_bytes(payload[4:8], "big")
            bit_depth = payload[8]
            color_type = payload[9]
            interlace = payload[12]
            valid_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if (
                width == 0
                or height == 0
                or bit_depth not in valid_depths.get(color_type, set())
                or payload[10] != 0
                or payload[11] != 0
                or interlace not in {0, 1}
            ):
                raise RagBuildError(f"invalid PNG IHDR fields: {reference}")
        elif chunk_type == b"PLTE":
            if not seen_ihdr or seen_idat or seen_plte:
                raise RagBuildError(f"invalid PNG PLTE ordering: {reference}")
            entries, remainder = divmod(length, 3)
            if remainder or not 1 <= entries <= 256:
                raise RagBuildError(f"invalid PNG PLTE length: {reference}")
            if color_type in {0, 4} or (color_type == 3 and entries > 2**bit_depth):
                raise RagBuildError(f"PNG PLTE is incompatible with IHDR: {reference}")
            seen_plte = True
        elif chunk_type == b"IDAT":
            if not seen_ihdr or seen_iend or idat_closed:
                raise RagBuildError(f"invalid PNG IDAT ordering: {reference}")
            seen_idat = True
            idat_parts.append(payload)
        elif chunk_type == b"IEND":
            if length != 0 or seen_iend:
                raise RagBuildError(f"invalid or duplicate PNG IEND: {reference}")
            seen_iend = True
            if end != len(data):
                raise RagBuildError(f"trailing bytes after PNG IEND: {reference}")
        elif chunk_type[0] & 0x20 == 0:
            raise RagBuildError(f"unknown critical PNG chunk: {reference}")
        if seen_idat and chunk_type not in {b"IDAT", b"IEND"}:
            idat_closed = True
        position = end
        chunk_index += 1
        if chunk_index > 100000:
            raise RagBuildError(f"PNG contains too many chunks: {reference}")
    if not (seen_ihdr and seen_idat and seen_iend):
        raise RagBuildError(f"incomplete PNG structure: {reference}")
    if color_type == 3 and not seen_plte:
        raise RagBuildError(f"indexed PNG requires a PLTE chunk: {reference}")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    try:
        layout, expected_size = png_pass_layout(
            width,
            height,
            channels=channels,
            bit_depth=bit_depth,
            interlace=interlace,
        )
    except RagBuildError as exc:
        raise RagBuildError(f"{exc}: {reference}") from exc
    decoded = decompress_png_idat(
        idat_parts,
        expected_size=expected_size,
        reference=reference,
    )
    offset = 0
    for pass_width, pass_height in layout:
        row_bytes = (pass_width * channels * bit_depth + 7) // 8
        for _ in range(pass_height):
            if decoded[offset] not in {0, 1, 2, 3, 4}:
                raise RagBuildError(f"invalid PNG scanline filter byte: {reference}")
            offset += 1 + row_bytes
    if offset != len(decoded):
        raise RagBuildError(f"PNG scanline layout validation failed: {reference}")


def validate_jpeg_asset(data: bytes, *, reference: str) -> None:
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        raise RagBuildError(f"JPEG SOI signature mismatch: {reference}")
    position = 2
    seen_sof = False
    seen_sos = False
    in_scan = False
    while position < len(data):
        if in_scan:
            marker_start = data.find(b"\xff", position)
            if marker_start < 0:
                raise RagBuildError(f"JPEG scan has no EOI marker: {reference}")
            position = marker_start
        if data[position] != 0xFF:
            raise RagBuildError(f"invalid JPEG marker alignment: {reference}")
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            raise RagBuildError(f"truncated JPEG marker: {reference}")
        marker = data[position]
        position += 1
        if in_scan and marker == 0x00:
            in_scan = True
            continue
        if marker in range(0xD0, 0xD8) or marker == 0x01:
            continue
        if marker == 0xD9:
            if position != len(data):
                raise RagBuildError(f"trailing bytes after JPEG EOI: {reference}")
            if not seen_sof or not seen_sos:
                raise RagBuildError(f"JPEG lacks required SOF/SOS structure: {reference}")
            return
        in_scan = False
        if marker in {0x00, 0xD8}:
            raise RagBuildError(f"invalid JPEG marker sequence: {reference}")
        if position + 2 > len(data):
            raise RagBuildError(f"truncated JPEG segment length: {reference}")
        segment_length = int.from_bytes(data[position : position + 2], "big")
        if segment_length < 2 or position + segment_length > len(data):
            raise RagBuildError(f"invalid JPEG segment length: {reference}")
        payload = data[position + 2 : position + segment_length]
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if len(payload) < 6:
                raise RagBuildError(f"truncated JPEG SOF segment: {reference}")
            height = int.from_bytes(payload[1:3], "big")
            width = int.from_bytes(payload[3:5], "big")
            components = payload[5]
            if width == 0 or height == 0 or components == 0 or len(payload) != 6 + 3 * components:
                raise RagBuildError(f"invalid JPEG SOF fields: {reference}")
            seen_sof = True
        if marker == 0xDA:
            if len(payload) < 4:
                raise RagBuildError(f"truncated JPEG SOS segment: {reference}")
            components = payload[0]
            if components == 0 or len(payload) != 1 + 2 * components + 3:
                raise RagBuildError(f"invalid JPEG SOS fields: {reference}")
            seen_sos = True
            in_scan = True
        position += segment_length
    raise RagBuildError(f"JPEG lacks a terminal EOI marker: {reference}")


def validate_webp_asset(data: bytes, *, reference: str) -> None:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise RagBuildError(f"WebP RIFF/WEBP signature mismatch: {reference}")
    declared_size = int.from_bytes(data[4:8], "little")
    if declared_size != len(data) - 8:
        raise RagBuildError(f"WebP RIFF size mismatch: {reference}")
    position = 12
    image_chunks = 0
    while position < len(data):
        if len(data) - position < 8:
            raise RagBuildError(f"truncated WebP chunk header: {reference}")
        chunk_type = data[position : position + 4]
        chunk_length = int.from_bytes(data[position + 4 : position + 8], "little")
        payload_start = position + 8
        payload_end = payload_start + chunk_length
        padded_end = payload_end + (chunk_length & 1)
        if padded_end > len(data):
            raise RagBuildError(f"truncated WebP chunk payload: {reference}")
        payload = data[payload_start:payload_end]
        if chunk_type == b"VP8 ":
            if len(payload) < 10 or payload[3:6] != b"\x9d\x01\x2a":
                raise RagBuildError(f"invalid WebP VP8 frame header: {reference}")
            width = int.from_bytes(payload[6:8], "little") & 0x3FFF
            height = int.from_bytes(payload[8:10], "little") & 0x3FFF
            if width == 0 or height == 0:
                raise RagBuildError(f"invalid WebP VP8 dimensions: {reference}")
            image_chunks += 1
        elif chunk_type == b"VP8L":
            if len(payload) < 5 or payload[0] != 0x2F:
                raise RagBuildError(f"invalid WebP VP8L frame header: {reference}")
            packed = int.from_bytes(payload[1:5], "little")
            width = (packed & 0x3FFF) + 1
            height = ((packed >> 14) & 0x3FFF) + 1
            if width == 0 or height == 0:
                raise RagBuildError(f"invalid WebP VP8L dimensions: {reference}")
            image_chunks += 1
        elif chunk_type == b"VP8X":
            if len(payload) != 10:
                raise RagBuildError(f"invalid WebP VP8X header: {reference}")
            width = int.from_bytes(payload[4:7], "little") + 1
            height = int.from_bytes(payload[7:10], "little") + 1
            if width == 0 or height == 0:
                raise RagBuildError(f"invalid WebP VP8X dimensions: {reference}")
        position = padded_end
    if position != len(data) or image_chunks != 1:
        raise RagBuildError(f"WebP must contain exactly one image payload chunk: {reference}")


def split_xml_name(raw_name: str) -> tuple[str, str]:
    if raw_name.startswith("{") and "}" in raw_name:
        namespace, local = raw_name[1:].split("}", 1)
        return namespace, local
    if ":" in raw_name:
        _, local = raw_name.rsplit(":", 1)
        return "", local
    return "", raw_name


def validate_svg_css_value(value: str, *, reference: str) -> None:
    lowered = value.casefold()
    if "@import" in lowered or "expression(" in lowered or "-moz-binding" in lowered:
        raise RagBuildError(f"active or external SVG CSS is prohibited: {reference}")
    if "/*" in value or "\\" in value:
        raise RagBuildError(f"obfuscated SVG CSS is prohibited: {reference}")
    matches = list(re.finditer(r"url\s*\(([^)]*)\)", value, re.I))
    if "url" in lowered and not matches:
        raise RagBuildError(f"malformed SVG CSS url() is prohibited: {reference}")
    for match in matches:
        target = match.group(1).strip().strip("'\"").strip()
        if re.fullmatch(r"#[A-Za-z_][A-Za-z0-9_.:-]*", target) is None:
            raise RagBuildError(f"external SVG CSS url() is prohibited: {reference}")
    if re.search(r"(?:https?|ftp|file|data|javascript)\s*:", lowered):
        raise RagBuildError(f"external or active SVG attribute content is prohibited: {reference}")


def validate_svg_asset(data: bytes, *, reference: str) -> None:
    if len(data) > MAX_SVG_BYTES:
        raise RagBuildError(f"SVG exceeds the {MAX_SVG_BYTES}-byte safety limit: {reference}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RagBuildError(f"SVG asset must be UTF-8 text: {reference}") from exc
    lowered = text.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise RagBuildError(f"SVG DTD/entity declarations are prohibited: {reference}")
    processing_instructions = re.findall(r"<\?\s*([A-Za-z_:][A-Za-z0-9_.:-]*)", text)
    if any(name.casefold() != "xml" for name in processing_instructions):
        raise RagBuildError(f"SVG processing instructions are prohibited: {reference}")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise RagBuildError(f"SVG XML structure is invalid: {reference}: {exc}") from exc
    root_namespace, root_local = split_xml_name(root.tag)
    if root_local.casefold() != "svg" or root_namespace not in {"", SVG_NAMESPACE}:
        raise RagBuildError(f"SVG root element/namespace is invalid: {reference}")
    for element in root.iter():
        namespace, local = split_xml_name(element.tag)
        local_key = local.casefold()
        if local_key in SVG_PROHIBITED_ELEMENTS:
            raise RagBuildError(f"prohibited SVG element {local!r}: {reference}")
        if namespace not in {"", SVG_NAMESPACE}:
            raise RagBuildError(f"foreign SVG element namespace is prohibited: {reference}")
        if local_key not in SVG_ALLOWED_ELEMENTS:
            raise RagBuildError(f"SVG element is not allowlisted: {local!r}: {reference}")
        for raw_attribute, raw_value in element.attrib.items():
            attribute_namespace, attribute_local = split_xml_name(raw_attribute)
            attribute_key = attribute_local.casefold()
            if attribute_key.startswith("on"):
                raise RagBuildError(f"SVG event attributes are prohibited: {reference}")
            if attribute_namespace not in {"", XLINK_NAMESPACE, XML_NAMESPACE}:
                raise RagBuildError(f"foreign SVG attribute namespace is prohibited: {reference}")
            if attribute_key not in SVG_ALLOWED_ATTRIBUTES:
                raise RagBuildError(
                    f"SVG attribute is not allowlisted: {attribute_local!r}: {reference}"
                )
            value = raw_value.strip()
            if attribute_key in {"href", "src"}:
                if re.fullmatch(r"#[A-Za-z_][A-Za-z0-9_.:-]*", value) is None:
                    raise RagBuildError(
                        f"external, data, or javascript SVG href/src is prohibited: {reference}"
                    )
            validate_svg_css_value(value, reference=reference)


def validate_asset_media(data: bytes, *, media_type: str, reference: str) -> None:
    expected_extensions = ASSET_EXTENSIONS.get(media_type)
    if expected_extensions is None:
        raise RagBuildError(f"unsupported asset media type: {media_type}")
    suffix = PurePosixPath(reference).suffix.casefold()
    if suffix not in expected_extensions:
        raise RagBuildError(
            f"asset extension {suffix or '<none>'!r} does not match declared "
            f"media_type {media_type!r}: {reference}"
        )
    if media_type == "image/png":
        validate_png_asset(data, reference=reference)
    elif media_type == "image/jpeg":
        validate_jpeg_asset(data, reference=reference)
    elif media_type == "image/webp":
        validate_webp_asset(data, reference=reference)
    elif media_type == "image/svg+xml":
        validate_svg_asset(data, reference=reference)
    else:
        raise RagBuildError(f"unsupported asset media type: {media_type}")


def resolve_asset(source: CanonicalSource, reference: str, *, root: Path) -> Path:
    relative = safe_relative_path(reference, label="asset_reference")
    candidate = source.assets_root.joinpath(*relative.parts)
    return resolve_regular_file(root, candidate, label="asset")


def collect_asset_source_paths(
    sources: Sequence[CanonicalSource], *, root: Path
) -> list[Path]:
    paths: dict[tuple[int, int], Path] = {}
    for source in sources:
        validate_asset_references(source.payload["blocks"])
        for block in source.payload["blocks"]:
            if block["block_type"] != "IMAGE":
                continue
            path = resolve_asset(source, block["asset_reference"], root=root)
            status = path.stat(follow_symlinks=False)
            paths[(status.st_dev, status.st_ino)] = path
    return sorted(paths.values())


def load_assets(
    source: CanonicalSource,
    *,
    root: Path,
) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    files: dict[str, bytes] = {}
    records_by_reference: dict[str, dict[str, Any]] = {}
    seen_references: dict[str, tuple[str, str]] = {}
    validate_asset_references(source.payload["blocks"])
    for block in source.payload["blocks"]:
        if block["block_type"] != "IMAGE":
            continue
        reference = block["asset_reference"]
        media_type = block["media_type"]
        path = resolve_asset(source, reference, root=root)
        data = read_regular_nofollow(path, label="asset", max_bytes=MAX_ASSET_BYTES)
        actual_digest = sha256_bytes(data)
        declared = block["asset_checksum"]
        if declared["algorithm"] != "SHA-256" or actual_digest.casefold() != declared["digest"].casefold():
            raise RagBuildError(f"asset checksum mismatch: {reference}")
        validate_asset_media(data, media_type=media_type, reference=reference)
        previous = seen_references.get(reference)
        identity = (actual_digest, media_type)
        if previous is not None and previous != identity:
            raise RagBuildError(f"conflicting duplicate asset reference: {reference}")
        seen_references[reference] = identity
        files[reference] = data
        if reference not in records_by_reference:
            records_by_reference[reference] = {
                "asset_reference": reference,
                "checksum": checksum_object(data),
                "media_type": media_type,
                "source_block_ids": [],
                "source_locators": [],
            }
        record = records_by_reference[reference]
        record["source_block_ids"].append(block["block_id"])
        record["source_locators"].append(
            {
                "block_id": block["block_id"],
                "source_page": block["provenance"]["source_page"],
                "source_region": block["provenance"]["source_region"],
            }
        )
    return files, [records_by_reference[key] for key in sorted(records_by_reference)]


def page_coverage(blocks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pages = sorted(
        {
            block["provenance"]["source_page"]
            for block in blocks
            if isinstance(block["provenance"]["source_page"], int)
            and not isinstance(block["provenance"]["source_page"], bool)
        }
    )
    return {
        "first_page": pages[0] if pages else "UNKNOWN",
        "last_page": pages[-1] if pages else "UNKNOWN",
        "pages_represented": pages,
        "status": "DERIVED_FROM_BLOCK_PROVENANCE" if pages else "UNKNOWN",
    }


def make_file_descriptor(path: str, media_type: str, data: bytes) -> dict[str, Any]:
    safe_relative_path(path, label="manifest path")
    return {
        "path": path,
        "media_type": media_type,
        "creation_status": "CREATED",
        "qa_status": "PASS",
        "checksum": checksum_object(data),
        "limitations": [],
    }


def make_inventory_record(
    path: str,
    media_type: str,
    data: bytes,
    *,
    purpose: str,
    required: bool,
    source_block_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        **make_file_descriptor(path, media_type, data),
        "purpose": purpose,
        "required": required,
        "size_bytes": len(data),
        "source_block_ids": list(source_block_ids),
    }


def deduplicate_strings(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def build_document_files(
    source: CanonicalSource,
    *,
    root: Path,
    package_id: str,
    metadata_template: Mapping[str, Any],
    metadata_template_bytes: bytes,
    manifest_template: Mapping[str, Any],
    manifest_template_bytes: bytes,
    chunking: ChunkingRequest | None,
    runtime_release_version: str,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    relative_files: dict[str, bytes] = {}
    blocks = source.payload["blocks"]
    block_ids = [block["block_id"] for block in blocks]
    defaults = metadata_template.get("defaults")
    if not isinstance(defaults, dict):
        raise RagBuildError("rag-metadata.json defaults must be an object")
    classification = defaults.get("classification")
    if (
        not isinstance(classification, list)
        or not classification
        or any(not isinstance(value, str) or not value for value in classification)
    ):
        raise RagBuildError("rag-metadata.json classification default is invalid")

    markdown = render_markdown(source)
    relative_files["document.md"] = markdown
    assets, asset_records = load_assets(source, root=root)
    relative_files.update(assets)

    title = next(
        (
            block["text"]
            for block in blocks
            if block["block_type"] == "HEADING" and block["level"] == 1
        ),
        "UNKNOWN",
    )
    limitations = deduplicate_strings(
        [
            *source.payload["limitations"],
            "Original source filename/reference is unavailable in the canonical-content contract.",
            *(
                ["Canonical null table cells are rendered as ⟦CANONICAL_NULL⟧."]
                if any(
                    block["block_type"] == "TABLE"
                    and any(value is None for row in block["rows"] for value in row)
                    for block in blocks
                )
                else []
            ),
            "Live target ingestion and retrieval quality were not tested.",
        ]
    )
    metadata = {
        "metadata_version": "1.0.0",
        "package_id": package_id,
        "document_id": source.document_id,
        "content_id": source.payload["content_id"],
        "title": title,
        "document_type": defaults.get("document_type", "UNKNOWN"),
        "language": defaults.get("language", "UNKNOWN"),
        "extraction_method": defaults.get("extraction_method", "UNKNOWN"),
        "classification": classification,
        "source": {
            "source_filename": "UNKNOWN",
            "source_reference": "UNKNOWN",
            "source_content_id": source.payload["source_content_id"],
            "source_hash_status": source.payload["source_hash_status"],
        },
        "canonical": {
            "input_filename": source.path.name,
            "input_reference": source.source_reference,
            "schema_version": source.payload["schema_version"],
            "skill_id": source.payload["skill_id"],
            "skill_release_version": source.payload["skill_release_version"],
            "fidelity_mode": source.payload["fidelity_mode"],
            "reading_order_status": source.payload["reading_order_status"],
            "declared_structural_validation_status": source.payload[
                "structural_validation_status"
            ],
            "builder_schema_validation_status": "PASS",
            "builder_semantic_validation_status": "PASS",
            "canonical_input_checksum": {
                "algorithm": "SHA-256",
                "digest": sha256_bytes(source.raw_bytes),
                "computed_at": "UNKNOWN",
                "object_role": "DERIVATIVE",
            },
        },
        "builder": {
            "skill_id": SKILL_ID,
            "skill_release_version": runtime_release_version,
            "tool_name": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "execution_mode": "OFFLINE_DETERMINISTIC",
        },
        "coverage": {
            "block_count": len(blocks),
            "block_type_counts": dict(sorted(Counter(block["block_type"] for block in blocks).items())),
            "page_range": page_coverage(blocks),
        },
        "assets": asset_records,
        "review_status": {
            "package_structural_qa": "PASS",
            "source_fidelity_review": "NOT_TESTED",
            "target_ingestion": "NOT_TESTED",
        },
        "limitations": limitations,
        "template": {
            "name": METADATA_TEMPLATE.name,
            "version": metadata_template["template_version"],
            "checksum": f"sha256:{sha256_bytes(metadata_template_bytes)}",
        },
    }
    metadata_bytes = canonical_json_bytes(metadata)
    relative_files["metadata.json"] = metadata_bytes

    chunks_bytes: bytes | None = None
    if chunking is not None:
        chunks_bytes = render_chunks(source, chunking, classification=classification)
        relative_files["chunks.jsonl"] = chunks_bytes

    inventory: list[dict[str, Any]] = [
        make_inventory_record(
            "document.md",
            "text/markdown",
            markdown,
            purpose="RAG_SOURCE_VIEW",
            required=True,
            source_block_ids=block_ids,
        ),
        make_inventory_record(
            "metadata.json",
            "application/json",
            metadata_bytes,
            purpose="DOCUMENT_AND_PROVENANCE_METADATA",
            required=True,
            source_block_ids=block_ids,
        ),
    ]
    for asset in asset_records:
        inventory.append(
            make_inventory_record(
                asset["asset_reference"],
                asset["media_type"],
                relative_files[asset["asset_reference"]],
                purpose="CANONICAL_IMAGE_ASSET",
                required=True,
                source_block_ids=asset["source_block_ids"],
            )
        )
    if chunks_bytes is not None:
        inventory.append(
            make_inventory_record(
                "chunks.jsonl",
                "application/x-ndjson",
                chunks_bytes,
                purpose="TARGET_SPECIFIC_DERIVED_CHUNKS",
                required=True,
                source_block_ids=block_ids,
            )
        )
    assert_path_set_has_no_collisions(
        [record["path"] for record in inventory],
        label="document manifest inventory",
    )
    inventory.sort(key=lambda item: item["path"])

    expected_scope = "PAYLOAD_FILES_EXCLUDING_THIS_MANIFEST_AND_RAG_PACKAGE_CONTROL"
    if manifest_template.get("checksum_scope") != expected_scope:
        raise RagBuildError("rag-manifest.json checksum_scope is invalid")
    manifest = {
        "manifest_version": manifest_template.get("manifest_version"),
        "package_id": package_id,
        "document_id": source.document_id,
        "directory": source.directory,
        "created_by": {
            "skill_id": SKILL_ID,
            "skill_release_version": runtime_release_version,
            "tool_name": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "execution_mode": "OFFLINE_DETERMINISTIC",
        },
        "checksum_scope": expected_scope,
        "control_reference": "../rag-package.json",
        "listed_payload_file_count": len(inventory),
        "document_file_count_including_manifest": len(inventory) + 1,
        "files": inventory,
        "warnings": [],
        "exclusions": [
            "manifest.json is checksummed by rag-package.json and is not self-listed.",
            "rag-package.json is the schema-valid control object and is outside this manifest checksum scope.",
        ],
        "unresolved_items": [],
        "qa": {
            "status": "PASS",
            "scope": manifest_template.get("qa_scope", "STRUCTURAL_PACKAGE_BUILD_ONLY"),
            "source_fidelity_review": "NOT_TESTED",
            "target_ingestion": "NOT_TESTED",
        },
        "limitations": limitations,
        "template": {
            "name": MANIFEST_TEMPLATE.name,
            "version": manifest_template["template_version"],
            "checksum": f"sha256:{sha256_bytes(manifest_template_bytes)}",
        },
    }
    manifest_bytes = canonical_json_bytes(manifest)
    relative_files["manifest.json"] = manifest_bytes
    assert_path_set_has_no_collisions(
        list(relative_files),
        label="document package member",
    )

    asset_descriptors = [
        make_file_descriptor(
            asset["asset_reference"],
            asset["media_type"],
            relative_files[asset["asset_reference"]],
        )
        for asset in asset_records
    ]
    chunk_descriptor = None
    if chunks_bytes is not None and chunking is not None:
        chunk_descriptor = {
            **make_file_descriptor(
                "chunks.jsonl", "application/x-ndjson", chunks_bytes
            ),
            "target_id": chunking.target_id,
            "chunking_config_checksum": chunking.checksum,
        }
    control_document = {
        "document_id": source.document_id,
        "directory": source.directory,
        "status": "PASS",
        "document_markdown": make_file_descriptor(
            "document.md", "text/markdown", markdown
        ),
        "metadata": make_file_descriptor(
            "metadata.json", "application/json", metadata_bytes
        ),
        "manifest": make_file_descriptor(
            "manifest.json", "application/json", manifest_bytes
        ),
        "assets": asset_descriptors,
        "chunks": chunk_descriptor,
        "limitations": limitations,
    }
    return relative_files, control_document


def compute_package_id(
    sources: Sequence[CanonicalSource],
    package_kind: str,
    chunking: ChunkingRequest | None,
    runtime_release_version: str,
) -> str:
    identity = {
        "tool_name": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "skill_release_version": runtime_release_version,
        "package_kind": package_kind,
        "documents": [
            {
                "document_id": source.document_id,
                "canonical_checksum": sha256_bytes(source.raw_bytes),
            }
            for source in sources
        ],
        "chunking": (
            None
            if chunking is None
            else {
                "target_id": chunking.target_id,
                "config_checksum": chunking.checksum,
            }
        ),
    }
    return f"rag-{package_kind.casefold()}-{sha256_bytes(canonical_json_bytes(identity, pretty=False))[:24]}"


def build_collection_manifest(
    package_id: str,
    documents: Sequence[Mapping[str, Any]],
    files: Mapping[str, bytes],
) -> bytes:
    entries = []
    for document in documents:
        manifest_path = f"{document['directory']}/manifest.json"
        manifest_bytes = files[manifest_path]
        occurrence_seed = f"{package_id}\x00{document['document_id']}\x00{document['directory']}"
        entries.append(
            {
                "document_id": document["document_id"],
                "directory": document["directory"],
                "manifest_path": manifest_path,
                "manifest_checksum": checksum_object(manifest_bytes),
                "source_occurrence_id": f"occ-{sha256_bytes(occurrence_seed.encode('utf-8'))[:24]}",
                "status": document["status"],
            }
        )
    value = {
        "collection_manifest_version": "1.0.0",
        "package_id": package_id,
        "ordering_basis": "DOCUMENT_ID_ASCENDING",
        "document_count": len(entries),
        "documents": entries,
        "checksum_scope": "DOCUMENT_MANIFESTS_EXCLUDING_THIS_COLLECTION_MANIFEST_AND_RAG_PACKAGE_CONTROL",
        "qa": {
            "status": "PASS",
            "scope": "STRUCTURAL_PACKAGE_BUILD_ONLY",
            "source_set_completeness": "NOT_TESTED",
            "target_ingestion": "NOT_TESTED",
        },
        "limitations": [
            "Folder/source-set completeness was not independently established.",
            "Live target ingestion and retrieval quality were not tested.",
        ],
    }
    return canonical_json_bytes(value)


def validate_control(control: Mapping[str, Any]) -> None:
    try:
        validator = InternalSchemaValidator(RAG_SCHEMA, SCHEMA_ROOT)
        errors = validator.validate(control)
    except ValidationToolError as exc:
        raise RagBuildError(f"cannot run bundled RAG package validator: {exc}") from exc
    if errors:
        raise RagBuildError(format_schema_errors(errors, label="rag-package.json"))


def verify_control_checksums(control: Mapping[str, Any], files: Mapping[str, bytes]) -> None:
    kind = control["package_kind"]
    for document in control["documents"]:
        base = document["directory"]
        descriptors = [
            document["document_markdown"],
            document["metadata"],
            document["manifest"],
            *document["assets"],
        ]
        if document["chunks"] is not None:
            descriptors.append(document["chunks"])
        for descriptor in descriptors:
            key = f"{base}/{descriptor['path']}"
            if key not in files:
                raise RagBuildError(f"control descriptor points to missing file: {key}")
            actual = sha256_bytes(files[key])
            if actual.casefold() != descriptor["checksum"]["digest"].casefold():
                raise RagBuildError(f"control checksum mismatch: {key}")
    if kind == "COLLECTION":
        descriptor = control["collection_manifest"]
        key = descriptor["path"]
        if key not in files:
            raise RagBuildError(f"control descriptor points to missing file: {key}")
        if sha256_bytes(files[key]).casefold() != descriptor["checksum"]["digest"].casefold():
            raise RagBuildError(f"control checksum mismatch: {key}")


def add_file(files: dict[str, bytes], path: str, data: bytes) -> None:
    assert_path_set_has_no_collisions(
        [*files, path],
        label="output member path",
    )
    files[path] = data


def build_package(
    sources: Sequence[CanonicalSource],
    *,
    root: Path,
    package_kind: str,
    package_id: str | None,
    chunking: ChunkingRequest | None,
) -> BuildResult:
    if package_kind == "DOCUMENT" and len(sources) != 1:
        raise RagBuildError("DOCUMENT package kind requires exactly one canonical input")
    if package_kind == "COLLECTION" and not sources:
        raise RagBuildError("COLLECTION package kind requires at least one canonical input")
    runtime_release_version = load_runtime_release_version()
    selected_package_id = package_id or compute_package_id(
        sources,
        package_kind,
        chunking,
        runtime_release_version,
    )
    if not IDENTIFIER_PATTERN.fullmatch(selected_package_id):
        raise RagBuildError("--package-id must satisfy the shared identifier contract")

    metadata_template, metadata_template_bytes = load_template(
        METADATA_TEMPLATE, expected_artifact="metadata.json"
    )
    manifest_template, manifest_template_bytes = load_template(
        MANIFEST_TEMPLATE, expected_artifact="manifest.json"
    )
    files: dict[str, bytes] = {}
    control_documents: list[dict[str, Any]] = []
    for source in sources:
        document_files, control_document = build_document_files(
            source,
            root=root,
            package_id=selected_package_id,
            metadata_template=metadata_template,
            metadata_template_bytes=metadata_template_bytes,
            manifest_template=manifest_template,
            manifest_template_bytes=manifest_template_bytes,
            chunking=chunking,
            runtime_release_version=runtime_release_version,
        )
        for relative, data in sorted(document_files.items()):
            add_file(files, f"{source.directory}/{relative}", data)
        control_documents.append(control_document)

    collection_descriptor = None
    if package_kind == "COLLECTION":
        collection_bytes = build_collection_manifest(
            selected_package_id, control_documents, files
        )
        add_file(files, "collection-manifest.json", collection_bytes)
        collection_descriptor = make_file_descriptor(
            "collection-manifest.json", "application/json", collection_bytes
        )

    limitations = [
        "rag-package.json is a schema-valid control object excluded from its own checksum scope.",
        "Live target ingestion and retrieval quality were not tested.",
    ]
    if package_kind == "COLLECTION":
        limitations.append("Folder/source-set completeness was not independently established.")
    control = {
        "schema_version": "1.0.0",
        "skill_id": SKILL_ID,
        "skill_release_version": runtime_release_version,
        "package_id": selected_package_id,
        "package_kind": package_kind,
        "status": "PASS",
        "documents": control_documents,
        "collection_manifest": collection_descriptor,
        "limitations": limitations,
    }
    validate_control(control)
    verify_control_checksums(control, files)
    add_file(files, "rag-package.json", canonical_json_bytes(control))
    total_bytes = sum(len(data) for data in files.values())
    if total_bytes > MAX_PACKAGE_BYTES:
        raise RagBuildError(
            f"package exceeds the {MAX_PACKAGE_BYTES}-byte aggregate safety limit"
        )
    return BuildResult(
        files=files,
        control=control,
        package_id=selected_package_id,
        package_kind=package_kind,
    )


def protected_inodes(paths: Iterable[Path]) -> set[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    for path in paths:
        try:
            status = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise RagBuildError(f"cannot inspect protected input {path}: {exc}") from exc
        result.add((status.st_dev, status.st_ino))
    return result


def validate_existing_output(
    output: Path,
    *,
    protected_paths: Sequence[Path],
    overwrite: bool,
) -> None:
    protected = protected_inodes(protected_paths)
    if not output.exists():
        return
    output_status = output.stat(follow_symlinks=False)
    if (output_status.st_dev, output_status.st_ino) in protected:
        raise RagBuildError("output must not alias a protected input")
    if not overwrite:
        raise RagBuildError(f"output already exists; use --overwrite: {output}")
    if not output.is_dir():
        raise RagBuildError("overwrite output must be an existing real directory")
    for path in output.rglob("*"):
        if path.is_symlink():
            raise RagBuildError(f"existing output contains a symlink: {path}")
        status = path.stat(follow_symlinks=False)
        if stat.S_ISREG(status.st_mode):
            if (status.st_dev, status.st_ino) in protected:
                raise RagBuildError("existing output contains a hardlink alias of a protected input")
            if status.st_nlink > 1:
                raise RagBuildError(f"existing output contains a hardlinked file: {path}")


def reject_output_contains_inputs(output: Path, protected_paths: Sequence[Path]) -> None:
    for protected in protected_paths:
        try:
            protected.relative_to(output)
        except ValueError:
            continue
        raise RagBuildError(f"output must not contain or replace protected input: {protected}")


def write_staging_tree(staging: Path, files: Mapping[str, bytes]) -> None:
    for relative, data in sorted(files.items()):
        safe = safe_relative_path(relative, label="output member path")
        destination = staging.joinpath(*safe.parts)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            raise RagBuildError(f"cannot create staged output file {relative}: {exc}") from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)


def verify_staging_tree(staging: Path, expected: Mapping[str, bytes]) -> None:
    observed: dict[str, bytes] = {}
    for path in sorted(staging.rglob("*")):
        if path.is_symlink():
            raise RagBuildError(f"staging tree unexpectedly contains symlink: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise RagBuildError(f"staging tree contains non-regular entry: {path}")
        relative = path.relative_to(staging).as_posix()
        observed[relative] = read_regular_nofollow(
            path,
            label="staged output",
            max_bytes=MAX_ASSET_BYTES,
        )
    if set(observed) != set(expected):
        raise RagBuildError("staging tree file set does not match the build plan")
    for relative, expected_bytes in expected.items():
        if observed[relative] != expected_bytes:
            raise RagBuildError(f"staged output byte mismatch: {relative}")


def publish_directory(
    output: Path,
    files: Mapping[str, bytes],
    *,
    overwrite: bool,
) -> None:
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    backup: Path | None = None
    published = False
    try:
        write_staging_tree(staging, files)
        verify_staging_tree(staging, files)
        if output.exists():
            if not overwrite:
                raise RagBuildError(f"output already exists; use --overwrite: {output}")
            backup = Path(
                tempfile.mkdtemp(prefix=f".{output.name}.backup-slot-", dir=output.parent)
            )
            backup.rmdir()
            os.rename(output, backup)
        try:
            os.rename(staging, output)
        except OSError as exc:
            if backup is not None and backup.exists() and not output.exists():
                try:
                    os.rename(backup, output)
                except OSError:
                    pass
                else:
                    backup = None
            preservation = (
                f"; previous output preserved at {backup}"
                if backup is not None and backup.exists()
                else ""
            )
            raise RagBuildError(
                f"atomic directory publication failed: {exc}{preservation}"
            ) from exc
        published = True
        if backup is not None:
            shutil.rmtree(backup)
            backup = None
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup is not None and backup.exists():
            if published:
                shutil.rmtree(backup)
            elif not output.exists():
                try:
                    os.rename(backup, output)
                except OSError:
                    # A recovery artifact is safer than deleting the previous
                    # output if restoration loses a concurrent destination race.
                    pass


def package_summary(result: BuildResult, *, status: str, output: Path) -> dict[str, Any]:
    control_bytes = result.files["rag-package.json"]
    return {
        "status": status,
        "package_id": result.package_id,
        "package_kind": result.package_kind,
        "output": str(output),
        "file_count": len(result.files),
        "total_bytes": sum(len(data) for data in result.files.values()),
        "rag_package_sha256": sha256_bytes(control_bytes),
        "files": [
            {
                "path": path,
                "size_bytes": len(data),
                "sha256": sha256_bytes(data),
            }
            for path, data in sorted(result.files.items())
        ],
        "validation": {
            "canonical_schema": "PASS",
            "canonical_semantic_structure": "PASS",
            "rag_package_schema": "PASS",
            "descriptor_checksums": "PASS",
            "live_target_ingestion": "NOT_TESTED",
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="+",
        help="one or more canonical-content JSON files below --root",
    )
    parser.add_argument("--root", default=".", help="authorized input/output root")
    parser.add_argument(
        "--output",
        required=True,
        help="new package directory below --root; parent must already exist",
    )
    parser.add_argument(
        "--package-kind",
        choices=("auto", "document", "collection"),
        default="auto",
        help="auto selects DOCUMENT for one input and COLLECTION otherwise",
    )
    parser.add_argument("--package-id", help="optional shared-contract identifier")
    parser.add_argument(
        "--assets-root",
        help="optional common asset root below --root; default is each input's directory",
    )
    parser.add_argument(
        "--target-id",
        help="explicit downstream target identifier; requires --chunk-config",
    )
    parser.add_argument(
        "--chunk-config",
        help="explicit deterministic chunk configuration below --root; requires --target-id",
    )
    parser.add_argument("--dry-run", action="store_true", help="validate and print the exact plan without writing")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing safe package directory")
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    root = resolve_root(args.root, label="authorized root")
    output = resolve_output_directory(root, args.output)
    explicit_assets_root = None
    if args.assets_root is not None:
        explicit_assets_root = resolve_directory_below_root(
            root,
            args.assets_root,
            label="assets root",
        )
    sources = load_sources(
        root,
        args.inputs,
        explicit_assets_root=explicit_assets_root,
    )
    chunking, chunk_config_path = load_chunking_request(
        root,
        target_id=args.target_id,
        raw_config=args.chunk_config,
    )
    if args.package_kind == "auto":
        package_kind = "DOCUMENT" if len(sources) == 1 else "COLLECTION"
    else:
        package_kind = args.package_kind.upper()
    protected_paths = [source.path for source in sources]
    protected_paths.extend(source.assets_root for source in sources)
    if chunk_config_path is not None:
        protected_paths.append(chunk_config_path)
    protected_paths.extend(
        [
            Path(__file__).resolve(),
            SCRIPT_DIRECTORY / "validate_records.py",
            CANONICAL_SCHEMA,
            RAG_SCHEMA,
            SCHEMA_ROOT / "common" / "shared-definitions.schema.json",
            METADATA_TEMPLATE,
            MANIFEST_TEMPLATE,
            RELEASE_VERSION_FILE,
        ]
    )
    reject_output_contains_inputs(output, protected_paths)
    protected_paths.extend(collect_asset_source_paths(sources, root=root))
    reject_output_contains_inputs(output, protected_paths)
    validate_existing_output(
        output,
        protected_paths=protected_paths,
        overwrite=args.overwrite,
    )
    result = build_package(
        sources,
        root=root,
        package_kind=package_kind,
        package_id=args.package_id,
        chunking=chunking,
    )
    if args.dry_run:
        return package_summary(result, status="DRY_RUN", output=output)
    publish_directory(output, result.files, overwrite=args.overwrite)
    return package_summary(result, status="WRITTEN", output=output)


def main(argv: list[str] | None = None) -> int:
    try:
        summary = run(argv)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except (RagBuildError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
