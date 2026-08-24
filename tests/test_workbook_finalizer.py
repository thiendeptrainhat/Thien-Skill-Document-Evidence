from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import os
from pathlib import Path
import posixpath
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "thien-skill-document-evidence" / "scripts" / "finalize_workbook.py"
SPEC = importlib.util.spec_from_file_location("workbook_finalizer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
FINALIZER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = FINALIZER
SPEC.loader.exec_module(FINALIZER)

SS_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
FIXED_TIME = (2026, 8, 23, 1, 2, 4)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o100644 << 16)
    return info


def _worksheet_xml(kind: str = "data", *, table_parts: str = "") -> bytes:
    if kind == "readme":
        body = (
            '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>README</t>'
            "</is></c></row></sheetData>"
        )
    elif kind == "notes":
        body = (
            '<sheetData><row r="1">'
            '<c r="A1" t="inlineStr"><is><t>left</t></is></c>'
            '<c r="C1" t="inlineStr"><is><t>right</t></is></c>'
            "</row></sheetData>"
        )
    elif kind == "formula":
        body = (
            '<sheetData><row r="1">'
            '<c r="A1" t="inlineStr"><is><t>id</t></is></c>'
            '<c r="B1" t="inlineStr"><is><t>amount</t></is></c></row>'
            '<row r="2"><c r="A2" t="inlineStr"><is><t>0001</t></is></c>'
            '<c r="B2"><f>1+1</f><v>2</v></c></row></sheetData>'
        )
    elif kind == "hyperlink":
        body = (
            '<sheetData><row r="1">'
            '<c r="A1" t="inlineStr"><is><t>id</t></is></c>'
            '<c r="B1" t="inlineStr"><is><t>amount</t></is></c></row>'
            '<row r="2"><c r="A2" t="inlineStr"><is><t>0001</t></is></c>'
            '<c r="B2"><v>2</v></c></row></sheetData>'
            '<hyperlinks><hyperlink ref="A2"/></hyperlinks>'
        )
    else:
        body = (
            '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
            '<sheetData><row r="1">'
            '<c r="A1" t="inlineStr"><is><t>identifier</t></is></c>'
            '<c r="B1" t="inlineStr"><is><t>amount</t></is></c></row>'
            '<row r="2"><c r="A2" t="inlineStr"><is><t>0001</t></is></c>'
            '<c r="B2"><v>12.5</v></c></row></sheetData>'
        )
    relationship_namespace = f' xmlns:r="{DOC_REL_NS}"' if table_parts else ""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{SS_NS}"{relationship_namespace}>{body}{table_parts}</worksheet>'
    ).encode()


