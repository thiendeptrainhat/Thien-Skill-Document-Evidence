from __future__ import annotations

import hashlib
import json
import posixpath
import shutil
import struct
import subprocess
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "thien-skill-document-evidence"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise AssertionError(f"not a PNG with an IHDR header: {path}")
    return struct.unpack(">II", data[16:24])


class ArtifactIntegrityTests(unittest.TestCase):
    def test_master_license_is_byte_identical_in_canonical_skill(self) -> None:
        expected = "ced33214d371fabe382d3ca303042af7219ad96fb98acdd1b858d0d89478d4b5"
        self.assertEqual(sha256(ROOT / "LICENSE"), expected)
        self.assertEqual(sha256(SKILL / "LICENSE.md"), expected)

    def test_brand_assets_preserve_declared_dimensions_and_hashes(self) -> None:
        expected = {
            "logo-original.png": ((1100, 1100), "020a47a3c831664c700c9e4491c7ae00cf5a8f330e6c3c57422ee246df56d69e"),
            "logo-large.png": ((1100, 1100), "020a47a3c831664c700c9e4491c7ae00cf5a8f330e6c3c57422ee246df56d69e"),
            "icon-512.png": ((512, 512), "be8ef61706db7ea9d0d8a6911d41a09b8f368e9d27d5ab02fbf44b000799c220"),
            "icon-small.png": ((400, 400), "25f406f44dcf349a70305529e7c23e388b55a88e79d4de98d0fa5e4ce6d581ac"),
            "icon-128.png": ((128, 128), "58695db66aa845d5b58631fc97ee0303d100cd1d0b1b81fd0bbf89b933d4ee12"),
            "icon-64.png": ((64, 64), "1b3acfa3a717f8286bba000a027e133e9a28275b8abee5936a9c947b3a500322"),
        }
        brand = SKILL / "assets" / "brand"
        for name, (size, digest) in expected.items():
            with self.subTest(name=name):
                path = brand / name
                self.assertEqual(png_size(path), size)
                self.assertEqual(sha256(path), digest)

    def test_workbook_template_has_safe_structure(self) -> None:
        workbook = SKILL / "assets" / "templates" / "document-evidence-workbook.xlsx"
        expected_sheets = {
            "00_README",
            "01_DOCUMENT_INDEX",
            "02_DOCUMENT_FIELDS",
            "03_LINE_ITEMS",
            "08_CONTRACT_CLAUSES",
            "09_CONTRACT_OBLIGATIONS",
            "11_DOCUMENT_LINKS",
            "12_RECONCILIATION",
            "13_DISCREPANCIES",
            "14_EVIDENCE_REGISTER",
            "15_CHAIN_OF_CUSTODY",
            "16_FIELD_DICTIONARY",
            "17_HUMAN_REVIEW",
            "18_QA_RESULTS",
            "19_RUN_LOG",
        }
        with zipfile.ZipFile(workbook) as archive:
            names = set(archive.namelist())
            forbidden = (
                "vbaproject",
                "externallinks/",
                "activex/",
                "embeddings/",
            )
            self.assertFalse(any(any(token in name.lower() for token in forbidden) for name in names))

            root = ET.fromstring(archive.read("xl/workbook.xml"))
            relationship_root = ET.fromstring(
                archive.read("xl/_rels/workbook.xml.rels")
            )
            relationship_targets = {
                node.attrib["Id"]: (
                    node.attrib["Target"].lstrip("/")
                    if node.attrib["Target"].startswith("/")
                    else posixpath.normpath(
                        posixpath.join("xl", node.attrib["Target"])
                    )
                )
                for node in relationship_root
            }
            sheet_members: dict[str, str] = {}
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] != "sheet":
                    continue
                relationship_id = next(
                    value
                    for key, value in node.attrib.items()
                    if key.rsplit("}", 1)[-1] == "id"
                )
                sheet_members[node.attrib["name"]] = relationship_targets[
                    relationship_id
                ]
            actual_sheets = set(sheet_members)
            self.assertEqual(actual_sheets, expected_sheets)

            expected_pane = {
                "ySplit": "1",
                "topLeftCell": "A2",
                "activePane": "bottomLeft",
                "state": "frozen",
            }
            for sheet_name, member_name in sheet_members.items():
                sheet = ET.fromstring(archive.read(member_name))
                local_names = {node.tag.rsplit("}", 1)[-1] for node in sheet.iter()}
                self.assertNotIn("f", local_names, member_name)
                self.assertNotIn("hyperlinks", local_names, member_name)
                if sheet_name == "00_README":
                    continue
                panes = [
                    node
                    for node in sheet.iter()
                    if node.tag.rsplit("}", 1)[-1] == "pane"
                ]
                self.assertEqual(len(panes), 1, sheet_name)
                self.assertEqual(panes[0].attrib, expected_pane, sheet_name)
                self.assertNotIn("mergeCells", local_names, sheet_name)
                self.assertTrue(
                    "autoFilter" in local_names or "tableParts" in local_names,
                    f"{sheet_name} has neither an autoFilter nor a structured table",
                )

            for table_name in sorted(
                name
                for name in names
                if name.startswith("xl/tables/") and name.endswith(".xml")
            ):
                table = ET.fromstring(archive.read(table_name))
                table_locals = {
                    node.tag.rsplit("}", 1)[-1] for node in table.iter()
                }
                self.assertIn("autoFilter", table_locals, table_name)

            for name in names:
                if name.endswith(".rels"):
                    relationships = ET.fromstring(archive.read(name))
                    for relation in relationships.iter():
                        self.assertNotEqual(relation.attrib.get("TargetMode"), "External", name)

    def test_workbook_builder_requires_a_matching_schema_report(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is unavailable")
        script = SKILL / "scripts" / "build_workbook.mjs"
        package = ROOT / "tests" / "fixtures" / "workbook-package.json"
        report_fixture = ROOT / "tests" / "fixtures" / "workbook-package.validation.json"
        with tempfile.TemporaryDirectory() as raw_temp:
            temp = Path(raw_temp)
            output = temp / "result.xlsx"
            missing = subprocess.run(
                [node, str(script), "--package", str(package), "--output", str(output)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(missing.returncode, 2)
            self.assertIn("--schema-validation-report is required", missing.stderr)
            self.assertFalse(output.exists())

            stale_report = json.loads(report_fixture.read_text(encoding="utf-8"))
            stale_report["run_manifest"]["input_sha256"] = "0" * 64
            stale_path = temp / "stale-report.json"
            stale_path.write_text(json.dumps(stale_report), encoding="utf-8")
            stale = subprocess.run(
                [
                    node,
                    str(script),
                    "--package",
                    str(package),
                    "--schema-validation-report",
                    str(stale_path),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(stale.returncode, 2)
            self.assertIn("input SHA-256 does not match package bytes", stale.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
