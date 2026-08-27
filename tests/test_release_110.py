"""Reperform the existing packaged oracles for the final 1.1.0 identity.

RC2's test module and its pinned bytes remain unchanged. This subclass uses
the new release checksum inventory and separately limits core differences to
the six intended release-metadata files. No workflow assertions are relaxed.
"""

from __future__ import annotations

import hashlib
from unittest import mock

from tests import test_phase3_packaged_workflows as frozen


RC2_HASHES = dict(frozen.FROZEN_SHA256)
RC2_ARCHIVES = dict(frozen.ARCHIVE_NAMES)
RC2_DISTRIBUTION = set(frozen.DISTRIBUTION_FILES)
FINAL_DISTRIBUTION = {
    "INSTALLATION.md", "ACCEPTANCE-REPORT-v1.1.0.md", "LEGAL-REVIEW-v1.1.0.md",
}
METADATA_CHANGES = {
    "VERSION", "registry/skill-registry-entry.yaml", "LICENSE-APPLICATION.md",
    "NOTICE", "THIRD-PARTY-NOTICES.md", "assets/brand/PROVENANCE.md",
}


class FinalReleaseWorkflowTests(frozen.Phase3PackagedWorkflowTests):
    @classmethod
    def setUpClass(cls) -> None:
        config = frozen.read_json(frozen.REPOSITORY / "build/config.json")
        if config["version"] != "1.1.0":
            raise AssertionError("This acceptance suite is specifically for final 1.1.0")
        archives = {
            platform: f"{platform}/{config['artifact_names'][platform]}"
            for platform in frozen.PLATFORMS
        }
        expected_names = {
            *archives.values(), "PARITY-v1.1.0.json", "release-manifest-v1.1.0.json",
        }
        inventory = {}
        for line in (frozen.DIST / "SHA256SUMS-v1.1.0.txt").read_text().splitlines():
            digest, name = line.split("  ", 1)
            if name in inventory:
                raise AssertionError(f"Duplicate checksum entry: {name}")
            inventory[name] = digest
        if set(inventory) != expected_names:
            raise AssertionError("Final checksum inventory has unexpected/missing entries")
        parity = frozen.read_json(frozen.DIST / "PARITY-v1.1.0.json")
        patcher = mock.patch.multiple(
            frozen, RELEASE="1.1.0", CORE_SHA256=parity["core_sha256"],
            FROZEN_SHA256=inventory, ARCHIVE_NAMES=archives,
            DISTRIBUTION_FILES=FINAL_DISTRIBUTION,
        )
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        super().setUpClass()

    def test_frozen_hashes_embedded_manifests_and_exact_core_parity(self) -> None:
        # The inherited version of this identity check intentionally names
        # RC2 report files literally. Keep its checks but select final paths.
        release = frozen.read_json(frozen.DIST / "release-manifest-v1.1.0.json")
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

    def test_final_identity_and_current_report_names(self) -> None:
        self.assertEqual((frozen.REPOSITORY / "VERSION").read_text().strip(), "1.1.0")
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

    def test_final_core_only_changes_release_metadata(self) -> None:
        for platform, package in self.packages.items():
            with self.subTest(platform=platform):
                old_relative = RC2_ARCHIVES[platform]
                old_files = frozen.safe_archive_payload(
                    frozen.DIST / old_relative, RC2_HASHES[old_relative],
                )
                prefix = "" if platform == "universal" else f"skills/{frozen.SKILL_ID}/"
                old_core = {
                    path[len(prefix):]: payload
                    for path, payload in old_files.items()
                    if path.startswith(prefix)
                    and not path[len(prefix):].startswith("agents/")
                    and path[len(prefix):] != "PACKAGE-MANIFEST.json"
                    and path[len(prefix):] not in RC2_DISTRIBUTION
                }
                current_core = {
                    path: (package.skill / path).read_bytes()
                    for path in frozen.tree_hashes(package.skill)
                    if not path.startswith("agents/")
                    and path != "PACKAGE-MANIFEST.json"
                    and path not in FINAL_DISTRIBUTION
                }
                self.assertEqual(set(current_core), set(old_core))
                changed = {path for path in current_core if current_core[path] != old_core[path]}
                self.assertEqual(changed, METADATA_CHANGES)
                self.assertEqual(len(current_core), 87)
                for path in current_core.keys() - METADATA_CHANGES:
                    self.assertEqual(
                        hashlib.sha256(current_core[path]).hexdigest(),
                        hashlib.sha256(old_core[path]).hexdigest(),
                        path,
                    )
