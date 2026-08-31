#!/usr/bin/env python3
"""Render deterministic offline artifacts from canonical semantic content.

The helper accepts the bundled ``canonical-content.schema.json`` contract and
creates JSON, Markdown, DOCX, XLSX, or PPTX without network access or dependency
installation. OOXML packages are written directly with the Python standard
library. Every output is structurally inspected before atomic publication.

The renderer is intentionally conservative: it never overwrites by default,
never follows input/asset/output symlinks, never mutates an input, and never
claims visual QA without an actual render inspection. PAGE_AS_SLIDE additionally
requires canonical PAGE_IMAGE content with one declared PNG/JPEG asset per page.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from typing import Iterable, Mapping, Sequence
from urllib.parse import quote
import zipfile
import xml.etree.ElementTree as ET


TOOL_NAME = "thien-canonical-artifact-renderer"
TOOL_VERSION = "1.0.0"
CANONICAL_SCHEMA_VERSION = "1.0.0"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = SKILL_ROOT / "schemas"
MAX_CANONICAL_BYTES = 64 * 1024 * 1024
MAX_ASSET_BYTES = 128 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 512 * 1024 * 1024
MAX_BLOCK_COUNT = 100_000

FORMAT_SUFFIX = {
    "JSON": ".json",
    "MD": ".md",
    "DOCX": ".docx",
    "XLSX": ".xlsx",
    "PPTX": ".pptx",
}
MEDIA_TYPE = {
    "JSON": "application/json",
    "MD": "text/markdown",
    "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "PPTX": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
PROFILE_BY_FORMAT = {
    "DOCX": {"SEMANTIC_EDITABLE"},
    "XLSX": {"STRUCTURED_DATA"},
    "PPTX": {
        "EDITABLE_PRESENTATION",
        "PAGE_AS_SLIDE",
        "VISUAL_FIDELITY_BEST_EFFORT",
    },
}
PPTX_INTENT_PROFILE = {
    "PRESENTATION": "EDITABLE_PRESENTATION",
    "FAITHFUL_PAGE_CONVERSION": "PAGE_AS_SLIDE",
    "VISUAL_FIDELITY": "VISUAL_FIDELITY_BEST_EFFORT",
}
IMAGE_EXTENSION = {
    "image/png": "png",
    "image/jpeg": "jpg",
}
XML_FORBIDDEN = re.compile(
    "[\x00-\x08\x0B\x0C\x0E-\x1F\uD800-\uDFFF\uFFFE\uFFFF]"
)
WINDOWS_RESERVED = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE
)
SEMANTIC_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class ConversionError(ValueError):
    """Raised for invalid contracts, unsafe paths, or unsupported rendering."""


def _read_skill_release_version() -> str:
    path = SKILL_ROOT / "VERSION"
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"cannot read installed skill VERSION: {exc}") from exc
    if len(data) > 256:
        raise RuntimeError("installed skill VERSION exceeds 256-byte safety limit")
    try:
        version = data.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeError("installed skill VERSION must be ASCII semantic version") from exc
    if SEMANTIC_VERSION.fullmatch(version) is None:
        raise RuntimeError(f"installed skill VERSION is not semantic version: {version!r}")
    return version


SKILL_RELEASE_VERSION = _read_skill_release_version()


def canonical_json_bytes(value: object, *, pretty: bool = False) -> bytes:
    if pretty:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        return (rendered + "\n").encode("utf-8")
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _absolute_without_resolution(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def resolve_root(raw_root: str | Path) -> Path:
    supplied = Path(raw_root).expanduser()
    if supplied.is_symlink():
        raise ConversionError(f"authorized root must not be a symlink: {supplied}")
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise ConversionError(f"cannot resolve authorized root {supplied}: {exc}") from exc
    if not root.is_dir():
        raise ConversionError(f"authorized root is not a directory: {supplied}")
    return root


def _inside_root(root: Path, raw_path: str | Path, *, label: str) -> tuple[Path, Path]:
    supplied = Path(raw_path).expanduser()
    lexical = supplied if supplied.is_absolute() else root / supplied
    lexical = _absolute_without_resolution(lexical)
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise ConversionError(f"{label} escapes authorized root: {raw_path}") from exc
    return lexical, relative


def _reject_symlink_components(root: Path, relative: Path, *, label: str) -> None:
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ConversionError(f"{label} must not traverse a symlink: {relative}")


def resolve_regular_file(root: Path, raw_path: str | Path, *, label: str) -> Path:
    lexical, relative = _inside_root(root, raw_path, label=label)
    _reject_symlink_components(root, relative, label=label)
    if not lexical.is_file():
        raise ConversionError(f"{label} is not a regular file: {raw_path}")
    return lexical


def resolve_directory(root: Path, raw_path: str | Path, *, label: str) -> Path:
    lexical, relative = _inside_root(root, raw_path, label=label)
    _reject_symlink_components(root, relative, label=label)
    if not lexical.is_dir():
        raise ConversionError(f"{label} is not a directory: {raw_path}")
    return lexical


def resolve_output(root: Path, raw_path: str | Path, *, label: str) -> Path:
    lexical, relative = _inside_root(root, raw_path, label=label)
    _reject_symlink_components(root, relative.parent, label=label)
    if lexical.is_symlink():
        raise ConversionError(f"{label} must not be a symlink: {relative}")
    if not lexical.parent.is_dir() or lexical.parent.is_symlink():
        raise ConversionError(f"{label} parent must be an existing real directory")
    if lexical.exists() and not lexical.is_file():
        raise ConversionError(f"{label} is not a regular file path: {relative}")
    return lexical


def read_regular_nofollow(path: Path, *, label: str, max_bytes: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ConversionError(f"{label} is not a regular file")
        if metadata.st_size > max_bytes:
            raise ConversionError(f"{label} exceeds {max_bytes}-byte safety limit")
        handle = os.fdopen(descriptor, "rb")
        descriptor = -1
        with handle:
            data = handle.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ConversionError(f"{label} exceeds {max_bytes}-byte safety limit")
            return data
    except OSError as exc:
        raise ConversionError(f"cannot safely read {label}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load_json_object(path: Path, *, label: str) -> tuple[dict[str, object], bytes]:
    raw = read_regular_nofollow(path, label=label, max_bytes=MAX_CANONICAL_BYTES)

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate object key {key!r}")
            value[key] = item
        return value

    def reject_nonfinite(token: str) -> object:
        raise ValueError(f"non-finite JSON number {token!r}")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ConversionError(f"{label} must contain valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ConversionError(f"{label} must be a JSON object")
    return value, raw


def _load_internal_validator():
    path = Path(__file__).with_name("validate_records.py")
    spec = importlib.util.spec_from_file_location(
        "thien_conversion_contract_validator", path
    )
    if spec is None or spec.loader is None:
        raise ConversionError(f"cannot load bundled schema validator from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate_schema(payload: object, schema_name: str) -> None:
    module = _load_internal_validator()
    schema_path = SCHEMA_ROOT / "common" / schema_name
    validator = module.InternalSchemaValidator(schema_path, SCHEMA_ROOT)
    errors = validator.validate(payload)
    if errors:
        rendered = "; ".join(
            f"{error['path']} ({error['keyword']}): {error['message']}"
            for error in errors[:10]
        )
        if len(errors) > 10:
            rendered += f"; plus {len(errors) - 10} additional errors"
        raise ConversionError(f"{schema_name} validation failed: {rendered}")


def safe_relative_path(raw_path: str) -> PurePosixPath:
    if (
        not raw_path
        or "\\" in raw_path
        or "\x00" in raw_path
        or raw_path.startswith("/")
        or re.match(r"^[A-Za-z]:", raw_path)
        or "//" in raw_path
    ):
        raise ConversionError(f"unsafe relative asset path: {raw_path!r}")
    path = PurePosixPath(raw_path)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ConversionError(f"unsafe relative asset path: {raw_path!r}")
    for part in path.parts:
        if part[-1:] in {" ", "."} or WINDOWS_RESERVED.fullmatch(part):
            raise ConversionError(f"unsafe relative asset path: {raw_path!r}")
        if any(ord(character) < 32 or character in '<>:"|?*' for character in part):
            raise ConversionError(f"unsafe relative asset path: {raw_path!r}")
    return path


def resolve_asset(assets_root: Path, raw_path: str) -> Path:
    relative = safe_relative_path(raw_path)
    lexical = _absolute_without_resolution(assets_root.joinpath(*relative.parts))
    try:
        local_relative = lexical.relative_to(assets_root)
    except ValueError as exc:
        raise ConversionError(f"asset escapes asset root: {raw_path}") from exc
    _reject_symlink_components(assets_root, local_relative, label="asset")
    if not lexical.is_file():
        raise ConversionError(f"asset is not a regular file: {raw_path}")
    return lexical


def reject_output_alias(path: Path, protected_paths: Iterable[Path]) -> None:
    if not path.exists():
        return
    for protected in protected_paths:
        try:
            aliases = os.path.samefile(path, protected)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ConversionError(f"cannot verify output/input inode separation: {exc}") from exc
        if aliases:
            raise ConversionError("output must not replace or alias an input or asset file")


def atomic_write(path: Path, data: bytes, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ConversionError(f"output already exists; use --overwrite: {path}")
    if path.is_symlink():
        raise ConversionError(f"output must not be a symlink: {path}")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ConversionError(f"output parent must be an existing real directory: {path.parent}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        if overwrite:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise ConversionError(
                    f"output appeared during atomic publication; refusing overwrite: {path}"
                ) from exc
            except OSError as exc:
                raise ConversionError(
                    f"cannot atomically publish output without overwrite: {path}: {exc}"
                ) from exc
            temporary.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()


def _stage_transaction_file(path: Path, data: bytes) -> tuple[Path, tuple[int, int]]:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.txn-stage.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        metadata = temporary.stat()
        return temporary, (metadata.st_dev, metadata.st_ino)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _has_identity(path: Path, identity: tuple[int, int]) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return (metadata.st_dev, metadata.st_ino) == identity


def _transactional_publish(
    files: Sequence[tuple[Path, bytes]], *, overwrite: bool
) -> None:
    """Publish a related file set with rollback on any publication failure."""

    if not files:
        raise ConversionError("transaction requires at least one output file")
    targets = [path for path, _ in files]
    if len(targets) != len(set(targets)):
        raise ConversionError("transaction output paths must be distinct")
    for target in targets:
        if target.is_symlink():
            raise ConversionError(f"transaction output must not be a symlink: {target}")
        if not target.parent.is_dir() or target.parent.is_symlink():
            raise ConversionError(
                f"transaction output parent must be an existing real directory: {target.parent}"
            )
        if target.exists() and not target.is_file():
            raise ConversionError(f"transaction output is not a regular file: {target}")
        if target.exists() and not overwrite:
            raise ConversionError(f"output already exists; use --overwrite: {target}")

    staged: list[tuple[Path, Path, tuple[int, int]]] = []
    try:
        for target, data in files:
            temporary, identity = _stage_transaction_file(target, data)
            staged.append((target, temporary, identity))
    except Exception:
        for _, temporary, _ in staged:
            temporary.unlink(missing_ok=True)
        raise

    if not overwrite:
        published: list[tuple[Path, Path, tuple[int, int]]] = []
        try:
            for target, temporary, identity in staged:
                try:
                    os.link(temporary, target)
                except FileExistsError as exc:
                    raise ConversionError(
                        f"output appeared during transaction; refusing overwrite: {target}"
                    ) from exc
                except OSError as exc:
                    raise ConversionError(
                        f"cannot atomically publish transaction output {target}: {exc}"
                    ) from exc
                published.append((target, temporary, identity))
        except Exception as exc:
            rollback_errors: list[str] = []
            for target, _, identity in reversed(published):
                if _has_identity(target, identity):
                    try:
                        target.unlink()
                    except OSError as rollback_exc:
                        rollback_errors.append(f"cannot remove {target}: {rollback_exc}")
                elif target.exists() or target.is_symlink():
                    rollback_errors.append(
                        f"refused to remove externally replaced transaction output {target}"
                    )
            for _, temporary, _ in staged:
                temporary.unlink(missing_ok=True)
            if rollback_errors:
                raise ConversionError(
                    f"transaction failed ({exc}); rollback incomplete: "
                    + "; ".join(rollback_errors)
                ) from exc
            raise ConversionError(f"transaction failed and was rolled back: {exc}") from exc
        else:
            for _, temporary, _ in staged:
                temporary.unlink(missing_ok=True)
            return

    backups: dict[Path, Path | None] = {}
    published: list[tuple[Path, tuple[int, int]]] = []
    try:
        for target in targets:
            if target.is_symlink():
                raise ConversionError(
                    f"transaction output became a symlink before backup: {target}"
                )
            if target.exists():
                if not target.is_file():
                    raise ConversionError(
                        f"transaction output is no longer a regular file: {target}"
                    )
                descriptor, backup_name = tempfile.mkstemp(
                    prefix=f".{target.name}.txn-backup.", dir=target.parent
                )
                os.close(descriptor)
                backup = Path(backup_name)
                try:
                    os.replace(target, backup)
                except Exception:
                    backup.unlink(missing_ok=True)
                    raise
                backups[target] = backup
            else:
                backups[target] = None

        for target, temporary, identity in staged:
            os.replace(temporary, target)
            published.append((target, identity))
    except Exception as exc:
        rollback_errors: list[str] = []
        for target, identity in reversed(published):
            if _has_identity(target, identity):
                try:
                    target.unlink()
                except OSError as rollback_exc:
                    rollback_errors.append(f"cannot remove new {target}: {rollback_exc}")
            elif target.exists() or target.is_symlink():
                rollback_errors.append(
                    f"refused to remove externally replaced transaction output {target}"
                )
        for target in reversed(targets):
            backup = backups.get(target)
            if backup is None:
                continue
            if target.exists() or target.is_symlink():
                rollback_errors.append(
                    f"cannot restore {target}: destination unexpectedly exists"
                )
                continue
            try:
                os.replace(backup, target)
            except OSError as rollback_exc:
                rollback_errors.append(f"cannot restore {target}: {rollback_exc}")
        for _, temporary, _ in staged:
            temporary.unlink(missing_ok=True)
        for backup in backups.values():
            if backup is not None and backup.exists():
                if not rollback_errors:
                    backup.unlink(missing_ok=True)
        if rollback_errors:
            raise ConversionError(
                f"transaction failed ({exc}); rollback incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        raise ConversionError(f"transaction failed and was rolled back: {exc}") from exc
    else:
        for backup in backups.values():
            if backup is not None:
                backup.unlink(missing_ok=True)
        for _, temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def _semantic_errors(content: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    blocks_value = content.get("blocks")
    if not isinstance(blocks_value, list):
        return ["blocks must be an array"]
    blocks = [block for block in blocks_value if isinstance(block, dict)]
    if len(blocks) != len(blocks_value):
        return ["every block must be an object"]

    block_ids = [block.get("block_id") for block in blocks]
    orders = [block.get("reading_order") for block in blocks]
    if len(block_ids) != len(set(block_ids)):
        errors.append("block_id values must be unique")
    if len(orders) != len(set(orders)):
        errors.append("reading_order values must be unique")
    if any(
        not isinstance(left, int)
        or isinstance(left, bool)
        or not isinstance(right, int)
        or isinstance(right, bool)
        or left >= right
        for left, right in zip(orders, orders[1:])
    ):
        errors.append("reading_order must be strictly increasing in array order")

    known_ids = {value for value in block_ids if isinstance(value, str)}
    parents = {
        block.get("block_id"): block.get("parent_block_id")
        for block in blocks
        if isinstance(block.get("block_id"), str)
    }
    for block_id, parent_id in parents.items():
        if parent_id is not None and parent_id not in known_ids:
            errors.append(f"dangling parent_block_id for {block_id}")
            continue
        seen = {block_id}
        cursor = parent_id
        while cursor is not None:
            if cursor in seen:
                errors.append(f"cyclic parent_block_id for {block_id}")
                break
            seen.add(cursor)
            cursor = parents.get(cursor)

    for block in blocks:
        block_id = block.get("block_id")
        block_type = block.get("block_type")
        if block_type == "CAPTION" and block.get("target_block_id") not in known_ids:
            errors.append(f"dangling caption target for {block_id}")
        if block_type == "TABLE":
            columns = block.get("columns")
            rows = block.get("rows")
            if isinstance(columns, list) and isinstance(rows, list):
                if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
                    errors.append(f"table row width mismatch for {block_id}")
        provenance = block.get("provenance")
        if not isinstance(provenance, dict):
            continue
        box = provenance.get("bounding_box")
        if isinstance(box, dict):
            x = box.get("x")
            y = box.get("y")
            width = box.get("width")
            height = box.get("height")
            page_width = box.get("page_width")
            page_height = box.get("page_height")
            if all(isinstance(value, (int, float)) for value in (x, width, page_width)):
                if float(x) + float(width) > float(page_width) + 1e-12:
                    errors.append(f"horizontal bounding-box overflow for {block_id}")
            if all(isinstance(value, (int, float)) for value in (y, height, page_height)):
                if float(y) + float(height) > float(page_height) + 1e-12:
                    errors.append(f"vertical bounding-box overflow for {block_id}")
    return errors


def validate_canonical(content: Mapping[str, object]) -> None:
    validate_schema(content, "canonical-content.schema.json")
    blocks = content.get("blocks")
    if isinstance(blocks, list) and len(blocks) > MAX_BLOCK_COUNT:
        raise ConversionError(
            f"canonical content exceeds {MAX_BLOCK_COUNT}-block safety limit"
        )
    errors = _semantic_errors(content)
    if errors:
        raise ConversionError("canonical semantic validation failed: " + "; ".join(errors))


def _xml_escape(value: object, *, attribute: bool = False) -> str:
    text = str(value)
    if XML_FORBIDDEN.search(text):
        raise ConversionError("OOXML output cannot represent XML 1.0 control characters")
    return html.escape(text, quote=attribute)


def _canonical_custom_xml(content: Mapping[str, object]) -> bytes:
    payload = canonical_json_bytes(content).decode("utf-8")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<de:canonicalContent xmlns:de="urn:thien:document-evidence:canonical:1">'
        f'<de:schemaVersion>{CANONICAL_SCHEMA_VERSION}</de:schemaVersion>'
        f'<de:contentId>{_xml_escape(content["content_id"])}</de:contentId>'
        f'<de:documentId>{_xml_escape(content["document_id"])}</de:documentId>'
        f'<de:json>{_xml_escape(payload)}</de:json>'
        '</de:canonicalContent>'
    ).encode("utf-8")


def _zip_bytes(parts: Mapping[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name in sorted(parts):
            if name.startswith("/") or "\\" in name or ".." in PurePosixPath(name).parts:
                raise ConversionError(f"unsafe OOXML member name: {name}")
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            archive.writestr(info, parts[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output.getvalue()


def _core_properties(title: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f'<dc:title>{_xml_escape(title)}</dc:title>'
        f'<dc:creator>{TOOL_NAME}</dc:creator>'
        f'<cp:lastModifiedBy>{TOOL_NAME}</cp:lastModifiedBy>'
        '<dcterms:created xsi:type="dcterms:W3CDTF">1980-01-01T00:00:00Z</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">1980-01-01T00:00:00Z</dcterms:modified>'
        '</cp:coreProperties>'
    ).encode("utf-8")


def _package_relationships(main_target: str, office_type: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{office_type}" Target="{main_target}"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="customXml/item1.xml"/>'
        '</Relationships>'
    ).encode("utf-8")


def _app_properties(application: str, count_name: str, count: int) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        f'<Application>{_xml_escape(application)}</Application>'
        f'<AppVersion>{TOOL_VERSION}</AppVersion>'
        f'<{count_name}>{count}</{count_name}>'
        '</Properties>'
    ).encode("utf-8")


def _word_runs(text: str, *, bold: bool = False, italic: bool = False) -> str:
    lines = text.split("\n")
    fragments: list[str] = []
    properties = ""
    if bold or italic:
        properties = "<w:rPr>" + ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") + "</w:rPr>"
    for index, line in enumerate(lines):
        if index:
            fragments.append(f"<w:r>{properties}<w:br/></w:r>")
        fragments.append(
            f'<w:r>{properties}<w:t xml:space="preserve">{_xml_escape(line)}</w:t></w:r>'
        )
    return "".join(fragments)


def _word_paragraph(text: str, *, style: str | None = None, italic: bool = False) -> str:
    paragraph_properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{paragraph_properties}{_word_runs(text, italic=italic)}</w:p>"


def _word_table(block: Mapping[str, object]) -> str:
    columns = block["columns"]
    rows = block["rows"]
    assert isinstance(columns, list) and isinstance(rows, list)
    all_rows: list[Sequence[object]] = [columns, *rows]
    rendered_rows: list[str] = []
    for row_index, row in enumerate(all_rows):
        cells = []
        for value in row:
            text = "" if value is None else str(value)
            cell_properties = "<w:tcPr><w:tcW w:w=\"2400\" w:type=\"dxa\"/></w:tcPr>"
            cells.append(
                f"<w:tc>{cell_properties}<w:p>{_word_runs(text, bold=row_index == 0)}</w:p></w:tc>"
            )
        rendered_rows.append("<w:tr>" + "".join(cells) + "</w:tr>")
    return (
        '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
        '<w:tblW w:w="0" w:type="auto"/></w:tblPr>'
        + "".join(rendered_rows)
        + "</w:tbl>"
    )


def _word_image(
    block: Mapping[str, object],
    relationship_id: str,
    drawing_id: int,
    width: int,
    height: int,
) -> str:
    alt = block.get("alt_text") or ""
    description = f"{block['block_id']} | {block['asset_reference']} | {alt}"
    return (
        '<w:p><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f'<wp:extent cx="{width}" cy="{height}"/>'
        f'<wp:docPr id="{drawing_id}" name="Image {drawing_id}" descr="{_xml_escape(description, attribute=True)}"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:nvPicPr>'
        f'<pic:cNvPr id="{drawing_id}" name="{_xml_escape(block["asset_reference"], attribute=True)}"/>'
        '<pic:cNvPicPr><a:picLocks noChangeAspect="1"/></pic:cNvPicPr></pic:nvPicPr>'
        f'<pic:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="{relationship_id}"/>'
        '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{width}" cy="{height}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
    )


def _image_blocks(content: Mapping[str, object]) -> list[Mapping[str, object]]:
    blocks = content["blocks"]
    assert isinstance(blocks, list)
    return [block for block in blocks if isinstance(block, dict) and block.get("block_type") == "IMAGE"]


def _load_assets(
    content: Mapping[str, object], assets_root: Path | None, *, required: bool
) -> tuple[dict[str, bytes], list[Path]]:
    image_blocks = _image_blocks(content)
    if image_blocks and assets_root is None and required:
        raise ConversionError("--assets-root is required to embed declared image assets")
    data_by_id: dict[str, bytes] = {}
    paths: list[Path] = []
    if assets_root is None:
        return data_by_id, paths
    total_bytes = 0
    for block in image_blocks:
        media_type = block.get("media_type")
        if required and media_type not in IMAGE_EXTENSION:
            raise ConversionError(
                f"OOXML embedding supports PNG/JPEG only; block {block.get('block_id')} uses {media_type}"
            )
        raw_reference = block.get("asset_reference")
        if not isinstance(raw_reference, str):
            raise ConversionError(f"image block {block.get('block_id')} lacks asset_reference")
        path = resolve_asset(assets_root, raw_reference)
        data = read_regular_nofollow(
            path,
            label=f"asset {raw_reference}",
            max_bytes=MAX_ASSET_BYTES,
        )
        if media_type == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ConversionError(f"declared PNG asset has invalid signature: {raw_reference}")
        if media_type == "image/jpeg" and not data.startswith(b"\xff\xd8\xff"):
            raise ConversionError(f"declared JPEG asset has invalid signature: {raw_reference}")
        if media_type in IMAGE_EXTENSION:
            _image_dimensions(data, str(media_type), label=raw_reference)
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL_ASSET_BYTES:
            raise ConversionError(
                f"declared assets exceed {MAX_TOTAL_ASSET_BYTES}-byte aggregate safety limit"
            )
        checksum = block.get("asset_checksum")
        expected = checksum.get("digest") if isinstance(checksum, dict) else None
        actual = sha256_bytes(data)
        if not isinstance(expected, str) or actual.casefold() != expected.casefold():
            raise ConversionError(
                f"asset SHA-256 mismatch for {raw_reference}: expected {expected}, got {actual}"
            )
        block_id = block.get("block_id")
        assert isinstance(block_id, str)
        data_by_id[block_id] = data
        paths.append(path)
    return data_by_id, paths


def _image_dimensions(data: bytes, media_type: str, *, label: str) -> tuple[int, int]:
    if media_type == "image/png":
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise ConversionError(f"declared PNG asset lacks a valid IHDR: {label}")
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
    elif media_type == "image/jpeg":
        width = 0
        height = 0
        index = 2
        start_of_frame = {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }
        while index + 1 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            while index < len(data) and data[index] == 0xFF:
                index += 1
            if index >= len(data):
                break
            marker = data[index]
            index += 1
            if marker in {0x01, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                continue
            if index + 2 > len(data):
                break
            segment_length = int.from_bytes(data[index:index + 2], "big")
            if segment_length < 2 or index + segment_length > len(data):
                break
            if marker in start_of_frame and segment_length >= 7:
                height = int.from_bytes(data[index + 3:index + 5], "big")
                width = int.from_bytes(data[index + 5:index + 7], "big")
                break
            index += segment_length
    else:
        raise ConversionError(f"cannot read dimensions for unsupported image type {media_type}")
    if width <= 0 or height <= 0:
        raise ConversionError(f"declared image has invalid or unreadable dimensions: {label}")
    return width, height


def _fit_box(
    image_width: int,
    image_height: int,
    x: int,
    y: int,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    scale = min(width / image_width, height / image_height)
    fitted_width = max(1, int(round(image_width * scale)))
    fitted_height = max(1, int(round(image_height * scale)))
    return (
        x + (width - fitted_width) // 2,
        y + (height - fitted_height) // 2,
        fitted_width,
        fitted_height,
    )


def render_docx(content: Mapping[str, object], asset_data: Mapping[str, bytes]) -> bytes:
    blocks = content["blocks"]
    assert isinstance(blocks, list)
    image_blocks = _image_blocks(content)
    image_names = {
        str(block["block_id"]): f"image{index}.{IMAGE_EXTENSION[str(block['media_type'])]}"
        for index, block in enumerate(image_blocks, start=1)
    }
    image_relationships = {
        str(block["block_id"]): f"rId{index + 1}"
        for index, block in enumerate(image_blocks, start=1)
    }
    body: list[str] = []
    drawing_id = 1
    for block in blocks:
        assert isinstance(block, dict)
        block_type = block["block_type"]
        if block_type == "HEADING":
            body.append(_word_paragraph(str(block["text"]), style=f"Heading{block['level']}"))
        elif block_type == "PARAGRAPH":
            body.append(_word_paragraph(str(block["text"])))
        elif block_type == "TABLE":
            body.append(_word_table(block))
        elif block_type == "IMAGE":
            block_id = str(block["block_id"])
            image_width, image_height = _image_dimensions(
                asset_data[block_id],
                str(block["media_type"]),
                label=str(block["asset_reference"]),
            )
            _, _, fitted_width, fitted_height = _fit_box(
                image_width, image_height, 0, 0, 4_572_000, 2_743_200
            )
            body.append(
                _word_image(
                    block,
                    image_relationships[block_id],
                    drawing_id,
                    fitted_width,
                    fitted_height,
                )
            )
            drawing_id += 1
        elif block_type == "CAPTION":
            body.append(_word_paragraph(str(block["text"]), style="Caption", italic=True))

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<w:body>' + "".join(body) +
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
        '</w:body></w:document>'
    ).encode("utf-8")
    relationships = [
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    ]
    for block in image_blocks:
        block_id = str(block["block_id"])
        relationships.append(
            f'<Relationship Id="{image_relationships[block_id]}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{image_names[block_id]}"/>'
        )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(relationships) + "</Relationships>"
    ).encode("utf-8")
    style_entries = [
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>',
        '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>'
        '<w:top w:val="single" w:sz="4" w:color="auto"/><w:left w:val="single" w:sz="4" w:color="auto"/>'
        '<w:bottom w:val="single" w:sz="4" w:color="auto"/><w:right w:val="single" w:sz="4" w:color="auto"/>'
        '<w:insideH w:val="single" w:sz="4" w:color="auto"/><w:insideV w:val="single" w:sz="4" w:color="auto"/>'
        '</w:tblBorders></w:tblPr></w:style>',
        '<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/><w:basedOn w:val="Normal"/><w:rPr><w:i/></w:rPr></w:style>',
    ]
    for level in range(1, 7):
        size = 36 - (level - 1) * 2
        style_entries.append(
            f'<w:style w:type="paragraph" w:styleId="Heading{level}"><w:name w:val="heading {level}"/>'
            f'<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:rPr><w:b/><w:sz w:val="{size}"/></w:rPr></w:style>'
        )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        + "".join(style_entries) + "</w:styles>"
    ).encode("utf-8")
    defaults = [
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
    ]
    for extension, media_type in sorted({value: key for key, value in IMAGE_EXTENSION.items()}.items()):
        if any(name.endswith("." + extension) for name in image_names.values()):
            defaults.append(f'<Default Extension="{extension}" ContentType="{media_type}"/>')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        + "".join(defaults)
        + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '</Types>'
    ).encode("utf-8")
    parts: dict[str, bytes] = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": _package_relationships("word/document.xml", "officeDocument"),
        "customXml/item1.xml": _canonical_custom_xml(content),
        "docProps/app.xml": _app_properties("Thien Document Evidence", "Pages", 1),
        "docProps/core.xml": _core_properties(str(content["content_id"])),
        "word/_rels/document.xml.rels": document_rels,
        "word/document.xml": document,
        "word/styles.xml": styles,
    }
    for block in image_blocks:
        block_id = str(block["block_id"])
        parts[f"word/media/{image_names[block_id]}"] = asset_data[block_id]
    return _zip_bytes(parts)


def _xlsx_cell(
    reference: str,
    value: object,
    *,
    numeric_integer: bool = False,
    style_id: int | None = None,
) -> str:
    style = f' s="{style_id}"' if style_id is not None else ""
    if numeric_integer and isinstance(value, int) and not isinstance(value, bool):
        return f'<c r="{reference}"{style}><v>{value}</v></c>'
    text = "" if value is None else str(value)
    if len(text) > 32_767:
        raise ConversionError(
            f"XLSX cell {reference} exceeds Excel's 32767-code-point text limit; refusing truncation"
        )
    return (
        f'<c r="{reference}"{style} t="inlineStr"><is><t xml:space="preserve">'
        f'{_xml_escape(text)}</t></is></c>'
    )


def _column_name(index: int) -> str:
    result = ""
    value = index
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _xlsx_row_height(row: list[object], column_widths: tuple[int, ...]) -> int:
    """Estimate a readable wrapped height within Excel's row-height limit."""

    wrapped_lines = 1
    for value, width in zip(row, column_widths):
        text = "" if value is None else str(value)
        characters_per_line = max(8, int(width * 1.15))
        cell_lines = sum(
            max(1, (len(segment) + characters_per_line - 1) // characters_per_line)
            for segment in text.split("\n")
        )
        wrapped_lines = max(wrapped_lines, cell_lines)
    return min(405, max(30, wrapped_lines * 15))


def render_xlsx(content: Mapping[str, object]) -> bytes:
    headers = [
        "block_id", "block_type", "reading_order", "parent_block_id",
        "source_page", "source_region", "source_snippet", "geometry_status",
        "text", "level", "columns_json", "rows_json", "asset_reference",
        "media_type", "alt_text", "target_block_id",
    ]
    rows: list[list[object]] = [headers]
    blocks = content["blocks"]
    assert isinstance(blocks, list)
    for block in blocks:
        assert isinstance(block, dict)
        provenance = block["provenance"]
        assert isinstance(provenance, dict)
        rows.append([
            block["block_id"], block["block_type"], block["reading_order"],
            block.get("parent_block_id"), provenance["source_page"],
            provenance["source_region"], provenance.get("source_snippet"),
            provenance["geometry_status"], block.get("text"), block.get("level"),
            json.dumps(block.get("columns"), ensure_ascii=False, separators=(",", ":")) if "columns" in block else None,
            json.dumps(block.get("rows"), ensure_ascii=False, separators=(",", ":")) if "rows" in block else None,
            block.get("asset_reference"), block.get("media_type"), block.get("alt_text"),
            block.get("target_block_id"),
        ])
    column_widths = (24, 16, 13, 24, 12, 26, 44, 18, 52, 10, 34, 52, 30, 24, 38, 24)
    rendered_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = [
            _xlsx_cell(
                f"{_column_name(column_index)}{row_index}",
                value,
                numeric_integer=(
                    row_index > 1
                    and headers[column_index - 1]
                    in {"reading_order", "source_page", "level"}
                ),
                style_id=1 if row_index == 1 else 2,
            )
            for column_index, value in enumerate(row, start=1)
        ]
        height = 30 if row_index == 1 else _xlsx_row_height(row, column_widths)
        rendered_rows.append(
            f'<row r="{row_index}" ht="{height}" customHeight="1">'
            + "".join(cells)
            + "</row>"
        )
    final_column = _column_name(len(headers))
    rendered_columns = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(column_widths, start=1)
    )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>'
        f'<dimension ref="A1:{final_column}{len(rows)}"/>'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        '<cols>' + rendered_columns + '</cols>'
        '<sheetData>' + "".join(rendered_rows) + '</sheetData>'
        f'<autoFilter ref="A1:{final_column}{len(rows)}"/>'
        '<pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>'
        '<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
        '</worksheet>'
    ).encode("utf-8")
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<bookViews><workbookView/></bookViews><sheets><sheet name="Canonical Content" sheetId="1" r:id="rId1"/></sheets>'
        '<calcPr calcId="0" calcMode="manual"/></workbook>'
    ).encode("utf-8")
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    ).encode("utf-8")
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Aptos"/><family val="2"/></font>'
        '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos"/><family val="2"/></font>'
        '</fonts>'
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF001838"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    ).encode("utf-8")
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '</Types>'
    ).encode("utf-8")
    return _zip_bytes({
        "[Content_Types].xml": content_types,
        "_rels/.rels": _package_relationships("xl/workbook.xml", "officeDocument"),
        "customXml/item1.xml": _canonical_custom_xml(content),
        "docProps/app.xml": _app_properties("Thien Document Evidence", "Worksheets", 1),
        "docProps/core.xml": _core_properties(str(content["content_id"])),
        "xl/_rels/workbook.xml.rels": workbook_rels,
        "xl/styles.xml": styles,
        "xl/workbook.xml": workbook,
        "xl/worksheets/sheet1.xml": worksheet,
    })


