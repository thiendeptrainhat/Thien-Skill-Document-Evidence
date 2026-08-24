#!/usr/bin/env python3
"""Safely finalize a generated XLSX workbook using only the Python stdlib.

The input is treated as an immutable OOXML package.  The finalizer rejects
active or ambiguous content, adds the canonical header controls to eligible
worksheets, verifies the rewritten package, and publishes a distinct output
atomically.  It does not extract ZIP members to disk.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import struct
import sys
import tempfile
from typing import Iterable
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile


VERSION = "1.0.0"
MIB = 1024 * 1024

SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
STRICT_SPREADSHEET_NS = "http://purl.oclc.org/ooxml/spreadsheetml/main"
RELATIONSHIP_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

ET.register_namespace("x", SPREADSHEET_NS)
ET.register_namespace("r", OFFICE_REL_NS)
ET.register_namespace("mc", "http://schemas.openxmlformats.org/markup-compatibility/2006")
ET.register_namespace("x14ac", "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac")
ET.register_namespace("xr", "http://schemas.microsoft.com/office/spreadsheetml/2014/revision")

REQUIRED_MEMBERS = {
    "[Content_Types].xml",
    "_rels/.rels",
    "xl/workbook.xml",
    "xl/_rels/workbook.xml.rels",
}

UNSAFE_MEMBER_MARKERS = (
    "xl/activex/",
    "xl/ctrlprops/",
    "xl/embeddings/",
    "xl/externallinks/",
    "xl/macrosheets/",
    "customui/",
    "_xmlsignatures/",
)

UNSAFE_RELATIONSHIP_TYPE_MARKERS = (
    "/attachedtemplate",
    "/control",
    "/customui",
    "/externallink",
    "/externallinkpath",
    "/hyperlink",
    "/oleobject",
    "/package",
    "/vbaproject",
)

UNSAFE_CONTENT_TYPE_MARKERS = (
    "activex",
    "macroenabled",
    "oleobject",
    "vbaproject",
)

FORMULA_ELEMENT_NAMES = {
    "calculatedcolumnformula",
    "definedname",
    "f",
    "formula",
    "formula1",
    "formula2",
    "totalsrowformula",
}

HYPERLINK_ELEMENT_NAMES = {
    "hlinkclick",
    "hlinkhover",
    "hlinkmouseover",
    "hyperlink",
    "hyperlinks",
}

README_SHEET_NAMES = {"README", "00_README"}
CELL_REFERENCE_RE = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")
RANGE_REFERENCE_RE = re.compile(
    r"^\$?([A-Z]{1,3})\$?([1-9][0-9]{0,6}):"
    r"\$?([A-Z]{1,3})\$?([1-9][0-9]{0,6})$"
)


class FinalizationError(ValueError):
    """Raised when a path or OOXML safety invariant is not satisfied."""


@dataclass(frozen=True)
class ArchiveLimits:
    """Fixed CLI limits; injectable in tests without weakening production."""

    max_archive_bytes: int = 128 * MIB
    max_members: int = 4096
    max_member_uncompressed_bytes: int = 64 * MIB
    max_total_uncompressed_bytes: int = 512 * MIB
    max_xml_bytes: int = 32 * MIB
    max_compression_ratio: float = 200.0
    compression_ratio_floor_bytes: int = 1 * MIB
    max_member_name_chars: int = 512


DEFAULT_LIMITS = ArchiveLimits()


@dataclass(frozen=True)
class Relationship:
    relationship_id: str
    relationship_type: str
    target: str
    resolved_target: str


@dataclass(frozen=True)
class SheetBinding:
    name: str
    relationship_id: str
    member_name: str


@dataclass(frozen=True)
class TableBinding:
    sheet_name: str
    worksheet_member: str
    relationship_id: str
    member_name: str


@dataclass
class ArchiveState:
    infos: tuple[zipfile.ZipInfo, ...]
    members: dict[str, bytes]
    xml_roots: dict[str, ET.Element]
    relationships: dict[str, dict[str, Relationship]]
    sheets: tuple[SheetBinding, ...]
    tables: tuple[TableBinding, ...]
    archive_comment: bytes


@dataclass(frozen=True)
class FinalizationPlan:
    modified_members: frozenset[str]
    frozen_sheets: tuple[str, ...]
    filters_added: tuple[tuple[str, str], ...]
    table_filters_added: tuple[tuple[str, str, str], ...]
    table_filters_verified: tuple[tuple[str, str, str], ...]
    filters_skipped: tuple[str, ...]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _q(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}" if namespace else local_name


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _absolute_path(value: str | os.PathLike[str], base: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return Path(os.path.abspath(os.fspath(candidate)))


def _resolve_root(value: str | os.PathLike[str]) -> Path:
    raw = _absolute_path(value, Path.cwd())
    try:
        metadata = os.lstat(raw)
    except FileNotFoundError as exc:
        raise FinalizationError(f"authorized root does not exist: {raw}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise FinalizationError(f"authorized root must not be a symlink: {raw}")
    if not stat.S_ISDIR(metadata.st_mode):
        raise FinalizationError(f"authorized root is not a directory: {raw}")
    return raw.resolve(strict=True)


def _resolve_input(root: Path, value: str | os.PathLike[str]) -> Path:
    raw = _absolute_path(value, root)
    if raw.suffix.casefold() != ".xlsx":
        raise FinalizationError("input must have an .xlsx extension")
    try:
        metadata = os.lstat(raw)
    except FileNotFoundError as exc:
        raise FinalizationError(f"input does not exist: {raw}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise FinalizationError(f"input must not be a symlink: {raw}")
    if not stat.S_ISREG(metadata.st_mode):
        raise FinalizationError(f"input is not a regular file: {raw}")
    resolved = raw.resolve(strict=True)
    if not _is_below(resolved, root):
        raise FinalizationError(f"input escapes authorized root: {raw}")
    return resolved


def _resolve_output(root: Path, value: str | os.PathLike[str]) -> Path:
    raw = _absolute_path(value, root)
    if raw.suffix.casefold() != ".xlsx":
        raise FinalizationError("output must have an .xlsx extension")
    try:
        parent = raw.parent.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FinalizationError(f"output parent does not exist: {raw.parent}") from exc
    if not parent.is_dir():
        raise FinalizationError(f"output parent is not a directory: {parent}")
    resolved = parent / raw.name
    if not _is_below(resolved, root):
        raise FinalizationError(f"output escapes authorized root: {raw}")
    if raw.exists() or raw.is_symlink():
        metadata = os.lstat(raw)
        if stat.S_ISLNK(metadata.st_mode):
            raise FinalizationError(f"output must not be a symlink: {raw}")
        if not stat.S_ISREG(metadata.st_mode):
            raise FinalizationError(f"existing output is not a regular file: {raw}")
        existing = raw.resolve(strict=True)
        if existing != resolved:
            raise FinalizationError(f"output resolves through an unsafe alias: {raw}")
    return resolved


def _read_regular_file(path: Path, maximum_bytes: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise FinalizationError(f"cannot safely open input: {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise FinalizationError(f"input changed and is no longer regular: {path}")
        if metadata.st_size > maximum_bytes:
            raise FinalizationError(
                f"input archive exceeds {maximum_bytes} bytes: {metadata.st_size}"
            )
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > maximum_bytes:
            raise FinalizationError(f"input archive exceeds {maximum_bytes} bytes")
        return data
    finally:
        os.close(descriptor)


def _extra_field_ids(extra: bytes) -> Iterable[int]:
    offset = 0
    while offset < len(extra):
        if len(extra) - offset < 4:
            raise FinalizationError("malformed ZIP extra field")
        header_id, data_size = struct.unpack_from("<HH", extra, offset)
        offset += 4
        if len(extra) - offset < data_size:
            raise FinalizationError("truncated ZIP extra field")
        yield header_id
        offset += data_size


def _validate_member_name(name: str, maximum_chars: int) -> None:
    if not name or len(name) > maximum_chars:
        raise FinalizationError(f"unsafe ZIP member name length: {name!r}")
    if "\x00" in name or "\\" in name or name.startswith("/"):
        raise FinalizationError(f"unsafe ZIP member path: {name!r}")
    directory_name = name[:-1] if name.endswith("/") else name
    if not directory_name:
        raise FinalizationError(f"unsafe ZIP member path: {name!r}")
    parts = directory_name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise FinalizationError(f"unsafe ZIP member path: {name!r}")
    if ":" in parts[0]:
        raise FinalizationError(f"drive-like ZIP member path: {name!r}")
    if posixpath.normpath(directory_name) != directory_name:
        raise FinalizationError(f"non-canonical ZIP member path: {name!r}")


def _validate_zip_infos(
    infos: list[zipfile.ZipInfo], limits: ArchiveLimits
) -> None:
    if not infos:
        raise FinalizationError("empty ZIP archive is not an XLSX package")
    if len(infos) > limits.max_members:
        raise FinalizationError(
            f"ZIP member count exceeds {limits.max_members}: {len(infos)}"
        )
    exact_names: set[str] = set()
    folded_names: set[str] = set()
    total_uncompressed = 0
    for info in infos:
        _validate_member_name(info.filename, limits.max_member_name_chars)
        folded = info.filename.casefold()
        if info.filename in exact_names or folded in folded_names:
            raise FinalizationError(f"duplicate or case-colliding ZIP member: {info.filename}")
        exact_names.add(info.filename)
        folded_names.add(folded)
        if info.flag_bits & 0x1 or 0x9901 in set(_extra_field_ids(info.extra)):
            raise FinalizationError(f"encrypted ZIP member is not allowed: {info.filename}")
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise FinalizationError(
                f"unsupported ZIP compression for {info.filename}: {info.compress_type}"
            )
        if info.file_size < 0 or info.compress_size < 0:
            raise FinalizationError(f"invalid ZIP member size: {info.filename}")
        if info.file_size > limits.max_member_uncompressed_bytes:
            raise FinalizationError(
                f"ZIP member exceeds {limits.max_member_uncompressed_bytes} bytes: "
                f"{info.filename} ({info.file_size})"
            )
        total_uncompressed += info.file_size
        if total_uncompressed > limits.max_total_uncompressed_bytes:
            raise FinalizationError(
                f"ZIP uncompressed total exceeds {limits.max_total_uncompressed_bytes} bytes"
            )
        if info.file_size >= limits.compression_ratio_floor_bytes:
            ratio = info.file_size / max(1, info.compress_size)
            if ratio > limits.max_compression_ratio:
                raise FinalizationError(
                    f"unsafe ZIP compression ratio for {info.filename}: {ratio:.1f}"
                )
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        file_kind = stat.S_IFMT(unix_mode)
        if info.create_system == 3 and file_kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise FinalizationError(f"non-regular ZIP member is not allowed: {info.filename}")
        lowered = info.filename.casefold()
        if lowered.endswith(".bin") or any(marker in lowered for marker in UNSAFE_MEMBER_MARKERS):
            raise FinalizationError(f"unsafe OOXML package member: {info.filename}")
        if lowered in {"origin.sigs", "xl/calcchain.xml", "xl/connections.xml"}:
            raise FinalizationError(f"unsafe OOXML package member: {info.filename}")


def _parse_xml(member_name: str, data: bytes, limits: ArchiveLimits) -> ET.Element:
    if len(data) > limits.max_xml_bytes:
        raise FinalizationError(
            f"XML member exceeds {limits.max_xml_bytes} bytes: {member_name}"
        )
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise FinalizationError(f"DTD/entity declarations are not allowed: {member_name}")
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
        root = ET.fromstring(data, parser=parser)
    except ET.ParseError as exc:
        raise FinalizationError(f"malformed XML member {member_name}: {exc}") from exc
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        local = _local_name(element.tag).casefold()
        if local in FORMULA_ELEMENT_NAMES:
            if local != "definedname" or "".join(element.itertext()).strip():
                raise FinalizationError(
                    f"formula-bearing element {local!r} is not allowed: {member_name}"
                )
        if local in HYPERLINK_ELEMENT_NAMES:
            raise FinalizationError(
                f"hyperlink-bearing element {local!r} is not allowed: {member_name}"
            )
        for attribute, value in element.attrib.items():
            if _local_name(attribute).casefold() == "href" and value.strip():
                raise FinalizationError(f"active href is not allowed: {member_name}")
    return root


def _relationship_source_part(rels_name: str) -> str:
    if rels_name == "_rels/.rels":
        return ""
    marker = "/_rels/"
    if marker not in rels_name or not rels_name.endswith(".rels"):
        raise FinalizationError(f"invalid relationship part path: {rels_name}")
    directory, leaf = rels_name.split(marker, 1)
    if "/" in leaf:
        raise FinalizationError(f"invalid relationship part path: {rels_name}")
    return f"{directory}/{leaf[:-5]}"


def _resolve_relationship_target(rels_name: str, target: str) -> str:
    if not target or "\x00" in target or "\\" in target:
        raise FinalizationError(f"unsafe relationship target in {rels_name}: {target!r}")
    decoded = unquote(target)
    parsed = urlsplit(decoded)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise FinalizationError(f"external/ambiguous relationship target in {rels_name}: {target}")
    source_part = _relationship_source_part(rels_name)
    if parsed.path.startswith("/"):
        joined = parsed.path.lstrip("/")
    else:
        joined = posixpath.join(posixpath.dirname(source_part), parsed.path)
    normalized = posixpath.normpath(joined)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise FinalizationError(f"relationship target escapes package: {rels_name} -> {target}")
    _validate_member_name(normalized, DEFAULT_LIMITS.max_member_name_chars)
    return normalized


def _parse_relationships(
    rels_name: str, root: ET.Element, member_names: set[str]
) -> dict[str, Relationship]:
    if _local_name(root.tag) != "Relationships":
        raise FinalizationError(f"invalid relationships root: {rels_name}")
    relationships: dict[str, Relationship] = {}
    for element in root:
        if not isinstance(element.tag, str) or _local_name(element.tag) != "Relationship":
            continue
        relationship_id = element.attrib.get("Id", "")
        relationship_type = element.attrib.get("Type", "")
        target = element.attrib.get("Target", "")
        if not relationship_id or relationship_id in relationships:
            raise FinalizationError(f"missing/duplicate relationship Id in {rels_name}")
        if element.attrib.get("TargetMode", "").casefold() == "external":
            raise FinalizationError(f"external relationship is not allowed: {rels_name}")
        lowered_type = relationship_type.casefold()
        if any(marker in lowered_type for marker in UNSAFE_RELATIONSHIP_TYPE_MARKERS):
            raise FinalizationError(
                f"unsafe relationship type in {rels_name}: {relationship_type}"
            )
        resolved = _resolve_relationship_target(rels_name, target)
        if resolved not in member_names:
            raise FinalizationError(
                f"relationship target is missing from package: {rels_name} -> {resolved}"
            )
        relationships[relationship_id] = Relationship(
            relationship_id=relationship_id,
            relationship_type=relationship_type,
            target=target,
            resolved_target=resolved,
        )
    return relationships


def _validate_content_types(root: ET.Element) -> None:
    if _local_name(root.tag) != "Types":
        raise FinalizationError("invalid [Content_Types].xml root")
    for element in root:
        content_type = element.attrib.get("ContentType", "").casefold()
        if any(marker in content_type for marker in UNSAFE_CONTENT_TYPE_MARKERS):
            raise FinalizationError(f"unsafe OOXML content type: {content_type}")


def _office_relationship_id(element: ET.Element, context: str) -> str:
    relationship_ids = [
        value
        for attribute, value in element.attrib.items()
        if _local_name(attribute) == "id"
        and "officeDocument" in _namespace(attribute)
        and _namespace(attribute).endswith("/relationships")
    ]
    if len(relationship_ids) != 1 or not relationship_ids[0]:
        raise FinalizationError(f"missing/ambiguous relationship id: {context}")
    return relationship_ids[0]


def _relationship_part_for_source(source_part: str) -> str:
    directory, leaf = posixpath.split(source_part)
    if not leaf:
        raise FinalizationError(f"invalid OOXML source part: {source_part}")
    prefix = f"{directory}/" if directory else ""
    return f"{prefix}_rels/{leaf}.rels"


def _map_sheets(
    workbook: ET.Element,
    workbook_relationships: dict[str, Relationship],
    member_names: set[str],
) -> tuple[SheetBinding, ...]:
    if _local_name(workbook.tag) != "workbook":
        raise FinalizationError("invalid xl/workbook.xml root")
    sheets: list[SheetBinding] = []
    folded_names: set[str] = set()
    targets: set[str] = set()
    for element in workbook.iter():
        if not isinstance(element.tag, str) or _local_name(element.tag) != "sheet":
            continue
        name = element.attrib.get("name", "")
        relationship_id = _office_relationship_id(element, f"sheet {name or '<unnamed>'}")
        if not name or len(name) > 31 or name.casefold() in folded_names:
            raise FinalizationError(f"invalid or duplicate workbook sheet name: {name!r}")
        folded_names.add(name.casefold())
        relationship = workbook_relationships.get(relationship_id)
        if relationship is None:
            raise FinalizationError(f"sheet relationship is missing: {name} ({relationship_id})")
        if not relationship.relationship_type.casefold().endswith("/worksheet"):
            raise FinalizationError(f"unsupported non-worksheet sheet: {name}")
        target = relationship.resolved_target
        if not target.casefold().startswith("xl/worksheets/") or not target.casefold().endswith(
            ".xml"
        ):
            raise FinalizationError(f"worksheet target is outside xl/worksheets: {name}")
        if target not in member_names or target in targets:
            raise FinalizationError(f"missing/duplicate worksheet target: {name} -> {target}")
        targets.add(target)
        sheets.append(SheetBinding(name, relationship_id, target))
    if not sheets:
        raise FinalizationError("workbook contains no worksheets")
    worksheet_members = {
        name
        for name in member_names
        if name.casefold().startswith("xl/worksheets/")
        and name.casefold().endswith(".xml")
        and "/_rels/" not in name.casefold()
    }
    if worksheet_members != targets:
        orphaned = sorted(worksheet_members - targets)
        missing = sorted(targets - worksheet_members)
        raise FinalizationError(
            f"worksheet mapping is incomplete; orphaned={orphaned}, missing={missing}"
        )
    return tuple(sheets)


def _map_tables(
    sheets: tuple[SheetBinding, ...],
    xml_roots: dict[str, ET.Element],
    relationships: dict[str, dict[str, Relationship]],
    member_names: set[str],
) -> tuple[TableBinding, ...]:
    bindings: list[TableBinding] = []
    mapped_targets: set[str] = set()
    table_ids: set[int] = set()
    table_names: set[str] = set()
    for sheet in sheets:
        worksheet = xml_roots[sheet.member_name]
        table_parts_nodes = [
            child
            for child in worksheet
            if isinstance(child.tag, str) and _local_name(child.tag) == "tableParts"
        ]
        if len(table_parts_nodes) > 1:
            raise FinalizationError(f"multiple tableParts containers: {sheet.name}")
        if table_parts_nodes and sheet.name.upper() in README_SHEET_NAMES:
            raise FinalizationError(f"README worksheet must not contain tableParts: {sheet.name}")
        rels_name = _relationship_part_for_source(sheet.member_name)
        sheet_relationships = relationships.get(rels_name, {})
        table_relationships = {
            relationship_id: relationship
            for relationship_id, relationship in sheet_relationships.items()
            if relationship.relationship_type.casefold().endswith("/table")
        }
        if not table_parts_nodes:
            if table_relationships:
                raise FinalizationError(
                    f"unreferenced table relationship on worksheet: {sheet.name}"
                )
            continue
        table_parts = table_parts_nodes[0]
        parts = [
            child
            for child in table_parts
            if isinstance(child.tag, str) and _local_name(child.tag) == "tablePart"
        ]
        try:
            declared_count = int(table_parts.attrib.get("count", ""))
        except ValueError as exc:
            raise FinalizationError(f"invalid tableParts count: {sheet.name}") from exc
        if declared_count != len(parts) or not parts:
            raise FinalizationError(
                f"tableParts count mismatch/empty container: {sheet.name}"
            )
        if rels_name not in relationships:
            raise FinalizationError(
                f"tableParts relationship file is missing: {sheet.name} ({rels_name})"
            )
        used_relationship_ids: set[str] = set()
        for index, part in enumerate(parts, start=1):
            relationship_id = _office_relationship_id(
                part, f"tablePart {index} on {sheet.name}"
            )
            if relationship_id in used_relationship_ids:
                raise FinalizationError(
                    f"duplicate tablePart relationship on worksheet: {sheet.name} ({relationship_id})"
                )
            used_relationship_ids.add(relationship_id)
            relationship = sheet_relationships.get(relationship_id)
            if relationship is None:
                raise FinalizationError(
                    f"tablePart relationship is missing: {sheet.name} ({relationship_id})"
                )
            if not relationship.relationship_type.casefold().endswith("/table"):
                raise FinalizationError(
                    f"tablePart relationship does not resolve to a table: "
                    f"{sheet.name} ({relationship_id})"
                )
            target = relationship.resolved_target
            if (
                not target.casefold().startswith("xl/tables/")
                or not target.casefold().endswith(".xml")
            ):
                raise FinalizationError(
                    f"tablePart target is outside xl/tables: {sheet.name} -> {target}"
                )
            if target not in member_names or target in mapped_targets:
                raise FinalizationError(
                    f"missing/ambiguous tablePart target: {sheet.name} -> {target}"
                )
            table = xml_roots.get(target)
            if table is None or _local_name(table.tag) != "table":
                raise FinalizationError(f"invalid table XML root: {target}")
            if _namespace(table.tag) not in {SPREADSHEET_NS, STRICT_SPREADSHEET_NS}:
                raise FinalizationError(f"unsupported table namespace: {target}")
            try:
                table_id = int(table.attrib.get("id", ""))
            except ValueError as exc:
                raise FinalizationError(f"invalid table id: {target}") from exc
            name = table.attrib.get("name", "").strip()
            display_name = table.attrib.get("displayName", "").strip()
            if table_id <= 0 or table_id in table_ids:
                raise FinalizationError(f"missing/duplicate table id: {target}")
            if (
                not name
                or not display_name
                or name.casefold() in table_names
                or display_name.casefold() in table_names
            ):
                raise FinalizationError(f"missing/duplicate table name: {target}")
            table_ids.add(table_id)
            table_names.add(name.casefold())
            table_names.add(display_name.casefold())
            mapped_targets.add(target)
            bindings.append(
                TableBinding(
                    sheet_name=sheet.name,
                    worksheet_member=sheet.member_name,
                    relationship_id=relationship_id,
                    member_name=target,
                )
            )
        if set(table_relationships) != used_relationship_ids:
            unused = sorted(set(table_relationships) - used_relationship_ids)
            raise FinalizationError(
                f"unreferenced/ambiguous table relationships on {sheet.name}: {unused}"
            )
    table_members = {
        name
        for name in member_names
        if name.casefold().startswith("xl/tables/")
        and name.casefold().endswith(".xml")
    }
    if table_members != mapped_targets:
        raise FinalizationError(
            "table mapping is incomplete; "
            f"orphaned={sorted(table_members - mapped_targets)}, "
            f"missing={sorted(mapped_targets - table_members)}"
        )
    return tuple(bindings)


def _load_and_validate_archive(data: bytes, limits: ArchiveLimits) -> ArchiveState:
    if len(data) > limits.max_archive_bytes:
        raise FinalizationError(f"archive exceeds {limits.max_archive_bytes} bytes")
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
            infos = archive.infolist()
            _validate_zip_infos(infos, limits)
            names = {info.filename for info in infos}
            missing = REQUIRED_MEMBERS - names
            if missing:
                raise FinalizationError(f"XLSX package is missing members: {sorted(missing)}")
            members: dict[str, bytes] = {}
            for info in infos:
                try:
                    members[info.filename] = archive.read(info)
                except (RuntimeError, zipfile.BadZipFile, OSError) as exc:
                    raise FinalizationError(
                        f"cannot safely read ZIP member {info.filename}: {exc}"
                    ) from exc
            archive_comment = archive.comment
    except zipfile.BadZipFile as exc:
        raise FinalizationError(f"input is not a valid ZIP/XLSX archive: {exc}") from exc

    xml_roots: dict[str, ET.Element] = {}
    for name, member_data in members.items():
        lowered = name.casefold()
        if lowered.endswith(".xml") or lowered.endswith(".rels"):
            xml_roots[name] = _parse_xml(name, member_data, limits)

    _validate_content_types(xml_roots["[Content_Types].xml"])
    relationships: dict[str, dict[str, Relationship]] = {}
    for name, root in xml_roots.items():
        if name.casefold().endswith(".rels"):
            relationships[name] = _parse_relationships(name, root, set(members))
    sheets = _map_sheets(
        xml_roots["xl/workbook.xml"],
        relationships["xl/_rels/workbook.xml.rels"],
        set(members),
    )
    tables = _map_tables(sheets, xml_roots, relationships, set(members))
    return ArchiveState(
        infos=tuple(infos),
        members=members,
        xml_roots=xml_roots,
        relationships=relationships,
        sheets=sheets,
        tables=tables,
        archive_comment=archive_comment,
    )


def _column_number(letters: str) -> int:
    value = 0
    for character in letters:
        value = value * 26 + ord(character) - ord("A") + 1
    return value


def _column_letters(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _cell_coordinate(reference: str) -> tuple[int, int] | None:
    match = CELL_REFERENCE_RE.fullmatch(reference.upper())
    if match is None:
        return None
    column = _column_number(match.group(1))
    row = int(match.group(2))
    if column > 16384 or row > 1048576:
        return None
    return column, row


def _range_coordinates(reference: str) -> tuple[int, int, int, int] | None:
    match = RANGE_REFERENCE_RE.fullmatch(reference.upper())
    if match is None:
        return None
    first_column = _column_number(match.group(1))
    first_row = int(match.group(2))
    last_column = _column_number(match.group(3))
    last_row = int(match.group(4))
    if (
        first_column > 16384
        or last_column > 16384
        or first_row > 1048576
        or last_row > 1048576
        or first_column > last_column
        or first_row > last_row
    ):
        return None
    return first_column, first_row, last_column, last_row


def _rectangles_overlap(
    left: tuple[int, int, int, int], right: tuple[int, int, int, int]
) -> bool:
    left_column, left_row, right_column, right_row = left
    other_left, other_top, other_right, other_bottom = right
    return not (
        right_column < other_left
        or other_right < left_column
        or right_row < other_top
        or other_bottom < left_row
    )


def _cell_text(cell: ET.Element, shared_strings: tuple[str, ...]) -> str:
    cell_type = cell.attrib.get("t", "")
    values = [
        "".join(element.itertext())
        for element in cell.iter()
        if isinstance(element.tag, str) and _local_name(element.tag) in {"t", "v"}
    ]
    if cell_type == "s" and values:
        try:
            index = int(values[-1])
            return shared_strings[index]
        except (ValueError, IndexError):
            return ""
    return "".join(values).strip()


def _shared_strings(state: ArchiveState) -> tuple[str, ...]:
    root = state.xml_roots.get("xl/sharedStrings.xml")
    if root is None:
        return ()
    strings: list[str] = []
    for item in root:
        if isinstance(item.tag, str) and _local_name(item.tag) == "si":
            strings.append(
                "".join(
                    "".join(node.itertext())
                    for node in item.iter()
                    if isinstance(node.tag, str) and _local_name(node.tag) == "t"
                )
            )
    return tuple(strings)


def _insert_ordered(parent: ET.Element, element: ET.Element, before_names: set[str]) -> None:
    for index, child in enumerate(parent):
        if isinstance(child.tag, str) and _local_name(child.tag) in before_names:
            parent.insert(index, element)
            return
    parent.append(element)


def _ensure_frozen_header(worksheet: ET.Element) -> bool:
    namespace = _namespace(worksheet.tag)
    if namespace not in {SPREADSHEET_NS, STRICT_SPREADSHEET_NS}:
        raise FinalizationError(f"unsupported worksheet namespace: {namespace!r}")
    changed = False
    sheet_views = next(
        (
            child
            for child in worksheet
            if isinstance(child.tag, str) and _local_name(child.tag) == "sheetViews"
        ),
        None,
    )
    if sheet_views is None:
        sheet_views = ET.Element(_q(namespace, "sheetViews"))
        _insert_ordered(
            worksheet,
            sheet_views,
            {
                "sheetFormatPr",
                "cols",
                "sheetData",
                "sheetCalcPr",
                "sheetProtection",
                "protectedRanges",
                "scenarios",
                "autoFilter",
                "sortState",
                "dataConsolidate",
                "customSheetViews",
                "mergeCells",
                "phoneticPr",
                "conditionalFormatting",
                "dataValidations",
                "hyperlinks",
                "printOptions",
                "pageMargins",
                "pageSetup",
                "headerFooter",
            },
        )
        changed = True
    sheet_views_list = [
        child
        for child in sheet_views
        if isinstance(child.tag, str) and _local_name(child.tag) == "sheetView"
    ]
    if not sheet_views_list:
        sheet_view = ET.SubElement(sheet_views, _q(namespace, "sheetView"))
        sheet_view.set("workbookViewId", "0")
        sheet_views_list = [sheet_view]
        changed = True
    expected = {
        "ySplit": "1",
        "topLeftCell": "A2",
        "activePane": "bottomLeft",
        "state": "frozen",
    }
    for sheet_view in sheet_views_list:
        panes = [
            child
            for child in sheet_view
            if isinstance(child.tag, str) and _local_name(child.tag) == "pane"
        ]
        if panes:
            pane = panes[0]
            for duplicate in panes[1:]:
                sheet_view.remove(duplicate)
                changed = True
        else:
            pane = ET.Element(_q(namespace, "pane"))
            sheet_view.insert(0, pane)
            changed = True
        if pane.attrib != expected:
            pane.attrib.clear()
            pane.attrib.update(expected)
            changed = True
    return changed


def _merged_header(worksheet: ET.Element) -> bool:
    for element in worksheet.iter():
        if not isinstance(element.tag, str) or _local_name(element.tag) != "mergeCell":
            continue
        match = RANGE_REFERENCE_RE.fullmatch(element.attrib.get("ref", "").upper())
        if match is None:
            return True
        if int(match.group(2)) <= 1 <= int(match.group(4)):
            return True
    return False


def _merge_intersects_header_range(
    worksheet: ET.Element,
    first_column: int,
    header_row: int,
    last_column: int,
) -> bool:
    header_rectangle = (first_column, header_row, last_column, header_row)
    for element in worksheet.iter():
        if not isinstance(element.tag, str) or _local_name(element.tag) != "mergeCell":
            continue
        merge_rectangle = _range_coordinates(element.attrib.get("ref", ""))
        if merge_rectangle is None or _rectangles_overlap(
            header_rectangle, merge_rectangle
        ):
            return True
    return False


def _ensure_table_auto_filter(
    *,
    worksheet: ET.Element,
    table: ET.Element,
    table_member: str,
    shared_strings: tuple[str, ...],
) -> tuple[bool, str, tuple[int, int, int, int]]:
    reference = table.attrib.get("ref", "")
    rectangle = _range_coordinates(reference)
    if rectangle is None or reference != reference.upper() or "$" in reference:
        raise FinalizationError(f"invalid/non-canonical table range: {table_member}")
    first_column, header_row, last_column, _ = rectangle
    if header_row != 1:
        raise FinalizationError(
            f"table header is incompatible with frozen pane A2: {table_member}"
        )
    if table.attrib.get("headerRowCount", "1") != "1":
        raise FinalizationError(f"table does not have one filterable header row: {table_member}")
    if any(
        isinstance(child.tag, str) and _local_name(child.tag) == "sheetProtection"
        for child in worksheet
    ):
        raise FinalizationError(f"protected worksheet table cannot be finalized: {table_member}")
    if _merge_intersects_header_range(
        worksheet, first_column, header_row, last_column
    ):
        raise FinalizationError(f"table header intersects merged/invalid range: {table_member}")

    table_columns_nodes = [
        child
        for child in table
        if isinstance(child.tag, str) and _local_name(child.tag) == "tableColumns"
    ]
    if len(table_columns_nodes) != 1:
        raise FinalizationError(f"missing/ambiguous tableColumns: {table_member}")
    table_columns = [
        child
        for child in table_columns_nodes[0]
        if isinstance(child.tag, str) and _local_name(child.tag) == "tableColumn"
    ]
    expected_width = last_column - first_column + 1
    try:
        declared_count = int(table_columns_nodes[0].attrib.get("count", ""))
    except ValueError as exc:
        raise FinalizationError(f"invalid tableColumns count: {table_member}") from exc
    if declared_count != expected_width or len(table_columns) != expected_width:
        raise FinalizationError(f"tableColumns/range width mismatch: {table_member}")
    column_names = [column.attrib.get("name", "").strip() for column in table_columns]
    if (
        any(not name for name in column_names)
        or len({name.casefold() for name in column_names}) != len(column_names)
    ):
        raise FinalizationError(f"missing/duplicate table column name: {table_member}")
    try:
        column_ids = [int(column.attrib.get("id", "")) for column in table_columns]
    except ValueError as exc:
        raise FinalizationError(f"invalid table column id: {table_member}") from exc
    if any(identifier <= 0 for identifier in column_ids) or len(set(column_ids)) != len(
        column_ids
    ):
        raise FinalizationError(f"missing/duplicate table column id: {table_member}")

    sheet_data_nodes = [
        child
        for child in worksheet
        if isinstance(child.tag, str) and _local_name(child.tag) == "sheetData"
    ]
    if len(sheet_data_nodes) != 1:
        raise FinalizationError(f"missing/ambiguous worksheet sheetData: {table_member}")
    header_rows = [
        row
        for row in sheet_data_nodes[0]
        if isinstance(row.tag, str)
        and _local_name(row.tag) == "row"
        and row.attrib.get("r") == str(header_row)
    ]
    if len(header_rows) != 1:
        raise FinalizationError(f"table header row is missing/ambiguous: {table_member}")
    header_cells: dict[int, str] = {}
    for cell in header_rows[0]:
        if not isinstance(cell.tag, str) or _local_name(cell.tag) != "c":
            continue
        coordinate = _cell_coordinate(cell.attrib.get("r", ""))
        if coordinate is None or coordinate[1] != header_row:
            raise FinalizationError(f"invalid table header cell reference: {table_member}")
        column = coordinate[0]
        if first_column <= column <= last_column:
            if column in header_cells:
                raise FinalizationError(f"duplicate table header cell: {table_member}")
            header_cells[column] = _cell_text(cell, shared_strings).strip()
    expected_columns = set(range(first_column, last_column + 1))
    if set(header_cells) != expected_columns:
        raise FinalizationError(f"table header cells do not match range: {table_member}")
    sheet_names = [header_cells[column] for column in range(first_column, last_column + 1)]
    if [name.casefold() for name in sheet_names] != [
        name.casefold() for name in column_names
    ]:
        raise FinalizationError(f"worksheet/table header names disagree: {table_member}")

    auto_filters = [
        child
        for child in table
        if isinstance(child.tag, str) and _local_name(child.tag) == "autoFilter"
    ]
    if len(auto_filters) > 1:
        raise FinalizationError(f"multiple table autoFilter elements: {table_member}")
    if auto_filters:
        if auto_filters[0].attrib.get("ref") != reference:
            raise FinalizationError(f"table autoFilter range mismatch: {table_member}")
        return False, reference, rectangle
    auto_filter = ET.Element(_q(_namespace(table.tag), "autoFilter"), {"ref": reference})
    _insert_ordered(
        table,
        auto_filter,
        {"sortState", "tableColumns", "tableStyleInfo", "extLst"},
    )
    return True, reference, rectangle


def _safe_filter_ref(
    worksheet: ET.Element, shared_strings: tuple[str, ...]
) -> str | None:
    direct_names = [
        _local_name(child.tag)
        for child in worksheet
        if isinstance(child.tag, str)
    ]
    if "autoFilter" in direct_names or "tableParts" in direct_names:
        return None
    if "sheetProtection" in direct_names or _merged_header(worksheet):
        return None
    sheet_data = next(
        (
            child
            for child in worksheet
            if isinstance(child.tag, str) and _local_name(child.tag) == "sheetData"
        ),
        None,
    )
    if sheet_data is None:
        return None
    rows = [
        child
        for child in sheet_data
        if isinstance(child.tag, str) and _local_name(child.tag) == "row"
    ]
    header_rows = [row for row in rows if row.attrib.get("r") == "1"]
    if len(header_rows) != 1:
        return None
    header_cells: dict[int, str] = {}
    for cell in header_rows[0]:
        if not isinstance(cell.tag, str) or _local_name(cell.tag) != "c":
            continue
        coordinate = _cell_coordinate(cell.attrib.get("r", ""))
        if coordinate is None or coordinate[1] != 1:
            return None
        column = coordinate[0]
        if column in header_cells:
            return None
        header_cells[column] = _cell_text(cell, shared_strings)
    if len(header_cells) < 2:
        return None
    last_column = max(header_cells)
    if set(header_cells) != set(range(1, last_column + 1)):
        return None
    normalized_headers = [header_cells[index].strip().casefold() for index in range(1, last_column + 1)]
    if any(not value for value in normalized_headers) or len(set(normalized_headers)) != len(
        normalized_headers
    ):
        return None
    last_row = 1
    for row in rows:
        try:
            row_number = int(row.attrib.get("r", "0"))
        except ValueError:
            return None
        if not 1 <= row_number <= 1048576:
            return None
        if any(isinstance(cell.tag, str) and _local_name(cell.tag) == "c" for cell in row):
            last_row = max(last_row, row_number)
    return f"A1:{_column_letters(last_column)}{last_row}"


def _add_auto_filter(worksheet: ET.Element, reference: str) -> None:
    namespace = _namespace(worksheet.tag)
    auto_filter = ET.Element(_q(namespace, "autoFilter"), {"ref": reference})
    preceding_names = {
        "sheetPr",
        "dimension",
        "sheetViews",
        "sheetFormatPr",
        "cols",
        "sheetData",
        "sheetCalcPr",
        "sheetProtection",
        "protectedRanges",
        "scenarios",
    }
    insertion_index = 0
    for index, child in enumerate(worksheet):
        if isinstance(child.tag, str) and _local_name(child.tag) in preceding_names:
            insertion_index = index + 1
    worksheet.insert(insertion_index, auto_filter)


def _serialize_xml(root: ET.Element) -> bytes:
    return ET.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
        short_empty_elements=True,
    )


def _prepare_members(state: ArchiveState) -> tuple[dict[str, bytes], FinalizationPlan]:
    members = dict(state.members)
    shared_strings = _shared_strings(state)
    modified: set[str] = set()
    frozen: list[str] = []
    filters_added: list[tuple[str, str]] = []
    table_filters_added: list[tuple[str, str, str]] = []
    table_filters_verified: list[tuple[str, str, str]] = []
    filters_skipped: list[str] = []
    tables_by_sheet: dict[str, list[TableBinding]] = {}
    for table in state.tables:
        tables_by_sheet.setdefault(table.sheet_name, []).append(table)
    for sheet in state.sheets:
        if sheet.name.upper() in README_SHEET_NAMES:
            continue
        root = state.xml_roots[sheet.member_name]
        changed = _ensure_frozen_header(root)
        frozen.append(sheet.name)
        sheet_tables = tables_by_sheet.get(sheet.name, [])
        if sheet_tables:
            worksheet_filters = [
                child
                for child in root
                if isinstance(child.tag, str) and _local_name(child.tag) == "autoFilter"
            ]
            if worksheet_filters:
                raise FinalizationError(
                    f"worksheet autoFilter with tableParts is ambiguous: {sheet.name}"
                )
            rectangles: list[tuple[int, int, int, int]] = []
            for table_binding in sheet_tables:
                table_root = state.xml_roots[table_binding.member_name]
                table_changed, reference, rectangle = _ensure_table_auto_filter(
                    worksheet=root,
                    table=table_root,
                    table_member=table_binding.member_name,
                    shared_strings=shared_strings,
                )
                if any(_rectangles_overlap(rectangle, existing) for existing in rectangles):
                    raise FinalizationError(
                        f"overlapping table ranges on worksheet: {sheet.name}"
                    )
                rectangles.append(rectangle)
                record = (sheet.name, table_binding.member_name, reference)
                if table_changed:
                    members[table_binding.member_name] = _serialize_xml(table_root)
                    modified.add(table_binding.member_name)
                    table_filters_added.append(record)
                else:
                    table_filters_verified.append(record)
        else:
            filter_reference = _safe_filter_ref(root, shared_strings)
            if filter_reference is not None:
                _add_auto_filter(root, filter_reference)
                filters_added.append((sheet.name, filter_reference))
                changed = True
            else:
                filters_skipped.append(sheet.name)
        if changed:
            members[sheet.member_name] = _serialize_xml(root)
            modified.add(sheet.member_name)
    return members, FinalizationPlan(
        modified_members=frozenset(modified),
        frozen_sheets=tuple(frozen),
        filters_added=tuple(filters_added),
        table_filters_added=tuple(table_filters_added),
        table_filters_verified=tuple(table_filters_verified),
        filters_skipped=tuple(filters_skipped),
    )


def _clone_zip_info(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    clone = zipfile.ZipInfo(info.filename, info.date_time)
    clone.compress_type = info.compress_type
    clone.comment = info.comment
    clone.extra = info.extra
    clone.create_system = info.create_system
    clone.create_version = info.create_version
    clone.extract_version = info.extract_version
    clone.reserved = info.reserved
    clone.volume = info.volume
    clone.internal_attr = info.internal_attr
    clone.external_attr = info.external_attr
    clone.flag_bits = info.flag_bits & ~0x1
    return clone


def _write_archive(path: Path, state: ArchiveState, members: dict[str, bytes]) -> None:
    with path.open("wb") as raw_output:
        with zipfile.ZipFile(raw_output, "w", allowZip64=False) as archive:
            archive.comment = state.archive_comment
            for info in state.infos:
                clone = _clone_zip_info(info)
                archive.writestr(
                    clone,
                    members[info.filename],
                    compress_type=clone.compress_type,
                    compresslevel=9 if clone.compress_type == zipfile.ZIP_DEFLATED else None,
                )
        raw_output.flush()
        os.fsync(raw_output.fileno())


def _pane_is_exact(worksheet: ET.Element) -> bool:
    expected = {
        "ySplit": "1",
        "topLeftCell": "A2",
        "activePane": "bottomLeft",
        "state": "frozen",
    }
    sheet_views = [
        element
        for element in worksheet.iter()
        if isinstance(element.tag, str) and _local_name(element.tag) == "sheetView"
    ]
    if not sheet_views:
        return False
    for sheet_view in sheet_views:
        panes = [
            child
            for child in sheet_view
            if isinstance(child.tag, str) and _local_name(child.tag) == "pane"
        ]
        if len(panes) != 1 or panes[0].attrib != expected:
            return False
    return True


def _table_filter_is_exact(table: ET.Element, reference: str) -> bool:
    filters = [
        child
        for child in table
        if isinstance(child.tag, str) and _local_name(child.tag) == "autoFilter"
    ]
    return len(filters) == 1 and filters[0].attrib.get("ref") == reference


def _verify_output(
    source: ArchiveState,
    output_data: bytes,
    plan: FinalizationPlan,
    limits: ArchiveLimits,
) -> ArchiveState:
    output = _load_and_validate_archive(output_data, limits)
    if [info.filename for info in output.infos] != [info.filename for info in source.infos]:
        raise FinalizationError("output ZIP member order/set differs from input")
    for name, source_data in source.members.items():
        if name not in plan.modified_members and output.members[name] != source_data:
            raise FinalizationError(f"unchanged package member was altered: {name}")
    output_sheets = {sheet.name: sheet for sheet in output.sheets}
    for sheet_name in plan.frozen_sheets:
        binding = output_sheets.get(sheet_name)
        if binding is None or not _pane_is_exact(output.xml_roots[binding.member_name]):
            raise FinalizationError(f"frozen header verification failed: {sheet_name}")
    for sheet_name, reference in plan.filters_added:
        binding = output_sheets.get(sheet_name)
        if binding is None:
            raise FinalizationError(f"autoFilter sheet disappeared: {sheet_name}")
        filters = [
            child
            for child in output.xml_roots[binding.member_name]
            if isinstance(child.tag, str) and _local_name(child.tag) == "autoFilter"
        ]
        if len(filters) != 1 or filters[0].attrib.get("ref") != reference:
            raise FinalizationError(f"autoFilter verification failed: {sheet_name}")
    output_tables = {
        (table.sheet_name, table.member_name): table for table in output.tables
    }
    for sheet_name, table_member, reference in (
        plan.table_filters_added + plan.table_filters_verified
    ):
        binding = output_tables.get((sheet_name, table_member))
        if binding is None or not _table_filter_is_exact(
            output.xml_roots[binding.member_name], reference
        ):
            raise FinalizationError(
                f"table autoFilter verification failed: {sheet_name} -> {table_member}"
            )
        sheet_binding = output_sheets.get(sheet_name)
        if sheet_binding is None:
            raise FinalizationError(f"table worksheet disappeared: {sheet_name}")
        if any(
            isinstance(child.tag, str) and _local_name(child.tag) == "autoFilter"
            for child in output.xml_roots[sheet_binding.member_name]
        ):
            raise FinalizationError(
                f"overlapping worksheet autoFilter was created: {sheet_name}"
            )
    return output


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_atomic(temp_path: Path, output: Path, overwrite: bool) -> None:
    if overwrite:
        os.replace(temp_path, output)
    else:
        try:
            # The source is a newly-created regular file in this exact directory;
            # omitting follow_symlinks keeps this portable to Python/Windows builds
            # that do not expose that keyword while retaining atomic O_EXCL-like
            # destination semantics.
            os.link(temp_path, output)
        except FileExistsError as exc:
            raise FinalizationError(f"output already exists: {output}") from exc
        except OSError as exc:
            raise FinalizationError(
                f"atomic no-overwrite publish is unavailable for {output}: {exc}"
            ) from exc
        temp_path.unlink()
    _fsync_directory(output.parent)


def finalize_workbook(
    *,
    root: str | os.PathLike[str],
    input_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    overwrite: bool = False,
    limits: ArchiveLimits = DEFAULT_LIMITS,
) -> dict[str, object]:
    """Finalize one XLSX and return a deterministic, JSON-serializable report."""

    authorized_root = _resolve_root(root)
    source_path = _resolve_input(authorized_root, input_path)
    destination_path = _resolve_output(authorized_root, output_path)
    if source_path == destination_path:
        raise FinalizationError("input and output must be distinct paths")
    if destination_path.exists() and os.path.samefile(source_path, destination_path):
        raise FinalizationError("input and output resolve to the same file")
    if destination_path.exists() and not overwrite:
        raise FinalizationError(f"output already exists: {destination_path}")

    source_data = _read_regular_file(source_path, limits.max_archive_bytes)
    source_digest = _sha256(source_data)
    state = _load_and_validate_archive(source_data, limits)
    members, plan = _prepare_members(state)

    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.", suffix=".tmp", dir=destination_path.parent
    )
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        _write_archive(temp_path, state, members)
        output_data = _read_regular_file(temp_path, limits.max_archive_bytes)
        _verify_output(state, output_data, plan, limits)
        current_source = _read_regular_file(source_path, limits.max_archive_bytes)
        if _sha256(current_source) != source_digest:
            raise FinalizationError("input changed during finalization; output was not published")
        _publish_atomic(temp_path, destination_path, overwrite)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return {
        "status": "PASS",
        "tool": "finalize_workbook.py",
        "tool_version": VERSION,
        "input": str(source_path),
        "input_sha256": source_digest,
        "output": str(destination_path),
        "output_sha256": _sha256(output_data),
        "sheet_count": len(state.sheets),
        "table_count": len(state.tables),
        "frozen_sheets": list(plan.frozen_sheets),
        "auto_filters_added": [
            {"sheet": sheet_name, "ref": reference}
            for sheet_name, reference in plan.filters_added
        ],
        "table_auto_filters_added": [
            {"sheet": sheet_name, "table_member": table_member, "ref": reference}
            for sheet_name, table_member, reference in plan.table_filters_added
        ],
        "table_auto_filters_verified": [
            {"sheet": sheet_name, "table_member": table_member, "ref": reference}
            for sheet_name, table_member, reference in plan.table_filters_verified
        ],
        "auto_filters_skipped": list(plan.filters_skipped),
        "source_mutated": False,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Safely add A2 frozen panes and eligible header filters to a generated "
            "formula-free XLSX package."
        )
    )
    parser.add_argument("--root", required=True, help="Authorized directory for input/output")
    parser.add_argument("--input", required=True, help="Existing regular non-symlink .xlsx")
    parser.add_argument("--output", required=True, help="Distinct destination .xlsx")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Atomically replace an existing regular destination (never the input)",
    )
    parser.add_argument("--version", action="version", version=VERSION)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        report = finalize_workbook(
            root=arguments.root,
            input_path=arguments.input,
            output_path=arguments.output,
            overwrite=arguments.overwrite,
        )
    except (FinalizationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
