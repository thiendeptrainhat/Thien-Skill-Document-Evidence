#!/usr/bin/env python3
"""Create a deterministic, read-only document inventory.

The script hashes source bytes, records conservative signature/MIME findings,
and performs bounded read-only checks for PDF and OOXML active content. It does
not execute document content, open URLs, extract archives, or modify sources.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import io
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from typing import BinaryIO, Iterable, Mapping
import xml.etree.ElementTree as ET
import zipfile


TOOL_NAME = "thien-document-inventory"
TOOL_VERSION = "1.0.0"
CHUNK_SIZE = 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 512 * 1024 * 1024
MAX_RELATIONSHIP_BYTES = 2 * 1024 * 1024
MAX_RELATIONSHIP_TOTAL_BYTES = 16 * 1024 * 1024
MAX_PDF_SCAN_BYTES = 256 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1_000

EXTENSION_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".zip": "application/zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".docm": "application/vnd.ms-word.document.macroEnabled.12",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pptm": "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".ppt": "application/vnd.ms-powerpoint",
    ".rtf": "application/rtf",
    ".json": "application/json",
    ".xml": "application/xml",
    ".csv": "text/csv",
    ".txt": "text/plain",
}

OOXML_MIME = {
    "word": {
        False: EXTENSION_MIME[".docx"],
        True: EXTENSION_MIME[".docm"],
    },
    "xl": {
        False: EXTENSION_MIME[".xlsx"],
        True: EXTENSION_MIME[".xlsm"],
    },
    "ppt": {
        False: EXTENSION_MIME[".pptx"],
        True: EXTENSION_MIME[".pptm"],
    },
}


class InventoryError(ValueError):
    """Raised for unsafe paths, unreadable inputs, or invalid CLI requests."""


class UnsafeRelationshipXml(ValueError):
    """Raised when OOXML relationship XML declares a DTD or entity set."""


class _RelationshipTreeBuilder(ET.TreeBuilder):
    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        del name, pubid, system
        raise UnsafeRelationshipXml("DTD declarations are not allowed in relationships XML")


def open_regular_nofollow(path: Path) -> BinaryIO:
    """Open a regular file without following a final-component symlink."""

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise InventoryError(f"cannot safely open {path.name}: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise InventoryError(f"source is not a regular file: {path.name}")
        return os.fdopen(descriptor, "rb")
    except Exception:
        os.close(descriptor)
        raise


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _absolute_without_symlink_resolution(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def resolve_authorized_root(raw_root: str | Path) -> Path:
    supplied = Path(raw_root).expanduser()
    if supplied.is_symlink():
        raise InventoryError(f"authorized root must not be a symlink: {supplied}")
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise InventoryError(f"cannot resolve authorized root {supplied}: {exc}") from exc
    if not root.is_dir():
        raise InventoryError(f"authorized root is not a directory: {supplied}")
    return root


def resolve_input(root: Path, raw_path: str | Path) -> Path:
    supplied = Path(raw_path).expanduser()
    lexical = supplied if supplied.is_absolute() else root / supplied
    lexical = _absolute_without_symlink_resolution(lexical)
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise InventoryError(f"input path escapes authorized root: {raw_path}") from exc

    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise InventoryError(f"symlink input is not allowed: {cursor.relative_to(root)}")
    if not lexical.exists():
        raise InventoryError(f"input path does not exist: {raw_path}")
    return lexical


def resolve_output(root: Path, raw_path: str | Path) -> Path:
    supplied = Path(raw_path).expanduser()
    lexical = supplied if supplied.is_absolute() else root / supplied
    lexical = _absolute_without_symlink_resolution(lexical)
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise InventoryError(f"output path escapes authorized root: {raw_path}") from exc
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise InventoryError(f"output must not traverse a symlink: {relative}")
    if lexical.is_symlink():
        raise InventoryError(f"output must not be a symlink: {relative}")
    if not lexical.parent.is_dir():
        raise InventoryError(f"output parent must be an existing directory: {lexical.parent}")
    if lexical.exists() and not lexical.is_file():
        raise InventoryError(f"output is not a regular file path: {relative}")
    return lexical


def walk_regular_files(root: Path, inputs: Iterable[str | Path]) -> list[Path]:
    collected: dict[str, Path] = {}

    def visit(path: Path) -> None:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise InventoryError(f"symlink input is not allowed: {relative}")
        if path.is_file():
            collected[relative] = path
            return
        if not path.is_dir():
            raise InventoryError(f"input is not a regular file or directory: {relative}")
        try:
            entries = sorted(os.scandir(path), key=lambda item: item.name)
        except OSError as exc:
            raise InventoryError(f"cannot enumerate {relative or '.'}: {exc}") from exc
        for entry in entries:
            entry_path = Path(entry.path)
            if entry.is_symlink():
                raise InventoryError(
                    f"symlink encountered during inventory: {entry_path.relative_to(root)}"
                )
            if entry.is_dir(follow_symlinks=False) or entry.is_file(follow_symlinks=False):
                visit(entry_path)
            else:
                raise InventoryError(
                    f"special filesystem entry is not allowed: {entry_path.relative_to(root)}"
                )

    for raw_path in inputs:
        visit(resolve_input(root, raw_path))
    return [collected[key] for key in sorted(collected)]


def _source_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Return fields that must remain stable while a source snapshot is captured."""

    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def capture_source_snapshot(path: Path, snapshot: Path) -> tuple[str, int]:
    """Copy one stable source view while hashing it for later inspection.

    All signature and active-content inspection uses the private snapshot rather
    than reopening the source path. Identity and metadata checks fail closed if
    the source changes while that snapshot is being captured.
    """

    digest = hashlib.sha256()
    size = 0
    try:
        with open_regular_nofollow(path) as source, snapshot.open("xb") as target:
            before = os.fstat(source.fileno())
            while True:
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break
                target.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            target.flush()
            after = os.fstat(source.fileno())
    except OSError as exc:
        raise InventoryError(f"cannot snapshot {path.name}: {exc}") from exc

    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise InventoryError(f"source changed during snapshot: {path.name}: {exc}") from exc
    if (
        not stat.S_ISREG(current.st_mode)
        or _source_identity(before) != _source_identity(after)
        or _source_identity(current) != _source_identity(after)
        or size != after.st_size
    ):
        raise InventoryError(f"source changed during snapshot: {path.name}")
    return digest.hexdigest(), size


