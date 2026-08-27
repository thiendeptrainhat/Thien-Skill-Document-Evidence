"""Regression tests for Phase 2 matching profiles and reconciliation workflow."""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "thien-skill-document-evidence"
SCRIPT = SKILL / "scripts" / "prepare_reconciliation_workbook.py"
VALIDATE_SCRIPT = SKILL / "scripts" / "validate_records.py"
SCHEMAS = SKILL / "schemas"
PROFILES = SKILL / "assets" / "reconciliation-profiles"
FIXTURE = ROOT / "tests" / "fixtures" / "phase2-reconciliation"


def load_workflow_module():
    spec = importlib.util.spec_from_file_location("phase2_reconciliation_workflow", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import reconciliation workflow from {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WORKFLOW = load_workflow_module()


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def decode_json(data: bytes) -> dict[str, object]:
    return json.loads(data.decode("utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def profile(profile_id: str) -> tuple[dict[str, object], bytes]:
    value, data, _ = WORKFLOW.load_profile(profile_id)
    return value, data


def copy_fixture() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    shutil.copytree(FIXTURE, root / "fixture")
    return temporary, root


def source_schema_fields(filename: str) -> set[str]:
    value = read_json(SKILL / "schemas" / "document-types" / filename)
    return {
        str(field["field_name"])
        for collection in ("field_definitions", "line_item_definitions")
        for field in value.get(collection, [])
    }


class Phase2ReconciliationTests(unittest.TestCase):
    maxDiff = None

    REQUIRED_PROFILE_IDS = {
        "PR_PO",
        "PO_GRN_INVOICE",
        "PR_PO_GRN_INVOICE",
        "CONTRACT_ACCEPTANCE_INVOICE_PAYMENT_REQUEST",
        "INVOICE_PAYMENT_BANK_SETTLEMENT",
        "CONTRACT_PO_GRN_INVOICE_BANK_PAYMENT",
        "CUSTOM_N_WAY",
    }
    ADDITIVE_PROFILE_IDS = {
        "OUTBOUND_INVOICE_GOODS_ISSUE_CUSTOMER_RECEIPT",
        "INVENTORY_COUNT_BOOK_STOCK",
    }

    def build(
        self,
        root: Path,
        profile_id: str,
        inputs: list[str],
        overrides: dict[str, object] | None = None,
    ) -> tuple[dict[str, bytes], dict[str, object]]:
        selected, selected_bytes = profile(profile_id)
        return WORKFLOW.build_workflow(
            root, inputs, selected, selected_bytes, overrides
        )

    def test_all_bundled_profiles_validate_without_embedded_tolerance_values(self) -> None:
        found: dict[str, dict[str, object]] = {}
        validator = WORKFLOW.VALIDATE.InternalSchemaValidator(
            SKILL / "schemas" / "common" / "matching-profile.schema.json", SCHEMAS
        )
        for path in sorted(PROFILES.glob("*.json")):
            value = read_json(path)
            found[str(value["profile_id"])] = value
            with self.subTest(profile=path.name):
                self.assertEqual(validator.validate(value), [])
                WORKFLOW.validate_profile(value)
                self.assertIn("date", value["comparison_basis"])
                self.assertIn("currency", value["comparison_basis"])
                self.assertEqual(
                    value["policy_sources"]["materiality_use"],
                    "NOT_USED_AS_MATCH_TOLERANCE",
                )
                for rule in value["match_rules"]:
                    self.assertIn("cardinality", rule)
                    self.assertIn("partial_handling", rule)
                    self.assertIn("missing_field_policy", rule)
                    self.assertIn("multiple_candidate_policy", rule)
                    for component in rule["components"]:
                        self.assertEqual(
                            set(component["tolerance_source"]),
                            {"mode", "unit", "approval_reference_required"},
                        )
                config = WORKFLOW.materialize_config(value, None)
                for rule in config["link_rules"]:
                    for component in rule["components"]:
                        tolerance = component["tolerance"]
                        self.assertIsNone(tolerance["value"])
                        self.assertIn(
                            tolerance["status"], {"NOT_APPLICABLE", "NOT_PROVIDED"}
                        )
        self.assertTrue(self.REQUIRED_PROFILE_IDS.issubset(found))
        self.assertTrue(self.ADDITIVE_PROFILE_IDS.issubset(found))
        self.assertEqual(len(found), 9)

    def test_open_profile_registry_and_semantic_mutations_fail_closed(self) -> None:
        base, _ = profile("CUSTOM_N_WAY")
        future = copy.deepcopy(base)
        future["profile_id"] = "FUTURE_LEDGER_CHAIN"
        future["profile_kind"] = "FUTURE_LEDGER_CHAIN"
        replacements = {"ROLE_A": "FUTURE_LEFT", "ROLE_B": "FUTURE_RIGHT"}
        for role_value in future["roles"]:
            old = role_value["role_id"]
            role_value["role_id"] = replacements[old]
            role_value["output_sheet"] = replacements[old]
        future["roles"].append(
            {
                "role_id": "FUTURE_CONTEXT",
                "label": "Future contextual source",
                "source_kind": "SYSTEM_RECORD",
                "document_types": ["FUTURE_CONTEXT_RECORD"],
                "role_aliases": [],
                "required": False,
                "field_mappings": {
                    "reference_id": "reference_id",
                    "currency": "currency",
                },
                "output_sheet": "FUTURE_CONTEXT",
            }
        )
        future["match_rules"][0]["left_role"] = "FUTURE_LEFT"
        future["match_rules"][0]["right_role"] = "FUTURE_RIGHT"
        future["comparison_basis"]["currency"]["role_currency_fields"] = {
            "FUTURE_LEFT": "currency",
            "FUTURE_RIGHT": "currency",
            "FUTURE_CONTEXT": "currency",
        }
        WORKFLOW.validate_profile(future)

        mutations: list[tuple[str, dict[str, object]]] = []
        duplicate_role = copy.deepcopy(future)
        duplicate_role["roles"][1]["role_id"] = "FUTURE_LEFT"
        mutations.append(("duplicate role", duplicate_role))
        unknown_rule_role = copy.deepcopy(future)
        unknown_rule_role["match_rules"][0]["right_role"] = "UNKNOWN_ROLE"
        mutations.append(("unknown rule role", unknown_rule_role))
        unknown_basis_field = copy.deepcopy(future)
        unknown_basis_field["comparison_basis"]["currency"]["role_currency_fields"][
            "FUTURE_LEFT"
        ] = "no_such_field"
        mutations.append(("unknown basis field", unknown_basis_field))
        bad_decimal_unit = copy.deepcopy(future)
        bad_decimal_unit["match_rules"][0]["components"][1]["tolerance_source"][
            "unit"
        ] = "CALENDAR_DAYS"
        mutations.append(("decimal calendar unit", bad_decimal_unit))
        inventory, _ = profile("INVENTORY_COUNT_BOOK_STOCK")
        bad_date_unit = copy.deepcopy(inventory)
        bad_date_unit["match_rules"][0]["components"][0]["tolerance_source"][
            "unit"
        ] = "ABSOLUTE_AMOUNT"
        mutations.append(("date amount unit", bad_date_unit))
        bad_aggregation = copy.deepcopy(future)
        bad_aggregation["aggregation_rules"] = [
            {
                "aggregation_id": "future-total",
                "role_id": "FUTURE_LEFT",
                "group_by_fields": ["reference_id"],
                "value_field": "no_such_field",
                "operation": "SUM_DECIMAL",
                "result_field": "future_total",
            }
        ]
        mutations.append(("unmapped aggregation field", bad_aggregation))
        bad_bridge = copy.deepcopy(future)
        bad_bridge["match_rules"][0]["cardinality"] = "MANY_TO_MANY_WITH_EXPLICIT_BRIDGE"
        bad_bridge["match_rules"][0]["explicit_bridge"] = {
            "bridge_role": "FUTURE_CONTEXT",
            "allocation_key_fields": ["no_such_field"],
        }
        mutations.append(("unmapped bridge field", bad_bridge))
        for label, value in mutations:
            with self.subTest(label=label):
                with self.assertRaises(WORKFLOW.WorkflowError):
                    WORKFLOW.validate_profile(value)

    def test_required_component_mappings_align_with_bundled_source_schemas(self) -> None:
        schema_by_type = {
            "PURCHASE_REQUISITION": source_schema_fields("purchase-requisition.json"),
            "PURCHASE_ORDER": source_schema_fields("purchase-order.json"),
            "GOODS_RECEIPT": source_schema_fields("goods-receipt.json"),
            "INVOICE": source_schema_fields("invoice.json"),
            "SUPPLIER_INVOICE": source_schema_fields("invoice.json"),
            "PAYMENT_REQUEST": source_schema_fields("payment-request.json"),
            "BANK_TRANSACTION": source_schema_fields("bank-statement.json"),
            "BANK_STATEMENT_TRANSACTION": source_schema_fields("bank-statement.json"),
            "CONTRACT": source_schema_fields("contract.json"),
        }
        for path in sorted(PROFILES.glob("*.json")):
            value = read_json(path)
            roles = {role["role_id"]: role for role in value["roles"]}
            required: dict[str, set[str]] = {role_id: set() for role_id in roles}
            for rule in value["match_rules"]:
                for component in rule["components"]:
                    if component["required"]:
                        required[rule["left_role"]].add(component["left_field"])
                        required[rule["right_role"]].add(component["right_field"])
            for role_id, role_value in roles.items():
                mappings = role_value["field_mappings"]
                variants = role_value.get("field_mapping_variants", {})
                for document_type in role_value["document_types"]:
                    if document_type not in schema_by_type:
                        continue
                    source_fields = schema_by_type[document_type]
                    for canonical_field in sorted(required[role_id]):
                        declared = variants.get(document_type, {}).get(
                            canonical_field, mappings[canonical_field]
                        )
                        candidates = declared if isinstance(declared, list) else [declared]
                        with self.subTest(
                            profile=value["profile_id"],
                            role=role_id,
                            document_type=document_type,
                            field=canonical_field,
                        ):
                            self.assertTrue(set(candidates).intersection(source_fields))

    def test_pr_po_canonical_mapping_reconciles_end_to_end(self) -> None:
        temporary, root = copy_fixture()
        self.addCleanup(temporary.cleanup)
        files, manifest = self.build(
            root, "PR_PO", ["fixture/pr.json", "fixture/po.json"]
        )
        records = decode_json(files["records.json"])["records"]
        by_role = {record["role"]: record for record in records}
        self.assertEqual(by_role["PR"]["fields"]["quantity"], "100")
        self.assertEqual(by_role["PO"]["fields"]["quantity"], "100")
        self.assertEqual(by_role["PR"]["fields"]["requisition_number"], "000001")
        result = decode_json(files["reconciliation-result.json"])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["links"][0]["status"], "EXACT_MATCH")
        self.assertEqual(manifest["status"], "READY_FOR_LIMITED_USE")

    def test_custom_dotted_source_mapping_is_resolved_deterministically(self) -> None:
        temporary, root = copy_fixture()
        self.addCleanup(temporary.cleanup)
        custom, _ = profile("CUSTOM_N_WAY")
        custom = copy.deepcopy(custom)
        custom["profile_id"] = "CUSTOM_DOTTED_PATHS"
        custom["profile_kind"] = "CUSTOM_DOTTED_PATHS"
        custom["roles"][0]["field_mappings"] = {
            "reference_id": "header.reference_id",
            "amount": "totals.amount",
            "currency": "totals.currency",
        }
        WORKFLOW.validate_profile(custom)
        left = {
            "document_id": "LEFT-1",
            "document_type": "CUSTOM_SOURCE_A",
            "fields": {
                "header": {"reference_id": "000042"},
                "totals": {"amount": "10", "currency": "VND"},
            },
        }
        right = {
            "document_id": "RIGHT-1",
            "document_type": "CUSTOM_SOURCE_B",
            "fields": {"reference_id": "000042", "amount": "10", "currency": "VND"},
        }
        write_json(root / "left.json", left)
        write_json(root / "right.json", right)
        files, _ = WORKFLOW.build_workflow(
            root,
            ["left.json", "right.json"],
            custom,
            WORKFLOW.pretty_json_bytes(custom),
        )
        records = decode_json(files["records.json"])["records"]
        by_role = {record["role"]: record for record in records}
        self.assertEqual(by_role["ROLE_A"]["fields"]["reference_id"], "000042")
        self.assertEqual(by_role["ROLE_A"]["fields"]["amount"], "10")
        self.assertEqual(
            decode_json(files["reconciliation-result.json"])["status"], "PASS"
        )

    def test_contract_order_and_receipt_alternative_branches_reconcile(self) -> None:
        temporary, root = copy_fixture()
        self.addCleanup(temporary.cleanup)
        order = read_json(root / "fixture" / "po.json")
        receipt = read_json(root / "fixture" / "grn.json")
        invoice = read_json(root / "fixture" / "invoice.json")
        request = {
            "document_id": "PAYREQ-1",
            "document_type": "PAYMENT_REQUEST",
            "fields": {
                "request_date": "2026-08-07",
                "invoice_number": "000888",
                "requested_amount": "500",
                "currency": "VND",
            },
        }
        write_json(root / "order.json", order)
        write_json(root / "receipt.json", receipt)
        write_json(root / "invoice.json", invoice)
        write_json(root / "request.json", request)
        files, _ = self.build(
            root,
            "CONTRACT_ACCEPTANCE_INVOICE_PAYMENT_REQUEST",
            ["order.json", "receipt.json", "invoice.json", "request.json"],
        )
        result = decode_json(files["reconciliation-result.json"])
        self.assertEqual(result["status"], "PASS")
        records = decode_json(files["records.json"])["records"]
        by_role = {record["role"]: record for record in records}
        self.assertEqual(by_role["CONTRACT_BASE"]["fields"]["contract_number"], "000123")
        self.assertEqual(by_role["ACCEPTANCE"]["fields"]["acceptance_number"], "000777")

        contract = {
            "document_id": "CONTRACT-1",
            "document_type": "CONTRACT",
            "fields": {
                "contract_number": "BASE-1",
                "effective_date": "2026-08-01",
                "price": "500",
                "currency": "VND",
            },
        }
        contract_receipt = copy.deepcopy(receipt)
        contract_receipt["document_id"] = "GRN-CONTRACT-1"
        contract_receipt["fields"]["po_number"] = "BASE-1"
        contract_receipt["fields"]["delivered_quantity"] = "50"
        contract_invoice = copy.deepcopy(invoice)
        contract_invoice["document_id"] = "INV-CONTRACT-1"
        contract_invoice["fields"].pop("po_number", None)
        contract_invoice["fields"]["contract_number"] = "BASE-1"
        bank = {
            "document_id": "BANK-TXN-1",
            "document_type": "BANK_STATEMENT_TRANSACTION",
            "fields": {
                "transaction_reference": "000888",
                "booking_date": "2026-08-08",
                "signed_amount": "500",
                "transaction_currency": "VND",
                "counterparty_account": "000000123456",
            },
        }
        for name, value in {
            "contract.json": contract,
            "contract-receipt.json": contract_receipt,
            "contract-invoice.json": contract_invoice,
            "bank.json": bank,
        }.items():
            write_json(root / name, value)
        files, _ = self.build(
            root,
            "CONTRACT_PO_GRN_INVOICE_BANK_PAYMENT",
            ["contract.json", "contract-receipt.json", "contract-invoice.json", "bank.json"],
        )
        result = decode_json(files["reconciliation-result.json"])
        self.assertEqual(result["status"], "PASS")
        records = decode_json(files["records.json"])["records"]
        by_role = {record["role"]: record for record in records}
        self.assertEqual(by_role["CONTRACT_BASE"]["fields"]["base_number"], "BASE-1")
        self.assertEqual(by_role["BANK_TRANSACTION"]["fields"]["invoice_number"], "000888")

    def test_invoice_payment_request_bank_settlement_exact_and_approved_partial(self) -> None:
        temporary, root = copy_fixture()
        self.addCleanup(temporary.cleanup)
        invoice = read_json(root / "fixture" / "invoice.json")
        invoice["document_type"] = "SUPPLIER_INVOICE"
        payment_request = {
            "document_id": "PAYREQ-000888",
            "document_type": "PAYMENT_REQUEST",
            "fields": {
                "request_date": "2026-08-07",
                "invoice_number": "000888",
                "payment_reference": "PAY-000888",
                "requested_amount": "500",
                "currency": "VND",
                "beneficiary_bank_account": "000000123456",
            },
        }
        bank = {
            "document_id": "BANK-000888",
            "document_type": "BANK_TRANSACTION",
            "fields": {
                "transaction_reference": "PAY-000888",
                "booking_date": "2026-08-08",
                "signed_amount": "500",
                "transaction_currency": "VND",
                "counterparty_account": "000000123456",
            },
        }
        for name, value in {
            "supplier-invoice.json": invoice,
            "payment-request.json": payment_request,
            "bank-transaction.json": bank,
        }.items():
            write_json(root / name, value)
        inputs = [
            "supplier-invoice.json",
            "payment-request.json",
            "bank-transaction.json",
        ]
        files, manifest = self.build(
            root, "INVOICE_PAYMENT_BANK_SETTLEMENT", inputs
        )
        result = decode_json(files["reconciliation-result.json"])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            {link["rule_id"]: link["status"] for link in result["links"]},
            {
                "invoice-to-payment-request": "EXACT_MATCH",
                "payment-request-to-bank": "EXACT_MATCH",
            },
        )
        records = decode_json(files["records.json"])["records"]
        by_role = {record["role"]: record for record in records}
        self.assertEqual(by_role["INVOICE"]["fields"]["amount"], "500")
        self.assertEqual(
            by_role["PAYMENT_REQUEST"]["fields"]["payment_reference"], "PAY-000888"
        )
        self.assertEqual(
            by_role["BANK_TRANSACTION"]["fields"]["payment_reference"], "PAY-000888"
        )
        self.assertTrue(
            {"INVOICES", "PAYMENT_REQUESTS", "BANK_TRANSACTIONS", "MATCH_RESULTS", "SOURCE_INDEX", "RUN_LOG"}.issubset(
                set(manifest["workbook_sheets"])
            )
        )
        self.assertEqual(
            decode_json(files["workbook-package.validation.json"])["status"], "PASS"
        )

        bank["fields"]["signed_amount"] = "400"
        write_json(root / "bank-partial.json", bank)
        approved_partial = {
            "schema_version": "1.0.0",
            "approval": {
                "status": "APPROVED",
                "owner": "Synthetic settlement policy owner",
                "approval_reference": "APPROVAL-SETTLEMENT-001",
            },
            "tolerances": {},
            "partial_policies": {
                "payment-request-to-bank": {
                    "mode": "ALLOW_WHEN_DOCUMENTED",
                    "allowed_relation": "RIGHT_LESS_THAN_OR_EQUAL_LEFT",
                    "aggregation_id": None,
                    "basis": "Synthetic approved partial-settlement fixture",
                    "owner": "Synthetic settlement policy owner",
                    "approval_reference": "APPROVAL-SETTLEMENT-001",
                    "approval_status": "APPROVED",
                }
            },
        }
        files, manifest = self.build(
            root,
            "INVOICE_PAYMENT_BANK_SETTLEMENT",
            ["supplier-invoice.json", "payment-request.json", "bank-partial.json"],
            approved_partial,
        )
        result = decode_json(files["reconciliation-result.json"])
        self.assertEqual(result["status"], "PASS_WITH_WARNINGS")
        settlement = next(
            link for link in result["links"]
            if link["rule_id"] == "payment-request-to-bank"
        )
        self.assertEqual(settlement["status"], "PARTIAL_MATCH")
        self.assertEqual(manifest["status"], "READY_FOR_LIMITED_USE")

    def test_workflow_package_is_byte_stable_role_conditional_and_formula_safe(self) -> None:
        temporary, root = copy_fixture()
        self.addCleanup(temporary.cleanup)
        selected, selected_bytes = profile("PO_GRN_INVOICE")
        overrides = read_json(root / "fixture" / "approved-partial-policy.json")
        inputs = ["fixture/po.json", "fixture/grn.json", "fixture/invoice.json"]
        first, first_manifest = WORKFLOW.build_workflow(
            root, inputs, selected, selected_bytes, overrides
        )
        second, second_manifest = WORKFLOW.build_workflow(
            root, list(reversed(inputs)), selected, selected_bytes, overrides
        )
        self.assertEqual(first, second)
        self.assertEqual(first_manifest, second_manifest)
        self.assertEqual(
            decode_json(first["workbook-package.validation.json"])["status"], "PASS"
        )
        records = decode_json(first["records.json"])["records"]
        po_record = next(record for record in records if record["role"] == "PO")
        self.assertEqual(po_record["fields"]["po_number"], "000123")
        package = decode_json(first["workbook-package.json"])
        po_number = next(
            field
            for field in package["extracted_fields"]
            if field["document_id"] == "PO-000123" and field["field_name"] == "po_number"
        )
        self.assertEqual(po_number["values"]["raw_value"], "000123")
        description = next(
            field
            for field in package["extracted_fields"]
            if field["document_id"] == "PO-000123" and field["field_name"] == "description"
        )
        self.assertTrue(description["formula_injection_flag"])

        with zipfile.ZipFile(io.BytesIO(first["reconciliation-workbook.xlsx"])) as archive:
            names = set(archive.namelist())
            self.assertFalse(any("externalLink" in name or name.endswith("vbaProject.bin") for name in names))
            workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
            sheet_names = set(re.findall(r'<sheet name="([^"]+)"', workbook_xml))
            self.assertTrue(
                {"PURCHASE_ORDERS", "GOODS_RECEIPTS", "INVOICES", "SOURCE_INDEX", "MATCH_RESULTS", "RUN_LOG"}.issubset(sheet_names)
            )
            self.assertNotIn("PURCHASE_REQUISITIONS", sheet_names)
            worksheet_xml = b"\n".join(
                archive.read(name)
                for name in sorted(names)
                if name.startswith("xl/worksheets/")
            )
            self.assertNotIn(b"<f", worksheet_xml)
            self.assertIn(b"'=HYPERLINK", worksheet_xml)
            self.assertIn(b"<autoFilter", worksheet_xml)
            self.assertIn(b"<pane", worksheet_xml)
            sheet_count = len(
                [name for name in names if name.startswith("xl/worksheets/")]
            )
            self.assertEqual(worksheet_xml.count(b'<pageSetUpPr fitToPage="1"'), sheet_count)
            self.assertEqual(worksheet_xml.count(b'orientation="landscape"'), sheet_count)
            self.assertEqual(worksheet_xml.count(b'fitToWidth="1"'), sheet_count)
            self.assertEqual(worksheet_xml.count(b'<pageMargins left="0.25"'), sheet_count)
            styles_xml = archive.read("xl/styles.xml")
            self.assertIn(b'numFmtId="164" formatCode="yyyy-mm-dd"', styles_xml)
            self.assertIn(b'wrapText="1"', styles_xml)

    def test_approved_partial_is_preserved_and_cumulative_overallocation_is_blocked(self) -> None:
        temporary, root = copy_fixture()
        self.addCleanup(temporary.cleanup)
        overrides = read_json(root / "fixture" / "approved-partial-policy.json")
        files, _ = self.build(
            root,
            "PO_GRN_INVOICE",
            ["fixture/po.json", "fixture/grn.json", "fixture/invoice.json"],
            overrides,
        )
        result = decode_json(files["reconciliation-result.json"])
        self.assertEqual(result["status"], "PASS_WITH_WARNINGS")
        self.assertEqual(
            {link["rule_id"]: link["status"] for link in result["links"]},
            {
                "po-to-grn": "PARTIAL_MATCH",
                "po-to-invoice": "PARTIAL_MATCH",
                "grn-to-invoice": "EXACT_MATCH",
            },
        )
        self.assertEqual(len(result["allocations"]), 3)

        receipt_a = read_json(root / "fixture" / "grn.json")
        receipt_a["fields"]["delivered_quantity"] = "80"
        receipt_b = copy.deepcopy(receipt_a)
        receipt_b["document_id"] = "GRN-000778"
        receipt_b["fields"]["grn_number"] = "000778"
        write_json(root / "receipt-a.json", receipt_a)
        write_json(root / "receipt-b.json", receipt_b)
        files, manifest = self.build(
            root,
            "PO_GRN_INVOICE",
            ["fixture/po.json", "receipt-a.json", "receipt-b.json"],
            overrides,
        )
        result = decode_json(files["reconciliation-result.json"])
        self.assertIn(
            "PARTIAL_OVER_ALLOCATION",
            {item["discrepancy_code"] for item in result["discrepancies"]},
        )
        affected = [link for link in result["links"] if link["rule_id"] == "po-to-grn"]
        self.assertTrue(affected)
        self.assertTrue(all(link["status"] == "HUMAN_REVIEW_REQUIRED" for link in affected))
        self.assertEqual(manifest["status"], "READY_FOR_HUMAN_REVIEW")

    def test_per_file_failure_missing_roles_and_conditional_sheets_are_explicit(self) -> None:
        temporary, root = copy_fixture()
        self.addCleanup(temporary.cleanup)
        files, manifest = self.build(
            root,
            "PO_GRN_INVOICE",
            ["fixture/po.json", "fixture/invalid.json"],
        )
        scope = manifest["source_scope"]
        self.assertEqual(scope["processed_file_count"], 1)
        self.assertEqual(scope["failed_file_count"], 1)
        self.assertIn("accessible", scope["coverage_statement"].casefold())
        issue_codes = {issue["issue_code"] for issue in manifest["preparation_issues"]}
        self.assertIn("MISSING_REQUIRED_ROLE", issue_codes)
        self.assertEqual(manifest["status"], "READY_FOR_HUMAN_REVIEW")
        self.assertIn("PURCHASE_ORDERS", manifest["workbook_sheets"])
        self.assertNotIn("GOODS_RECEIPTS", manifest["workbook_sheets"])
        self.assertNotIn("INVOICES", manifest["workbook_sheets"])
        self.assertIn("SOURCE_INDEX", manifest["workbook_sheets"])
        self.assertIn("HUMAN_REVIEW", manifest["workbook_sheets"])
        self.assertIn("RUN_LOG", manifest["workbook_sheets"])
        self.assertEqual(
            decode_json(files["workbook-package.validation.json"])["status"], "PASS"
        )

    def test_nonpass_reconciliation_is_never_labeled_ready_for_limited_use(self) -> None:
        temporary, root = copy_fixture()
        self.addCleanup(temporary.cleanup)
        receipt = read_json(root / "fixture" / "grn.json")
        receipt["fields"]["delivered_quantity"] = "120"
        invoice = read_json(root / "fixture" / "invoice.json")
        invoice["fields"]["quantity"] = "120"
        invoice["fields"]["total_amount"] = "1200"
        write_json(root / "receipt-mismatch.json", receipt)
        write_json(root / "invoice-mismatch.json", invoice)
        files, manifest = self.build(
            root,
            "PO_GRN_INVOICE",
            ["fixture/po.json", "receipt-mismatch.json", "invoice-mismatch.json"],
        )
        result = decode_json(files["reconciliation-result.json"])
        self.assertEqual(manifest["preparation_issues"], [])
        self.assertEqual(result["status"], "CONDITIONAL")
        self.assertEqual(manifest["status"], "READY_FOR_HUMAN_REVIEW")
        self.assertNotEqual(manifest["status"], "READY_FOR_LIMITED_USE")
        self.assertEqual(
            WORKFLOW.workflow_readiness_status("FAIL", []),
            "READY_FOR_HUMAN_REVIEW",
        )
        self.assertEqual(
            WORKFLOW.workflow_readiness_status("BLOCKED", []),
            "READY_FOR_HUMAN_REVIEW",
        )

    def test_duplicate_business_content_with_distinct_ids_is_retained_and_flagged(self) -> None:
        temporary, root = copy_fixture()
        self.addCleanup(temporary.cleanup)
        first = read_json(root / "fixture" / "po.json")
        second = copy.deepcopy(first)
        second["document_id"] = "PO-OCCURRENCE-2"
        write_json(root / "po-first.json", first)
        write_json(root / "po-second.json", second)
        files, manifest = self.build(
            root,
            "PR_PO",
            ["fixture/pr.json", "po-first.json", "po-second.json"],
        )
        issue_codes = {issue["issue_code"] for issue in manifest["preparation_issues"]}
        self.assertIn("DUPLICATE_CONTENT", issue_codes)
        self.assertNotIn("DUPLICATE_RECORD_ID", issue_codes)
        package = decode_json(files["workbook-package.json"])
        occurrences = [
            item for item in package["document_inventory"]
            if item["document_id"] in {"PO-000123", "PO-OCCURRENCE-2"}
        ]
        self.assertEqual(len(occurrences), 2)
        self.assertEqual(occurrences[0]["content_id"], occurrences[1]["content_id"])
        self.assertTrue(
            all(
                any(link["relationship_type"] == "EXACT_DUPLICATE" for link in item["relationships"])
                for item in occurrences
            )
        )

    def test_unsafe_paths_symlinks_and_output_members_are_rejected(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        root = base / "authorized"
        root.mkdir()
        outside = base / "outside.json"
        write_json(outside, {"outside": True})
        with self.assertRaises(WORKFLOW.WorkflowError):
            WORKFLOW.enumerate_inputs(root, ["../outside.json"])
        link = root / "linked.json"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            pass
        else:
            with self.assertRaises(WORKFLOW.WorkflowError):
                WORKFLOW.enumerate_inputs(root, ["linked.json"])
        with self.assertRaises(WORKFLOW.WorkflowError):
            WORKFLOW.publish_directory(root, "../escape", {"safe.json": b"{}\n"})
        with self.assertRaises(WORKFLOW.WorkflowError):
            WORKFLOW.publish_directory(root, "unsafe-output", {"../escape.json": b"{}\n"})
        self.assertFalse((root / "unsafe-output").exists())
        self.assertEqual(list(root.glob(".unsafe-output.stage-*")), [])

    def test_publish_is_atomic_no_overwrite_and_cleans_failed_stage(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        files = {"a.json": b"{\"a\":1}\n", "b.txt": b"stable\n"}
        published = WORKFLOW.publish_directory(root, "published", files)
        before = {path.name: path.read_bytes() for path in published.iterdir()}
        with self.assertRaises(WORKFLOW.WorkflowError):
            WORKFLOW.publish_directory(root, "published", {"a.json": b"changed\n"})
        self.assertEqual(
            {path.name: path.read_bytes() for path in published.iterdir()}, before
        )

        with mock.patch.object(
            WORKFLOW,
            "_rename_directory_noreplace",
            side_effect=WORKFLOW.WorkflowError("synthetic publication failure"),
        ):
            with self.assertRaises(WORKFLOW.WorkflowError):
                WORKFLOW.publish_directory(root, "failed", files)
        self.assertFalse((root / "failed").exists())
        self.assertEqual(list(root.glob(".failed.stage-*")), [])

        staged = root / ".race-stage"
        staged.mkdir()
        target = root / "race-target"
        target.mkdir()
        (target / "sentinel.txt").write_text("preserve", encoding="utf-8")
        with self.assertRaises(WORKFLOW.WorkflowError):
            WORKFLOW._rename_directory_noreplace(staged, target)
        self.assertEqual((target / "sentinel.txt").read_text(encoding="utf-8"), "preserve")
        self.assertTrue(staged.is_dir())

    def test_cli_exact_command_and_existing_validator_compatibility(self) -> None:
        temporary, root = copy_fixture()
        self.addCleanup(temporary.cleanup)
        command = [
            sys.executable,
            "-B",
            str(SCRIPT),
            "--root",
            str(root),
            "--profile-id",
            "PR_PO",
            "--input",
            "fixture/pr.json",
            "--input",
            "fixture/po.json",
            "--output-dir",
            "reconciliation-output",
        ]
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertEqual(summary["status"], "READY_FOR_LIMITED_USE")
        output = root / "reconciliation-output"
        self.assertTrue((output / "reconciliation-workbook.xlsx").is_file())

        validation = subprocess.run(
            [
                sys.executable,
                "-B",
                str(VALIDATE_SCRIPT),
                "reconciliation-output/workbook-package.json",
                "--root",
                str(root),
                "--schema",
                "common/extraction-package.schema.json",
                "--schema-root",
                str(SCHEMAS),
                "--output",
                "reconciliation-output/workbook-package.revalidation.json",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(validation.returncode, 0, validation.stderr)
        self.assertEqual(
            read_json(output / "workbook-package.revalidation.json")["status"], "PASS"
        )
        before = {
            path.relative_to(output).as_posix(): path.read_bytes()
            for path in sorted(output.rglob("*"))
            if path.is_file()
        }
        repeated = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(repeated.returncode, 2)
        self.assertIn("refusing overwrite", repeated.stderr)
        self.assertEqual(
            {
                path.relative_to(output).as_posix(): path.read_bytes()
                for path in sorted(output.rglob("*"))
                if path.is_file()
            },
            before,
        )


if __name__ == "__main__":
    unittest.main()