PML_NS = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
)
SLIDE_WIDTH = 12_192_000
SLIDE_HEIGHT = 6_858_000


def _ppt_group_properties() -> str:
    return (
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
    )


def _ppt_text_shape(
    shape_id: int,
    name: str,
    text: str,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    size: int = 1800,
    bold: bool = False,
    italic: bool = False,
    description: str = "",
) -> str:
    paragraphs = []
    lines = text.split("\n") or [""]
    for line in lines:
        run_props = f' lang="en-US" sz="{size}"' + (' b="1"' if bold else "") + (' i="1"' if italic else "")
        paragraphs.append(
            f'<a:p><a:r><a:rPr{run_props}/><a:t>{_xml_escape(line)}</a:t></a:r><a:endParaRPr lang="en-US" sz="{size}"/></a:p>'
        )
    return (
        '<p:sp><p:nvSpPr>'
        f'<p:cNvPr id="{shape_id}" name="{_xml_escape(name, attribute=True)}" descr="{_xml_escape(description, attribute=True)}"/>'
        '<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{width}" cy="{height}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr>'
        '<p:txBody><a:bodyPr wrap="square"/><a:lstStyle/>' + "".join(paragraphs) + '</p:txBody></p:sp>'
    )


def _ppt_table_shape(
    shape_id: int,
    block: Mapping[str, object],
    x: int,
    y: int,
    width: int,
    height: int,
) -> str:
    columns = block["columns"]
    rows = block["rows"]
    assert isinstance(columns, list) and isinstance(rows, list)
    all_rows: list[Sequence[object]] = [columns, *rows]
    column_width = max(1, width // len(columns))
    grid = "".join(f'<a:gridCol w="{column_width}"/>' for _ in columns)
    rendered_rows = []
    row_height = max(1, height // max(1, len(all_rows)))
    for row_index, row in enumerate(all_rows):
        cells = []
        for value in row:
            text = "" if value is None else str(value)
            bold = ' b="1"' if row_index == 0 else ""
            cells.append(
                '<a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r>'
                f'<a:rPr lang="en-US" sz="1200"{bold}>'
                '<a:solidFill><a:srgbClr val="000000"/></a:solidFill>'
                '<a:latin typeface="Arial"/></a:rPr>'
                f'<a:t>{_xml_escape(text)}</a:t></a:r>'
                '<a:endParaRPr lang="en-US" sz="1200">'
                '<a:solidFill><a:srgbClr val="000000"/></a:solidFill>'
                '<a:latin typeface="Arial"/></a:endParaRPr></a:p></a:txBody>'
                '<a:tcPr marL="45720" marR="45720" marT="22860" marB="22860">'
                '<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:tcPr></a:tc>'
            )
        rendered_rows.append(f'<a:tr h="{row_height}">' + "".join(cells) + '</a:tr>')
    return (
        '<p:graphicFrame><p:nvGraphicFramePr>'
        f'<p:cNvPr id="{shape_id}" name="Table {shape_id}" descr="{_xml_escape(str(block["block_id"]), attribute=True)}"/>'
        '<p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>'
        f'<p:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{width}" cy="{height}"/></p:xfrm>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">'
        '<a:tbl><a:tblPr firstRow="1" bandRow="1"><a:tableStyleId>{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}</a:tableStyleId></a:tblPr>'
        f'<a:tblGrid>{grid}</a:tblGrid>' + "".join(rendered_rows) + '</a:tbl>'
        '</a:graphicData></a:graphic></p:graphicFrame>'
    )


def _ppt_picture(
    shape_id: int,
    block: Mapping[str, object],
    relationship_id: str,
    x: int,
    y: int,
    width: int,
    height: int,
) -> str:
    alt = block.get("alt_text") or ""
    description = f"{block['block_id']} | {block['asset_reference']} | {alt}"
    return (
        '<p:pic><p:nvPicPr>'
        f'<p:cNvPr id="{shape_id}" name="{_xml_escape(str(block["asset_reference"]), attribute=True)}" descr="{_xml_escape(description, attribute=True)}"/>'
        '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="{relationship_id}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{width}" cy="{height}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
    )


def _ppt_theme() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Thien Evidence">'
        '<a:themeElements><a:clrScheme name="Evidence">'
        '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
        '<a:dk2><a:srgbClr val="1F2937"/></a:dk2><a:lt2><a:srgbClr val="F3F4F6"/></a:lt2>'
        '<a:accent1><a:srgbClr val="1D4ED8"/></a:accent1><a:accent2><a:srgbClr val="0F766E"/></a:accent2>'
        '<a:accent3><a:srgbClr val="B45309"/></a:accent3><a:accent4><a:srgbClr val="7E22CE"/></a:accent4>'
        '<a:accent5><a:srgbClr val="BE123C"/></a:accent5><a:accent6><a:srgbClr val="0369A1"/></a:accent6>'
        '<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink>'
        '</a:clrScheme><a:fontScheme name="Evidence"><a:majorFont><a:latin typeface="Aptos Display"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
        '<a:minorFont><a:latin typeface="Aptos"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
        '<a:fmtScheme name="Evidence"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
        '<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln></a:lnStyleLst>'
        '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
        '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>'
        '</a:fmtScheme></a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>'
    ).encode("utf-8")


def _ppt_master_and_layout() -> tuple[bytes, bytes, bytes, bytes]:
    master = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sldMaster {PML_NS}><p:cSld><p:spTree>{_ppt_group_properties()}</p:spTree></p:cSld>'
        '<p:clrMap accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" bg1="lt1" bg2="lt2" folHlink="folHlink" hlink="hlink" tx1="dk1" tx2="dk2"/>'
        '<p:sldLayoutIdLst><p:sldLayoutId id="1" r:id="rId1"/></p:sldLayoutIdLst>'
        '<p:txStyles><p:titleStyle><a:lvl1pPr/></p:titleStyle><p:bodyStyle><a:lvl1pPr/></p:bodyStyle><p:otherStyle><a:defPPr/></p:otherStyle></p:txStyles>'
        '</p:sldMaster>'
    ).encode("utf-8")
    master_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'
        '</Relationships>'
    ).encode("utf-8")
    layout = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sldLayout {PML_NS} type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>{_ppt_group_properties()}</p:spTree></p:cSld>'
        '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'
    ).encode("utf-8")
    layout_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
        '</Relationships>'
    ).encode("utf-8")
    return master, master_rels, layout, layout_rels


