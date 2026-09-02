"""Reperform package-native oracles for the frozen final 1.1.0 identity.

The retired RC2 artifact is no longer required at runtime. The 1.1.0 release
remains protected by literal checksums, canonical/core digests, and the full
workflow harness.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from unittest import mock

from tests import package_workflow_harness as frozen


RC2_DISTRIBUTION = {
    "INSTALLATION.md",
    "ACCEPTANCE-REPORT-v1.1.0-rc.2.md",
    "LEGAL-REVIEW-v1.1.0-rc.2.md",
}
FINAL_DISTRIBUTION = {
    "INSTALLATION.md", "ACCEPTANCE-REPORT-v1.1.0.md", "LEGAL-REVIEW-v1.1.0.md",
}
FROZEN_110_ARCHIVES = {
    "openai": "1.1.0/Thien-Skill-Document-Evidence-OpenAI-v1.1.0.zip",
    "claude": "1.1.0/Thien-Skill-Document-Evidence-Claude-v1.1.0.zip",
    "universal": "1.1.0/Thien-Skill-Document-Evidence-Universal-v1.1.0.zip",
}
FROZEN_110_SHA256 = {
    "1.1.0/PARITY.json":
        "fb9624043201110d8e5ba3b3794ec1485fb95f01be4887941954ac6885b350e7",
    "1.1.0/Thien-Skill-Document-Evidence-Claude-v1.1.0.zip":
        "eba9cba922f72bc4205b046d0ced096874ab429268fef2c0cb45e4e863c13261",
    "1.1.0/Thien-Skill-Document-Evidence-OpenAI-v1.1.0.zip":
        "6d9033446f2b3e53d208dba11fc09f6ba90892fc4f3ce01a9b5155def23bf319",
    "1.1.0/release-manifest.json":
        "6c71cd4d41ca6661ddeb915870d2e983e40586a16f16900c8d14941ae5d722f2",
    "1.1.0/Thien-Skill-Document-Evidence-Universal-v1.1.0.zip":
        "9af2c542a487484d0f26b090b9061f80836d386eb885ef1eb4946d95619b9aaa",
}
class FinalReleaseWorkflowTests(frozen.Phase3PackagedWorkflowTests):
    @classmethod
    def setUpClass(cls) -> None:
        archives = dict(FROZEN_110_ARCHIVES)
        expected_names = {
            *(PurePosixPath(path).name for path in archives.values()),
            "PARITY.json", "release-manifest.json",
        }
        inventory = {}
        for line in (frozen.DIST / "1.1.0/SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ", 1)
            if name in inventory:
                raise AssertionError(f"Duplicate checksum entry: {name}")
            inventory[name] = digest
        if set(inventory) != expected_names:
            raise AssertionError("Final checksum inventory has unexpected/missing entries")
        if inventory != {
            PurePosixPath(path).name: digest
            for path, digest in FROZEN_110_SHA256.items()
        }:
            raise AssertionError("Frozen 1.1.0 checksum inventory changed")
        parity = frozen.read_json(frozen.DIST / "1.1.0/PARITY.json")
        patcher = mock.patch.multiple(
            frozen, RELEASE="1.1.0", CORE_SHA256=parity["core_sha256"],
            FROZEN_SHA256=dict(FROZEN_110_SHA256), ARCHIVE_NAMES=archives,
            DISTRIBUTION_FILES=FINAL_DISTRIBUTION,
            ARCHIVE_TIMESTAMP=(2026, 8, 27, 0, 0, 0),
            WORKFLOW_READINESS_STATUS="READY_FOR_LIMITED_USE",
        )
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        super().setUpClass()

    def test_frozen_hashes_embedded_manifests_and_exact_core_parity(self) -> None:
        # The inherited version of this identity check intentionally names
        # RC2 report files literally. Keep its checks but select final paths.
        release = frozen.read_json(frozen.DIST / "1.1.0/release-manifest.json")
        self.assertEqual(release["version"], "1.1.0")
        cores = {}
        for platform, package in self.packages.items():
            with self.subTest(platform=platform):
                entry = next(item for item in release["artifacts"] if item["platform"] == platform)
                relative = frozen.ARCHIVE_NAMES[platform]
                self.assertEqual(entry["sha256"], frozen.FROZEN_SHA256[relative])
                self.assertEqual(entry["size_bytes"], (frozen.DIST / relative).stat().st_size)
                self.assertEqual(entry["file_count"], frozen.PACKAGE_FILE_COUNTS[platform])
                if platform != "universal":
                    adapter = ".codex-plugin/plugin.json" if platform == "openai" else ".claude-plugin/plugin.json"
                    self.assertEqual(frozen.read_json(package.root / adapter)["version"], "1.1.0")
                for helper in (
                    "render_canonical_artifacts.py", "build_rag_package.py",
                    "prepare_reconciliation_workbook.py", "reconcile_records.py", "validate_records.py",
                ):
                    self.assertTrue((package.skill / "scripts" / helper).is_file())
                self.assertEqual(len(list((package.skill / "assets/reconciliation-profiles").glob("*.json"))), 9)
                core = {
                    name: (package.skill / name).read_bytes()
                    for name in frozen.tree_hashes(package.skill)
                    if not name.startswith("agents/")
                    and name != "PACKAGE-MANIFEST.json" and name not in FINAL_DISTRIBUTION
                }
                self.assertEqual(len(core), 87)
                self.assertEqual(frozen.tree_digest(core), frozen.CORE_SHA256)
                self.assertEqual(package.manifest["core_sha256"], frozen.CORE_SHA256)
                cores[platform] = {name: frozen.sha256(data) for name, data in core.items()}
                self.assertFalse(any("HANDOFF.md" in name or "__pycache__" in name for name in package.original_hashes))
        self.assert_same_outputs(cores)

    def test_frozen_110_identity_and_report_names(self) -> None:
        for platform, package in self.packages.items():
            with self.subTest(platform=platform):
                self.assertEqual(package.manifest["version"], "1.1.0")
                self.assertNotIn("rc.", frozen.ARCHIVE_NAMES[platform])
                self.assertEqual(package.manifest["status"], "Testing")
                self.assertEqual((package.skill / "VERSION").read_text().strip(), "1.1.0")
                for filename in FINAL_DISTRIBUTION:
                    self.assertTrue((package.root / filename).is_file())
                for filename in RC2_DISTRIBUTION - FINAL_DISTRIBUTION:
                    self.assertFalse((package.root / filename).exists())

    def test_frozen_110_manifest_pins_canonical_identity(self) -> None:
        release = frozen.read_json(frozen.DIST / "1.1.0/release-manifest.json")
        parity = frozen.read_json(frozen.DIST / "1.1.0/PARITY.json")
        self.assertEqual(release["canonical_file_count"], 88)
        self.assertEqual(
            release["canonical_sha256"],
            "0dcf6c12e4e880fa54f3b8a67d99e6048796ac472d8eb2fece2274cd70fde88b",
        )
        self.assertEqual(parity["core_file_count"], 87)
        self.assertEqual(
            parity["core_sha256"],
            "7c67b20eba5c884289449f363b6c2b49ca0f05422e516a7c2cec20ce792c7c9c",
        )