def _write_fixture(
    path: Path,
    *,
    data_kind: str = "data",
    external_relationship: bool = False,
    vba: bool = False,
    unsafe_member: bool = False,
    large_member: int = 0,
    with_table: bool = False,
    ambiguous_table: bool = False,
    wrong_table_relationship: bool = False,
) -> None:
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/a-readme.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/z-data.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/m-notes.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/p-plain.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        + (
            '<Override PartName="/xl/tables/table7.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>'
            if with_table
            else ""
        )
        + (
            '<Override PartName="/xl/vbaProject.bin" '
            'ContentType="application/vnd.ms-office.vbaProject"/>'
            if vba
            else ""
        )
        + "</Types>"
    ).encode()
    root_relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{PKG_REL_NS}">'
        f'<Relationship Id="rRoot" Type="{DOC_REL_NS}/officeDocument" '
        'Target="xl/workbook.xml"/>'
        + (
            f'<Relationship Id="rExternal" Type="{DOC_REL_NS}/hyperlink" '
            'Target="https://example.invalid/" TargetMode="External"/>'
            if external_relationship
            else ""
        )
        + "</Relationships>"
    ).encode()
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<workbook xmlns="{SS_NS}" xmlns:r="{DOC_REL_NS}"><sheets>'
        '<sheet name="00_README" sheetId="1" r:id="rRead"/>'
        '<sheet name="01_DATA" sheetId="2" r:id="rData"/>'
        '<sheet name="02_NOTES" sheetId="3" r:id="rNotes"/>'
        '<sheet name="03_PLAIN" sheetId="4" r:id="rPlain"/>'
        "</sheets></workbook>"
    ).encode()
    workbook_relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{PKG_REL_NS}">'
        f'<Relationship Id="rData" Type="{DOC_REL_NS}/worksheet" '
        'Target="/xl/worksheets/z-data.xml"/>'
        f'<Relationship Id="rNotes" Type="{DOC_REL_NS}/worksheet" '
        'Target="worksheets/m-notes.xml"/>'
        f'<Relationship Id="rRead" Type="{DOC_REL_NS}/worksheet" '
        'Target="worksheets/a-readme.xml"/>'
        f'<Relationship Id="rPlain" Type="{DOC_REL_NS}/worksheet" '
        'Target="worksheets/p-plain.xml"/>'
        "</Relationships>"
    ).encode()
    table_parts = ""
    if with_table:
        table_parts = (
            f'<tableParts count="{2 if ambiguous_table else 1}">'
            '<tablePart r:id="rTable"/>'
            + ('<tablePart r:id="rTable"/>' if ambiguous_table else "")
            + "</tableParts>"
        )
    members: list[tuple[str, bytes]] = [
        ("[Content_Types].xml", content_types),
        ("_rels/.rels", root_relationships),
        ("xl/workbook.xml", workbook),
        ("xl/_rels/workbook.xml.rels", workbook_relationships),
        (
            "xl/worksheets/z-data.xml",
            _worksheet_xml(data_kind, table_parts=table_parts),
        ),
        ("xl/worksheets/a-readme.xml", _worksheet_xml("readme")),
        ("xl/worksheets/m-notes.xml", _worksheet_xml("notes")),
        ("xl/worksheets/p-plain.xml", _worksheet_xml("data")),
    ]
    if with_table:
        table_relationships = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<Relationships xmlns="{PKG_REL_NS}">'
            f'<Relationship Id="rTable" Type="{DOC_REL_NS}/'
            f'{"worksheet" if wrong_table_relationship else "table"}" '
            'Target="../tables/table7.xml"/>'
            "</Relationships>"
        ).encode()
        table_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<table xmlns="{SS_NS}" id="7" name="DataTable" '
            'displayName="DataTable" ref="A1:B2" headerRowCount="1" '
            'totalsRowCount="0" totalsRowShown="0">'
            '<tableColumns count="2">'
            '<tableColumn id="1" name="identifier"/>'
            '<tableColumn id="2" name="amount"/>'
            "</tableColumns>"
            '<tableStyleInfo name="TableStyleMedium2" showFirstColumn="0" '
            'showLastColumn="0" showRowStripes="1" showColumnStripes="0"/>'
            "</table>"
        ).encode()
        members.extend(
            [
                ("xl/worksheets/_rels/z-data.xml.rels", table_relationships),
                ("xl/tables/table7.xml", table_xml),
            ]
        )
    if vba:
        members.append(("xl/vbaProject.bin", b"not-a-real-vba-project"))
    if unsafe_member:
        members.append(("../escaped.xml", b"<unsafe/>"))
    if large_member:
        members.append(("docProps/large.txt", b"x" * large_member))
    with zipfile.ZipFile(path, "w", allowZip64=False) as archive:
        for name, data in members:
            archive.writestr(_zip_info(name), data, compresslevel=9)


def _sheet_roots(path: Path) -> dict[str, ET.Element]:
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {}
        for node in relationships:
            target = node.attrib["Target"]
            targets[node.attrib["Id"]] = (
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.normpath(posixpath.join("xl", target))
            )
        roots: dict[str, ET.Element] = {}
        for sheet in workbook.iter():
            if sheet.tag.rsplit("}", 1)[-1] != "sheet":
                continue
            relationship_id = next(
                value
                for key, value in sheet.attrib.items()
                if key.rsplit("}", 1)[-1] == "id"
            )
            roots[sheet.attrib["name"]] = ET.fromstring(archive.read(targets[relationship_id]))
        return roots


def _table_root(path: Path, member: str = "xl/tables/table7.xml") -> ET.Element:
    with zipfile.ZipFile(path) as archive:
        return ET.fromstring(archive.read(member))