SLIDE_TOP_MARGIN = 300_000
SLIDE_BOTTOM_MARGIN = 300_000
SLIDE_CONTENT_BOTTOM = SLIDE_HEIGHT - SLIDE_BOTTOM_MARGIN
SLIDE_ITEM_GAP = 120_000


def _text_line_count(text: str, characters_per_line: int) -> int:
    lines = 1
    column = 0
    for character in text:
        if character == "\n":
            lines += 1
            column = 0
            continue
        if column >= characters_per_line:
            lines += 1
            column = 0
        column += 1
    return lines


def _text_prefix_for_lines(
    text: str, characters_per_line: int, maximum_lines: int
) -> int:
    lines = 1
    column = 0
    for index, character in enumerate(text):
        if character == "\n":
            if lines >= maximum_lines:
                return max(1, index + 1)
            lines += 1
            column = 0
            continue
        if column >= characters_per_line:
            if lines >= maximum_lines:
                return max(1, index)
            lines += 1
            column = 0
        column += 1
    return len(text)


def _editable_slide_layout(
    content: Mapping[str, object], asset_data: Mapping[str, bytes]
) -> list[list[dict[str, object]]]:
    blocks = content["blocks"]
    assert isinstance(blocks, list)
    slides: list[list[dict[str, object]]] = [[]]
    y = SLIDE_TOP_MARGIN

    def new_slide() -> None:
        nonlocal y
        if slides[-1]:
            slides.append([])
        y = SLIDE_TOP_MARGIN

    for block in blocks:
        assert isinstance(block, dict)
        block_type = block["block_type"]
        if block_type == "HEADING" and slides[-1]:
            new_slide()

        if block_type in {"HEADING", "PARAGRAPH", "CAPTION"}:
            remaining = str(block["text"])
            if block_type == "HEADING":
                x, width = 500_000, 11_192_000
                characters_per_line, line_height, padding = 58, 430_000, 100_000
                font_size, bold, italic = 2800, True, False
            elif block_type == "PARAGRAPH":
                x, width = 650_000, 10_892_000
                characters_per_line, line_height, padding = 105, 285_000, 90_000
                font_size, bold, italic = 1800, False, False
            else:
                x, width = 650_000, 10_892_000
                characters_per_line, line_height, padding = 120, 240_000, 80_000
                font_size, bold, italic = 1400, False, True
            while remaining:
                available = SLIDE_CONTENT_BOTTOM - y
                maximum_lines = (available - padding) // line_height
                if maximum_lines < 1:
                    new_slide()
                    continue
                prefix_length = _text_prefix_for_lines(
                    remaining, characters_per_line, maximum_lines
                )
                fragment = remaining[:prefix_length]
                remaining = remaining[prefix_length:]
                line_count = min(
                    maximum_lines,
                    _text_line_count(fragment, characters_per_line),
                )
                height = padding + max(1, line_count) * line_height
                slides[-1].append(
                    {
                        "block": block,
                        "text": fragment,
                        "x": x,
                        "y": y,
                        "width": width,
                        "height": height,
                        "font_size": font_size,
                        "bold": bold,
                        "italic": italic,
                    }
                )
                y += height + SLIDE_ITEM_GAP
                if remaining:
                    new_slide()
            continue

        if block_type == "TABLE":
            rows = block["rows"]
            assert isinstance(rows, list)
            remaining_rows = list(rows)
            emitted = False
            while remaining_rows or not emitted:
                available = SLIDE_CONTENT_BOTTOM - y
                possible_rows = available // 350_000 - 1
                if possible_rows < 1 and remaining_rows:
                    new_slide()
                    continue
                if not remaining_rows and available < 350_000:
                    new_slide()
                    continue
                take = min(len(remaining_rows), max(0, possible_rows))
                chunk = remaining_rows[:take]
                remaining_rows = remaining_rows[take:]
                height = (len(chunk) + 1) * 350_000
                slides[-1].append(
                    {
                        "block": block,
                        "rows": chunk,
                        "x": 650_000,
                        "y": y,
                        "width": 10_892_000,
                        "height": height,
                    }
                )
                emitted = True
                y += height + SLIDE_ITEM_GAP
                if remaining_rows:
                    new_slide()
            continue

        if block_type == "IMAGE":
            block_id = str(block["block_id"])
            image_width, image_height = _image_dimensions(
                asset_data[block_id],
                str(block["media_type"]),
                label=str(block["asset_reference"]),
            )
            _, _, width, height = _fit_box(
                image_width, image_height, 0, 0, 4_572_000, 2_743_200
            )
            if y + height > SLIDE_CONTENT_BOTTOM:
                new_slide()
            slides[-1].append(
                {
                    "block": block,
                    "x": 650_000,
                    "y": y,
                    "width": width,
                    "height": height,
                }
            )
            y += height + SLIDE_ITEM_GAP
            continue

        raise ConversionError(f"unsupported editable PPTX block type: {block_type}")
    return slides or [[]]