def read_prefix(path: Path, limit: int = 8192) -> bytes:
    try:
        with open_regular_nofollow(path) as handle:
            return handle.read(limit)
    except OSError as exc:
        raise InventoryError(f"cannot inspect {path.name}: {exc}") from exc


def detect_signature(prefix: bytes, extension: str) -> tuple[str, str | None]:
    if prefix.startswith(b"%PDF-"):
        return "PDF", "application/pdf"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG", "image/png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "JPEG", "image/jpeg"
    if prefix.startswith((b"II*\x00", b"MM\x00*")):
        return "TIFF", "image/tiff"
    if prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "ZIP_CONTAINER", "application/zip"
    if prefix.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "OLE_COMPOUND_FILE", "application/x-ole-storage"
    if prefix.lstrip().startswith(b"{\\rtf"):
        return "RTF", "application/rtf"
    if prefix.startswith((b"GIF87a", b"GIF89a")):
        return "GIF", "image/gif"
    if prefix.startswith(b"\x7fELF") or prefix.startswith(b"MZ"):
        return "EXECUTABLE", "application/x-executable"
    if b"\x00" not in prefix:
        try:
            decoded = prefix.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            stripped = decoded.lstrip("\ufeff \t\r\n")
            if extension == ".json" and stripped.startswith(("{", "[")):
                return "JSON_TEXT", "application/json"
            if extension == ".xml" and stripped.startswith("<"):
                return "XML_TEXT", "application/xml"
            if extension == ".csv":
                return "DELIMITED_TEXT", "text/csv"
            return "UTF8_TEXT", "text/plain"
    return "UNKNOWN", None


