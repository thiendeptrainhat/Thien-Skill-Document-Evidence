"""Candidate-aware packaged acceptance oracle for release 1.2.1.

The historical 1.1.0 and 1.2.0 suites remain byte-pinned. This suite binds the
current 1.2.1 release configuration to the generated checksum inventory,
reperforms package-native workflows, and constrains the core delta from the
frozen 1.2.0 release to the explicitly reviewed identity files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
import unittest
from unittest import mock

from tests import package_workflow_harness as frozen
from tests import test_release_120 as release_120


RELEASE = "1.2.1"
DISPLAY_NAME = "Thiện's Skill — Document Intelligence & Reconciliation"
ARCHIVE_TIMESTAMP = (2026, 9, 2, 0, 0, 0)
CANDIDATE_ARCHIVES = {
    "openai": "1.2.1/Thien-Skill-Document-Evidence-OpenAI-v1.2.1.zip",
    "claude": "1.2.1/Thien-Skill-Document-Evidence-Claude-v1.2.1.zip",
    "universal": "1.2.1/Thien-Skill-Document-Evidence-Universal-v1.2.1.zip",
}
CANDIDATE_DISTRIBUTION = {
    "INSTALLATION.md",
    "ACCEPTANCE-REPORT-v1.2.1.md",
    "LEGAL-REVIEW-v1.2.1.md",
}
INTENDED_CORE_CHANGES_FROM_120 = {
    "LICENSE-APPLICATION.md",
    "NOTICE",
    "SKILL.md",
    "THIRD-PARTY-NOTICES.md",
    "VERSION",
    "assets/brand/PROVENANCE.md",
    "registry/skill-registry-entry.yaml",
}


def checksum_inventory(path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if name in inventory:
            raise AssertionError(f"duplicate checksum entry: {name}")
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise AssertionError(f"invalid SHA-256 checksum entry: {name}")
        inventory[name] = digest
    return inventory


class Release121WorkflowTests(frozen.Phase3PackagedWorkflowTests):
    @classmethod
    def setUpClass(cls) -> None:
        config = frozen.read_json(frozen.REPOSITORY / "build/config.json")
        expected_config = {
            "version": RELEASE,
            "release_date": "2026-09-02",
            "display_name": DISPLAY_NAME,
            "artifact_names": {
                platform: relative.split("/", 1)[1]
                for platform, relative in CANDIDATE_ARCHIVES.items()
            },
            "distribution_files": sorted(CANDIDATE_DISTRIBUTION),
        }
        if config["version"] != expected_config["version"]:
            raise AssertionError("current build configuration is not release 1.2.1")
        if config["release_date"] != expected_config["release_date"]:
            raise AssertionError("release 1.2.1 has an unexpected archive date")
        if config["display_name"] != expected_config["display_name"]:
            raise AssertionError("release 1.2.1 has an unexpected display name")
        if config["artifact_names"] != expected_config["artifact_names"]:
            raise AssertionError("release 1.2.1 artifact names changed")
        if sorted(config["distribution_files"]) != expected_config["distribution_files"]:
            raise AssertionError("release 1.2.1 distribution files changed")
        if config["preserved_dist_versions"] != ["1.0.0", "1.1.0", "1.2.0"]:
            raise AssertionError("required frozen predecessor releases are not preserved")
        if (frozen.REPOSITORY / "VERSION").read_text(encoding="ascii").strip() != RELEASE:
            raise AssertionError("current repository VERSION is not 1.2.1")

        release_root = frozen.DIST / RELEASE
        checksum_path = release_root / "SHA256SUMS"
        if not checksum_path.is_file():
            raise AssertionError("release 1.2.1 candidate distribution has not been built")
        inventory = checksum_inventory(checksum_path)
        expected_names = {
            *(PurePosixPath(path).name for path in CANDIDATE_ARCHIVES.values()),
            "PARITY.json",
            "release-manifest.json",
        }
        if set(inventory) != expected_names:
            raise AssertionError("release 1.2.1 checksum inventory has unexpected/missing entries")
        for name, digest in inventory.items():
            if frozen.sha256((release_root / name).read_bytes()) != digest:
                raise AssertionError(f"release 1.2.1 checksum mismatch: {name}")

        parity = frozen.read_json(release_root / "PARITY.json")
        frozen_artifact_hashes = {
            relative: inventory[PurePosixPath(relative).name]
            for relative in CANDIDATE_ARCHIVES.values()
        }
        cls.candidate_inventory = inventory
        patcher = mock.patch.multiple(
            frozen,
            RELEASE=RELEASE,
            CORE_SHA256=parity["core_sha256"],
            FROZEN_SHA256=frozen_artifact_hashes,
            ARCHIVE_NAMES=dict(CANDIDATE_ARCHIVES),
            DISTRIBUTION_FILES=set(CANDIDATE_DISTRIBUTION),
            ARCHIVE_TIMESTAMP=ARCHIVE_TIMESTAMP,
            WORKFLOW_READINESS_STATUS="READY_FOR_HUMAN_REVIEW",
            ROLE_SHEETS=frozen.ROLE_SHEETS | {"ROLE_A", "ROLE_B"},
        )
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        super().setUpClass()

    def assert_reconciliation_provenance(self, manifest, result, package) -> None:
        self.assertEqual(manifest["schema_version"], "1.0.0")
        self.assertEqual(manifest["skill_release_version"], RELEASE)
        self.assertEqual(manifest["tool_version"], "1.0.0")
        self.assertEqual(result["schema_version"], "1.0.0")
        self.assertEqual(result["run_manifest"]["tool_version"], "1.0.0")
        self.assertEqual(package["schema_version"], "1.0.0")
        self.assertEqual(package["skill_version"], "1.0.0")
        self.assertNotIn("skill_release_version", package)
        self.assertEqual(
            package["run_manifest"]["tool_versions"]["thien-record-reconciler"],
            "1.0.0",
        )
        self.assertEqual(
            package["run_manifest"]["tool_versions"][
                "thien-skill-document-evidence"
            ],
            RELEASE,
        )

    def workflow(self, platform, root, profile, documents, policy=None):
        workflow = super().workflow(platform, root, profile, documents, policy)
        _, manifest, result, package, _, _ = workflow
        self.assertEqual(manifest["status"], "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(package["status"], "READY_FOR_HUMAN_REVIEW")
        self.assert_reconciliation_provenance(manifest, result, package)
        return workflow

    def test_frozen_hashes_embedded_manifests_and_exact_core_parity(self) -> None:
        self.assertEqual(
            checksum_inventory(frozen.DIST / "1.2.1/SHA256SUMS"),
            self.candidate_inventory,
        )
        release = frozen.read_json(frozen.DIST / "1.2.1/release-manifest.json")
        parity = frozen.read_json(frozen.DIST / "1.2.1/PARITY.json")
        self.assertEqual(
            set(release),
            {
                "artifact_directory", "artifacts", "canonical_file_count", "canonical_sha256",
                "canonical_source", "display_name", "license", "parity",
                "release_date", "repository_status", "schema_version",
                "skill_id", "status", "version",
            },
        )
        self.assertEqual(
            set(parity),
            {
                "adapters", "canonical_only", "core_file_count", "core_sha256",
                "distribution_files", "ignored_generated_files", "schema_version",
                "skill_id", "status", "version",
            },
        )
        self.assertEqual(release["version"], RELEASE)
        self.assertEqual(release["release_date"], "2026-09-02")
        self.assertEqual(release["display_name"], DISPLAY_NAME)
        self.assertEqual(release["artifact_directory"], "dist/1.2.1")
        self.assertEqual(release["schema_version"], 1)
        self.assertEqual(parity["version"], RELEASE)
        self.assertEqual(parity["schema_version"], 1)
        self.assertEqual(parity["status"], "PASS")
        self.assertEqual(parity["core_file_count"], 87)
        self.assertEqual(parity["core_sha256"], frozen.CORE_SHA256)
        self.assertEqual(set(parity["distribution_files"]), CANDIDATE_DISTRIBUTION)
        self.assertEqual(release["parity"], {
            "core_sha256": frozen.CORE_SHA256,
            "path": "PARITY.json",
            "status": "PASS",
        })

        canonical = {
            path.relative_to(frozen.REPOSITORY / frozen.SKILL_ID).as_posix(): path.read_bytes()
            for path in sorted((frozen.REPOSITORY / frozen.SKILL_ID).rglob("*"))
            if path.is_file()
        }
        self.assertEqual(len(canonical), 88)
        self.assertEqual(release["canonical_file_count"], len(canonical))
        self.assertEqual(release["canonical_sha256"], frozen.tree_digest(canonical))

        cores = {}
        self.assertEqual(
            {item["platform"] for item in release["artifacts"]},
            set(frozen.PLATFORMS),
        )
        for platform, package in self.packages.items():
            with self.subTest(platform=platform):
                entry = next(
                    item for item in release["artifacts"]
                    if item["platform"] == platform
                )
                relative = CANDIDATE_ARCHIVES[platform]
                filename = PurePosixPath(relative).name
                self.assertEqual(
                    set(entry),
                    {
                        "file_count", "format", "path", "platform",
                        "root_layout", "sha256", "size_bytes",
                    },
                )
                self.assertEqual(entry["path"], filename)
                self.assertEqual(entry["format"], frozen.PACKAGE_FORMATS[platform])
                self.assertEqual(entry["sha256"], self.candidate_inventory[filename])
                self.assertEqual(entry["size_bytes"], (frozen.DIST / relative).stat().st_size)
                self.assertEqual(entry["file_count"], frozen.PACKAGE_FILE_COUNTS[platform])
                self.assertEqual(package.manifest["version"], RELEASE)
                self.assertEqual(package.manifest["core_sha256"], frozen.CORE_SHA256)
                self.assertEqual((package.skill / "VERSION").read_text().strip(), RELEASE)
                if platform != "universal":
                    adapter = (
                        ".codex-plugin/plugin.json"
                        if platform == "openai"
                        else ".claude-plugin/plugin.json"
                    )
                    self.assertEqual(frozen.read_json(package.root / adapter)["version"], RELEASE)
                core = {
                    name: (package.skill / name).read_bytes()
                    for name in frozen.tree_hashes(package.skill)
                    if not name.startswith("agents/")
                    and name != "PACKAGE-MANIFEST.json"
                    and name not in CANDIDATE_DISTRIBUTION
                }
                self.assertEqual(len(core), 87)
                self.assertEqual(frozen.tree_digest(core), frozen.CORE_SHA256)
                cores[platform] = {
                    name: frozen.sha256(data) for name, data in core.items()
                }
        self.assert_same_outputs(cores)

    def test_candidate_core_matches_source_and_explicit_frozen_120_delta(self) -> None:
        source_root = frozen.REPOSITORY / frozen.SKILL_ID
        source_core = {
            path.relative_to(source_root).as_posix(): path.read_bytes()
            for path in sorted(source_root.rglob("*"))
            if path.is_file()
            and not path.relative_to(source_root).as_posix().startswith("agents/")
            and path.relative_to(source_root).as_posix() not in CANDIDATE_DISTRIBUTION
        }
        self.assertEqual(len(source_core), 87)
        for platform, package in self.packages.items():
            with self.subTest(platform=platform):
                current_core = {
                    path: (package.skill / path).read_bytes()
                    for path in frozen.tree_hashes(package.skill)
                    if not path.startswith("agents/")
                    and path != "PACKAGE-MANIFEST.json"
                    and path not in CANDIDATE_DISTRIBUTION
                }
                self.assertEqual(current_core, source_core)

                old_relative = release_120.FROZEN_120_ARCHIVES[platform]
                with mock.patch.object(
                    frozen, "ARCHIVE_TIMESTAMP", (2026, 9, 1, 0, 0, 0)
                ):
                    old_files = frozen.safe_archive_payload(
                        frozen.DIST / old_relative,
                        release_120.FROZEN_120_SHA256[old_relative],
                    )
                prefix = "" if platform == "universal" else f"skills/{frozen.SKILL_ID}/"
                old_core = {
                    path[len(prefix):]: payload
                    for path, payload in old_files.items()
                    if path.startswith(prefix)
                    and not path[len(prefix):].startswith("agents/")
                    and path[len(prefix):] != "PACKAGE-MANIFEST.json"
                    and path[len(prefix):] not in release_120.FROZEN_120_DISTRIBUTION
                }
                self.assertEqual(set(current_core), set(old_core))
                changed = {
                    path for path in current_core
                    if current_core[path] != old_core[path]
                }
                self.assertEqual(changed, INTENDED_CORE_CHANGES_FROM_120)
                for path in current_core.keys() - INTENDED_CORE_CHANGES_FROM_120:
                    self.assertEqual(
                        hashlib.sha256(current_core[path]).hexdigest(),
                        hashlib.sha256(old_core[path]).hexdigest(),
                        path,
                    )

    def test_packaged_contract_po_grn_invoice_bank_payment_exact(self) -> None:
        case = (
            [
                frozen.synthetic_document(
                    "CONTRACT-000009", "CONTRACT", contract_number="000009",
                    price="500", currency="VND", effective_date="2026-08-01",
                    item_code="000045", quantity="10",
                ),
                frozen.synthetic_document(
                    "GRN-000777", "GOODS_RECEIPT", contract_number="000009",
                    receipt_date="2026-08-05", item_code="000045",
                    delivered_quantity="10",
                ),
                frozen.synthetic_document(
                    "INV-000888", "INVOICE", contract_number="000009",
                    invoice_number="000888", invoice_date="2026-08-06",
                    item_code="000045", quantity="10", total_amount="500",
                    currency="VND", seller_bank_account="000000123456",
                    description=frozen.FORMULA_TEXT,
                ),
                frozen.synthetic_document(
                    "BANK-000888", "BANK_TRANSACTION",
                    transaction_reference="000888",
                    booking_date="2026-08-07", signed_amount="500",
                    transaction_currency="VND", counterparty_account="000000123456",
                ),
            ],
            {"contract-to-grn", "grn-to-invoice", "invoice-to-bank"},
            {
                "CONTRACT_BASE": "CONTRACT_BASE",
                "GRN": "GOODS_RECEIPTS",
                "INVOICE": "INVOICES",
                "BANK_TRANSACTION": "BANK_TRANSACTIONS",
            },
            {
                "CONTRACT_BASE": {"base_number": "000009", "amount": "500"},
                "GRN": {"base_number": "000009", "quantity": "10"},
                "INVOICE": {
                    "base_number": "000009", "invoice_number": "000888",
                    "amount": "500", "bank_account": "000000123456",
                },
                "BANK_TRANSACTION": {
                    "invoice_number": "000888", "amount": "500",
                    "bank_account": "000000123456",
                },
            },
        )
        with mock.patch.object(frozen, "exact_reconciliation_case", return_value=case):
            self.exact_profile("CONTRACT_PO_GRN_INVOICE_BANK_PAYMENT")

    def test_packaged_custom_n_way_template_exact(self) -> None:
        case = (
            [
                frozen.synthetic_document(
                    "CUSTOM-A-000123", "CUSTOM_SOURCE_A", reference_id="000123",
                    amount="500", currency="VND", description=frozen.FORMULA_TEXT,
                ),
                frozen.synthetic_document(
                    "CUSTOM-B-000123", "CUSTOM_SOURCE_B", reference_id="000123",
                    amount="500", currency="VND",
                ),
            ],
            {"role-a-to-role-b"},
            {"ROLE_A": "ROLE_A", "ROLE_B": "ROLE_B"},
            {
                "ROLE_A": {"reference_id": "000123", "amount": "500"},
                "ROLE_B": {"reference_id": "000123", "amount": "500"},
            },
        )
        with mock.patch.object(frozen, "exact_reconciliation_case", return_value=case):
            self.exact_profile("CUSTOM_N_WAY")

    def test_package_native_missing_required_role_is_blocked(self) -> None:
        snapshots = {}
        documents = [frozen.fixture_document("pr")]
        for platform in frozen.PLATFORMS:
            with self.subTest(platform=platform):
                root = self.workspace(platform, "missing-required-role")
                frozen.write_json(root / "documents.json", {"documents": documents})
                completed = self.run_helper(
                    platform,
                    root,
                    "prepare_reconciliation_workbook.py",
                    "--profile-id", "PR_PO",
                    "--input", "documents.json",
                    "--output-dir", "workflow",
                )
                summary = json.loads(completed.stdout)
                output = root / "workflow"
                manifest = frozen.read_json(output / "workflow-manifest.json")
                result = frozen.read_json(output / "reconciliation-result.json")
                package = frozen.read_json(output / "workbook-package.json")
                issue_codes = {
                    issue["issue_code"] for issue in manifest["preparation_issues"]
                }
                self.assertIn("MISSING_REQUIRED_ROLE", issue_codes)
                self.assertEqual(summary["status"], "BLOCKED")
                self.assertEqual(manifest["status"], "BLOCKED")
                self.assertEqual(package["status"], "BLOCKED")
                self.assert_reconciliation_provenance(manifest, result, package)
                self.assertEqual(
                    frozen.read_json(output / "workbook-package.validation.json")["status"],
                    "PASS",
                )
                self.validate_output(
                    platform,
                    root,
                    "workflow/workbook-package.json",
                    "extraction-package.schema.json",
                )
                snapshots[platform] = frozen.tree_hashes(output)
        self.assert_same_outputs(snapshots)


if __name__ == "__main__":
    unittest.main()
