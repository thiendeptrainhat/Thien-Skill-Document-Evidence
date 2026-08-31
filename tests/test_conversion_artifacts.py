"""Structural, determinism, and safety tests for Phase 2 canonical conversion."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "thien-skill-document-evidence"
    / "scripts"
    / "render_canonical_artifacts.py"
)
FIXTURES = ROOT / "tests" / "fixtures" / "conversion"


def load_renderer():
    spec = importlib.util.spec_from_file_location("phase2_conversion_renderer", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load renderer from {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RENDER = load_renderer()


class ConversionWorkspace:
    def __init__(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="conversion-artifacts-")
        self.root = Path(self._temporary.name)
        (self.root / "assets").mkdir()
        (self.root / "out").mkdir()
        shutil.copyfile(
            FIXTURES / "canonical-content.json", self.root / "canonical-content.json"
        )
        encoded = (FIXTURES / "page-1.png.b64").read_text(encoding="ascii")
        (self.root / "assets" / "page-1.png").write_bytes(base64.b64decode(encoded))

    def close(self) -> None:
        self._temporary.cleanup()

    def __enter__(self) -> "ConversionWorkspace":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def canonical(self) -> dict[str, object]:
        return json.loads((self.root / "canonical-content.json").read_text(encoding="utf-8"))

    def write_canonical(self, value: dict[str, object], name: str = "input.json") -> str:
        (self.root / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return name


def render(
    workspace: ConversionWorkspace,
    output_format: str,
    *,
    output_name: str | None = None,
    canonical_name: str = "canonical-content.json",
    profile: str | None = None,
    intent: str | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    suffix = RENDER.FORMAT_SUFFIX[output_format]
    output_name = output_name or f"out/result{suffix}"
    needs_assets = output_format in {"DOCX", "PPTX"}
    return RENDER.render_canonical_artifact(
        root=workspace.root,
        canonical_path=canonical_name,
        output_path=output_name,
        output_format=output_format,
        output_profile=profile,
        presentation_intent=intent,
        assets_root="assets" if needs_assets else None,
        overwrite=overwrite,
    )


class ConversionArtifactTests(unittest.TestCase):
    def test_json_and_markdown_preserve_semantics_and_source_locator(self) -> None:
        with ConversionWorkspace() as workspace:
            source_before = (workspace.root / "canonical-content.json").read_bytes()
            json_manifest = render(workspace, "JSON", output_name="out/content.json")
            markdown_manifest = render(workspace, "MD", output_name="out/content.md")

            canonical = workspace.canonical()
            rendered_json = json.loads((workspace.root / "out/content.json").read_text())
            self.assertEqual(rendered_json, canonical)
            self.assertEqual(rendered_json["skill_release_version"], "1.1.0-rc.1")
            self.assertEqual(RENDER.TOOL_VERSION, "1.0.0")
            self.assertEqual(
                RENDER.SKILL_RELEASE_VERSION,
                (ROOT / "thien-skill-document-evidence" / "VERSION").read_text().strip(),
            )
            self.assertEqual(
                json_manifest["skill_release_version"], RENDER.SKILL_RELEASE_VERSION
            )
            markdown = (workspace.root / "out/content.md").read_text(encoding="utf-8")
            self.assertIn("# Quarterly Evidence Summary", markdown)
            self.assertIn("| Reference | Amount |", markdown)
            self.assertIn("![One-pixel synthetic fixture](page-1.png)", markdown)
            self.assertIn('data-block-id="block-caption-001"', markdown)
            self.assertIn('data-source-region="page-1/caption-1"', markdown)
            self.assertIn("Synthetic image used only for structural conversion QA.", markdown)
            self.assertEqual(json_manifest["status"], "PASS")
            self.assertEqual(markdown_manifest["status"], "PASS_WITH_WARNINGS")
            self.assertEqual(
                (workspace.root / "canonical-content.json").read_bytes(), source_before
            )

    def test_office_outputs_are_real_structural_ooxml_with_canonical_provenance(self) -> None:
        cases = {
            "DOCX": ("SEMANTIC_EDITABLE", None),
            "XLSX": ("STRUCTURED_DATA", None),
            "PPTX": ("EDITABLE_PRESENTATION", "PRESENTATION"),
        }
        with ConversionWorkspace() as workspace:
            canonical = workspace.canonical()
            for output_format, (profile, intent) in cases.items():
                with self.subTest(output_format=output_format):
                    output = workspace.root / f"out/content.{output_format.casefold()}"
                    manifest = render(
                        workspace,
                        output_format,
                        output_name=f"out/content.{output_format.casefold()}",
                        profile=profile,
                        intent=intent,
                    )
                    self.assertTrue(output.read_bytes().startswith(b"PK"))
                    with zipfile.ZipFile(output) as archive:
                        self.assertIsNone(archive.testzip())
                        self.assertIn("customXml/item1.xml", archive.namelist())
                        custom_root = ET.fromstring(archive.read("customXml/item1.xml"))
                        payload = next(
                            element.text
                            for element in custom_root.iter()
                            if element.tag.endswith("}json")
                        )
                        self.assertEqual(json.loads(payload), canonical)
                        self.assertEqual(json.loads(payload)["skill_release_version"], "1.1.0-rc.1")
                        relationships = b"".join(
                            archive.read(name)
                            for name in archive.namelist()
                            if name.endswith(".rels")
                        )
                        self.assertNotIn(b'TargetMode="External"', relationships)
                        self.assertFalse(
                            any("vbaproject.bin" in name.casefold() for name in archive.namelist())
                        )
                        if output_format == "DOCX":
                            main = archive.read("word/document.xml")
                            self.assertIn(b"Heading1", main)
                            self.assertIn(b"<w:tbl>", main)
                            self.assertIn(b"<w:drawing>", main)
                            self.assertIn("word/media/image1.png", archive.namelist())
                        elif output_format == "XLSX":
                            main = archive.read("xl/worksheets/sheet1.xml")
                            styles = archive.read("xl/styles.xml")
                            self.assertIn(b"<autoFilter", main)
                            self.assertIn(b'state="frozen"', main)
                            self.assertIn(b"block-caption-001", main)
                            self.assertIn(b'<c r="C2" s="2"><v>1</v></c>', main)
                            self.assertIn(b'<c r="E2" s="2"><v>1</v></c>', main)
                            self.assertIn(b'<c r="J2" s="2"><v>1</v></c>', main)
                            self.assertIn(
                                b'<c r="A2" s="2" t="inlineStr"><is><t xml:space="preserve">block-heading-001',
                                main,
                            )
                            self.assertIn(b'<c r="A1" s="1" t="inlineStr">', main)
                            self.assertIn(b'<col min="7" max="7" width="44"', main)
                            self.assertIn(b'<col min="9" max="9" width="52"', main)
                            self.assertNotIn(b'min="1" max="16" width="22"', main)
                            self.assertIn(b'<cellXfs count="3">', styles)
                            self.assertEqual(styles.count(b'wrapText="1"'), 2)
                            self.assertIn(b'<pageSetUpPr fitToPage="1"/>', main)
                            self.assertIn(
                                b'<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/>',
                                main,
                            )
                        else:
                            main = archive.read("ppt/slides/slide1.xml")
                            self.assertIn(b"<a:tbl>", main)
                            self.assertIn(b"<p:pic>", main)
                            self.assertIn(b"Quarterly Evidence Summary", main)
                            self.assertIn("ppt/media/image1.png", archive.namelist())
                            slide_root = ET.fromstring(main)
                            namespaces = {
                                "a": "http://schemas.openxmlformats.org/drawingml/2006/main"
                            }
                            table_cells = slide_root.findall(".//a:tbl/a:tr/a:tc", namespaces)
                            self.assertEqual(len(table_cells), 6)
                            for cell in table_cells:
                                run_properties = cell.find(
                                    "./a:txBody/a:p/a:r/a:rPr", namespaces
                                )
                                self.assertIsNotNone(run_properties)
                                self.assertEqual(
                                    run_properties.find(
                                        "./a:solidFill/a:srgbClr", namespaces
                                    ).attrib.get("val"),
                                    "000000",
                                )
                                self.assertEqual(
                                    run_properties.find("./a:latin", namespaces).attrib.get(
                                        "typeface"
                                    ),
                                    "Arial",
                                )
                                self.assertEqual(
                                    cell.find(
                                        "./a:tcPr/a:solidFill/a:srgbClr", namespaces
                                    ).attrib.get("val"),
                                    "FFFFFF",
                                )
                    artifact = manifest["artifacts"][0]
                    self.assertEqual(
                        manifest["skill_release_version"], RENDER.SKILL_RELEASE_VERSION
                    )
                    self.assertEqual(manifest["status"], "NOT_TESTED")
                    self.assertEqual(artifact["creation_status"], "CREATED")
                    self.assertEqual(artifact["qa_status"], "NOT_TESTED")
                    self.assertTrue(
                        any("visual render/import QA was not executed" in item for item in artifact["limitations"])
                    )
                    self.assertEqual(
                        artifact["checksum"]["digest"], hashlib.sha256(output.read_bytes()).hexdigest()
                    )

    def test_xlsx_long_provenance_gets_adaptive_wrapped_row_height(self) -> None:
        with ConversionWorkspace() as workspace:
            canonical = workspace.canonical()
            canonical["blocks"][0]["provenance"]["source_snippet"] = " ".join(
                ["long-provenance-value"] * 30
            )
            canonical_name = workspace.write_canonical(canonical, "long-content.json")
            render(
                workspace,
                "XLSX",
                output_name="out/long-content.xlsx",
                canonical_name=canonical_name,
                profile="STRUCTURED_DATA",
            )
            with zipfile.ZipFile(workspace.root / "out/long-content.xlsx") as archive:
                worksheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            data_row = worksheet.find(".//x:sheetData/x:row[@r='2']", namespace)
            self.assertIsNotNone(data_row)
            height = int(data_row.attrib["ht"])
            self.assertGreater(height, 45)
            self.assertLess(height, 405)
            self.assertEqual(data_row.attrib["customHeight"], "1")
            self.assertEqual(RENDER._xlsx_row_height(["x" * 32_767], (44,)), 405)

    def test_every_format_is_deterministic_for_identical_relative_inputs(self) -> None:
        cases = {
            "JSON": (None, None),
            "MD": (None, None),
            "DOCX": ("SEMANTIC_EDITABLE", None),
            "XLSX": ("STRUCTURED_DATA", None),
            "PPTX": ("EDITABLE_PRESENTATION", "PRESENTATION"),
        }
        for output_format, (profile, intent) in cases.items():
            with self.subTest(output_format=output_format):
                with ConversionWorkspace() as first, ConversionWorkspace() as second:
                    suffix = RENDER.FORMAT_SUFFIX[output_format]
                    relative = f"out/deterministic{suffix}"
                    render(first, output_format, output_name=relative, profile=profile, intent=intent)
                    render(second, output_format, output_name=relative, profile=profile, intent=intent)
                    self.assertEqual(
                        (first.root / relative).read_bytes(),
                        (second.root / relative).read_bytes(),
                    )
                    self.assertEqual(
                        (first.root / (relative + ".manifest.json")).read_bytes(),
                        (second.root / (relative + ".manifest.json")).read_bytes(),
                    )
                    self.assertEqual(
                        (first.root / (relative + ".conversion-run.json")).read_bytes(),
                        (second.root / (relative + ".conversion-run.json")).read_bytes(),
                    )

    def test_pptx_intent_pairing_and_page_image_gate_are_fail_closed(self) -> None:
        with ConversionWorkspace() as workspace:
            with self.assertRaisesRegex(RENDER.ConversionError, "requires output profile"):
                render(
                    workspace,
                    "PPTX",
                    profile="PAGE_AS_SLIDE",
                    intent="PRESENTATION",
                )
            with self.assertRaisesRegex(RENDER.ConversionError, "explicitly resolved"):
                render(
                    workspace,
                    "PPTX",
                    profile="EDITABLE_PRESENTATION",
                    intent="AMBIGUOUS",
                )
            with self.assertRaisesRegex(RENDER.ConversionError, "fidelity_mode PAGE_IMAGE"):
                render(
                    workspace,
                    "PPTX",
                    profile="PAGE_AS_SLIDE",
                    intent="FAITHFUL_PAGE_CONVERSION",
                )

            page_image = workspace.canonical()
            page_image["fidelity_mode"] = "PAGE_IMAGE"
            image = copy.deepcopy(page_image["blocks"][3])
            caption = copy.deepcopy(page_image["blocks"][4])
            image["reading_order"] = 1
            image["parent_block_id"] = None
            image["provenance"]["source_region"] = "page-1/full-page"
            caption["reading_order"] = 2
            page_image["blocks"] = [image, caption]
            canonical_name = workspace.write_canonical(page_image, "page-image.json")
            manifest = render(
                workspace,
                "PPTX",
                output_name="out/page-as-slide.pptx",
                canonical_name=canonical_name,
                profile="PAGE_AS_SLIDE",
                intent="FAITHFUL_PAGE_CONVERSION",
            )
            with zipfile.ZipFile(workspace.root / "out/page-as-slide.pptx") as archive:
                slides = [
                    name
                    for name in archive.namelist()
                    if re_full_slide_name(name)
                ]
                self.assertEqual(slides, ["ppt/slides/slide1.xml"])
                slide = archive.read(slides[0])
                self.assertIn(b'<a:off x="2667000" y="0"/>', slide)
                self.assertIn(b'<a:ext cx="6858000" cy="6858000"/>', slide)
                self.assertIn(b'<p:pic>', slide)
            self.assertEqual(manifest["artifacts"][0]["qa_status"], "NOT_TESTED")

    def test_invalid_schema_and_semantic_invariants_are_rejected(self) -> None:
        mutations = []
        with ConversionWorkspace() as workspace:
            canonical = workspace.canonical()
            duplicate = copy.deepcopy(canonical)
            duplicate["blocks"][1]["block_id"] = duplicate["blocks"][0]["block_id"]
            mutations.append(("duplicate.json", duplicate, "block_id values must be unique"))

            bad_table = copy.deepcopy(canonical)
            bad_table["blocks"][2]["rows"][0] = ["only-one-cell"]
            mutations.append(("table.json", bad_table, "table row width mismatch"))

            overflow = copy.deepcopy(canonical)
            provenance = overflow["blocks"][1]["provenance"]
            provenance["geometry_status"] = "CAPTURED"
            provenance["bounding_box"] = {
                "coordinate_system": "NORMALIZED_0_1",
                "x": 0.8,
                "y": 0.1,
                "width": 0.3,
                "height": 0.2,
                "page_width": 1,
                "page_height": 1,
            }
            mutations.append(("overflow.json", overflow, "horizontal bounding-box overflow"))

            unknown = copy.deepcopy(canonical)
            unknown["unexpected"] = True
            mutations.append(("unknown.json", unknown, "additionalProperties"))

            for index, (name, value, expected) in enumerate(mutations):
                with self.subTest(name=name):
                    workspace.write_canonical(value, name)
                    with self.assertRaisesRegex(RENDER.ConversionError, expected):
                        render(
                            workspace,
                            "JSON",
                            canonical_name=name,
                            output_name=f"out/invalid-{index}.json",
                        )

    def test_collision_extension_escape_symlink_and_inode_alias_are_rejected(self) -> None:
        with ConversionWorkspace() as workspace:
            render(workspace, "JSON", output_name="out/protected.json")
            original = (workspace.root / "out/protected.json").read_bytes()
            with self.assertRaisesRegex(RENDER.ConversionError, "already exists"):
                render(workspace, "JSON", output_name="out/protected.json")
            self.assertEqual((workspace.root / "out/protected.json").read_bytes(), original)

            with self.assertRaisesRegex(RENDER.ConversionError, "real \\.docx extension"):
                render(
                    workspace,
                    "DOCX",
                    output_name="out/fake.txt",
                    profile="SEMANTIC_EDITABLE",
                )
            with self.assertRaisesRegex(RENDER.ConversionError, "escapes authorized root"):
                render(workspace, "JSON", output_name="../escaped.json")

            outside = Path(workspace.root.parent) / "conversion-outside-target.json"
            link = workspace.root / "out/symlink.json"
            try:
                link.symlink_to(outside)
                with self.assertRaisesRegex(RENDER.ConversionError, "must not be a symlink"):
                    render(workspace, "JSON", output_name="out/symlink.json", overwrite=True)
            finally:
                link.unlink(missing_ok=True)

            alias = workspace.root / "out/input-alias.json"
            os.link(workspace.root / "canonical-content.json", alias)
            with self.assertRaisesRegex(RENDER.ConversionError, "alias an input"):
                render(
                    workspace,
                    "JSON",
                    output_name="out/input-alias.json",
                    overwrite=True,
                )

    def test_atomic_no_overwrite_publication_does_not_clobber_racing_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="conversion-atomic-") as raw:
            root = Path(raw)
            destination = root / "artifact.json"
            original_link = os.link

            def racing_link(source: str | bytes | os.PathLike[str], target: str | bytes | os.PathLike[str], *args: object, **kwargs: object) -> None:
                destination.write_bytes(b"racer\n")
                raise FileExistsError(os.fspath(target))

            with mock.patch.object(RENDER.os, "link", side_effect=racing_link):
                with self.assertRaisesRegex(RENDER.ConversionError, "appeared during atomic publication"):
                    RENDER.atomic_write(destination, b"renderer\n", overwrite=False)
            self.assertEqual(destination.read_bytes(), b"racer\n")
            self.assertEqual(list(root.glob(".artifact.json.*")), [])
            self.assertIs(original_link, os.link)

    def test_asset_checksum_mismatch_is_rejected_before_publication(self) -> None:
        with ConversionWorkspace() as workspace:
            asset = workspace.root / "assets/page-1.png"
            changed = bytearray(asset.read_bytes())
            changed[-1] ^= 1
            asset.write_bytes(changed)
            with self.assertRaisesRegex(RENDER.ConversionError, "SHA-256 mismatch"):
                render(
                    workspace,
                    "DOCX",
                    output_name="out/mismatch.docx",
                    profile="SEMANTIC_EDITABLE",
                )
            self.assertFalse((workspace.root / "out/mismatch.docx").exists())
            self.assertFalse((workspace.root / "out/mismatch.docx.manifest.json").exists())
            self.assertFalse((workspace.root / "out/mismatch.docx.conversion-run.json").exists())

    def test_canonical_and_asset_reads_are_bounded(self) -> None:
        with ConversionWorkspace() as workspace:
            with mock.patch.object(RENDER, "MAX_CANONICAL_BYTES", 16):
                with self.assertRaisesRegex(RENDER.ConversionError, "16-byte safety limit"):
                    render(workspace, "JSON", output_name="out/too-large.json")
            self.assertFalse((workspace.root / "out/too-large.json").exists())

            with mock.patch.object(RENDER, "MAX_ASSET_BYTES", 8):
                with self.assertRaisesRegex(RENDER.ConversionError, "8-byte safety limit"):
                    render(
                        workspace,
                        "DOCX",
                        output_name="out/asset-too-large.docx",
                        profile="SEMANTIC_EDITABLE",
                    )
            self.assertFalse((workspace.root / "out/asset-too-large.docx").exists())

    def test_conversion_run_sidecar_links_runtime_source_and_both_outputs(self) -> None:
        with ConversionWorkspace() as workspace:
            render(workspace, "JSON", output_name="out/linked.json")
            artifact = workspace.root / "out/linked.json"
            manifest_path = workspace.root / "out/linked.json.manifest.json"
            run_path = workspace.root / "out/linked.json.conversion-run.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            run = json.loads(run_path.read_text(encoding="utf-8"))

            self.assertEqual(run["schema_version"], "1.0.0")
            self.assertEqual(
                run["tool"], {"name": RENDER.TOOL_NAME, "version": "1.0.0"}
            )
            self.assertEqual(
                run["runtime_skill"]["release_version"],
                RENDER.SKILL_RELEASE_VERSION,
            )
            self.assertEqual(
                run["source_canonical"]["source_skill_release_version"],
                "1.1.0-rc.1",
            )
            self.assertEqual(run["request"]["output_format"], "JSON")
            self.assertIsNone(run["request"]["output_profile"])
            self.assertIsNone(run["request"]["presentation_intent"])
            self.assertEqual(
                run["outputs"]["artifact"]["artifact_id"],
                manifest["artifacts"][0]["artifact_id"],
            )
            self.assertEqual(
                run["outputs"]["artifact_manifest"]["manifest_id"],
                manifest["manifest_id"],
            )
            self.assertEqual(
                run["outputs"]["artifact"]["checksum"]["digest"],
                hashlib.sha256(artifact.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                run["outputs"]["artifact_manifest"]["checksum"]["digest"],
                hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                run["source_canonical"]["checksum"]["digest"],
                hashlib.sha256(
                    (workspace.root / "canonical-content.json").read_bytes()
                ).hexdigest(),
            )
            invalid = copy.deepcopy(run)
            invalid["unexpected"] = True
            with self.assertRaisesRegex(RENDER.ConversionError, "additionalProperties"):
                RENDER.validate_schema(invalid, "conversion-run.schema.json")

            invalid_pptx_pair = copy.deepcopy(run)
            invalid_pptx_pair["request"] = {
                "output_format": "PPTX",
                "output_profile": None,
                "presentation_intent": None,
            }
            invalid_pptx_pair["outputs"]["artifact"]["format"] = "PPTX"
            invalid_pptx_pair["outputs"]["artifact"]["media_type"] = (
                "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            )
            with self.assertRaises(RENDER.ConversionError):
                RENDER.validate_schema(
                    invalid_pptx_pair, "conversion-run.schema.json"
                )

            invalid_artifact_link = copy.deepcopy(run)
            invalid_artifact_link["outputs"]["artifact"]["format"] = "MD"
            invalid_artifact_link["outputs"]["artifact"]["media_type"] = (
                "text/markdown"
            )
            with self.assertRaises(RENDER.ConversionError):
                RENDER.validate_schema(
                    invalid_artifact_link, "conversion-run.schema.json"
                )

    def test_three_file_transaction_rolls_back_create_and_overwrite_failures(self) -> None:
        with ConversionWorkspace() as workspace:
            artifact = workspace.root / "out/transaction.json"
            manifest = workspace.root / "out/transaction.json.manifest.json"
            run_path = workspace.root / "out/transaction.json.conversion-run.json"
            original_link = os.link
            link_calls = 0

            def fail_second_link(
                source: object, target: object, *args: object, **kwargs: object
            ) -> None:
                nonlocal link_calls
                link_calls += 1
                if link_calls == 2:
                    raise OSError("injected create publication failure")
                original_link(source, target, *args, **kwargs)

            with mock.patch.object(RENDER.os, "link", side_effect=fail_second_link):
                with self.assertRaisesRegex(RENDER.ConversionError, "rolled back"):
                    render(workspace, "JSON", output_name="out/transaction.json")
            self.assertFalse(artifact.exists())
            self.assertFalse(manifest.exists())
            self.assertFalse(run_path.exists())
            self.assertEqual(list((workspace.root / "out").glob(".*.txn-*")), [])

            render(workspace, "JSON", output_name="out/transaction.json")
            old_bytes = {
                path: path.read_bytes() for path in (artifact, manifest, run_path)
            }
            changed = workspace.canonical()
            changed["blocks"][1]["text"] = "Changed content for overwrite rollback."
            workspace.write_canonical(changed, "canonical-content.json")
            original_replace = os.replace
            stage_replacements = 0

            def fail_second_stage(
                source: object, target: object, *args: object, **kwargs: object
            ) -> None:
                nonlocal stage_replacements
                if ".txn-stage." in Path(os.fspath(source)).name:
                    stage_replacements += 1
                    if stage_replacements == 2:
                        raise OSError("injected overwrite publication failure")
                original_replace(source, target, *args, **kwargs)

            with mock.patch.object(
                RENDER.os, "replace", side_effect=fail_second_stage
            ):
                with self.assertRaisesRegex(RENDER.ConversionError, "rolled back"):
                    render(
                        workspace,
                        "JSON",
                        output_name="out/transaction.json",
                        overwrite=True,
                    )
            for path, expected in old_bytes.items():
                self.assertEqual(path.read_bytes(), expected)
            self.assertEqual(list((workspace.root / "out").glob(".*.txn-*")), [])

            render(
                workspace,
                "JSON",
                output_name="out/transaction.json",
                overwrite=True,
            )
            self.assertIn(
                b"Changed content for overwrite rollback.", artifact.read_bytes()
            )
            refreshed_run = json.loads(run_path.read_text(encoding="utf-8"))
            self.assertEqual(
                refreshed_run["outputs"]["artifact_manifest"]["checksum"]["digest"],
                hashlib.sha256(manifest.read_bytes()).hexdigest(),
            )
            self.assertEqual(list((workspace.root / "out").glob(".*.txn-*")), [])

    def test_xlsx_refuses_oversize_cell_without_truncation_or_partial_outputs(self) -> None:
        with ConversionWorkspace() as workspace:
            canonical = workspace.canonical()
            canonical["blocks"][1]["text"] = "x" * 32_768
            workspace.write_canonical(canonical, "oversize-cell.json")
            with self.assertRaisesRegex(RENDER.ConversionError, "32767-code-point"):
                render(
                    workspace,
                    "XLSX",
                    canonical_name="oversize-cell.json",
                    output_name="out/oversize.xlsx",
                    profile="STRUCTURED_DATA",
                )
            self.assertFalse((workspace.root / "out/oversize.xlsx").exists())
            self.assertFalse(
                (workspace.root / "out/oversize.xlsx.manifest.json").exists()
            )
            self.assertFalse(
                (workspace.root / "out/oversize.xlsx.conversion-run.json").exists()
            )

    def test_editable_presentation_paginates_and_keeps_every_shape_on_canvas(self) -> None:
        with ConversionWorkspace() as workspace:
            canonical = workspace.canonical()
            long_text = "Long canonical paragraph. " * 900
            canonical["blocks"][1]["text"] = long_text
            canonical_name = workspace.write_canonical(
                canonical, "long-presentation.json"
            )
            render(
                workspace,
                "PPTX",
                canonical_name=canonical_name,
                output_name="out/long.pptx",
                profile="EDITABLE_PRESENTATION",
                intent="PRESENTATION",
            )
            with zipfile.ZipFile(workspace.root / "out/long.pptx") as archive:
                slides = sorted(
                    (name for name in archive.namelist() if re_full_slide_name(name)),
                    key=lambda name: int(name.rsplit("/", 1)[1][5:-4]),
                )
                self.assertGreater(len(slides), 2)
                paragraph_fragments: list[str] = []
                for name in slides:
                    payload = archive.read(name).decode("utf-8")
                    for x, y, width, height in re.findall(
                        r'<a:off x="([0-9]+)" y="([0-9]+)"/><a:ext cx="([0-9]+)" cy="([0-9]+)"/>',
                        payload,
                    ):
                        self.assertLessEqual(
                            int(x) + int(width), RENDER.SLIDE_WIDTH
                        )
                        self.assertLessEqual(
                            int(y) + int(height), RENDER.SLIDE_HEIGHT
                        )
                    root = ET.fromstring(payload)
                    namespaces = {
                        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                    }
                    for shape in root.findall(".//p:sp", namespaces):
                        metadata = shape.find("./p:nvSpPr/p:cNvPr", namespaces)
                        if (
                            metadata is not None
                            and metadata.attrib.get("name")
                            == "Paragraph block-paragraph-001"
                        ):
                            paragraph_fragments.extend(
                                node.text or ""
                                for node in shape.findall(".//a:t", namespaces)
                            )
                self.assertEqual("".join(paragraph_fragments), long_text)

    def test_geometry_fidelity_is_distinct_page_mapped_and_fail_closed(self) -> None:
        with ConversionWorkspace() as workspace:
            with self.assertRaisesRegex(
                RENDER.ConversionError, "fidelity_mode GEOMETRY_AWARE"
            ):
                render(
                    workspace,
                    "PPTX",
                    output_name="out/rejected-fidelity.pptx",
                    profile="VISUAL_FIDELITY_BEST_EFFORT",
                    intent="VISUAL_FIDELITY",
                )

            geometry = workspace.canonical()
            geometry["fidelity_mode"] = "GEOMETRY_AWARE"
            boxes = [
                (36, 30, 540, 50),
                (36, 100, 540, 80),
                (36, 210, 540, 160),
                (36, 400, 200, 150),
                (36, 570, 300, 35),
            ]
            for block, (x, y, width, height) in zip(geometry["blocks"], boxes):
                block["provenance"]["geometry_status"] = "CAPTURED"
                block["provenance"]["bounding_box"] = {
                    "coordinate_system": "PDF_POINT",
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                    "page_width": 612,
                    "page_height": 792,
                }
            canonical_name = workspace.write_canonical(geometry, "geometry.json")
            render(
                workspace,
                "PPTX",
                canonical_name=canonical_name,
                output_name="out/geometry.pptx",
                profile="VISUAL_FIDELITY_BEST_EFFORT",
                intent="VISUAL_FIDELITY",
            )
            render(
                workspace,
                "PPTX",
                canonical_name=canonical_name,
                output_name="out/editable-from-geometry.pptx",
                profile="EDITABLE_PRESENTATION",
                intent="PRESENTATION",
            )
            self.assertNotEqual(
                (workspace.root / "out/geometry.pptx").read_bytes(),
                (workspace.root / "out/editable-from-geometry.pptx").read_bytes(),
            )
            geometry_run = json.loads(
                (
                    workspace.root
                    / "out/geometry.pptx.conversion-run.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(geometry_run["request"]["output_format"], "PPTX")
            self.assertEqual(
                geometry_run["request"]["output_profile"],
                "VISUAL_FIDELITY_BEST_EFFORT",
            )
            self.assertEqual(
                geometry_run["request"]["presentation_intent"],
                "VISUAL_FIDELITY",
            )
            with zipfile.ZipFile(workspace.root / "out/geometry.pptx") as archive:
                slides = [
                    name for name in archive.namelist() if re_full_slide_name(name)
                ]
                self.assertEqual(slides, ["ppt/slides/slide1.xml"])
                payload = archive.read(slides[0]).decode("utf-8")
                self.assertNotIn('<a:off x="500000" y="300000"/>', payload)
                for x, y, width, height in re.findall(
                    r'<a:off x="([0-9]+)" y="([0-9]+)"/><a:ext cx="([0-9]+)" cy="([0-9]+)"/>',
                    payload,
                ):
                    self.assertLessEqual(int(x) + int(width), RENDER.SLIDE_WIDTH)
                    self.assertLessEqual(int(y) + int(height), RENDER.SLIDE_HEIGHT)

            missing = copy.deepcopy(geometry)
            missing["blocks"][0]["provenance"]["geometry_status"] = "NOT_AVAILABLE"
            missing["blocks"][0]["provenance"]["bounding_box"] = None
            missing_name = workspace.write_canonical(
                missing, "missing-geometry.json"
            )
            with self.assertRaisesRegex(RENDER.ConversionError, "validation failed"):
                render(
                    workspace,
                    "PPTX",
                    canonical_name=missing_name,
                    output_name="out/missing-geometry.pptx",
                    profile="VISUAL_FIDELITY_BEST_EFFORT",
                    intent="VISUAL_FIDELITY",
                )


def re_full_slide_name(name: str) -> bool:
    parts = name.split("/")
    return (
        len(parts) == 3
        and parts[:2] == ["ppt", "slides"]
        and parts[2].startswith("slide")
        and parts[2].endswith(".xml")
        and parts[2][5:-4].isdigit()
    )


if __name__ == "__main__":
    unittest.main()