def scan_pdf(path: Path) -> tuple[dict[str, str], bool | None, list[str]]:
    needles: Mapping[str, tuple[bytes, ...]] = {
        "javascript": (b"/JavaScript", b"/JS"),
        "embedded_files": (b"/EmbeddedFile", b"/EmbeddedFiles"),
        "external_links": (b"/URI",),
    }
    found = {key: False for key in needles}
    encrypted = False
    carry = b""
    scanned = 0
    scan_limited = False
    try:
        with open_regular_nofollow(path) as handle:
            while True:
                remaining = MAX_PDF_SCAN_BYTES - scanned
                if remaining <= 0:
                    scan_limited = handle.read(1) != b""
                    break
                chunk = handle.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                scanned += len(chunk)
                window = carry + chunk
                encrypted = encrypted or b"/Encrypt" in window
                for key, patterns in needles.items():
                    found[key] = found[key] or any(pattern in window for pattern in patterns)
                carry = window[-64:]
    except OSError as exc:
        raise InventoryError(f"cannot inspect PDF {path.name}: {exc}") from exc
    states = {
        "javascript": "DETECTED" if found["javascript"] else "NOT_DETECTED",
        "macro": "NOT_DETECTED",
        "embedded_files": "DETECTED" if found["embedded_files"] else "NOT_DETECTED",
        "external_links": "DETECTED" if found["external_links"] else "NOT_DETECTED",
    }
    limitations = [
        "PDF active-content findings use bounded byte-pattern inspection and are not malware or forensic validation."
    ]
    if scan_limited:
        limitations.append(
            f"PDF active-content scan stopped at the {MAX_PDF_SCAN_BYTES}-byte safety limit."
        )
    return states, encrypted, limitations


def _safe_zip_name(raw_name: str) -> bool:
    if not raw_name or "\\" in raw_name or "\x00" in raw_name:
        return False
    path = PurePosixPath(raw_name)
    return (
        not path.is_absolute()
        and not re.match(r"^[A-Za-z]:", raw_name)
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _xml_local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].rsplit(":", 1)[-1].casefold()


def _mark_relationship_inspection_unknown(states: dict[str, str]) -> None:
    for key in ("external_links", "javascript"):
        if states[key] != "DETECTED":
            states[key] = "UNKNOWN"


def inspect_relationship_xml(
    payload: bytes,
    states: dict[str, str],
    security_flags: list[str],
) -> None:
    """Inspect bounded OOXML relationship XML without resolving external data."""

    folded = payload.lower()
    if b"<!doctype" in folded or b"<!entity" in folded:
        security_flags.append("UNSAFE_RELATIONSHIPS_XML_DECLARATION")
        _mark_relationship_inspection_unknown(states)
        return
    try:
        parser = ET.XMLParser(target=_RelationshipTreeBuilder())
        root = ET.fromstring(payload, parser=parser)
    except UnsafeRelationshipXml:
        security_flags.append("UNSAFE_RELATIONSHIPS_XML_DECLARATION")
        _mark_relationship_inspection_unknown(states)
        return
    except (ET.ParseError, RecursionError, ValueError):
        security_flags.append("MALFORMED_RELATIONSHIPS_XML")
        _mark_relationship_inspection_unknown(states)
        return

    for element in root.iter():
        if _xml_local_name(element.tag) != "relationship":
            continue
        attributes = {
            _xml_local_name(name): value.strip()
            for name, value in element.attrib.items()
        }
        if attributes.get("targetmode", "").casefold() == "external":
            states["external_links"] = "DETECTED"
        if attributes.get("target", "").lstrip().casefold().startswith("javascript:"):
            states["javascript"] = "DETECTED"