def _geometry_slide_layout(
    content: Mapping[str, object], asset_data: Mapping[str, bytes]
) -> list[list[dict[str, object]]]:
    if content.get("fidelity_mode") != "GEOMETRY_AWARE":
        raise ConversionError(
            "VISUAL_FIDELITY_BEST_EFFORT requires fidelity_mode GEOMETRY_AWARE"
        )
    blocks = content["blocks"]
    assert isinstance(blocks, list)
    if not blocks:
        raise ConversionError(
            "VISUAL_FIDELITY_BEST_EFFORT requires at least one geometry-captured block"
        )
    by_page: dict[int, list[Mapping[str, object]]] = {}
    page_dimensions: dict[int, tuple[str, float, float]] = {}
    for block in blocks:
        assert isinstance(block, dict)
        provenance = block["provenance"]
        assert isinstance(provenance, dict)
        page = provenance.get("source_page")
        box = provenance.get("bounding_box")
        if provenance.get("geometry_status") != "CAPTURED" or not isinstance(box, dict):
            raise ConversionError(
                f"VISUAL_FIDELITY_BEST_EFFORT requires captured geometry for block {block.get('block_id')}"
            )
        if not isinstance(page, int) or isinstance(page, bool):
            raise ConversionError(
                f"VISUAL_FIDELITY_BEST_EFFORT requires integer source_page for block {block.get('block_id')}"
            )
        dimensions = (
            str(box["coordinate_system"]),
            float(box["page_width"]),
            float(box["page_height"]),
        )
        prior = page_dimensions.setdefault(page, dimensions)
        if prior != dimensions:
            raise ConversionError(
                f"inconsistent coordinate system or page dimensions on source page {page}"
            )
        by_page.setdefault(page, []).append(block)
    pages = sorted(by_page)
    if pages != list(range(1, max(pages) + 1)):
        raise ConversionError(
            "VISUAL_FIDELITY_BEST_EFFORT source pages must be contiguous starting at page 1"
        )

    slides: list[list[dict[str, object]]] = []
    for page in pages:
        _, page_width, page_height = page_dimensions[page]
        scale = min(SLIDE_WIDTH / page_width, SLIDE_HEIGHT / page_height)
        offset_x = (SLIDE_WIDTH - page_width * scale) / 2
        offset_y = (SLIDE_HEIGHT - page_height * scale) / 2
        items: list[dict[str, object]] = []
        for block in by_page[page]:
            provenance = block["provenance"]
            assert isinstance(provenance, dict)
            box = provenance["bounding_box"]
            assert isinstance(box, dict)
            x = min(
                SLIDE_WIDTH - 1,
                max(0, int(round(offset_x + float(box["x"]) * scale))),
            )
            y = min(
                SLIDE_HEIGHT - 1,
                max(0, int(round(offset_y + float(box["y"]) * scale))),
            )
            width = max(1, int(round(float(box["width"]) * scale)))
            height = max(1, int(round(float(box["height"]) * scale)))
            width = max(1, min(width, SLIDE_WIDTH - x))
            height = max(1, min(height, SLIDE_HEIGHT - y))
            item: dict[str, object] = {
                "block": block,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            }
            block_type = block["block_type"]
            if block_type in {"HEADING", "PARAGRAPH", "CAPTION"}:
                item["text"] = block["text"]
                item["font_size"] = 2400 if block_type == "HEADING" else (1400 if block_type == "CAPTION" else 1800)
                item["bold"] = block_type == "HEADING"
                item["italic"] = block_type == "CAPTION"
            elif block_type == "TABLE":
                item["rows"] = block["rows"]
            elif block_type == "IMAGE":
                block_id = str(block["block_id"])
                image_width, image_height = _image_dimensions(
                    asset_data[block_id],
                    str(block["media_type"]),
                    label=str(block["asset_reference"]),
                )
                fitted_x, fitted_y, fitted_width, fitted_height = _fit_box(
                    image_width, image_height, x, y, width, height
                )
                item.update(
                    {
                        "x": fitted_x,
                        "y": fitted_y,
                        "width": fitted_width,
                        "height": fitted_height,
                    }
                )
            items.append(item)
        slides.append(items)
    return slides


