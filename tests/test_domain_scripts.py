"""Behavioral tests for the deterministic document-evidence Python core."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
SKILL = REPOSITORY / "thien-skill-document-evidence"
SCRIPTS = SKILL / "scripts"
FIXTURES = REPOSITORY / "tests/fixtures"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


INVENTORY = load_module("document_inventory_core", SCRIPTS / "document_inventory.py")
VALIDATE = load_module("validate_records_core", SCRIPTS / "validate_records.py")
RECONCILE = load_module("reconcile_records_core", SCRIPTS / "reconcile_records.py")


class AtomicPublicationTestCase(unittest.TestCase):
    MODULES = (
        (INVENTORY, INVENTORY.InventoryError),
        (VALIDATE, VALIDATE.ValidationToolError),
        (RECONCILE, RECONCILE.ReconciliationError),
    )

    def test_no_overwrite_publication_is_atomic_against_destination_race(self) -> None:
        real_link = os.link
        for module, error_type in self.MODULES:
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory(
                prefix="atomic-publication-race-"
            ) as temporary:
                destination = Path(temporary) / "result.json"

                def racing_link(source, target, *args, **kwargs):
                    Path(target).write_bytes(b"racer-won\n")
                    return real_link(source, target, *args, **kwargs)

                with mock.patch.object(module.os, "link", side_effect=racing_link):
                    with self.assertRaisesRegex(error_type, "atomic publication"):
                        module.atomic_write(destination, b"must-not-overwrite\n", overwrite=False)
                self.assertEqual(destination.read_bytes(), b"racer-won\n")
                self.assertEqual([path.name for path in Path(temporary).iterdir()], ["result.json"])

    def test_atomic_publication_success_overwrite_and_inode_alias_guard(self) -> None:
        for module, error_type in self.MODULES:
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory(
                prefix="atomic-publication-success-"
            ) as temporary:
                root = Path(temporary)
                destination = root / "result.json"
                module.atomic_write(destination, b"first\n", overwrite=False)
                self.assertEqual(destination.read_bytes(), b"first\n")
                module.atomic_write(destination, b"second\n", overwrite=True)
                self.assertEqual(destination.read_bytes(), b"second\n")
                with self.assertRaises(error_type):
                    module.atomic_write(destination, b"third\n", overwrite=False)
                self.assertEqual(destination.read_bytes(), b"second\n")

                protected = root / "input.json"
                alias = root / "hardlink-output.json"
                protected.write_bytes(b"protected\n")
                os.link(protected, alias)
                with self.assertRaisesRegex(error_type, "alias"):
                    module.reject_output_alias(alias, (protected,))
                self.assertEqual(protected.read_bytes(), b"protected\n")
                self.assertEqual(alias.read_bytes(), b"protected\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_snapshot(path: Path) -> tuple[bytes, int, int]:
    stat_result = path.stat()
    return path.read_bytes(), stat_result.st_mtime_ns, stat_result.st_mode


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def approved_config() -> dict[str, object]:
    return load_fixture("reconciliation-config-approved.json")


def partial_records() -> dict[str, object]:
    return load_fixture("reconciliation-records.json")


class InventoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="document-inventory-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "authorized"
        self.root.mkdir()

    def test_inventory_is_deterministic_read_only_and_links_duplicate_content(self) -> None:
        pdf_bytes = (
            b"%PDF-1.7\n1 0 obj << /Type /Catalog /JavaScript /EmbeddedFile "
            b"/URI /Encrypt >> endobj\n%%EOF\n"
        )
        first = self.root / "a.pdf"
        second = self.root / "nested/b.pdf"
        second.parent.mkdir()
        first.write_bytes(pdf_bytes)
        second.write_bytes(pdf_bytes)
        before = {path: source_snapshot(path) for path in (first, second)}

        package_one = INVENTORY.build_inventory(self.root, ["."])
        package_two = INVENTORY.build_inventory(self.root, ["."])

        self.assertEqual(package_one, package_two)
        self.assertEqual(
            INVENTORY.serialize_package(package_one),
            INVENTORY.serialize_package(package_two),
        )
        self.assertEqual(package_one["summary"]["document_count"], 2)
        self.assertEqual(package_one["summary"]["unique_content_count"], 1)
        self.assertEqual(package_one["summary"]["duplicate_content_group_count"], 1)
        records = package_one["records"]
        self.assertNotEqual(records[0]["document_id"], records[1]["document_id"])
        self.assertEqual(records[0]["content_id"], records[1]["content_id"])
        self.assertEqual(records[0]["relationships"][0]["relationship_type"], "EXACT_DUPLICATE")
        for record in records:
            active = record["integrity"]["active_content"]
            self.assertEqual(active["javascript"], "DETECTED")
            self.assertEqual(active["embedded_files"], "DETECTED")
            self.assertEqual(active["external_links"], "DETECTED")
            self.assertTrue(record["integrity"]["encrypted"])
            self.assertEqual(record["integrity"]["processing_eligibility"], "AUTHORIZATION_REQUIRED")
            self.assertFalse(Path(record["file"]["source_reference"]).is_absolute())
        self.assertEqual(before, {path: source_snapshot(path) for path in (first, second)})

    def test_ooxml_active_content_and_unsafe_member_are_flagged_without_extraction(self) -> None:
        document = self.root / "active.docm"
        with zipfile.ZipFile(document, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")
            archive.writestr("word/vbaProject.bin", b"macro-bytes")
            archive.writestr(
                "word/_rels/document.xml.rels",
                '<Relationships><Relationship TargetMode="External" Target="https://example.invalid/x"/></Relationships>',
            )
            archive.writestr("../escape.bin", b"must-not-extract")
        before = source_snapshot(document)

        package = INVENTORY.build_inventory(self.root, ["active.docm"])
        record = package["records"][0]

        self.assertEqual(record["classification"]["document_type"], "OOXML_WORD")
        self.assertEqual(record["integrity"]["active_content"]["macro"], "DETECTED")
        self.assertEqual(record["integrity"]["active_content"]["external_links"], "DETECTED")
        self.assertIn("UNSAFE_ARCHIVE_MEMBER_PATH", record["security_flags"])
        self.assertEqual(record["integrity"]["processing_eligibility"], "BLOCKED")
        self.assertFalse((self.root.parent / "escape.bin").exists())
        self.assertEqual(before, source_snapshot(document))

    def test_symlink_and_path_escape_are_rejected(self) -> None:
        outside = Path(self.temporary.name) / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        link = self.root / "linked.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        with self.assertRaisesRegex(INVENTORY.InventoryError, "symlink"):
            INVENTORY.build_inventory(self.root, ["linked.txt"])
        with self.assertRaisesRegex(INVENTORY.InventoryError, "escapes authorized root"):
            INVENTORY.build_inventory(self.root, ["../outside.txt"])
        with self.assertRaisesRegex(INVENTORY.InventoryError, "escapes authorized root"):
            INVENTORY.resolve_output(self.root, outside)
        with self.assertRaisesRegex(INVENTORY.InventoryError, "symlink"):
            INVENTORY.resolve_output(self.root, link)
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside")

    def test_inventory_records_validate_against_bundled_document_schema(self) -> None:
        source = self.root / "reference.txt"
        source.write_text("reference data\n", encoding="utf-8")
        package = INVENTORY.build_inventory(self.root, ["reference.txt"])
        schema_root = SKILL / "schemas"
        validator = VALIDATE.InternalSchemaValidator(
            schema_root / "common/document-record.schema.json", schema_root
        )
        for record in package["records"]:
            self.assertEqual(validator.validate(record), [])


class ValidatorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="record-validator-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "authorized"
        self.root.mkdir()
        source = self.root / "record.txt"
        source.write_text("data\n", encoding="utf-8")
        self.package = INVENTORY.build_inventory(self.root, ["record.txt"])
        self.schema_root = SKILL / "schemas"
        self.validator = VALIDATE.InternalSchemaValidator(
            self.schema_root / "common/document-record.schema.json",
            self.schema_root,
        )

    def test_leading_zero_identifier_is_not_coerced_and_missing_field_is_clear(self) -> None:
        record = copy.deepcopy(self.package["records"][0])
        record["document_id"] = "000123"
        self.assertEqual(self.validator.validate(record), [])
        self.assertEqual(record["document_id"], "000123")

        del record["integrity"]
        errors = self.validator.validate(record)
        self.assertTrue(
            any(
                error["keyword"] == "required" and "integrity" in error["message"]
                for error in errors
            )
        )

    def test_report_is_deterministic_and_marks_invalid_record(self) -> None:
        valid = self.package["records"][0]
        invalid = copy.deepcopy(valid)
        invalid["file"]["size_bytes"] = -1
        records = [valid, invalid]
        input_bytes = VALIDATE.canonical_json_bytes({"records": records})
        schema_path = self.schema_root / "common/document-record.schema.json"
        schema_bytes = schema_path.read_bytes()
        first = VALIDATE.build_validation_report(
            input_bytes=input_bytes,
            schema_bytes=schema_bytes,
            records=records,
            record_path="$.records",
            validator=self.validator,
        )
        second = VALIDATE.build_validation_report(
            input_bytes=input_bytes,
            schema_bytes=schema_bytes,
            records=records,
            record_path="$.records",
            validator=self.validator,
        )
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "FAIL")
        self.assertEqual(first["summary"]["valid_count"], 1)
        self.assertTrue(any(error["keyword"] == "minimum" for error in first["errors"]))

    def test_package_hash_validation_rejects_mismatch_and_symlink(self) -> None:
        member = self.root / "member.json"
        member.write_text('{"ok":true}\n', encoding="utf-8")
        payload = {"files": {"member.json": sha256_file(member)}}
        self.assertEqual(VALIDATE.verify_package_files(payload, self.root), [])

        payload["files"]["member.json"] = "0" * 64
        errors = VALIDATE.verify_package_files(payload, self.root)
        self.assertTrue(any("mismatch" in error["message"] for error in errors))

        link = self.root / "member-link.json"
        try:
            link.symlink_to(member)
        except (OSError, NotImplementedError):
            return
        link_payload = {"files": {"member-link.json": sha256_file(member)}}
        errors = VALIDATE.verify_package_files(link_payload, self.root)
        self.assertTrue(any("symlink" in error["message"] for error in errors))


class ReconciliationTestCase(unittest.TestCase):
    def make_quantity_package(self, left: str, right: str, *, right_po: str = "000123"):
        return {
            "schema_version": "1.0.0",
            "records": [
                {
                    "record_id": "po-001",
                    "role": "PO",
                    "fields": {"po_number": "000123", "quantity": left, "currency": "VND"},
                },
                {
                    "record_id": "invoice-001",
                    "role": "INVOICE",
                    "fields": {"po_number": right_po, "quantity": right, "currency": "VND"},
                },
            ],
        }

    def test_approved_tolerance_is_applied_and_unapproved_is_not_passed(self) -> None:
        package = self.make_quantity_package("100.00", "100.04")
        config = approved_config()
        quantity = config["link_rules"][0]["components"][1]
        quantity["tolerance"]["value"] = "0.05"
        config["link_rules"][0]["cardinality"] = "ONE_TO_ONE"

        approved = RECONCILE.reconcile(package, config)
        self.assertEqual(approved["links"][0]["status"], "WITHIN_TOLERANCE")
        comparison = approved["links"][0]["comparisons"][1]
        self.assertEqual(comparison["difference"]["absolute"], "0.04")
        self.assertTrue(comparison["tolerance"]["applicable"])

        pending_config = copy.deepcopy(config)
        pending_config["human_approval"]["status"] = "PENDING"
        pending = RECONCILE.reconcile(package, pending_config)
        quantity_result = pending["pair_results"][0]["comparisons"][1]
        self.assertEqual(quantity_result["status"], "HUMAN_REVIEW_REQUIRED")
        self.assertEqual(quantity_result["reason_code"], "TOLERANCE_NOT_APPROVED")
        self.assertEqual(pending["links"], [])

        policy_pending = copy.deepcopy(config)
        policy_pending["link_rules"][0]["components"][1]["tolerance"][
            "approval_status"
        ] = "PENDING"
        pending = RECONCILE.reconcile(package, policy_pending)
        quantity_result = pending["pair_results"][0]["comparisons"][1]
        self.assertEqual(quantity_result["status"], "HUMAN_REVIEW_REQUIRED")
        self.assertEqual(quantity_result["reason_code"], "TOLERANCE_NOT_APPROVED")

    def test_partial_flow_and_allocation_are_explicit(self) -> None:
        package = partial_records()
        config = approved_config()
        result = RECONCILE.reconcile(package, config)

        self.assertEqual(result["status"], "PASS_WITH_WARNINGS")
        self.assertEqual(result["links"][0]["status"], "PARTIAL_MATCH")
        self.assertEqual(result["allocations"][0]["allocated_value"], "50.00")
        self.assertEqual(result["allocations"][0]["capacity_value"], "100.00")
        self.assertEqual(result["discrepancies"], [])

        pending = approved_config()
        pending["link_rules"][0]["partial_policy"]["approval_status"] = "PENDING"
        pending_result = RECONCILE.reconcile(package, pending)
        quantity = pending_result["pair_results"][0]["comparisons"][1]
        self.assertEqual(quantity["status"], "HUMAN_REVIEW_REQUIRED")
        self.assertEqual(quantity["reason_code"], "PARTIAL_POLICY_NOT_APPROVED")
        self.assertEqual(pending_result["links"], [])

    def test_partial_overallocation_requires_review(self) -> None:
        package = partial_records()
        second = copy.deepcopy(package["records"][1])
        second["record_id"] = "invoice-002"
        second["fields"]["quantity"] = "60.00"
        package["records"].append(second)
        result = RECONCILE.reconcile(package, approved_config())

        self.assertEqual(result["status"], "CONDITIONAL")
        self.assertTrue(
            any(
                discrepancy["discrepancy_code"] == "PARTIAL_OVER_ALLOCATION"
                for discrepancy in result["discrepancies"]
            )
        )
        self.assertTrue(
            all(link["status"] == "HUMAN_REVIEW_REQUIRED" for link in result["links"])
        )

    def test_declared_aggregation_controls_aggregated_partial_flow(self) -> None:
        package = partial_records()
        package["records"][1]["fields"]["quantity"] = "40.00"
        second = copy.deepcopy(package["records"][1])
        second["record_id"] = "invoice-002"
        second["fields"]["quantity"] = "60.00"
        package["records"].append(second)
        config = approved_config()
        config["aggregation_rules"] = [
            {
                "aggregation_id": "invoice-quantity-by-po",
                "role_id": "INVOICE",
                "group_by_fields": ["po_number"],
                "value_field": "quantity",
                "operation": "SUM_DECIMAL",
                "result_field": "invoice_quantity_total"
            }
        ]
        partial = config["link_rules"][0]["partial_policy"]
        partial["allowed_relation"] = "AGGREGATED_PARTIAL_WITHIN_BASE"
        partial["aggregation_id"] = "invoice-quantity-by-po"

        result = RECONCILE.reconcile(package, config)

        self.assertEqual(result["aggregations"][0]["value"], "100.00")
        self.assertEqual(len(result["links"]), 2)
        self.assertTrue(all(link["status"] == "PARTIAL_MATCH" for link in result["links"]))
        self.assertEqual(result["allocations"], [])

    def test_leading_zero_mismatch_missing_field_and_ambiguity_are_not_confirmed(self) -> None:
        config = approved_config()
        config["link_rules"][0]["cardinality"] = "ONE_TO_ONE"

        different_identifier = self.make_quantity_package("100.00", "100.00", right_po="123")
        result = RECONCILE.reconcile(different_identifier, config)
        self.assertEqual(result["links"], [])
        identifier_result = result["pair_results"][0]["comparisons"][0]
        self.assertEqual(identifier_result["status"], "CONFLICTING_MATCH")
        self.assertEqual(identifier_result["normalized_left"], "000123")
        self.assertEqual(identifier_result["normalized_right"], "123")

        missing = self.make_quantity_package("100.00", "100.00")
        del missing["records"][1]["fields"]["po_number"]
        missing_result = RECONCILE.reconcile(missing, config)
        self.assertEqual(
            missing_result["pair_results"][0]["comparisons"][0]["status"],
            "HUMAN_REVIEW_REQUIRED",
        )

        ambiguous = self.make_quantity_package("100.00", "100.00")
        extra = copy.deepcopy(ambiguous["records"][1])
        extra["record_id"] = "invoice-002"
        ambiguous["records"].append(extra)
        ambiguous_result = RECONCILE.reconcile(ambiguous, config)
        self.assertEqual(ambiguous_result["links"], [])
        self.assertTrue(
            any(
                discrepancy["discrepancy_code"] == "AMBIGUOUS_MATCH"
                for discrepancy in ambiguous_result["discrepancies"]
            )
        )

    def test_reconciliation_is_deterministic_and_does_not_mutate_inputs(self) -> None:
        package = partial_records()
        config = approved_config()
        original_package = copy.deepcopy(package)
        original_config = copy.deepcopy(config)
        first = RECONCILE.reconcile(package, config)
        second = RECONCILE.reconcile(package, config)
        self.assertEqual(first, second)
        self.assertEqual(package, original_package)
        self.assertEqual(config, original_config)

        prohibited_keys = {
            "fraud",
            "legal_conclusion",
            "authenticity_conclusion",
            "materiality_conclusion",
            "payment_release_decision",
        }

        def visit(value: object) -> None:
            if isinstance(value, dict):
                self.assertFalse(prohibited_keys.intersection(value))
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(first)

    def test_fuzzy_or_executable_configuration_is_rejected(self) -> None:
        config = approved_config()
        config["link_rules"][0]["components"][0]["comparator"] = "FUZZY_TEXT"
        with self.assertRaisesRegex(RECONCILE.ReconciliationError, "unsupported comparator"):
            RECONCILE.reconcile(partial_records(), config)

        config = approved_config()
        config["link_rules"][0]["components"][0]["sql"] = "SELECT 1"
        with self.assertRaisesRegex(RECONCILE.ReconciliationError, "unsupported keys"):
            RECONCILE.reconcile(partial_records(), config)

    def test_config_and_schema_native_results_validate_against_bundled_schemas(self) -> None:
        schema_root = SKILL / "schemas"
        config_validator = VALIDATE.InternalSchemaValidator(
            schema_root / "common/reconciliation-config.schema.json", schema_root
        )
        config = approved_config()
        self.assertEqual(config_validator.validate(config), [])

        result = RECONCILE.reconcile(partial_records(), config)
        result_validator = VALIDATE.InternalSchemaValidator(
            schema_root / "common/reconciliation-result.schema.json", schema_root
        )
        self.assertGreater(len(result["reconciliation_results"]), 0)
        for record in result["reconciliation_results"]:
            self.assertEqual(result_validator.validate(record), [])

    def test_bank_account_conflict_creates_contract_discrepancy_without_conclusion(self) -> None:
        config = approved_config()
        for role in config["roles"]:
            role["field_mappings"]["bank_account"] = "bank_account"
        config["link_rules"][0]["cardinality"] = "ONE_TO_ONE"
        config["link_rules"][0]["components"] = [
            {
                "component_id": "beneficiary-bank-account",
                "left_field": "bank_account",
                "right_field": "bank_account",
                "comparator": "IDENTIFIER_EXACT",
                "normalizers": ["IDENTIFIER_PRESERVE"],
                "required": True,
                "candidate_only": False,
                "tolerance": {
                    "status": "NOT_APPLICABLE",
                    "value": None,
                    "unit": "NOT_APPLICABLE",
                    "basis": None,
                    "owner": None,
                    "approval_reference": None,
                    "approval_status": "NOT_REQUESTED"
                }
            }
        ]
        config["link_rules"][0]["partial_policy"] = {
            "mode": "DISALLOW",
            "allowed_relation": "NOT_APPLICABLE",
            "aggregation_id": None,
            "basis": None,
            "owner": None,
            "approval_reference": None,
            "approval_status": "NOT_REQUESTED"
        }
        package = {
            "schema_version": "1.0.0",
            "package_id": "pkg-bank-conflict-001",
            "records": [
                {
                    "record_id": "invoice-bank-001",
                    "role": "PO",
                    "source_reference": "invoice/001.json",
                    "evidence_ids": ["evidence.invoice-bank-001"],
                    "fields": {"bank_account": "000045"}
                },
                {
                    "record_id": "master-bank-001",
                    "role": "INVOICE",
                    "source_reference": "master/vendor-001.json",
                    "fields": {"bank_account": "000046"}
                }
            ]
        }

        result = RECONCILE.reconcile(package, config)

        self.assertEqual(result["links"], [])
        self.assertTrue(
            any(
                item["discrepancy_code"] == "BANK_ACCOUNT_MISMATCH"
                for item in result["discrepancies"]
            )
        )
        self.assertEqual(len(result["discrepancy_register"]), 1)
        discrepancy = result["discrepancy_register"][0]
        self.assertEqual(discrepancy["discrepancy_type"], "BANK_ACCOUNT_MISMATCH")
        self.assertEqual(discrepancy["values"]["left"]["raw_value"], "000045")
        self.assertEqual(discrepancy["values"]["right"]["raw_value"], "000046")
        self.assertEqual(discrepancy["human_review_status"], "PENDING")
        self.assertEqual(discrepancy["validation_status"], "HUMAN_REVIEW_REQUIRED")

        schema_root = SKILL / "schemas"
        package_validator = VALIDATE.InternalSchemaValidator(
            schema_root / "common/extraction-package.schema.json", schema_root
        )
        canonical_package = RECONCILE.canonical_package_view(result)
        self.assertEqual(package_validator.validate(canonical_package), [])
        register_view = RECONCILE.select_output_view(result, "discrepancies")
        self.assertEqual(register_view["discrepancies"], [discrepancy])
        rendered = json.dumps(result, ensure_ascii=False).casefold()
        self.assertNotIn("fraud confirmed", rendered)
        self.assertNotIn("automatic payment block", rendered)

    def test_cli_atomic_write_no_overwrite_and_dry_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="reconciliation-cli-tests-") as temporary:
            root = Path(temporary)
            input_path = root / "records.json"
            config_path = root / "config.json"
            output_path = root / "result.json"
            dry_path = root / "dry-result.json"
            input_path.write_text(
                json.dumps(partial_records(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            config_path.write_text(
                json.dumps(approved_config(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            before = {path: source_snapshot(path) for path in (input_path, config_path)}
            command = [
                sys.executable,
                "-B",
                str(SCRIPTS / "reconcile_records.py"),
                "records.json",
                "config.json",
                "--root",
                str(root),
                "--output",
                "result.json",
            ]
            first = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_bytes = output_path.read_bytes()
            second = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(output_path.read_bytes(), first_bytes)

            collision = subprocess.run(
                command[:-1] + ["records.json", "--overwrite"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(collision.returncode, 2)
            self.assertIn("must not replace", collision.stderr)

            hardlink_output = root / "records-hardlink.json"
            os.link(input_path, hardlink_output)
            hardlink_collision = subprocess.run(
                command[:-1] + ["records-hardlink.json", "--overwrite"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(hardlink_collision.returncode, 2)
            self.assertIn("must not alias", hardlink_collision.stderr)
            self.assertEqual(hardlink_output.read_bytes(), input_path.read_bytes())

            dry = subprocess.run(
                command[:-1] + ["dry-result.json", "--dry-run"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertFalse(dry_path.exists())
            self.assertEqual(json.loads(dry.stdout), json.loads(first_bytes))

            package_view = subprocess.run(
                command[:-2] + ["--output-view", "package"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(package_view.returncode, 0, package_view.stderr)
            package_payload = json.loads(package_view.stdout)
            self.assertEqual(package_payload["route"], "LINK_RECONCILE")
            self.assertIn("reconciliation_results", package_payload)
            self.assertIn("discrepancies", package_payload)

            discrepancy_view = subprocess.run(
                command[:-2] + ["--output-view", "discrepancies"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(discrepancy_view.returncode, 0, discrepancy_view.stderr)
            discrepancy_payload = json.loads(discrepancy_view.stdout)
            self.assertEqual(
                discrepancy_payload["output_type"],
                "DETERMINISTIC_DISCREPANCY_REGISTER",
            )
            self.assertIn("discrepancies", discrepancy_payload)
            self.assertEqual(before, {path: source_snapshot(path) for path in (input_path, config_path)})


if __name__ == "__main__":
    unittest.main()