def inspect_zip_container(
    path: Path,
) -> tuple[str, str | None, dict[str, str], bool | None, list[str], list[str]]:
    states = {
        "javascript": "NOT_DETECTED",
        "macro": "NOT_DETECTED",
        "embedded_files": "NOT_DETECTED",
        "external_links": "NOT_DETECTED",
    }
    security_flags: list[str] = []
    limitations = [
        "Archive/OOXML inspection lists metadata and bounded relationship content without extraction or execution."
    ]
    encrypted = False
    container_kind = "ZIP_CONTAINER"
    detected_mime: str | None = "application/zip"
    total_size = 0
    relationship_bytes = 0
    roots: set[str] = set()
    has_macro = False
    try:
        with open_regular_nofollow(path) as source_handle, zipfile.ZipFile(source_handle) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_MEMBERS:
                security_flags.append("ARCHIVE_MEMBER_LIMIT_EXCEEDED")
                _mark_relationship_inspection_unknown(states)
            for info in infos[: MAX_ARCHIVE_MEMBERS + 1]:
                raw_name = info.filename
                if not _safe_zip_name(raw_name):
                    security_flags.append("UNSAFE_ARCHIVE_MEMBER_PATH")
                    continue
                member_path = PurePosixPath(raw_name)
                if member_path.parts:
                    roots.add(member_path.parts[0].casefold())
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_IFMT(mode) == stat.S_IFLNK:
                    security_flags.append("ARCHIVE_SYMLINK_MEMBER")
                if info.flag_bits & 0x1:
                    encrypted = True
                    security_flags.append("ENCRYPTED_ARCHIVE_MEMBER")
                total_size += info.file_size
                if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                    security_flags.append("ARCHIVE_MEMBER_SIZE_LIMIT_EXCEEDED")
                if total_size > MAX_ARCHIVE_TOTAL_BYTES:
                    security_flags.append("ARCHIVE_TOTAL_SIZE_LIMIT_EXCEEDED")
                compressed = max(info.compress_size, 1)
                if info.file_size / compressed > MAX_COMPRESSION_RATIO:
                    security_flags.append("ARCHIVE_COMPRESSION_RATIO_LIMIT_EXCEEDED")

                folded = raw_name.casefold()
                if folded.endswith("vbaproject.bin") or "macroenabled" in folded:
                    has_macro = True
                    states["macro"] = "DETECTED"
                if "/embeddings/" in f"/{folded}" or folded.startswith("embeddings/"):
                    states["embedded_files"] = "DETECTED"
                if "/externallinks/" in f"/{folded}":
                    states["external_links"] = "DETECTED"
                if folded.endswith(".rels") and info.file_size > MAX_RELATIONSHIP_BYTES:
                    security_flags.append("RELATIONSHIP_MEMBER_SIZE_LIMIT_EXCEEDED")
                    _mark_relationship_inspection_unknown(states)
                    continue
                if folded.endswith(".rels"):
                    if relationship_bytes + info.file_size > MAX_RELATIONSHIP_TOTAL_BYTES:
                        security_flags.append("RELATIONSHIP_INSPECTION_LIMIT_EXCEEDED")
                        _mark_relationship_inspection_unknown(states)
                        continue
                    relationship_bytes += info.file_size
                    try:
                        relationships = archive.read(info)
                    except (OSError, RuntimeError, zipfile.BadZipFile):
                        security_flags.append("RELATIONSHIP_INSPECTION_FAILED")
                        _mark_relationship_inspection_unknown(states)
                    else:
                        inspect_relationship_xml(relationships, states, security_flags)
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        security_flags.append("INVALID_OR_UNREADABLE_ZIP_CONTAINER")
        limitations.append(f"ZIP container metadata could not be fully inspected: {type(exc).__name__}.")
        return container_kind, detected_mime, states, None, security_flags, limitations

    for root_name in ("word", "xl", "ppt"):
        if root_name in roots:
            container_kind = f"OOXML_{root_name.upper()}"
            detected_mime = OOXML_MIME[root_name][has_macro]
            break
    return (
        container_kind,
        detected_mime,
        states,
        encrypted,
        sorted(set(security_flags)),
        limitations,
    )


def mime_status(extension: str, declared: str | None, detected: str | None) -> str:
    if detected is None or declared is None:
        return "UNKNOWN"
    if declared == detected:
        return "MATCH"
    office_legacy = {
        ".doc": "application/x-ole-storage",
        ".xls": "application/x-ole-storage",
        ".ppt": "application/x-ole-storage",
    }
    if office_legacy.get(extension) == detected:
        return "MATCH"
    return "MISMATCH"


