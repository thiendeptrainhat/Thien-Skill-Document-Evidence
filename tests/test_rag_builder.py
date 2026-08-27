"""Tests for the offline deterministic Phase 2 RAG package builder."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "thien-skill-document-evidence"
SCRIPT = SKILL / "scripts" / "build_rag_package.py"
FIXTURE = ROOT / "tests" / "fixtures" / "rag"


def load_builder():
    spec = importlib.util.spec_from_file_location("phase2_rag_builder", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import RAG builder from {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RAG = load_builder()


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class RagBuilderTests(unittest.TestCase):
    maxDiff = None

    def make_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        shutil.copytree(FIXTURE, root / "fixture")
        return temporary, root

    def build_alpha(self, root: Path, output: str = "output", *extra: str):
        return RAG.run(
            [
                "fixture/canonical-alpha.json",
                "--root",
                str(root),
                "--output",
                output,
                *extra,
            ]
        )

    def write_asset_variant(
        self,
        root: Path,
        *,
        canonical_name: str,
        reference: str,
        media_type: str,
        data: bytes,
    ) -> str:
        canonical = read_json(root / "fixture" / "canonical-alpha.json")
        image = next(
            block for block in canonical["blocks"] if block["block_type"] == "IMAGE"
        )
        image["asset_reference"] = reference
        image["media_type"] = media_type
        image["asset_checksum"]["digest"] = hashlib.sha256(data).hexdigest()
        asset = root / "fixture" / Path(*reference.split("/"))
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(data)
        path = root / "fixture" / canonical_name
        write_json(path, canonical)
        return f"fixture/{canonical_name}"

    def run_named_input(self, root: Path, canonical: str, output: str):
        return RAG.run(
            [
                canonical,
                "--root",
                str(root),
                "--output",
                output,
            ]
        )

    def assert_control_checksums(self, output: Path) -> dict[str, object]:
        control = read_json(output / "rag-package.json")
        validator = RAG.InternalSchemaValidator(RAG.RAG_SCHEMA, RAG.SCHEMA_ROOT)
        self.assertEqual(validator.validate(control), [])

        for document in control["documents"]:
            base = output / document["directory"]
            descriptors = [
                document["document_markdown"],
                document["metadata"],
                document["manifest"],
                *document["assets"],
            ]
            if document["chunks"] is not None:
                descriptors.append(document["chunks"])
            for descriptor in descriptors:
                target = base / descriptor["path"]
                self.assertTrue(target.is_file(), target)
                self.assertEqual(
                    hashlib.sha256(target.read_bytes()).hexdigest(),
                    descriptor["checksum"]["digest"],
                )

            inventory = read_json(base / "manifest.json")
            inventory_paths = {record["path"] for record in inventory["files"]}
            self.assertNotIn("manifest.json", inventory_paths)
            self.assertNotIn("rag-package.json", inventory_paths)
            self.assertEqual(
                inventory["checksum_scope"],
                "PAYLOAD_FILES_EXCLUDING_THIS_MANIFEST_AND_RAG_PACKAGE_CONTROL",
            )
            for record in inventory["files"]:
                target = base / record["path"]
                self.assertEqual(
                    hashlib.sha256(target.read_bytes()).hexdigest(),
                    record["checksum"]["digest"],
                )

        if control["package_kind"] == "COLLECTION":
            descriptor = control["collection_manifest"]
            target = output / descriptor["path"]
            self.assertEqual(
                hashlib.sha256(target.read_bytes()).hexdigest(),
                descriptor["checksum"]["digest"],
            )
        return control

    def test_cli_help_documents_offline_controls(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--help"],
            cwd=ROOT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("deterministic offline RAG source package", completed.stdout)
        self.assertIn("--dry-run", completed.stdout)
        self.assertIn("--overwrite", completed.stdout)
        self.assertIn("--chunk-config", completed.stdout)

    def test_document_build_is_deterministic_and_every_checksum_verifies(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)

        first = self.build_alpha(root, "out-a")
        second = self.build_alpha(root, "out-b")
        self.assertEqual(first["status"], "WRITTEN")
        self.assertEqual(first["package_id"], second["package_id"])
        self.assertEqual(tree_bytes(root / "out-a"), tree_bytes(root / "out-b"))

        control = self.assert_control_checksums(root / "out-a")
        self.assertEqual(control["package_kind"], "DOCUMENT")
        self.assertEqual(control["status"], "PASS")
        self.assertEqual(
            control["skill_release_version"],
            (SKILL / "VERSION").read_text(encoding="utf-8").strip(),
        )
        self.assertIsNone(control["collection_manifest"])
        document = control["documents"][0]
        self.assertIsNone(document["chunks"])
        self.assertFalse((root / "out-a" / document["directory"] / "chunks.jsonl").exists())

        document_root = root / "out-a" / document["directory"]
        markdown = (document_root / "document.md").read_text(encoding="utf-8")
        self.assertIn("Generated source locator", markdown)
        self.assertIn("00017", markdown)
        self.assertIn("| Reference | Amount |", markdown)
        self.assertEqual(
            (document_root / "assets" / "figure-001.svg").read_bytes(),
            (root / "fixture" / "assets" / "figure-001.svg").read_bytes(),
        )
        metadata = read_json(document_root / "metadata.json")
        self.assertEqual(metadata["document_id"], "doc-alpha-001")
        self.assertEqual(
            metadata["canonical"]["skill_release_version"], "1.1.0-rc.1"
        )
        self.assertEqual(
            metadata["builder"]["skill_release_version"],
            (SKILL / "VERSION").read_text(encoding="utf-8").strip(),
        )
        self.assertEqual(metadata["review_status"]["target_ingestion"], "NOT_TESTED")
        self.assertEqual(
            metadata["canonical"]["builder_semantic_validation_status"], "PASS"
        )

    def test_reused_asset_path_is_consolidated_with_all_source_blocks(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        canonical_path = root / "fixture" / "canonical-alpha.json"
        canonical = read_json(canonical_path)
        second_image = copy.deepcopy(canonical["blocks"][3])
        second_image["block_id"] = "alpha-image-002"
        second_image["reading_order"] = 5
        second_image["provenance"]["source_region"] = "page-2-image-2"
        canonical["blocks"][4]["reading_order"] = 6
        canonical["blocks"].insert(4, second_image)
        write_json(root / "fixture" / "canonical-reused-asset.json", canonical)

        RAG.run(
            [
                "fixture/canonical-reused-asset.json",
                "--root",
                str(root),
                "--output",
                "reused-asset",
            ]
        )
        control = self.assert_control_checksums(root / "reused-asset")
        document = control["documents"][0]
        self.assertEqual(len(document["assets"]), 1)
        document_root = root / "reused-asset" / document["directory"]
        metadata = read_json(document_root / "metadata.json")
        self.assertEqual(len(metadata["assets"]), 1)
        self.assertEqual(
            metadata["assets"][0]["source_block_ids"],
            ["alpha-image-001", "alpha-image-002"],
        )
        inventory = read_json(document_root / "manifest.json")
        asset_records = [
            record
            for record in inventory["files"]
            if record["path"] == "assets/figure-001.svg"
        ]
        self.assertEqual(len(asset_records), 1)
        self.assertEqual(
            asset_records[0]["source_block_ids"],
            ["alpha-image-001", "alpha-image-002"],
        )

    def test_chunks_require_explicit_target_and_config_and_are_stable(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)

        with self.assertRaisesRegex(
            RAG.RagBuildError, "--target-id and --chunk-config must be supplied together"
        ):
            self.build_alpha(root, "missing-config", "--target-id", "synthetic-target")
        with self.assertRaisesRegex(
            RAG.RagBuildError, "--target-id and --chunk-config must be supplied together"
        ):
            self.build_alpha(
                root,
                "missing-target",
                "--chunk-config",
                "fixture/chunk-config.json",
            )

        options = (
            "--target-id",
            "synthetic-target",
            "--chunk-config",
            "fixture/chunk-config.json",
        )
        self.build_alpha(root, "chunk-a", *options)
        self.build_alpha(root, "chunk-b", *options)
        self.assertEqual(tree_bytes(root / "chunk-a"), tree_bytes(root / "chunk-b"))
        control = self.assert_control_checksums(root / "chunk-a")
        document = control["documents"][0]
        descriptor = document["chunks"]
        self.assertEqual(descriptor["target_id"], "synthetic-target")
        self.assertEqual(
            descriptor["chunking_config_checksum"],
            hashlib.sha256((root / "fixture" / "chunk-config.json").read_bytes()).hexdigest(),
        )
        chunk_path = root / "chunk-a" / document["directory"] / "chunks.jsonl"
        records = [json.loads(line) for line in chunk_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 3)
        self.assertEqual([record["sequence"] for record in records], [1, 2, 3])
        self.assertTrue(all(record["source_locators"] for record in records))
        self.assertTrue(all(record["block_ids"] for record in records))
        self.assertTrue(all(record["token_count"] is None for record in records))

    def test_collection_build_has_verified_collection_and_document_manifests(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)

        result = RAG.run(
            [
                "fixture/canonical-beta.json",
                "fixture/canonical-alpha.json",
                "--root",
                str(root),
                "--output",
                "collection",
            ]
        )
        self.assertEqual(result["package_kind"], "COLLECTION")
        control = self.assert_control_checksums(root / "collection")
        self.assertEqual(
            [document["document_id"] for document in control["documents"]],
            ["doc-alpha-001", "doc-beta-001"],
        )
        collection = read_json(root / "collection" / "collection-manifest.json")
        self.assertEqual(collection["document_count"], 2)
        self.assertEqual(collection["ordering_basis"], "DOCUMENT_ID_ASCENDING")
        for entry in collection["documents"]:
            path = root / "collection" / entry["manifest_path"]
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                entry["manifest_checksum"]["digest"],
            )

    def test_dry_run_fully_validates_without_creating_output(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        result = self.build_alpha(root, "planned", "--dry-run")
        self.assertEqual(result["status"], "DRY_RUN")
        self.assertFalse((root / "planned").exists())
        self.assertEqual(result["validation"]["rag_package_schema"], "PASS")
        self.assertEqual(result["validation"]["descriptor_checksums"], "PASS")
        self.assertEqual(result["validation"]["live_target_ingestion"], "NOT_TESTED")
        self.assertGreater(result["file_count"], 3)

    def test_schema_and_semantic_failures_leave_no_partial_output(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        canonical_path = root / "fixture" / "canonical-alpha.json"

        missing = read_json(canonical_path)
        del missing["source_hash_status"]
        write_json(root / "fixture" / "missing.json", missing)
        with self.assertRaisesRegex(RAG.RagBuildError, "failed schema validation"):
            RAG.run(
                [
                    "fixture/missing.json",
                    "--root",
                    str(root),
                    "--output",
                    "missing-output",
                ]
            )
        self.assertFalse((root / "missing-output").exists())

        duplicate = read_json(canonical_path)
        duplicate["blocks"][1]["block_id"] = duplicate["blocks"][0]["block_id"]
        write_json(root / "fixture" / "duplicate.json", duplicate)
        with self.assertRaisesRegex(RAG.RagBuildError, "block_id values must be unique"):
            RAG.run(
                [
                    "fixture/duplicate.json",
                    "--root",
                    str(root),
                    "--output",
                    "duplicate-output",
                ]
            )
        self.assertFalse((root / "duplicate-output").exists())

        declared_failure = read_json(canonical_path)
        declared_failure["structural_validation_status"] = "FAIL"
        write_json(root / "fixture" / "declared-failure.json", declared_failure)
        with self.assertRaisesRegex(
            RAG.RagBuildError, "declares structural_validation_status"
        ):
            RAG.run(
                [
                    "fixture/declared-failure.json",
                    "--root",
                    str(root),
                    "--output",
                    "declared-failure-output",
                ]
            )

    def test_asset_checksum_path_and_active_svg_guards(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        canonical_path = root / "fixture" / "canonical-alpha.json"

        (root / "fixture" / "assets" / "figure-001.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RAG.RagBuildError, "asset checksum mismatch"):
            self.build_alpha(root, "bad-checksum")
        self.assertFalse((root / "bad-checksum").exists())

        shutil.copy2(FIXTURE / "assets" / "figure-001.svg", root / "fixture" / "assets" / "figure-001.svg")
        unsafe = read_json(canonical_path)
        unsafe["blocks"][3]["asset_reference"] = "../outside.svg"
        write_json(root / "fixture" / "unsafe-path.json", unsafe)
        with self.assertRaisesRegex(RAG.RagBuildError, "failed schema validation"):
            RAG.run(
                [
                    "fixture/unsafe-path.json",
                    "--root",
                    str(root),
                    "--output",
                    "unsafe-path-output",
                ]
            )

        active = read_json(canonical_path)
        active_bytes = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>\n'
        active_path = root / "fixture" / "assets" / "active.svg"
        active_path.write_bytes(active_bytes)
        active["blocks"][3]["asset_reference"] = "assets/active.svg"
        active["blocks"][3]["asset_checksum"]["digest"] = hashlib.sha256(active_bytes).hexdigest()
        write_json(root / "fixture" / "active.json", active)
        with self.assertRaisesRegex(RAG.RagBuildError, "prohibited SVG element"):
            RAG.run(
                [
                    "fixture/active.json",
                    "--root",
                    str(root),
                    "--output",
                    "active-output",
                ]
            )

    def test_symlink_inputs_assets_and_outputs_are_rejected(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)

        try:
            (root / "input-link.json").symlink_to(root / "fixture" / "canonical-alpha.json")
        except OSError as exc:
            self.skipTest(f"cannot create symlink: {exc}")
        with self.assertRaisesRegex(RAG.RagBuildError, "symlink"):
            RAG.run(
                [
                    "input-link.json",
                    "--root",
                    str(root),
                    "--output",
                    "linked-input-output",
                ]
            )

        victim = root / "victim"
        victim.mkdir()
        (root / "output-link").symlink_to(victim, target_is_directory=True)
        with self.assertRaisesRegex(RAG.RagBuildError, "symlink"):
            self.build_alpha(root, "output-link")

        asset = root / "fixture" / "assets" / "figure-001.svg"
        asset.unlink()
        asset.symlink_to(FIXTURE / "assets" / "figure-001.svg")
        with self.assertRaisesRegex(RAG.RagBuildError, "symlink"):
            self.build_alpha(root, "linked-asset-output")

    def test_no_overwrite_and_explicit_safe_overwrite(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        first = self.build_alpha(root, "output")
        original_tree = tree_bytes(root / "output")
        with self.assertRaisesRegex(RAG.RagBuildError, "output already exists"):
            self.build_alpha(root, "output")
        self.assertEqual(tree_bytes(root / "output"), original_tree)

        second = self.build_alpha(root, "output", "--overwrite")
        self.assertEqual(second["status"], "WRITTEN")
        self.assertEqual(second["package_id"], first["package_id"])
        self.assertEqual(tree_bytes(root / "output"), original_tree)

    def test_hardlink_and_input_output_collisions_are_rejected(self) -> None:
        if not hasattr(os, "link"):
            self.skipTest("hardlinks are unavailable")
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        canonical = root / "fixture" / "canonical-alpha.json"

        hardlink_output = root / "hardlink-output"
        try:
            os.link(canonical, hardlink_output)
        except OSError as exc:
            self.skipTest(f"cannot create hardlink: {exc}")
        with self.assertRaisesRegex(RAG.RagBuildError, "alias a protected input"):
            self.build_alpha(root, "hardlink-output", "--overwrite")

        existing = root / "existing-output"
        existing.mkdir()
        os.link(canonical, existing / "canonical-alias.json")
        with self.assertRaisesRegex(RAG.RagBuildError, "hardlink alias"):
            self.build_alpha(root, "existing-output", "--overwrite")

        asset_output = root / "asset-alias-output"
        asset_output.mkdir()
        os.link(
            root / "fixture" / "assets" / "figure-001.svg",
            asset_output / "asset-alias.svg",
        )
        with self.assertRaisesRegex(RAG.RagBuildError, "hardlink alias"):
            self.build_alpha(root, "asset-alias-output", "--overwrite")

        containing = root / "containing-output"
        containing.mkdir()
        shutil.copy2(canonical, containing / "input.json")
        with self.assertRaisesRegex(RAG.RagBuildError, "must not contain or replace"):
            RAG.run(
                [
                    "containing-output/input.json",
                    "--root",
                    str(root),
                    "--output",
                    "containing-output",
                    "--overwrite",
                ]
            )

        with self.assertRaisesRegex(RAG.RagBuildError, "must not contain or replace"):
            RAG.run(
                [
                    "fixture/canonical-alpha.json",
                    "--root",
                    str(root),
                    "--assets-root",
                    str(root / "fixture" / "assets"),
                    "--output",
                    "fixture/assets",
                    "--overwrite",
                ]
            )

    def test_duplicate_json_keys_and_invalid_chunk_config_are_rejected(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        duplicate_json = root / "fixture" / "duplicate-key.json"
        duplicate_json.write_text(
            '{"schema_version":"1.0.0","schema_version":"1.0.0"}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RAG.RagBuildError, "duplicate object key"):
            RAG.run(
                [
                    "fixture/duplicate-key.json",
                    "--root",
                    str(root),
                    "--output",
                    "duplicate-key-output",
                ]
            )

        config = read_json(root / "fixture" / "chunk-config.json")
        config["overlap_blocks"] = config["max_blocks_per_chunk"]
        write_json(root / "fixture" / "invalid-chunk-config.json", config)
        with self.assertRaisesRegex(RAG.RagBuildError, "overlap_blocks"):
            self.build_alpha(
                root,
                "invalid-chunk-output",
                "--target-id",
                "synthetic-target",
                "--chunk-config",
                "fixture/invalid-chunk-config.json",
            )

    def test_generated_paths_asset_prefix_and_prefix_collisions_are_reserved(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        original = read_json(root / "fixture" / "canonical-alpha.json")

        reserved = copy.deepcopy(original)
        reserved["blocks"][3]["asset_reference"] = "document.md"
        write_json(root / "fixture" / "reserved.json", reserved)
        with self.assertRaisesRegex(RAG.RagBuildError, "reserved generated path"):
            self.run_named_input(root, "fixture/reserved.json", "reserved-output")

        wrong_prefix = copy.deepcopy(original)
        wrong_prefix["blocks"][3]["asset_reference"] = "images/figure-001.svg"
        write_json(root / "fixture" / "wrong-prefix.json", wrong_prefix)
        with self.assertRaisesRegex(RAG.RagBuildError, "below the reserved assets/"):
            self.run_named_input(root, "fixture/wrong-prefix.json", "wrong-prefix-output")

        for name, second_reference in (
            ("prefix", "assets/figure-001.svg/child.svg"),
            ("case", "assets/Figure-001.svg"),
        ):
            with self.subTest(collision=name):
                collision = copy.deepcopy(original)
                second_image = copy.deepcopy(collision["blocks"][3])
                second_image["block_id"] = f"alpha-image-{name}"
                second_image["reading_order"] = 5
                second_image["asset_reference"] = second_reference
                collision["blocks"][4]["reading_order"] = 6
                collision["blocks"].insert(4, second_image)
                write_json(root / "fixture" / f"{name}-collision.json", collision)
                with self.assertRaisesRegex(RAG.RagBuildError, "collision"):
                    self.run_named_input(
                        root,
                        f"fixture/{name}-collision.json",
                        f"{name}-collision-output",
                    )

        reserved_directory = copy.deepcopy(original)
        reserved_directory["document_id"] = "rag-package.json"
        write_json(root / "fixture" / "reserved-directory.json", reserved_directory)
        with self.assertRaisesRegex(RAG.RagBuildError, "reserved control path"):
            self.run_named_input(
                root,
                "fixture/reserved-directory.json",
                "reserved-directory-output",
            )

        with self.assertRaisesRegex(RAG.RagBuildError, "file/directory-prefix collision"):
            RAG.add_file({"alpha": b"file"}, "alpha/child", b"child")
        with self.assertRaisesRegex(RAG.RagBuildError, "file/directory-prefix collision"):
            RAG.add_file({"alpha/child": b"child"}, "alpha", b"file")
        with self.assertRaisesRegex(RAG.RagBuildError, "exact or case-insensitive"):
            RAG.assert_path_set_has_no_collisions(
                ["document.md", "document.md"],
                label="document manifest inventory",
            )

    def test_media_extension_signature_and_binary_structure_are_fail_closed(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        svg = (root / "fixture" / "assets" / "figure-001.svg").read_bytes()

        extension_case = self.write_asset_variant(
            root,
            canonical_name="extension-mismatch.json",
            reference="assets/spoof.png",
            media_type="image/svg+xml",
            data=svg,
        )
        with self.assertRaisesRegex(RAG.RagBuildError, "does not match declared media_type"):
            self.run_named_input(root, extension_case, "extension-mismatch-output")

        def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
            return (
                len(payload).to_bytes(4, "big")
                + chunk_type
                + payload
                + (zlib.crc32(chunk_type + payload) & 0xFFFFFFFF).to_bytes(4, "big")
            )

        def png_bytes(width: int, height: int, compressed: bytes) -> bytes:
            ihdr = (
                width.to_bytes(4, "big")
                + height.to_bytes(4, "big")
                + bytes((8, 6, 0, 0, 0))
            )
            return (
                b"\x89PNG\r\n\x1a\n"
                + png_chunk(b"IHDR", ihdr)
                + png_chunk(b"IDAT", compressed)
                + png_chunk(b"IEND", b"")
            )

        cases = (
            (
                "png-signature",
                "assets/spoof.png",
                "image/png",
                svg,
                "PNG signature mismatch",
            ),
            (
                "png-truncated",
                "assets/truncated.png",
                "image/png",
                b"\x89PNG\r\n\x1a\ntruncated",
                "truncated PNG",
            ),
            (
                "png-invalid-idat",
                "assets/invalid-idat.png",
                "image/png",
                png_bytes(1, 1, b"not-a-zlib-stream"),
                "IDAT zlib stream is invalid",
            ),
            (
                "png-decompression-bomb",
                "assets/decompression-bomb.png",
                "image/png",
                png_bytes(1, 1, zlib.compress(b"\x00" * 1000)),
                "expands beyond the declared scanline size",
            ),
            (
                "png-invalid-filter",
                "assets/invalid-filter.png",
                "image/png",
                png_bytes(1, 1, zlib.compress(b"\x05\x00\x00\x00\x00")),
                "invalid PNG scanline filter byte",
            ),
            (
                "png-pixel-limit",
                "assets/pixel-limit.png",
                "image/png",
                png_bytes(100001, 1000, zlib.compress(b"")),
                "pixel count exceeds the bounded validation limit",
            ),
            (
                "jpeg-structure",
                "assets/spoof.jpg",
                "image/jpeg",
                b"\xff\xd8\xff\xd9",
                "lacks required SOF/SOS",
            ),
            (
                "webp-structure",
                "assets/spoof.webp",
                "image/webp",
                b"RIFF\x04\x00\x00\x00WEBP",
                "exactly one image payload",
            ),
        )
        for name, reference, media_type, data, expected in cases:
            with self.subTest(case=name):
                canonical = self.write_asset_variant(
                    root,
                    canonical_name=f"{name}.json",
                    reference=reference,
                    media_type=media_type,
                    data=data,
                )
                with self.assertRaisesRegex(RAG.RagBuildError, expected):
                    self.run_named_input(root, canonical, f"{name}-output")

        valid_png = png_bytes(1, 1, zlib.compress(b"\x00\x00\x00\x00\x00"))
        valid_canonical = self.write_asset_variant(
            root,
            canonical_name="valid-png.json",
            reference="assets/valid.png",
            media_type="image/png",
            data=valid_png,
        )
        valid_result = self.run_named_input(root, valid_canonical, "valid-png-output")
        self.assertEqual(valid_result["status"], "WRITTEN")

    def test_svg_namespace_element_event_href_and_css_pocs_are_rejected(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        cases = [
            (
                "namespaced-script",
                '<svg xmlns="http://www.w3.org/2000/svg" xmlns:e="urn:evil"><e:script/></svg>',
                "prohibited SVG element",
            ),
            (
                "foreign-namespace",
                '<svg xmlns="http://www.w3.org/2000/svg" xmlns:e="urn:evil"><e:g/></svg>',
                "foreign SVG element namespace",
            ),
            (
                "event-attribute",
                '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1" onload="alert(1)"/></svg>',
                "event attributes",
            ),
            (
                "namespaced-event",
                '<svg xmlns="http://www.w3.org/2000/svg" xmlns:e="urn:evil"><rect e:onload="alert(1)"/></svg>',
                "event attributes",
            ),
            (
                "external-href",
                '<svg xmlns="http://www.w3.org/2000/svg"><use href="https://example.invalid/a.svg"/></svg>',
                "href/src is prohibited",
            ),
            (
                "data-href",
                '<svg xmlns="http://www.w3.org/2000/svg"><use href="data:image/svg+xml;base64,AA=="/></svg>',
                "href/src is prohibited",
            ),
            (
                "javascript-href",
                '<svg xmlns="http://www.w3.org/2000/svg"><use href="javascript:alert(1)"/></svg>',
                "href/src is prohibited",
            ),
            (
                "css-import",
                '<svg xmlns="http://www.w3.org/2000/svg"><rect style="@import url(https://example.invalid/x.css)"/></svg>',
                "active or external SVG CSS",
            ),
            (
                "css-external-url",
                '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(https://example.invalid/a.svg)"/></svg>',
                "external SVG CSS url",
            ),
            (
                "css-data-url",
                '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(data:image/png;base64,AA==)"/></svg>',
                "external SVG CSS url",
            ),
            (
                "xml-stylesheet",
                '<?xml-stylesheet href="https://example.invalid/x.css"?><svg xmlns="http://www.w3.org/2000/svg"/>',
                "processing instructions",
            ),
        ]
        for element in ("foreignObject", "iframe", "object", "embed", "style"):
            cases.append(
                (
                    f"element-{element.casefold()}",
                    f'<svg xmlns="http://www.w3.org/2000/svg"><{element}/></svg>',
                    "prohibited SVG element",
                )
            )

        for name, svg_text, expected in cases:
            with self.subTest(case=name):
                canonical = self.write_asset_variant(
                    root,
                    canonical_name=f"svg-{name}.json",
                    reference=f"assets/{name}.svg",
                    media_type="image/svg+xml",
                    data=(svg_text + "\n").encode("utf-8"),
                )
                with self.assertRaisesRegex(RAG.RagBuildError, expected):
                    self.run_named_input(root, canonical, f"svg-{name}-output")

        safe_svg = b'''<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2">
  <defs><linearGradient id="safe"><stop offset="0" stop-color="#fff"/></linearGradient></defs>
  <rect width="2" height="2" fill="url(#safe)"/>
</svg>\n'''
        canonical = self.write_asset_variant(
            root,
            canonical_name="svg-safe-fragment.json",
            reference="assets/safe-fragment.svg",
            media_type="image/svg+xml",
            data=safe_svg,
        )
        result = self.run_named_input(root, canonical, "svg-safe-fragment-output")
        self.assertEqual(result["status"], "WRITTEN")

    def test_relative_assets_root_is_anchored_to_authorized_root(self) -> None:
        temporary, root = self.make_root()
        self.addCleanup(temporary.cleanup)
        result = RAG.run(
            [
                "fixture/canonical-alpha.json",
                "--root",
                str(root),
                "--assets-root",
                "fixture",
                "--output",
                "relative-assets-root-output",
            ]
        )
        self.assertEqual(result["status"], "WRITTEN")

        outside = root.parent / f"{root.name}-outside-assets"
        outside.mkdir(exist_ok=False)
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        with self.assertRaisesRegex(RAG.RagBuildError, "escapes authorized root"):
            RAG.run(
                [
                    "fixture/canonical-alpha.json",
                    "--root",
                    str(root),
                    "--assets-root",
                    str(outside),
                    "--output",
                    "outside-assets-root-output",
                ]
            )

        if hasattr(os, "symlink"):
            link = root / "linked-assets-root"
            try:
                link.symlink_to(root / "fixture", target_is_directory=True)
            except OSError:
                return
            with self.assertRaisesRegex(RAG.RagBuildError, "symlink"):
                RAG.run(
                    [
                        "fixture/canonical-alpha.json",
                        "--root",
                        str(root),
                        "--assets-root",
                        "linked-assets-root",
                        "--output",
                        "linked-assets-root-output",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