def _page_image_blocks(content: Mapping[str, object]) -> list[Mapping[str, object]]:
    if content.get("fidelity_mode") != "PAGE_IMAGE":
        raise ConversionError(
            "PAGE_AS_SLIDE requires fidelity_mode PAGE_IMAGE; use EDITABLE_PRESENTATION otherwise"
        )
    blocks = content["blocks"]
    assert isinstance(blocks, list)
    images = _image_blocks(content)
    image_ids = {block["block_id"] for block in images}
    if not images:
        raise ConversionError("PAGE_AS_SLIDE requires at least one declared page-image asset")
    pages: list[int] = []
    for block in images:
        provenance = block["provenance"]
        assert isinstance(provenance, dict)
        page = provenance.get("source_page")
        if not isinstance(page, int) or isinstance(page, bool):
            raise ConversionError("every PAGE_AS_SLIDE image requires an integer source_page")
        pages.append(page)
    if len(pages) != len(set(pages)):
        raise ConversionError("PAGE_AS_SLIDE requires exactly one declared image asset per page")
    expected = list(range(1, max(pages) + 1))
    if sorted(pages) != expected:
        raise ConversionError("PAGE_AS_SLIDE source pages must be contiguous starting at page 1")
    for block in blocks:
        assert isinstance(block, dict)
        if block.get("block_type") == "IMAGE":
            continue
        if block.get("block_type") != "CAPTION" or block.get("target_block_id") not in image_ids:
            raise ConversionError(
                "PAGE_IMAGE content may contain only page IMAGE blocks and captions targeting them"
            )
    return sorted(images, key=lambda block: int(block["provenance"]["source_page"]))  # type: ignore[index]