def active_flags(states: Mapping[str, str]) -> list[str]:
    return sorted(key.upper() for key, state in states.items() if state == "DETECTED")


def make_base_record(
    *,
    path: Path,
    root: Path,
    digest: str,
    size: int,
    document_id: str,
    copy_role: str,
    inspection_path: Path | None = None,
) -> dict[str, object]:
    relative = path.relative_to(root).as_posix()
    raw_extension = path.suffix.lower()
    extension = raw_extension if re.fullmatch(r"\.[A-Za-z0-9]{1,16}", raw_extension) else ".unknown"
    declared = EXTENSION_MIME.get(raw_extension) or mimetypes.guess_type(path.name)[0]
    inspected_source = path if inspection_path is None else inspection_path
    signature, detected = detect_signature(read_prefix(inspected_source), raw_extension)
    states = {key: "NOT_TESTED" for key in ("javascript", "macro", "embedded_files", "external_links")}
    encrypted: bool | None = None
    security_flags: list[str] = []
    limitations: list[str] = []

    if signature == "PDF":
        states, encrypted, pdf_limitations = scan_pdf(inspected_source)
        limitations.extend(pdf_limitations)
    elif signature == "ZIP_CONTAINER":
        signature, detected, states, encrypted, zip_flags, zip_limitations = inspect_zip_container(
            inspected_source
        )
        security_flags.extend(zip_flags)
        limitations.extend(zip_limitations)
    elif signature == "OLE_COMPOUND_FILE":
        states["macro"] = "UNKNOWN"
        states["embedded_files"] = "UNKNOWN"
        limitations.append("Legacy OLE active content is not parsed by the stdlib-only inspector.")
    else:
        limitations.append("Active-content inspection is not applicable or unavailable for this signature.")

    extension_mime_status = mime_status(raw_extension, declared, detected)
    flags = active_flags(states)
    if extension_mime_status == "MISMATCH":
        security_flags.append("EXTENSION_MIME_MISMATCH")
    if signature == "EXECUTABLE":
        security_flags.append("EXECUTABLE_SIGNATURE")
    security_flags.extend(f"ACTIVE_CONTENT_{flag}" for flag in flags)
    if extension == ".unknown":
        limitations.append("The source filename has no schema-safe extension; `.unknown` records that state.")

    blocking_archive_flags = {
        "UNSAFE_ARCHIVE_MEMBER_PATH",
        "ARCHIVE_SYMLINK_MEMBER",
        "ARCHIVE_MEMBER_LIMIT_EXCEEDED",
        "ARCHIVE_MEMBER_SIZE_LIMIT_EXCEEDED",
        "ARCHIVE_TOTAL_SIZE_LIMIT_EXCEEDED",
        "ARCHIVE_COMPRESSION_RATIO_LIMIT_EXCEEDED",
        "EXECUTABLE_SIGNATURE",
    }
    if encrypted:
        eligibility = "AUTHORIZATION_REQUIRED"
    elif blocking_archive_flags.intersection(security_flags):
        eligibility = "BLOCKED"
    elif security_flags or flags or extension_mime_status != "MATCH":
        eligibility = "ELIGIBLE_WITH_LIMITATIONS"
    else:
        eligibility = "ELIGIBLE"
    review_status = "REQUIRED" if eligibility != "ELIGIBLE" else "NOT_REQUIRED"

    issues: list[dict[str, str]] = []
    for flag in sorted(set(security_flags)):
        severity = "HIGH" if flag in blocking_archive_flags else "MEDIUM"
        issues.append(
            {
                "issue_code": flag,
                "severity": severity,
                "description": flag.replace("_", " ").title(),
            }
        )

    return {
        "schema_version": "1.0.0",
        "record_version": 1,
        "document_id": document_id,
        "content_id": f"sha256:{digest}",
        "evidence_ids": [],
        "package_id": None,
        "file": {
            "original_filename": path.name,
            "source_reference": relative,
            "extension": extension,
            "declared_mime_type": declared,
            "detected_mime_type": detected,
            "size_bytes": size,
            "checksum": {
                "algorithm": "SHA-256",
                "digest": digest,
                "computed_at": "UNKNOWN",
                "object_role": copy_role,
            },
        },
        "copy_role": copy_role,
        "integrity": {
            "read_status": "READABLE",
            "extension_mime_status": extension_mime_status,
            "password_protected": encrypted,
            "encrypted": encrypted,
            "active_content": states,
            "page_count": {"observed": None, "declared": None},
            "page_completeness_status": "NOT_TESTED",
            "processing_eligibility": eligibility,
            "issues": issues,
        },
        "classification": {
            "document_type": signature,
            "profile_id": None,
            "profile_version": None,
            "status": "UNCLASSIFIED",
            "method": "RULE_BASED",
            "confidence": {
                "score": None,
                "band": "UNKNOWN",
                "source": "UNKNOWN",
                "methodology": "File signature and safe container preflight only.",
            },
            "candidate_types": [],
        },
        "processing": {
            "native_text_status": "NOT_TESTED",
            "selected_route": "NOT_EXECUTED",
            "adapter_run_ids": [],
            "status": "NOT_EXECUTED",
        },
        "relationships": [],
        "data_classification": ["UNKNOWN"],
        "security_flags": sorted(set(security_flags)),
        "review_status": review_status,
        "assumptions": [
            f"Copy role was supplied as {copy_role}; this inventory does not establish provenance."
        ],
        "limitations": limitations,
    }


