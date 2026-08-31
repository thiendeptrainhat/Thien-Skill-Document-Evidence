"""Focused regressions for the independent-QA RAG and intake findings."""

from __future__ import annotations

import errno
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "thien-skill-document-evidence" / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


INVENTORY = load_module("phase2_remediation_inventory", SCRIPTS / "document_inventory.py")
RAG = load_module("phase2_remediation_rag", SCRIPTS / "build_rag_package.py")


class RagOverwriteRecoveryTests(unittest.TestCase):
    def test_previous_output_is_preserved_when_destination_is_recreated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-overwrite-recovery-") as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            (output / "original.txt").write_text("original\n", encoding="utf-8")
            real_rename = os.rename
            raced = False

            def rename_with_race(source, destination):
                nonlocal raced
                source_path = Path(source)
                destination_path = Path(destination)
                if (
                    not raced
                    and source_path.name.startswith(".output.staging-")
                    and destination_path == output
                ):
                    raced = True
                    output.mkdir()
                    (output / "racer.txt").write_text("racer\n", encoding="utf-8")
                    raise OSError(errno.ENOTEMPTY, "simulated concurrent recreation")
                return real_rename(source, destination)

            with mock.patch.object(RAG.os, "rename", side_effect=rename_with_race):
                with self.assertRaisesRegex(
                    RAG.RagBuildError, "previous output preserved at"
                ):
                    RAG.publish_directory(
                        output,
                        {"replacement.txt": b"replacement\n"},
                        overwrite=True,
                    )

            self.assertEqual((output / "racer.txt").read_text(encoding="utf-8"), "racer\n")
            backups = list(root.glob(".output.backup-slot-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(
                (backups[0] / "original.txt").read_text(encoding="utf-8"),
                "original\n",
            )
            self.assertEqual(list(root.glob(".output.staging-*")), [])


class InventorySnapshotAndRelationshipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="inventory-remediation-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write_ooxml(self, name: str, relationships: bytes) -> Path:
        target = self.root / name
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")
            archive.writestr("word/_rels/document.xml.rels", relationships)
        return target

    def test_external_relationship_parser_handles_whitespace_case_and_namespace(self) -> None:
        relationships = b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" TargetMode = "eXtErNaL" Target="https://example.invalid/x" />
</Relationships>"""
        self.write_ooxml("external.docx", relationships)

        record = INVENTORY.build_inventory(self.root, ["external.docx"])["records"][0]

        self.assertEqual(
            record["integrity"]["active_content"]["external_links"], "DETECTED"
        )
        self.assertIn("ACTIVE_CONTENT_EXTERNAL_LINKS", record["security_flags"])
        self.assertEqual(record["review_status"], "REQUIRED")

    def test_malformed_and_oversize_relationships_fail_closed(self) -> None:
        malformed = b'<Relationships><Relationship TargetMode="External">'
        self.write_ooxml("malformed.docx", malformed)
        malformed_record = INVENTORY.build_inventory(
            self.root, ["malformed.docx"]
        )["records"][0]
        self.assertEqual(
            malformed_record["integrity"]["active_content"]["external_links"],
            "UNKNOWN",
        )
        self.assertIn("MALFORMED_RELATIONSHIPS_XML", malformed_record["security_flags"])
        self.assertEqual(malformed_record["review_status"], "REQUIRED")

        unsafe = (
            '<?xml version="1.0" encoding="UTF-16"?>'
            '<!DOCTYPE Relationships [<!ENTITY target "https://example.invalid/">]>'
            '<Relationships><Relationship Target="&target;"/></Relationships>'
        ).encode("utf-16")
        self.write_ooxml("unsafe-declaration.docx", unsafe)
        unsafe_record = INVENTORY.build_inventory(
            self.root, ["unsafe-declaration.docx"]
        )["records"][0]
        self.assertEqual(
            unsafe_record["integrity"]["active_content"]["external_links"],
            "UNKNOWN",
        )
        self.assertIn(
            "UNSAFE_RELATIONSHIPS_XML_DECLARATION", unsafe_record["security_flags"]
        )
        self.assertEqual(unsafe_record["review_status"], "REQUIRED")

        valid = b"<Relationships><Relationship TargetMode='External'/></Relationships>"
        self.write_ooxml("oversize.docx", valid)
        with mock.patch.object(INVENTORY, "MAX_RELATIONSHIP_BYTES", len(valid) - 1):
            oversize_record = INVENTORY.build_inventory(
                self.root, ["oversize.docx"]
            )["records"][0]
        self.assertEqual(
            oversize_record["integrity"]["active_content"]["external_links"],
            "UNKNOWN",
        )
        self.assertIn(
            "RELATIONSHIP_MEMBER_SIZE_LIMIT_EXCEEDED",
            oversize_record["security_flags"],
        )
        self.assertEqual(oversize_record["review_status"], "REQUIRED")

    def test_inventory_metadata_uses_the_hashed_immutable_snapshot(self) -> None:
        source = self.root / "mutable.pdf"
        original = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"
        replacement = (
            b"%PDF-1.7\n1 0 obj << /Type /Catalog /JavaScript /JS >> endobj\n%%EOF\n"
        )
        source.write_bytes(original)
        real_make_base_record = INVENTORY.make_base_record
        mutated = False

        def mutate_after_capture(**kwargs):
            nonlocal mutated
            if not mutated:
                mutated = True
                source.write_bytes(replacement)
            return real_make_base_record(**kwargs)

        with mock.patch.object(
            INVENTORY, "make_base_record", side_effect=mutate_after_capture
        ):
            record = INVENTORY.build_inventory(self.root, ["mutable.pdf"])["records"][0]

        self.assertEqual(
            record["file"]["checksum"]["digest"], hashlib.sha256(original).hexdigest()
        )
        self.assertEqual(record["file"]["size_bytes"], len(original))
        self.assertEqual(
            record["integrity"]["active_content"]["javascript"], "NOT_DETECTED"
        )
        self.assertEqual(source.read_bytes(), replacement)

    def test_source_change_during_snapshot_fails_closed(self) -> None:
        source = self.root / "changing.txt"
        source.write_bytes(b"before")
        real_open = INVENTORY.open_regular_nofollow
        changed = False

        class MutatingReader:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return self.handle.__exit__(exc_type, exc, traceback)

            def fileno(self):
                return self.handle.fileno()

            def read(self, size=-1):
                nonlocal changed
                data = self.handle.read(size)
                if not changed:
                    changed = True
                    source.write_bytes(b"changed-and-longer")
                return data

        def mutating_open(path):
            handle = real_open(path)
            if Path(path) == source:
                return MutatingReader(handle)
            return handle

        with mock.patch.object(
            INVENTORY, "open_regular_nofollow", side_effect=mutating_open
        ):
            with self.assertRaisesRegex(
                INVENTORY.InventoryError, "source changed during snapshot"
            ):
                INVENTORY.build_inventory(self.root, ["changing.txt"])


if __name__ == "__main__":
    unittest.main()