def _mark_first_member_encrypted(path: Path) -> None:
    payload = bytearray(path.read_bytes())
    local = payload.find(b"PK\x03\x04")
    central = payload.find(b"PK\x01\x02")
    if local < 0 or central < 0:
        raise AssertionError("fixture is missing ZIP headers")
    local_flags = struct.unpack_from("<H", payload, local + 6)[0]
    central_flags = struct.unpack_from("<H", payload, central + 8)[0]
    struct.pack_into("<H", payload, local + 6, local_flags | 0x1)
    struct.pack_into("<H", payload, central + 8, central_flags | 0x1)
    path.write_bytes(payload)


class WorkbookFinalizerTests(unittest.TestCase):
    def test_maps_relationships_adds_controls_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.xlsx"
            output = root / "finalized.xlsx"
            output_two = root / "finalized-two.xlsx"
            verified_output = root / "verified-existing-filter.xlsx"
            _write_fixture(source, with_table=True)
            source_before = hashlib.sha256(source.read_bytes()).hexdigest()

            report = FINALIZER.finalize_workbook(
                root=root, input_path=source, output_path=output
            )
            report_two = FINALIZER.finalize_workbook(
                root=root, input_path=source, output_path=output_two
            )
            verified_report = FINALIZER.finalize_workbook(
                root=root, input_path=output, output_path=verified_output
            )

            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_before)
            self.assertFalse(report["source_mutated"])
            self.assertEqual(report["input_sha256"], source_before)
            self.assertEqual(report["output_sha256"], report_two["output_sha256"])
            self.assertEqual(output.read_bytes(), output_two.read_bytes())

            roots = _sheet_roots(output)
            readme_locals = {
                node.tag.rsplit("}", 1)[-1] for node in roots["00_README"].iter()
            }
            self.assertNotIn("pane", readme_locals)
            self.assertNotIn("autoFilter", readme_locals)

            data = roots["01_DATA"]
            pane = next(
                node for node in data.iter() if node.tag.rsplit("}", 1)[-1] == "pane"
            )
            self.assertEqual(
                pane.attrib,
                {
                    "ySplit": "1",
                    "topLeftCell": "A2",
                    "activePane": "bottomLeft",
                    "state": "frozen",
                },
            )
            self.assertFalse(
                any(node.tag.rsplit("}", 1)[-1] == "autoFilter" for node in data)
            )
            table = _table_root(output)
            table_filter = next(
                node
                for node in table
                if node.tag.rsplit("}", 1)[-1] == "autoFilter"
            )
            self.assertEqual(table_filter.attrib, {"ref": "A1:B2"})
            self.assertEqual(
                [node.tag.rsplit("}", 1)[-1] for node in table][:2],
                ["autoFilter", "tableColumns"],
            )

            notes = roots["02_NOTES"]
            self.assertTrue(
                any(node.tag.rsplit("}", 1)[-1] == "pane" for node in notes.iter())
            )
            self.assertFalse(
                any(node.tag.rsplit("}", 1)[-1] == "autoFilter" for node in notes)
            )
            plain_filter = next(
                node
                for node in roots["03_PLAIN"]
                if node.tag.rsplit("}", 1)[-1] == "autoFilter"
            )
            self.assertEqual(plain_filter.attrib, {"ref": "A1:B2"})
            self.assertEqual(
                report["auto_filters_added"], [{"sheet": "03_PLAIN", "ref": "A1:B2"}]
            )
            self.assertEqual(
                report["table_auto_filters_added"],
                [
                    {
                        "sheet": "01_DATA",
                        "table_member": "xl/tables/table7.xml",
                        "ref": "A1:B2",
                    }
                ],
            )
            self.assertEqual(report["table_auto_filters_verified"], [])
            self.assertEqual(
                verified_report["table_auto_filters_verified"],
                [
                    {
                        "sheet": "01_DATA",
                        "table_member": "xl/tables/table7.xml",
                        "ref": "A1:B2",
                    }
                ],
            )

    def test_path_collision_no_overwrite_and_symlink_guards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "authorized"
            root.mkdir()
            source = root / "source.xlsx"
            _write_fixture(source)

            with self.assertRaisesRegex(FINALIZER.FinalizationError, "distinct"):
                FINALIZER.finalize_workbook(
                    root=root, input_path=source, output_path=source, overwrite=True
                )
            with self.assertRaisesRegex(FINALIZER.FinalizationError, "escapes authorized root"):
                FINALIZER.finalize_workbook(
                    root=root,
                    input_path=source,
                    output_path=parent / "escaped.xlsx",
                )

            occupied = root / "occupied.xlsx"
            occupied.write_bytes(b"do-not-overwrite")
            with self.assertRaisesRegex(FINALIZER.FinalizationError, "already exists"):
                FINALIZER.finalize_workbook(
                    root=root, input_path=source, output_path=occupied
                )
            self.assertEqual(occupied.read_bytes(), b"do-not-overwrite")

            if hasattr(os, "symlink"):
                source_link = root / "source-link.xlsx"
                source_link.symlink_to(source.name)
                with self.assertRaisesRegex(FINALIZER.FinalizationError, "must not be a symlink"):
                    FINALIZER.finalize_workbook(
                        root=root,
                        input_path=source_link,
                        output_path=root / "from-link.xlsx",
                    )
                victim = root / "victim.xlsx"
                victim.write_bytes(b"victim")
                output_link = root / "output-link.xlsx"
                output_link.symlink_to(victim.name)
                with self.assertRaisesRegex(FINALIZER.FinalizationError, "must not be a symlink"):
                    FINALIZER.finalize_workbook(
                        root=root,
                        input_path=source,
                        output_path=output_link,
                        overwrite=True,
                    )
                self.assertEqual(victim.read_bytes(), b"victim")

    def test_rejects_formula_hyperlink_external_vba_and_unsafe_member(self) -> None:
        cases = {
            "formula": ({"data_kind": "formula"}, "formula-bearing"),
            "hyperlink": ({"data_kind": "hyperlink"}, "hyperlink-bearing"),
            "external": ({"external_relationship": True}, "external relationship"),
            "vba": ({"vba": True}, "unsafe OOXML package member"),
            "path": ({"unsafe_member": True}, "unsafe ZIP member path"),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for case_name, (options, error_text) in cases.items():
                with self.subTest(case=case_name):
                    source = root / f"{case_name}.xlsx"
                    output = root / f"{case_name}-out.xlsx"
                    _write_fixture(source, **options)
                    with self.assertRaisesRegex(FINALIZER.FinalizationError, error_text):
                        FINALIZER.finalize_workbook(
                            root=root, input_path=source, output_path=output
                        )
                    self.assertFalse(output.exists())

    def test_rejects_ambiguous_or_wrong_type_table_relationships(self) -> None:
        cases = {
            "duplicate": (
                {"with_table": True, "ambiguous_table": True},
                "duplicate tablePart relationship",
            ),
            "wrong-type": (
                {"with_table": True, "wrong_table_relationship": True},
                "does not resolve to a table",
            ),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for case_name, (options, error_text) in cases.items():
                with self.subTest(case=case_name):
                    source = root / f"table-{case_name}.xlsx"
                    output = root / f"table-{case_name}-out.xlsx"
                    _write_fixture(source, **options)
                    with self.assertRaisesRegex(FINALIZER.FinalizationError, error_text):
                        FINALIZER.finalize_workbook(
                            root=root, input_path=source, output_path=output
                        )
                    self.assertFalse(output.exists())

    def test_rejects_encryption_and_configured_oversize_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            encrypted = root / "encrypted.xlsx"
            _write_fixture(encrypted)
            _mark_first_member_encrypted(encrypted)
            with self.assertRaisesRegex(FINALIZER.FinalizationError, "encrypted ZIP member"):
                FINALIZER.finalize_workbook(
                    root=root,
                    input_path=encrypted,
                    output_path=root / "encrypted-out.xlsx",
                )

            oversized = root / "oversized.xlsx"
            _write_fixture(oversized, large_member=4096)
            tight_limits = replace(
                FINALIZER.DEFAULT_LIMITS,
                max_member_uncompressed_bytes=2048,
                max_total_uncompressed_bytes=128 * 1024,
            )
            with self.assertRaisesRegex(FINALIZER.FinalizationError, "ZIP member exceeds"):
                FINALIZER.finalize_workbook(
                    root=root,
                    input_path=oversized,
                    output_path=root / "oversized-out.xlsx",
                    limits=tight_limits,
                )


if __name__ == "__main__":
    unittest.main()