def build_inventory(
    root: Path,
    paths: Iterable[str | Path],
    *,
    copy_role: str = "WORKING_COPY",
) -> dict[str, object]:
    if copy_role not in {"ORIGINAL", "WORKING_COPY", "DERIVATIVE"}:
        raise InventoryError(f"unsupported copy role: {copy_role}")
    files = walk_regular_files(root, paths)
    if not files:
        raise InventoryError("no regular files were found in the requested scope")

    occurrences: defaultdict[str, int] = defaultdict(int)
    records: list[dict[str, object]] = []
    by_digest: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    with tempfile.TemporaryDirectory(prefix="thien-document-inventory-") as snapshot_dir:
        snapshot_root = Path(snapshot_dir)
        for index, path in enumerate(files):
            snapshot = snapshot_root / f"source-{index:08d}.snapshot"
            digest, size = capture_source_snapshot(path, snapshot)
            occurrences[digest] += 1
            document_id = f"doc-{digest[:24]}-{occurrences[digest]:04d}"
            record = make_base_record(
                path=path,
                root=root,
                digest=digest,
                size=size,
                document_id=document_id,
                copy_role=copy_role,
                inspection_path=snapshot,
            )
            records.append(record)
            by_digest[digest].append(record)

    duplicate_groups: list[dict[str, object]] = []
    for digest in sorted(by_digest):
        group = by_digest[digest]
        if len(group) < 2:
            continue
        document_ids = sorted(str(record["document_id"]) for record in group)
        duplicate_groups.append(
            {
                "content_id": f"sha256:{digest}",
                "document_ids": document_ids,
                "relationship_basis": "SHA-256 byte equality",
            }
        )
        for record in group:
            related = [identifier for identifier in document_ids if identifier != record["document_id"]]
            record["relationships"] = [
                {
                    "relationship_type": "EXACT_DUPLICATE",
                    "related_document_id": identifier,
                    "method": "SHA-256 byte equality",
                    "confidence": {
                        "score": 1.0,
                        "band": "HIGH",
                        "source": "RULE_CALCULATED",
                        "methodology": "Exact equality of complete source-byte SHA-256 digests.",
                    },
                    "review_status": "NOT_REQUIRED",
                }
                for identifier in related
            ]

    records.sort(key=lambda record: str(record["file"]["source_reference"]))
    inventory_basis = [
        {
            "source_reference": record["file"]["source_reference"],
            "content_id": record["content_id"],
            "size_bytes": record["file"]["size_bytes"],
        }
        for record in records
    ]
    input_set_sha256 = sha256_bytes(canonical_json_bytes(inventory_basis))
    config = {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "copy_role": copy_role,
        "active_content_method": "STDLIB_BOUNDED_READ_ONLY_PREFLIGHT",
    }
    config_sha256 = sha256_bytes(canonical_json_bytes(config))
    domain_results = {
        "records": records,
        "duplicate_groups": duplicate_groups,
    }
    domain_results_sha256 = sha256_bytes(canonical_json_bytes(domain_results))
    run_id = "inventory-" + sha256_bytes(
        canonical_json_bytes(
            {"input_set_sha256": input_set_sha256, "config_sha256": config_sha256}
        )
    )[:24]
    return {
        "schema_version": "1.0.0",
        "package_type": "DOCUMENT_INVENTORY",
        "run_manifest": {
            "run_id": run_id,
            "tool": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "timestamp": "NOT_RECORDED_FOR_DETERMINISTIC_OUTPUT",
            "input_set_sha256": input_set_sha256,
            "config_sha256": config_sha256,
            "domain_results_sha256": domain_results_sha256,
            "deterministic": True,
            "source_root_disclosure": "RELATIVE_REFERENCES_ONLY",
        },
        "summary": {
            "document_count": len(records),
            "unique_content_count": len(by_digest),
            "duplicate_content_group_count": len(duplicate_groups),
            "review_required_count": sum(
                1 for record in records if record["review_status"] == "REQUIRED"
            ),
        },
        "records": records,
        "duplicate_groups": duplicate_groups,
        "decision_scope": "TECHNICAL_INVENTORY_ONLY",
    }