def render_pptx(
    content: Mapping[str, object],
    asset_data: Mapping[str, bytes],
    *,
    output_profile: str,
) -> bytes:
    image_blocks = _image_blocks(content)
    image_names = {
        str(block["block_id"]): f"image{index}.{IMAGE_EXTENSION[str(block['media_type'])]}"
        for index, block in enumerate(image_blocks, start=1)
    }
    if output_profile == "PAGE_AS_SLIDE":
        slide_groups = [[block] for block in _page_image_blocks(content)]
    elif output_profile == "VISUAL_FIDELITY_BEST_EFFORT":
        slide_groups = _geometry_slide_layout(content, asset_data)
    else:
        slide_groups = _editable_slide_layout(content, asset_data)

    slide_parts: dict[str, bytes] = {}
    slide_rel_parts: dict[str, bytes] = {}
    for slide_index, group in enumerate(slide_groups, start=1):
        shapes: list[str] = []
        relations = [
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
        ]
        shape_id = 2
        image_relation_index = 2
        if output_profile == "PAGE_AS_SLIDE":
            block = group[0]
            block_id = str(block["block_id"])
            relation_id = f"rId{image_relation_index}"
            relations.append(
                f'<Relationship Id="{relation_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/{image_names[block_id]}"/>'
            )
            image_width, image_height = _image_dimensions(
                asset_data[block_id], str(block["media_type"]), label=str(block["asset_reference"])
            )
            fitted = _fit_box(
                image_width, image_height, 0, 0, SLIDE_WIDTH, SLIDE_HEIGHT
            )
            shapes.append(_ppt_picture(shape_id, block, relation_id, *fitted))
        else:
            for item in group:
                assert isinstance(item, dict)
                block = item["block"]
                assert isinstance(block, dict)
                block_type = block["block_type"]
                description = f"block_id={block['block_id']};reading_order={block['reading_order']}"
                x = int(item["x"])
                y = int(item["y"])
                width = int(item["width"])
                height = int(item["height"])
                if block_type == "HEADING":
                    shapes.append(_ppt_text_shape(shape_id, f"Heading {block['block_id']}", str(item["text"]), x, y, width, height, size=int(item["font_size"]), bold=bool(item["bold"]), description=description))
                elif block_type == "PARAGRAPH":
                    shapes.append(_ppt_text_shape(shape_id, f"Paragraph {block['block_id']}", str(item["text"]), x, y, width, height, size=int(item["font_size"]), description=description))
                elif block_type == "TABLE":
                    rendered_block = dict(block)
                    rendered_block["rows"] = item["rows"]
                    shapes.append(_ppt_table_shape(shape_id, rendered_block, x, y, width, height))
                elif block_type == "IMAGE":
                    block_id = str(block["block_id"])
                    relation_id = f"rId{image_relation_index}"
                    image_relation_index += 1
                    relations.append(
                        f'<Relationship Id="{relation_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/{image_names[block_id]}"/>'
                    )
                    shapes.append(_ppt_picture(shape_id, block, relation_id, x, y, width, height))
                elif block_type == "CAPTION":
                    shapes.append(_ppt_text_shape(shape_id, f"Caption {block['block_id']}", str(item["text"]), x, y, width, height, size=int(item["font_size"]), italic=bool(item["italic"]), description=description))
                shape_id += 1
        slide = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<p:sld {PML_NS}><p:cSld><p:spTree>{_ppt_group_properties()}'
            + "".join(shapes)
            + '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
        ).encode("utf-8")
        slide_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(relations) + "</Relationships>"
        ).encode("utf-8")
        slide_parts[f"ppt/slides/slide{slide_index}.xml"] = slide
        slide_rel_parts[f"ppt/slides/_rels/slide{slide_index}.xml.rels"] = slide_rels

    presentation_relations = [
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
    ]
    slide_ids = []
    for index in range(1, len(slide_groups) + 1):
        relationship_id = f"rId{index + 1}"
        presentation_relations.append(
            f'<Relationship Id="{relationship_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{index}.xml"/>'
        )
        slide_ids.append(f'<p:sldId id="{255 + index}" r:id="{relationship_id}"/>')
    presentation = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:presentation {PML_NS}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        '<p:sldIdLst>' + "".join(slide_ids) + '</p:sldIdLst>'
        f'<p:sldSz cx="{SLIDE_WIDTH}" cy="{SLIDE_HEIGHT}" type="screen16x9"/>'
        '<p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle/></p:presentation>'
    ).encode("utf-8")
    presentation_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(presentation_relations) + "</Relationships>"
    ).encode("utf-8")
    master, master_rels, layout, layout_rels = _ppt_master_and_layout()
    overrides = [
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>',
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>',
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>',
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    overrides.extend(
        f'<Override PartName="/ppt/slides/slide{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for index in range(1, len(slide_groups) + 1)
    )
    defaults = [
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
    ]
    for extension, media_type in sorted({value: key for key, value in IMAGE_EXTENSION.items()}.items()):
        if any(name.endswith("." + extension) for name in image_names.values()):
            defaults.append(f'<Default Extension="{extension}" ContentType="{media_type}"/>')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        + "".join(defaults) + "".join(overrides) + '</Types>'
    ).encode("utf-8")
    parts: dict[str, bytes] = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": _package_relationships("ppt/presentation.xml", "officeDocument"),
        "customXml/item1.xml": _canonical_custom_xml(content),
        "docProps/app.xml": _app_properties("Thien Document Evidence", "Slides", len(slide_groups)),
        "docProps/core.xml": _core_properties(str(content["content_id"])),
        "ppt/_rels/presentation.xml.rels": presentation_rels,
        "ppt/presentation.xml": presentation,
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": layout_rels,
        "ppt/slideLayouts/slideLayout1.xml": layout,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": master_rels,
        "ppt/slideMasters/slideMaster1.xml": master,
        "ppt/theme/theme1.xml": _ppt_theme(),
        **slide_parts,
        **slide_rel_parts,
    }
    for block in image_blocks:
        block_id = str(block["block_id"])
        parts[f"ppt/media/{image_names[block_id]}"] = asset_data[block_id]
    return _zip_bytes(parts)