def reject_output_alias(path: Path, protected_paths: Iterable[Path]) -> None:
    if not path.exists():
        return
    for protected in protected_paths:
        try:
            aliases = os.path.samefile(path, protected)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise InventoryError(
                f"cannot verify output/source inode separation: {exc}"
            ) from exc
        if aliases:
            raise InventoryError(
                "output must not replace an inventoried source file; output must not alias protected inputs"
            )


def atomic_write(path: Path, data: bytes, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise InventoryError(f"output already exists; use --overwrite to replace it: {path}")
    if path.is_symlink():
        raise InventoryError(f"output must not be a symlink: {path}")
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise InventoryError(f"output parent must be an existing real directory: {parent}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
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
                raise InventoryError(
                    f"output appeared during atomic publication; refusing overwrite: {path}"
                ) from exc
            except OSError as exc:
                raise InventoryError(
                    f"cannot atomically publish output without overwrite: {path}: {exc}"
                ) from exc
            temporary.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()


def serialize_package(package: Mapping[str, object]) -> bytes:
    return (
        json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="files/directories below --root")
    parser.add_argument(
        "--root",
        default=".",
        help="authorized root; inputs must remain below it (default: current directory)",
    )
    parser.add_argument(
        "--copy-role",
        choices=("ORIGINAL", "WORKING_COPY", "DERIVATIVE"),
        default="WORKING_COPY",
        help="declared copy role; default avoids claiming original provenance",
    )
    parser.add_argument(
        "--output", type=Path,
        help="optional JSON output below --root; stdout is default",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="perform inventory and print JSON without writing --output",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="allow atomic replacement of an existing --output file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        root = resolve_authorized_root(args.root)
        package = build_inventory(root, args.paths, copy_role=args.copy_role)
        rendered = serialize_package(package)
        if args.output is None or args.dry_run:
            sys.stdout.buffer.write(rendered)
        else:
            output_path = resolve_output(root, args.output)
            source_paths = {
                _absolute_without_symlink_resolution(root / str(record["file"]["source_reference"]))
                for record in package["records"]
            }
            reject_output_alias(output_path, source_paths)
            atomic_write(output_path, rendered, overwrite=args.overwrite)
            print(
                json.dumps(
                    {
                        "status": "WRITTEN",
                        "output": str(output_path),
                        "sha256": sha256_bytes(rendered),
                    },
                    sort_keys=True,
                )
            )
    except (InventoryError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