def _markdown_escape(text: str) -> str:
    value = text.replace("\\", "\\\\")
    for character in "`*_{}[]<>#":
        value = value.replace(character, "\\" + character)
    return value


def _markdown_locator(block: Mapping[str, object]) -> str:
    provenance = block["provenance"]
    assert isinstance(provenance, dict)
    attributes = {
        "data-block-id": block["block_id"],
        "data-block-type": block["block_type"],
        "data-reading-order": block["reading_order"],
        "data-source-page": provenance["source_page"],
        "data-source-region": provenance["source_region"],
    }
    rendered = " ".join(
        f'{name}="{_xml_escape(value, attribute=True)}"' for name, value in attributes.items()
    )
    return f"<span {rendered}></span>"


def render_markdown(content: Mapping[str, object]) -> bytes:
    blocks = content["blocks"]
    assert isinstance(blocks, list)
    lines: list[str] = []
    for block in blocks:
        assert isinstance(block, dict)
        lines.append(_markdown_locator(block))
        block_type = block["block_type"]
        if block_type == "HEADING":
            lines.append("#" * int(block["level"]) + " " + _markdown_escape(str(block["text"])))
        elif block_type == "PARAGRAPH":
            lines.append(_markdown_escape(str(block["text"])))
        elif block_type == "TABLE":
            columns = block["columns"]
            rows = block["rows"]
            assert isinstance(columns, list) and isinstance(rows, list)

            def cell(value: object) -> str:
                raw = "" if value is None else str(value)
                return _markdown_escape(raw).replace("|", "\\|").replace("\n", "<br>")

            lines.append("| " + " | ".join(cell(value) for value in columns) + " |")
            lines.append("| " + " | ".join("---" for _ in columns) + " |")
            for row in rows:
                assert isinstance(row, list)
                lines.append("| " + " | ".join(cell(value) for value in row) + " |")
        elif block_type == "IMAGE":
            alt = "" if block.get("alt_text") is None else str(block["alt_text"])
            reference = quote(str(block["asset_reference"]), safe="/-._~")
            lines.append(f"![{_markdown_escape(alt)}]({reference})")
        elif block_type == "CAPTION":
            lines.append(f"*{_markdown_escape(str(block['text']))}*")
        lines.append("")
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def inspect_ooxml(data: bytes, output_format: str, block_ids: Iterable[str]) -> None:
    required = {
        "DOCX": {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "customXml/item1.xml"},
        "XLSX": {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/worksheets/sheet1.xml", "customXml/item1.xml"},
        "PPTX": {"[Content_Types].xml", "_rels/.rels", "ppt/presentation.xml", "ppt/slides/slide1.xml", "customXml/item1.xml"},
    }[output_format]
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ConversionError("OOXML contains duplicate ZIP member names")
            missing = sorted(required - set(names))
            if missing:
                raise ConversionError(f"OOXML is missing required members: {missing}")
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ConversionError(f"OOXML CRC test failed for {bad_member}")
            lowered = [name.casefold() for name in names]
            if any(name.endswith(("vbaproject.bin", ".vbs", ".js")) for name in lowered):
                raise ConversionError("OOXML unexpectedly contains active content")
            for name in names:
                if name.endswith((".xml", ".rels")):
                    payload = archive.read(name)
                    try:
                        root = ET.fromstring(payload)
                    except ET.ParseError as exc:
                        raise ConversionError(f"invalid OOXML XML member {name}: {exc}") from exc
                    for element in root.iter():
                        if element.attrib.get("TargetMode", "").casefold() == "external":
                            raise ConversionError(f"OOXML contains external relationship in {name}")
            custom = archive.read("customXml/item1.xml").decode("utf-8")
            for block_id in block_ids:
                if block_id not in custom:
                    raise ConversionError(f"OOXML provenance payload omits block {block_id}")
    except zipfile.BadZipFile as exc:
        raise ConversionError(f"rendered {output_format} is not a valid ZIP package") from exc


def _validate_profile(
    output_format: str,
    output_profile: str | None,
    presentation_intent: str | None,
) -> tuple[str | None, str | None]:
    if output_format in {"JSON", "MD"}:
        if output_profile is not None or presentation_intent is not None:
            raise ConversionError("JSON/MD outputs do not accept conversion profile or presentation intent")
        return None, None
    if output_profile is None:
        if output_format == "DOCX":
            output_profile = "SEMANTIC_EDITABLE"
        elif output_format == "XLSX":
            output_profile = "STRUCTURED_DATA"
        else:
            raise ConversionError("PPTX requires explicit --output-profile and --presentation-intent")
    if output_profile not in PROFILE_BY_FORMAT[output_format]:
        raise ConversionError(f"unsupported {output_format} output profile: {output_profile}")
    if output_format != "PPTX":
        if presentation_intent not in {None, "NOT_APPLICABLE"}:
            raise ConversionError(f"{output_format} presentation intent must be NOT_APPLICABLE")
        return output_profile, "NOT_APPLICABLE"
    if presentation_intent in {None, "AMBIGUOUS"}:
        raise ConversionError("PPTX intent must be explicitly resolved before rendering")
    expected = PPTX_INTENT_PROFILE.get(presentation_intent)
    if expected is None:
        raise ConversionError(f"unsupported PPTX presentation intent: {presentation_intent}")
    if output_profile != expected:
        raise ConversionError(
            f"PPTX intent {presentation_intent} requires output profile {expected}"
        )
    return output_profile, presentation_intent


def _build_manifest(
    content: Mapping[str, object],
    *,
    output_format: str,
    output_relative: str,
    output_bytes: bytes,
    output_profile: str | None,
) -> dict[str, object]:
    digest = sha256_bytes(output_bytes)
    stable_seed = canonical_json_bytes({
        "content_id": content["content_id"],
        "format": output_format,
        "profile": output_profile,
        "sha256": digest,
        "skill_release_version": SKILL_RELEASE_VERSION,
    })
    stable_id = sha256_bytes(stable_seed)[:24]
    limitations = list(content.get("limitations", []))
    qa_status = "PASS"
    top_status = "PASS"
    if output_format in {"DOCX", "XLSX", "PPTX"}:
        qa_status = "NOT_TESTED"
        top_status = "NOT_TESTED"
        limitations.append(
            "Structural OOXML/ZIP validation passed; visual render/import QA was not executed."
        )
    elif output_format == "MD" and _image_blocks(content):
        qa_status = "PASS_WITH_WARNING"
        top_status = "PASS_WITH_WARNINGS"
        limitations.append(
            "Markdown image links retain declared asset_reference values; image assets were not copied."
        )
    if output_profile == "VISUAL_FIDELITY_BEST_EFFORT":
        limitations.append(
            "Visual-fidelity output is best effort; no rendered visual comparison was executed."
        )
    manifest = {
        "schema_version": "1.0.0",
        "skill_id": content["skill_id"],
        "skill_release_version": SKILL_RELEASE_VERSION,
        "manifest_id": f"manifest-{stable_id}",
        "package_id": f"conversion-{stable_id}",
        "task_profile": "CONVERT_DOCUMENT",
        "generated_at": "UNKNOWN",
        "status": top_status,
        "artifacts": [
            {
                "artifact_id": f"artifact-{stable_id}",
                "artifact_role": "STRUCTURED_DATA" if output_format == "XLSX" else "PRIMARY_CONTENT",
                "format": output_format,
                "media_type": MEDIA_TYPE[output_format],
                "location_reference": output_relative,
                "checksum": {
                    "algorithm": "SHA-256",
                    "digest": digest,
                    "computed_at": "UNKNOWN",
                    "object_role": "DERIVATIVE",
                },
                "creation_status": "CREATED",
                "qa_status": qa_status,
                "record_count": len(content["blocks"]),  # type: ignore[arg-type]
                "source_document_ids": [content["document_id"]],
                "limitations": limitations,
            }
        ],
        "limitations": limitations,
        "human_review_status": "PENDING",
    }
    validate_schema(manifest, "artifact-manifest.schema.json")
    return manifest


def _checksum_record(data: bytes, *, object_role: str) -> dict[str, object]:
    return {
        "algorithm": "SHA-256",
        "digest": sha256_bytes(data),
        "computed_at": "UNKNOWN",
        "object_role": object_role,
    }


def _build_conversion_run(
    content: Mapping[str, object],
    *,
    canonical_relative: str,
    canonical_bytes: bytes,
    output_format: str,
    output_profile: str | None,
    presentation_intent: str | None,
    artifact_relative: str,
    artifact_bytes: bytes,
    manifest_relative: str,
    manifest: Mapping[str, object],
    manifest_bytes: bytes,
) -> dict[str, object]:
    artifacts = manifest["artifacts"]
    assert isinstance(artifacts, list) and len(artifacts) == 1
    artifact = artifacts[0]
    assert isinstance(artifact, dict)
    run_seed = canonical_json_bytes(
        {
            "runtime_skill_release_version": SKILL_RELEASE_VERSION,
            "source_skill_release_version": content["skill_release_version"],
            "canonical_sha256": sha256_bytes(canonical_bytes),
            "artifact_sha256": sha256_bytes(artifact_bytes),
            "manifest_sha256": sha256_bytes(manifest_bytes),
            "output_format": output_format,
            "output_profile": output_profile,
            "presentation_intent": presentation_intent,
        }
    )
    run = {
        "schema_version": "1.0.0",
        "run_id": "conversion-run-" + sha256_bytes(run_seed)[:24],
        "tool": {
            "name": TOOL_NAME,
            "version": TOOL_VERSION,
        },
        "runtime_skill": {
            "skill_id": "thien-skill-document-evidence",
            "release_version": SKILL_RELEASE_VERSION,
        },
        "source_canonical": {
            "location_reference": canonical_relative,
            "schema_version": content["schema_version"],
            "source_skill_release_version": content["skill_release_version"],
            "content_id": content["content_id"],
            "document_id": content["document_id"],
            "checksum": _checksum_record(
                canonical_bytes, object_role="WORKING_COPY"
            ),
        },
        "request": {
            "output_format": output_format,
            "output_profile": output_profile,
            "presentation_intent": presentation_intent,
        },
        "outputs": {
            "artifact": {
                "artifact_id": artifact["artifact_id"],
                "format": output_format,
                "media_type": MEDIA_TYPE[output_format],
                "location_reference": artifact_relative,
                "checksum": _checksum_record(
                    artifact_bytes, object_role="DERIVATIVE"
                ),
            },
            "artifact_manifest": {
                "manifest_id": manifest["manifest_id"],
                "media_type": "application/json",
                "location_reference": manifest_relative,
                "checksum": _checksum_record(
                    manifest_bytes, object_role="DERIVATIVE"
                ),
            },
        },
        "generated_at": "UNKNOWN",
        "status": manifest["status"],
        "structural_qa_status": "PASS",
        "visual_qa_status": (
            "NOT_TESTED" if output_format in {"DOCX", "XLSX", "PPTX"}
            else "NOT_APPLICABLE"
        ),
        "limitations": list(manifest["limitations"]),
        "human_review_status": manifest["human_review_status"],
    }
    validate_schema(run, "conversion-run.schema.json")
    return run


def render_canonical_artifact(
    *,
    root: str | Path,
    canonical_path: str | Path,
    output_path: str | Path,
    output_format: str,
    output_profile: str | None = None,
    presentation_intent: str | None = None,
    assets_root: str | Path | None = None,
    manifest_path: str | Path | None = None,
    conversion_run_path: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    """Validate, render, inspect, and transactionally publish three linked files."""

    authorized_root = resolve_root(root)
    canonical_file = resolve_regular_file(authorized_root, canonical_path, label="canonical input")
    selected_format = output_format.upper()
    if selected_format not in FORMAT_SUFFIX:
        raise ConversionError(f"unsupported output format: {output_format}")
    output = resolve_output(authorized_root, output_path, label="artifact output")
    if output.suffix.casefold() != FORMAT_SUFFIX[selected_format]:
        raise ConversionError(
            f"{selected_format} output must use the real {FORMAT_SUFFIX[selected_format]} extension"
        )
    profile, intent = _validate_profile(selected_format, output_profile, presentation_intent)
    if manifest_path is None:
        manifest_path = output.with_name(output.name + ".manifest.json")
    manifest_output = resolve_output(authorized_root, manifest_path, label="manifest output")
    if manifest_output.suffix.casefold() != ".json":
        raise ConversionError("manifest output must use .json extension")
    if conversion_run_path is None:
        conversion_run_path = output.with_name(output.name + ".conversion-run.json")
    run_output = resolve_output(
        authorized_root, conversion_run_path, label="conversion-run output"
    )
    if run_output.suffix.casefold() != ".json":
        raise ConversionError("conversion-run output must use .json extension")
    output_paths = [output, manifest_output, run_output]
    if len(set(output_paths)) != len(output_paths):
        raise ConversionError(
            "artifact, artifact manifest, and conversion-run outputs must be different files"
        )
    if not overwrite:
        for path in output_paths:
            if path.exists():
                raise ConversionError(f"output already exists; use --overwrite: {path}")

    content, canonical_bytes = load_json_object(canonical_file, label="canonical input")
    validate_canonical(content)
    asset_directory = (
        resolve_directory(authorized_root, assets_root, label="assets root")
        if assets_root is not None
        else None
    )
    require_embedded_assets = selected_format in {"DOCX", "PPTX"}
    asset_data, asset_paths = _load_assets(
        content, asset_directory, required=require_embedded_assets
    )
    if selected_format == "PPTX" and profile == "PAGE_AS_SLIDE":
        _page_image_blocks(content)

    protected = [canonical_file, *asset_paths]
    for path in output_paths:
        reject_output_alias(path, protected)
    for index, left in enumerate(output_paths):
        if not left.exists():
            continue
        for right in output_paths[index + 1:]:
            if not right.exists():
                continue
            try:
                if os.path.samefile(left, right):
                    raise ConversionError(
                        "transaction outputs must not be hard-link aliases"
                    )
            except OSError as exc:
                raise ConversionError(
                    f"cannot verify transaction output inode separation: {exc}"
                ) from exc

    if selected_format == "JSON":
        artifact_bytes = canonical_json_bytes(content, pretty=True)
    elif selected_format == "MD":
        artifact_bytes = render_markdown(content)
    elif selected_format == "DOCX":
        artifact_bytes = render_docx(content, asset_data)
    elif selected_format == "XLSX":
        artifact_bytes = render_xlsx(content)
    else:
        assert profile is not None
        artifact_bytes = render_pptx(content, asset_data, output_profile=profile)

    if selected_format in {"DOCX", "XLSX", "PPTX"}:
        inspect_ooxml(
            artifact_bytes,
            selected_format,
            (str(block["block_id"]) for block in content["blocks"]),  # type: ignore[index]
        )
    output_relative = output.relative_to(authorized_root).as_posix()
    safe_relative_path(output_relative)
    manifest_relative = manifest_output.relative_to(authorized_root).as_posix()
    run_relative = run_output.relative_to(authorized_root).as_posix()
    canonical_relative = canonical_file.relative_to(authorized_root).as_posix()
    safe_relative_path(manifest_relative)
    safe_relative_path(run_relative)
    safe_relative_path(canonical_relative)
    manifest = _build_manifest(
        content,
        output_format=selected_format,
        output_relative=output_relative,
        output_bytes=artifact_bytes,
        output_profile=profile,
    )
    manifest_bytes = canonical_json_bytes(manifest, pretty=True)
    conversion_run = _build_conversion_run(
        content,
        canonical_relative=canonical_relative,
        canonical_bytes=canonical_bytes,
        output_format=selected_format,
        output_profile=profile,
        presentation_intent=intent,
        artifact_relative=output_relative,
        artifact_bytes=artifact_bytes,
        manifest_relative=manifest_relative,
        manifest=manifest,
        manifest_bytes=manifest_bytes,
    )
    conversion_run_bytes = canonical_json_bytes(conversion_run, pretty=True)
    _transactional_publish(
        [
            (output, artifact_bytes),
            (manifest_output, manifest_bytes),
            (run_output, conversion_run_bytes),
        ],
        overwrite=overwrite,
    )
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("canonical", help="canonical-content JSON path below --root")
    parser.add_argument("--root", default=".", help="authorized input/output root")
    parser.add_argument("--output", required=True, help="artifact path below --root")
    parser.add_argument("--format", required=True, choices=tuple(FORMAT_SUFFIX))
    parser.add_argument(
        "--output-profile",
        choices=tuple(sorted({profile for values in PROFILE_BY_FORMAT.values() for profile in values})),
        help="DOCX/XLSX profile or explicit PPTX profile",
    )
    parser.add_argument(
        "--presentation-intent",
        choices=("NOT_APPLICABLE", "PRESENTATION", "FAITHFUL_PAGE_CONVERSION", "VISUAL_FIDELITY", "AMBIGUOUS"),
        help="required and resolved for PPTX",
    )
    parser.add_argument("--assets-root", help="directory below --root containing declared image assets")
    parser.add_argument("--manifest", help="manifest path; defaults to <output>.manifest.json")
    parser.add_argument(
        "--conversion-run",
        help="closed run sidecar path; defaults to <output>.conversion-run.json",
    )
    parser.add_argument("--overwrite", action="store_true", help="atomically replace exact output files")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        manifest = render_canonical_artifact(
            root=arguments.root,
            canonical_path=arguments.canonical,
            output_path=arguments.output,
            output_format=arguments.format,
            output_profile=arguments.output_profile,
            presentation_intent=arguments.presentation_intent,
            assets_root=arguments.assets_root,
            manifest_path=arguments.manifest,
            conversion_run_path=arguments.conversion_run,
            overwrite=arguments.overwrite,
        )
    except ConversionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(canonical_json_bytes(manifest, pretty=True).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
