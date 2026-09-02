"""Reusable package-workflow harness with frozen RC2 defaults.

Every executable is taken from a hash-pinned ZIP and run by absolute path in
an isolated Python subprocess, with an empty working directory outside the
repository and no inherited PYTHONPATH, credentials, or executable search path.
Only synthetic inputs and temporary outputs are used. No source helper is
imported, rebuilt, installed, or patched by this suite.

Coverage is deterministic/structural and representative reperformance. It
does not establish visual fidelity, OCR accuracy, real statement extraction,
live installation/ingestion, many-to-many resolution, or human approval.
"""

from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import unittest
import xml.etree.ElementTree as ET
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
DIST = REPOSITORY / "dist"
FIXTURES = REPOSITORY / "tests" / "fixtures"
SKILL_ID = "thien-skill-document-evidence"
RELEASE = "1.1.0-rc.2"
CORE_SHA256 = "226878464dd7c2a39a173511b342f67c2f62babc5047f992d88fe52bd2eed580"
PLATFORMS = ("openai", "claude", "universal")

# These identify the Phase 2 handoff, not whatever a later build happens to
# produce. A mismatch is a changed review basis and must not be auto-repaired.
FROZEN_SHA256 = {
    "PARITY-v1.1.0-rc.2.json": "d0d5c68f7e010b19259d1132ddaddaffd182310ee84a5b46da66c03cebada127",
    "release-manifest-v1.1.0-rc.2.json": "ffe007866c49b1445f487208aa9da65c0acf23c81d370e2f9a7e92f71e39296e",
    "openai/Thien-Skill-Document-Evidence-OpenAI-v1.1.0-rc.2.zip": "bc4e26afeace3633fd8f8ab7def510d532cc700dd63ed3dbbf4f8bdcb7a1a514",
    "claude/Thien-Skill-Document-Evidence-Claude-v1.1.0-rc.2.zip": "ff2e3d17ebb24ca193d35fa49c10b655dd26335eabcf7f1c9414f914d0bfb748",
    "universal/Thien-Skill-Document-Evidence-Universal-v1.1.0-rc.2.zip": "6d13e21fe7fd177da0da96a06cfb9afedbf2fb848eebf546015c3da0e9b3bc7d",
}
ARCHIVE_NAMES = {
    platform: next(name for name in FROZEN_SHA256 if name.startswith(platform + "/"))
    for platform in PLATFORMS
}
PACKAGE_FORMATS = {
    "openai": "native-openai-plugin",
    "claude": "native-claude-plugin",
    "universal": "universal-agent-skill",
}
PACKAGE_FILE_COUNTS = {"openai": 100, "claude": 97, "universal": 91}
DISTRIBUTION_FILES = {
    "INSTALLATION.md",
    "ACCEPTANCE-REPORT-v1.1.0-rc.2.md",
    "LEGAL-REVIEW-v1.1.0-rc.2.md",
}
ARCHIVE_TIMESTAMP = (2026, 8, 27, 0, 0, 0)
WORKFLOW_READINESS_STATUS = "READY_FOR_LIMITED_USE"
ROLE_SHEETS = {
    "PURCHASE_REQUISITIONS", "PURCHASE_ORDERS", "GOODS_RECEIPTS", "INVOICES",
    "PAYMENT_REQUESTS", "BANK_TRANSACTIONS", "OUTBOUND_INVOICES", "GOODS_ISSUES",
    "CUSTOMER_RECEIPTS", "INVENTORY_COUNTS", "BOOK_STOCK", "CONTRACT_BASE",
    "ACCEPTANCES",
}
FORMULA_TEXT = '=HYPERLINK("https://untrusted.invalid","source text")'
NS = {
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def tree_digest(files: dict[str, bytes]) -> str:
    """Independent reimplementation of the documented length-prefixed hash."""
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def safe_archive_payload(path: Path, expected_sha256: str) -> dict[str, bytes]:
    """Preflight all members before any extraction or package-code execution."""
    data = path.read_bytes()
    if sha256(data) != expected_sha256:
        raise ValueError(f"frozen archive hash mismatch: {path.name}")
    files: dict[str, bytes] = {}
    collision_keys: set[str] = set()
    total_size = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 2000:
            raise ValueError("archive has too many members")
        for member in archive.infolist():
            name = member.filename
            parts = name.split("/")
            if (
                "\\" in name or ":" in name
                or any(ord(character) < 32 for character in name)
                or len(parts) < 2 or parts[0] != SKILL_ID
                or any(part in {"", ".", ".."} for part in parts)
                or PurePosixPath(name).as_posix() != name
            ):
                raise ValueError(f"unsafe archive path: {name!r}")
            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_IFMT(mode) != stat.S_IFREG or member.is_dir():
                raise ValueError(f"archive member is not a regular file: {name}")
            if mode & (stat.S_ISUID | stat.S_ISGID) or member.flag_bits & 1:
                raise ValueError(f"unsafe archive metadata: {name}")
            expected_mode = 0o755 if "scripts" in parts else 0o644
            if stat.S_IMODE(mode) != expected_mode:
                raise ValueError(f"unexpected archive permissions: {name}")
            if member.date_time != ARCHIVE_TIMESTAMP:
                raise ValueError(f"unexpected frozen archive timestamp: {name}")
            total_size += member.file_size
            if member.file_size > 16 * 1024 * 1024 or total_size > 64 * 1024 * 1024:
                raise ValueError("archive decompressed size exceeds acceptance limit")
            relative = "/".join(parts[1:])
            key = unicodedata.normalize("NFKC", relative).casefold()
            if key in collision_keys:
                raise ValueError(f"duplicate/case-colliding archive member: {name}")
            collision_keys.add(key)
            files[relative] = archive.read(member)  # also validates this member's CRC
        if archive.testzip() is not None:
            raise ValueError("archive CRC validation failed")
    for key in collision_keys:
        if any(parent.as_posix() in collision_keys for parent in PurePosixPath(key).parents):
            raise ValueError("archive file/directory prefix collision")
    return files


@dataclass(frozen=True)
class ExtractedPackage:
    root: Path
    skill: Path
    manifest: dict[str, object]
    original_hashes: dict[str, str]


def unpack_frozen_package(platform: str, parent: Path) -> ExtractedPackage:
    relative = ARCHIVE_NAMES[platform]
    files = safe_archive_payload(DIST / relative, FROZEN_SHA256[relative])
    manifest = json.loads(files["PACKAGE-MANIFEST.json"])
    expected_skill_path = "." if platform == "universal" else f"skills/{SKILL_ID}"
    expected = {
        "skill_id": SKILL_ID, "version": RELEASE, "platform": platform,
        "package_format": PACKAGE_FORMATS[platform], "status": "Testing",
        "skill_path": expected_skill_path, "core_sha256": CORE_SHA256,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"{platform} package manifest mismatch: {key}")
    hashes = {name: sha256(data) for name, data in files.items()}
    if manifest["files"] != {
        name: digest for name, digest in hashes.items() if name != "PACKAGE-MANIFEST.json"
    }:
        raise ValueError(f"{platform} embedded file inventory/hash mismatch")
    if len(files) != PACKAGE_FILE_COUNTS[platform]:
        raise ValueError(f"{platform} unexpected frozen member count")
    version_name = "VERSION" if platform == "universal" else f"{expected_skill_path}/VERSION"
    if files[version_name].decode("ascii").strip() != RELEASE:
        raise ValueError(f"{platform} embedded skill version mismatch")

    # parent is a new private temporary directory. Nothing is written until
    # the whole archive and embedded inventory pass the preceding checks.
    output = parent / platform / SKILL_ID
    output.mkdir(parents=True)
    for name, data in files.items():
        target = output.joinpath(*PurePosixPath(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as destination:
            destination.write(data)
    return ExtractedPackage(output, output / expected_skill_path, manifest, hashes)


def fixture_document(name: str) -> dict[str, object]:
    return read_json(FIXTURES / "phase2-reconciliation" / f"{name}.json")


def synthetic_document(document_id: str, document_type: str, **fields):
    return {
        "document_id": document_id,
        "document_type": document_type,
        "fields": fields,
        "data_classification": ["INTERNAL"],
    }


def exact_reconciliation_case(profile_id: str):
    """Explicit oracles; these do not derive expectations from helper results."""
    if profile_id == "PR_PO":
        return (
            [fixture_document("pr"), fixture_document("po")],
            {"pr-to-po"},
            {"PR": "PURCHASE_REQUISITIONS", "PO": "PURCHASE_ORDERS"},
            {"PR": {"requisition_number": "000001", "quantity": "100"},
             "PO": {"requisition_number": "000001", "quantity": "100"}},
        )
    if profile_id == "PR_PO_GRN_INVOICE":
        receipt, invoice = fixture_document("grn"), fixture_document("invoice")
        receipt["fields"]["delivered_quantity"] = "100"
        invoice["fields"].update(quantity="100", total_amount="1000")
        return (
            [fixture_document("pr"), fixture_document("po"), receipt, invoice],
            {"pr-to-po", "po-to-grn", "po-to-invoice", "grn-to-invoice"},
            {"PR": "PURCHASE_REQUISITIONS", "PO": "PURCHASE_ORDERS",
             "GRN": "GOODS_RECEIPTS", "INVOICE": "INVOICES"},
            {"PR": {"requisition_number": "000001", "quantity": "100"},
             "PO": {"po_number": "000123", "amount": "1000"},
             "GRN": {"po_number": "000123", "quantity": "100"},
             "INVOICE": {"po_number": "000123", "quantity": "100", "amount": "1000"}},
        )
    if profile_id == "INVOICE_PAYMENT_BANK_SETTLEMENT":
        invoice = fixture_document("invoice")
        invoice["document_type"] = "SUPPLIER_INVOICE"
        invoice["fields"]["description"] = FORMULA_TEXT
        request = synthetic_document(
            "PAYREQ-000888", "PAYMENT_REQUEST", request_date="2026-08-07",
            invoice_number="000888", payment_reference="PAY-000888",
            requested_amount="500", currency="VND", beneficiary_bank_account="000000123456",
        )
        bank = synthetic_document(
            "BANK-000888", "BANK_TRANSACTION", transaction_reference="PAY-000888",
            booking_date="2026-08-08", signed_amount="500", transaction_currency="VND",
            counterparty_account="000000123456",
        )
        return (
            [invoice, request, bank],
            {"invoice-to-payment-request", "payment-request-to-bank"},
            {"INVOICE": "INVOICES", "PAYMENT_REQUEST": "PAYMENT_REQUESTS",
             "BANK_TRANSACTION": "BANK_TRANSACTIONS"},
            {"INVOICE": {"invoice_number": "000888", "bank_account": "000000123456"},
             "PAYMENT_REQUEST": {"amount": "500", "payment_reference": "PAY-000888"},
             "BANK_TRANSACTION": {"amount": "500", "bank_account": "000000123456"}},
        )
    if profile_id == "OUTBOUND_INVOICE_GOODS_ISSUE_CUSTOMER_RECEIPT":
        return (
            [
                synthetic_document(
                    "OUT-000888", "SALES_INVOICE", sales_order_number="000001",
                    delivery_number="000777", invoice_date="2026-08-06", item_code="000045",
                    quantity="10", net_amount="500", currency="VND", description=FORMULA_TEXT,
                ),
                synthetic_document(
                    "ISSUE-000777", "WAREHOUSE_ISSUE", sales_order_number="000001",
                    delivery_number="000777", issue_date="2026-08-05", item_code="000045", quantity="10",
                ),
                synthetic_document(
                    "POD-000777", "PROOF_OF_DELIVERY", delivery_number="000777",
                    receipt_date="2026-08-07", item_code="000045", quantity="10",
                ),
            ],
            {"invoice-to-goods-issue", "goods-issue-to-customer-receipt"},
            {"OUTBOUND_INVOICE": "OUTBOUND_INVOICES", "GOODS_ISSUE": "GOODS_ISSUES",
             "CUSTOMER_RECEIPT": "CUSTOMER_RECEIPTS"},
            {"OUTBOUND_INVOICE": {"sales_order_number": "000001", "amount": "500"},
             "GOODS_ISSUE": {"delivery_number": "000777", "quantity": "10"},
             "CUSTOMER_RECEIPT": {"delivery_number": "000777", "quantity": "10"}},
        )
    if profile_id == "INVENTORY_COUNT_BOOK_STOCK":
        return (
            [
                synthetic_document(
                    "COUNT-000045", "PHYSICAL_COUNT_SHEET", count_date="2026-08-27",
                    location_code="000002", item_code="000045", lot_number="000017",
                    counted_quantity="25", unit="EA", description=FORMULA_TEXT,
                ),
                synthetic_document(
                    "BOOK-000045", "INVENTORY_LEDGER_BALANCE", as_of_date="2026-08-27",
                    location_code="000002", item_code="000045", lot_number="000017",
                    book_quantity="25", unit="EA",
                ),
            ],
            {"count-to-book-stock"},
            {"INVENTORY_COUNT": "INVENTORY_COUNTS", "BOOK_STOCK": "BOOK_STOCK"},
            {"INVENTORY_COUNT": {"location_code": "000002", "lot_number": "000017", "quantity": "25"},
             "BOOK_STOCK": {"count_date": "2026-08-27", "item_code": "000045", "quantity": "25"}},
        )
    if profile_id == "CONTRACT_ACCEPTANCE_INVOICE_PAYMENT_REQUEST":
        invoice = fixture_document("invoice")
        invoice["fields"].update(contract_number="000009", description=FORMULA_TEXT)
        return (
            [
                synthetic_document(
                    "CONTRACT-000009", "CONTRACT", contract_number="000009", price="500",
                    currency="VND", effective_date="2026-08-01",
                ),
                synthetic_document(
                    "ACCEPT-000777", "ACCEPTANCE", contract_number="000009",
                    acceptance_number="000777", accepted_amount="500", currency="VND",
                    acceptance_date="2026-08-05",
                ),
                invoice,
                synthetic_document(
                    "PAYREQ-000888", "PAYMENT_REQUEST", contract_number="000009",
                    invoice_number="000888", request_date="2026-08-07",
                    requested_amount="500", currency="VND",
                ),
            ],
            {"contract-to-acceptance", "acceptance-to-invoice", "invoice-to-payment-request"},
            {"CONTRACT_BASE": "CONTRACT_BASE", "ACCEPTANCE": "ACCEPTANCES",
             "INVOICE": "INVOICES", "PAYMENT_REQUEST": "PAYMENT_REQUESTS"},
            {"CONTRACT_BASE": {"contract_number": "000009", "amount": "500"},
             "ACCEPTANCE": {"acceptance_number": "000777", "amount": "500"},
             "INVOICE": {"contract_number": "000009", "acceptance_number": "000777"},
             "PAYMENT_REQUEST": {"invoice_number": "000888", "amount": "500"}},
        )
    raise ValueError(f"no explicit Phase 3 oracle for {profile_id}")


class Phase3PackagedWorkflowTests(unittest.TestCase):
    """Run complete frozen-package workflows with independent output checks."""

    maxDiff = 2500

    @classmethod
    def setUpClass(cls) -> None:
        for name, digest in FROZEN_SHA256.items():
            if sha256((DIST / name).read_bytes()) != digest:
                raise AssertionError(f"Frozen RC2 review basis changed: {name}; do not rebuild silently")
        cls.temporary = tempfile.TemporaryDirectory(prefix="phase3-packaged-rc2-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name).resolve()
        if cls.root == REPOSITORY or REPOSITORY in cls.root.parents:
            raise AssertionError("acceptance temporary directory must be outside the repository")
        cls.runner = cls.root / "empty-runner"
        cls.runner.mkdir()
        cls.environment = {
            "PATH": str(cls.runner), "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1",
        }
        cls.packages = {
            platform: unpack_frozen_package(platform, cls.root / "extracted")
            for platform in PLATFORMS
        }

    @classmethod
    def tearDownClass(cls) -> None:
        for platform, package in cls.packages.items():
            if tree_hashes(package.root) != package.original_hashes:
                raise AssertionError(f"packaged files changed during offline execution: {platform}")
        for name, digest in FROZEN_SHA256.items():
            if sha256((DIST / name).read_bytes()) != digest:
                raise AssertionError(f"frozen distribution changed during tests: {name}")

    def workspace(self, platform: str, label: str = "case") -> Path:
        root = self.root / "runs" / self._testMethodName / platform / label
        root.mkdir(parents=True)
        return root

    def run_helper(
        self, platform: str, root: Path, script: str, *arguments: str, returncode: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        executable = self.packages[platform].skill / "scripts" / script
        self.assertTrue(executable.is_absolute())
        self.assertTrue(executable.is_file())
        self.assertNotIn(REPOSITORY, executable.parents)
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(executable), "--root", str(root), *arguments],
            cwd=self.runner, env=self.environment, capture_output=True, text=True,
            check=False, timeout=45,
        )
        self.assertEqual(
            completed.returncode, returncode,
            f"{platform}/{script}: {completed.stderr}\n{completed.stdout}",
        )
        return completed

    def validate_output(self, platform: str, root: Path, relative: str, schema: str) -> None:
        report = "validation-" + Path(relative).name + ".json"
        self.run_helper(
            platform, root, "validate_records.py", relative,
            "--schema", f"common/{schema}", "--schema-root",
            str(self.packages[platform].skill / "schemas"), "--output", report,
        )
        self.assertEqual(read_json(root / report)["status"], "PASS")

    def assert_same_outputs(self, snapshots: dict[str, dict[str, str]]) -> None:
        self.assertEqual(set(snapshots), set(PLATFORMS))
        self.assertEqual(snapshots["openai"], snapshots["claude"])
        self.assertEqual(snapshots["openai"], snapshots["universal"])

    def test_frozen_hashes_embedded_manifests_and_exact_core_parity(self) -> None:
        listed = {
            name: digest for digest, name in (
                line.split("  ", 1)
                for line in (DIST / "SHA256SUMS-v1.1.0-rc.2.txt").read_text().splitlines()
            )
        }
        self.assertEqual(listed, FROZEN_SHA256)
        release = read_json(DIST / "release-manifest-v1.1.0-rc.2.json")
        self.assertEqual(release["version"], RELEASE)
        cores = {}
        for platform, package in self.packages.items():
            with self.subTest(platform=platform):
                self.assertEqual(package.manifest["core_sha256"], CORE_SHA256)
                self.assertEqual((package.skill / "VERSION").read_text().strip(), RELEASE)
                artifact = next(item for item in release["artifacts"] if item["platform"] == platform)
                self.assertEqual(artifact["sha256"], FROZEN_SHA256[ARCHIVE_NAMES[platform]])
                self.assertEqual(artifact["size_bytes"], (DIST / ARCHIVE_NAMES[platform]).stat().st_size)
                self.assertEqual(artifact["file_count"], PACKAGE_FILE_COUNTS[platform])
                if platform != "universal":
                    adapter = ".codex-plugin/plugin.json" if platform == "openai" else ".claude-plugin/plugin.json"
                    self.assertEqual(read_json(package.root / adapter)["version"], RELEASE)
                for helper in (
                    "render_canonical_artifacts.py", "build_rag_package.py",
                    "prepare_reconciliation_workbook.py", "reconcile_records.py", "validate_records.py",
                ):
                    self.assertTrue((package.skill / "scripts" / helper).is_file())
                self.assertEqual(len(list((package.skill / "assets/reconciliation-profiles").glob("*.json"))), 9)
                core = {
                    name: (package.skill / name).read_bytes()
                    for name in tree_hashes(package.skill)
                    if not name.startswith("agents/")
                    and name != "PACKAGE-MANIFEST.json" and name not in DISTRIBUTION_FILES
                }
                self.assertEqual(len(core), 87)
                self.assertEqual(tree_digest(core), CORE_SHA256)
                cores[platform] = {name: sha256(data) for name, data in core.items()}
                self.assertFalse(any("HANDOFF.md" in name or "__pycache__" in name for name in package.original_hashes))
        self.assert_same_outputs(cores)

    def test_python_process_isolation_and_no_inherited_pythonpath(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-c",
             "import json,os,sys; print(json.dumps({'isolated':sys.flags.isolated,"
             "'bytecode':sys.dont_write_bytecode,'path':sys.path,'environment':dict(os.environ)}))"],
            cwd=self.runner, env=self.environment, text=True, capture_output=True,
            check=False, timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        observed = json.loads(completed.stdout)
        self.assertEqual(observed["isolated"], 1)
        self.assertTrue(observed["bytecode"])
        self.assertNotIn("PYTHONPATH", observed["environment"])
        self.assertEqual(observed["environment"]["PATH"], str(self.runner))
        self.assertNotIn("", observed["path"])
        for entry in observed["path"]:
            path = Path(entry).resolve()
            self.assertFalse(path == REPOSITORY or REPOSITORY in path.parents)
            self.assertFalse(path == self.runner or self.runner in path.parents)

    def conversion(self, output_format: str) -> None:
        profiles = {
            "JSON": (None, None), "MD": (None, None),
            "DOCX": ("SEMANTIC_EDITABLE", None), "XLSX": ("STRUCTURED_DATA", None),
            "PPTX": ("EDITABLE_PRESENTATION", "PRESENTATION"),
        }
        profile, intent = profiles[output_format]
        snapshots = {}
        for platform in PLATFORMS:
            with self.subTest(platform=platform, format=output_format):
                root = self.workspace(platform)
                (root / "assets").mkdir()
                (root / "out").mkdir()
                shutil.copyfile(FIXTURES / "conversion/canonical-content.json", root / "canonical-content.json")
                (root / "assets/page-1.png").write_bytes(base64.b64decode(
                    (FIXTURES / "conversion/page-1.png.b64").read_text().strip(), validate=True,
                ))
                input_hash = sha256((root / "canonical-content.json").read_bytes())
                relative = f"out/content.{output_format.lower()}"
                args = ["canonical-content.json", "--format", output_format, "--output", relative]
                if profile:
                    args.extend(["--output-profile", profile])
                if intent:
                    args.extend(["--presentation-intent", intent])
                if output_format in {"DOCX", "PPTX"}:
                    args.extend(["--assets-root", "assets"])
                completed = self.run_helper(platform, root, "render_canonical_artifacts.py", *args)
                artifact = root / relative
                manifest_path = root / (relative + ".manifest.json")
                run_path = root / (relative + ".conversion-run.json")
                manifest, run = read_json(manifest_path), read_json(run_path)
                self.assertEqual(json.loads(completed.stdout), manifest)
                self.assertEqual(manifest["skill_release_version"], RELEASE)
                self.assertEqual(run["runtime_skill"]["release_version"], RELEASE)
                self.assertEqual(run["source_canonical"]["source_skill_release_version"], "1.1.0-rc.1")
                self.assertEqual(run["source_canonical"]["checksum"]["digest"], input_hash)
                self.assertEqual(run["request"]["output_format"], output_format)
                self.assertEqual(run["request"]["output_profile"], profile)
                # The closed run contract normalizes an omitted non-slide
                # Office intent to NOT_APPLICABLE; JSON/MD retain null.
                expected_intent = "NOT_APPLICABLE" if output_format in {"DOCX", "XLSX"} else intent
                self.assertEqual(run["request"]["presentation_intent"], expected_intent)
                self.assertEqual(run["outputs"]["artifact"]["checksum"]["digest"], sha256(artifact.read_bytes()))
                self.assertEqual(run["outputs"]["artifact_manifest"]["checksum"]["digest"], sha256(manifest_path.read_bytes()))
                self.assertEqual(run["outputs"]["artifact_manifest"]["manifest_id"], manifest["manifest_id"])
                self.assertEqual(run["outputs"]["artifact"]["artifact_id"], manifest["artifacts"][0]["artifact_id"])
                self.assertEqual(manifest["artifacts"][0]["checksum"]["digest"], sha256(artifact.read_bytes()))
                self.assertEqual(sha256((root / "canonical-content.json").read_bytes()), input_hash)
                canonical = read_json(root / "canonical-content.json")
                if output_format == "JSON":
                    self.assertEqual(read_json(artifact), canonical)
                    self.assertEqual(manifest["status"], "PASS")
                elif output_format == "MD":
                    content = artifact.read_text()
                    for expected in (
                        "# Quarterly Evidence Summary", "PO-0007", "INV-0042",
                        "| Reference | Amount |", 'data-source-region="page-1/caption-1"',
                        "![One-pixel synthetic fixture](page-1.png)",
                    ):
                        self.assertIn(expected, content)
                    self.assertEqual(manifest["status"], "PASS_WITH_WARNINGS")
                else:
                    self.assertEqual(manifest["status"], "NOT_TESTED")
                    self.assertEqual(manifest["artifacts"][0]["qa_status"], "NOT_TESTED")
                    self.assert_office_structure(artifact, output_format, canonical)
                self.validate_output(platform, root, relative + ".manifest.json", "artifact-manifest.schema.json")
                self.validate_output(platform, root, relative + ".conversion-run.json", "conversion-run.schema.json")
                self.assertEqual(len(tree_hashes(root / "out")), 3)
                snapshots[platform] = tree_hashes(root / "out")
        self.assert_same_outputs(snapshots)

    def assert_office_structure(self, path: Path, kind: str, canonical: dict[str, object]) -> None:
        with zipfile.ZipFile(path) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            self.assertFalse(any("vbaproject.bin" in name.casefold() or "externalLink" in name for name in names))
            custom = ET.fromstring(archive.read("customXml/item1.xml"))
            payload = next(element.text for element in custom.iter() if element.tag.endswith("}json"))
            self.assertEqual(json.loads(payload), canonical)
            for name in names:
                if name.endswith(".rels"):
                    self.assertNotIn(b'TargetMode="External"', archive.read(name))
            if kind == "DOCX":
                main = archive.read("word/document.xml")
                for expected in (b"Quarterly Evidence Summary", b"PO-0007", b"INV-0042", b"<w:tbl>", b"<w:drawing>"):
                    self.assertIn(expected, main)
                self.assertIn("word/media/image1.png", names)
            elif kind == "XLSX":
                main = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
                self.assertEqual(len(main.findall("./s:sheetData/s:row", NS)), len(canonical["blocks"]) + 1)
                self.assertEqual(main.find("./s:pageSetup", NS).attrib["fitToWidth"], "1")
                for name in names:
                    if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                        self.assertEqual(ET.fromstring(archive.read(name)).findall(".//s:f", NS), [])
            else:
                main = ET.fromstring(archive.read("ppt/slides/slide1.xml"))
                self.assertIn("ppt/media/image1.png", names)
                cells = main.findall(".//a:tbl/a:tr/a:tc", NS)
                self.assertEqual(len(cells), 6)
                text = " ".join(element.text or "" for element in main.findall(".//a:t", NS))
                for expected in ("Quarterly Evidence Summary", "PO-0007", "INV-0042", "1250.00"):
                    self.assertIn(expected, text)
                # Regression for the Phase 2 table text visibility fix.
                for cell in cells:
                    run = cell.find("./a:txBody/a:p/a:r/a:rPr", NS)
                    self.assertEqual(run.find("./a:solidFill/a:srgbClr", NS).attrib["val"], "000000")
                    self.assertEqual(run.find("./a:latin", NS).attrib["typeface"], "Arial")

    def test_packaged_json_conversion(self) -> None:
        self.conversion("JSON")

    def test_packaged_markdown_conversion(self) -> None:
        self.conversion("MD")

    def test_packaged_docx_conversion(self) -> None:
        self.conversion("DOCX")

    def test_packaged_xlsx_conversion(self) -> None:
        self.conversion("XLSX")

    def test_packaged_pptx_editable_conversion(self) -> None:
        self.conversion("PPTX")

    def rag(self, *, chunks: bool = False, collection: bool = False, dry_run: bool = False) -> None:
        snapshots = {}
        for platform in PLATFORMS:
            with self.subTest(platform=platform):
                root = self.workspace(platform)
                shutil.copytree(FIXTURES / "rag", root / "fixture")
                before = tree_hashes(root / "fixture")
                args = ["fixture/canonical-alpha.json"]
                if collection:
                    args.insert(0, "fixture/canonical-beta.json")
                args.extend(["--output", "rag-output"])
                if chunks:
                    args.extend(["--target-id", "synthetic-target", "--chunk-config", "fixture/chunk-config.json"])
                if dry_run:
                    args.append("--dry-run")
                completed = self.run_helper(platform, root, "build_rag_package.py", *args)
                summary = json.loads(completed.stdout)
                self.assertEqual(summary["status"], "DRY_RUN" if dry_run else "WRITTEN")
                self.assertEqual(summary["validation"]["descriptor_checksums"], "PASS")
                self.assertEqual(summary["validation"]["live_target_ingestion"], "NOT_TESTED")
                output = root / "rag-output"
                if dry_run:
                    self.assertFalse(output.exists())
                    continue
                control = self.assert_rag_checksums(output, chunks=chunks, collection=collection)
                self.assertEqual(control["skill_release_version"], RELEASE)
                self.assertEqual(control["status"], "PASS")
                self.validate_output(platform, root, "rag-output/rag-package.json", "rag-package.schema.json")
                self.assertEqual(tree_hashes(root / "fixture"), before)
                snapshots[platform] = tree_hashes(output)
        if not dry_run:
            self.assert_same_outputs(snapshots)

    def assert_rag_checksums(self, output: Path, *, chunks: bool, collection: bool):
        control = read_json(output / "rag-package.json")
        self.assertEqual(control["package_kind"], "COLLECTION" if collection else "DOCUMENT")
        ids = ["doc-alpha-001", "doc-beta-001"] if collection else ["doc-alpha-001"]
        self.assertEqual([doc["document_id"] for doc in control["documents"]], ids)
        expected_files = {"rag-package.json"}
        for document in control["documents"]:
            root = output / document["directory"]
            descriptors = [document[key] for key in ("document_markdown", "metadata", "manifest")]
            descriptors.extend(document["assets"])
            if chunks:
                descriptor = document["chunks"]
                self.assertEqual(descriptor["target_id"], "synthetic-target")
                self.assertEqual(descriptor["chunking_config_checksum"], sha256((FIXTURES / "rag/chunk-config.json").read_bytes()))
                descriptors.append(descriptor)
                records = [json.loads(line) for line in (root / "chunks.jsonl").read_text().splitlines()]
                self.assertEqual(len(records), 3)
                self.assertEqual([record["sequence"] for record in records], [1, 2, 3])
                self.assertTrue(all(record["block_ids"] and record["source_locators"] for record in records))
                self.assertTrue(all(record["token_count"] is None for record in records))
            else:
                self.assertIsNone(document["chunks"])
                self.assertFalse((root / "chunks.jsonl").exists())
            for descriptor in descriptors:
                target = root / descriptor["path"]
                self.assertEqual(sha256(target.read_bytes()), descriptor["checksum"]["digest"])
                expected_files.add(target.relative_to(output).as_posix())
            inventory = read_json(root / "manifest.json")
            self.assertEqual(inventory["checksum_scope"], "PAYLOAD_FILES_EXCLUDING_THIS_MANIFEST_AND_RAG_PACKAGE_CONTROL")
            self.assertNotIn("manifest.json", {item["path"] for item in inventory["files"]})
            for item in inventory["files"]:
                self.assertEqual(sha256((root / item["path"]).read_bytes()), item["checksum"]["digest"])
            metadata = read_json(root / "metadata.json")
            self.assertEqual(metadata["builder"]["skill_release_version"], RELEASE)
            self.assertEqual(metadata["canonical"]["skill_release_version"], "1.1.0-rc.1")
            self.assertEqual(metadata["review_status"]["target_ingestion"], "NOT_TESTED")
            if document["document_id"] == "doc-alpha-001":
                self.assertIn("00017", (root / "document.md").read_text())
                self.assertEqual((root / "assets/figure-001.svg").read_bytes(), (FIXTURES / "rag/assets/figure-001.svg").read_bytes())
        if collection:
            descriptor = control["collection_manifest"]
            self.assertEqual(sha256((output / descriptor["path"]).read_bytes()), descriptor["checksum"]["digest"])
            expected_files.add(descriptor["path"])
            manifest = read_json(output / descriptor["path"])
            self.assertEqual(manifest["document_count"], 2)
            for document in manifest["documents"]:
                self.assertEqual(sha256((output / document["manifest_path"]).read_bytes()), document["manifest_checksum"]["digest"])
        else:
            self.assertIsNone(control["collection_manifest"])
        self.assertEqual(set(tree_hashes(output)), expected_files)
        return control

    def test_packaged_default_rag_has_no_chunks(self) -> None:
        self.rag()

    def test_packaged_explicit_target_rag_chunks(self) -> None:
        self.rag(chunks=True)

    def test_packaged_rag_collection(self) -> None:
        self.rag(collection=True)

    def test_packaged_rag_dry_run_has_no_output(self) -> None:
        self.rag(dry_run=True)

    def test_packaged_rag_incomplete_target_request_fails_closed(self) -> None:
        for platform in PLATFORMS:
            for label, arguments in (
                ("missing-config", ["--target-id", "synthetic-target"]),
                ("missing-target", ["--chunk-config", "fixture/chunk-config.json"]),
            ):
                with self.subTest(platform=platform, case=label):
                    root = self.workspace(platform, label)
                    shutil.copytree(FIXTURES / "rag", root / "fixture")
                    completed = self.run_helper(
                        platform, root, "build_rag_package.py", "fixture/canonical-alpha.json",
                        "--output", "rejected", *arguments, returncode=2,
                    )
                    self.assertIn("must be supplied together", completed.stderr)
                    self.assertFalse((root / "rejected").exists())

    def workflow(self, platform: str, root: Path, profile: str, documents: list, policy=None):
        write_json(root / "documents.json", {"documents": documents})
        source_before = (root / "documents.json").read_bytes()
        args = ["--profile-id", profile, "--input", "documents.json", "--output-dir", "workflow"]
        if policy is not None:
            write_json(root / "approved-policy.json", policy)
            args.extend(["--policy-overrides", "approved-policy.json"])
        completed = self.run_helper(platform, root, "prepare_reconciliation_workbook.py", *args)
        summary = json.loads(completed.stdout)
        output = root / "workflow"
        manifest = read_json(output / "workflow-manifest.json")
        result = read_json(output / "reconciliation-result.json")
        package = read_json(output / "workbook-package.json")
        records = read_json(output / "records.json")["records"]
        count = len(documents)
        self.assertEqual(summary["file_count"], 8)
        self.assertEqual(summary["processed_file_count"], 1)
        self.assertEqual(summary["failed_file_count"], 0)
        self.assertEqual(summary["classified_record_count"], count)
        self.assertEqual(manifest["source_scope"]["document_count"], count)
        self.assertEqual(manifest["source_scope"]["classified_record_count"], count)
        self.assertEqual(manifest["source_scope"]["requested_inputs"], ["documents.json"])
        self.assertEqual(manifest["source_scope"]["claim_scope"], "ACCESSIBLE_REQUESTED_INPUTS_ONLY")
        self.assertEqual(manifest["preparation_issues"], [])
        self.assertEqual(len(records), count)
        self.assertEqual({record["record_id"] for record in records}, {document["document_id"] for document in documents})
        self.assertEqual(len(package["document_inventory"]), count)
        self.assertEqual(package["outputs"][0]["record_count"], count)
        self.assertEqual(package["run_manifest"]["record_counts"]["classified_records"], count)
        self.assertEqual(package["status"], "READY_FOR_HUMAN_REVIEW")
        self.assertTrue(any("not re-extracted" in limitation for limitation in package["limitations"]))
        self.assertTrue(any("Many-to-many" in limitation for limitation in manifest["limitations"]))
        self.assertEqual(read_json(output / "workbook-package.validation.json")["status"], "PASS")
        self.assertEqual(package["outputs"][0]["checksum"]["digest"], sha256((output / "reconciliation-workbook.xlsx").read_bytes()))
        self.assertEqual(set(tree_hashes(output)), {*manifest["files"], "workflow-manifest.json"})
        for name, descriptor in manifest["files"].items():
            data = (output / name).read_bytes()
            self.assertEqual(sha256(data), descriptor["sha256"])
            self.assertEqual(len(data), descriptor["size_bytes"])
        original_profile = next(
            path for path in (self.packages[platform].skill / "assets/reconciliation-profiles").glob("*.json")
            if read_json(path)["profile_id"] == profile
        )
        self.assertEqual(manifest["profile"]["sha256"], sha256(original_profile.read_bytes()))
        self.validate_output(platform, root, "workflow/workbook-package.json", "extraction-package.schema.json")
        self.assertEqual((root / "documents.json").read_bytes(), source_before)
        return output, manifest, result, package, records, args

    def assert_workbook_safety(
        self, output: Path, role_sheets: dict[str, str], documents: list, records: list,
    ) -> None:
        expected_sheets = set(role_sheets.values())
        record_roles = {record["record_id"]: record["role"] for record in records}
        expected_rows = {sheet: {} for sheet in expected_sheets}
        for document in documents:
            sheet = role_sheets[record_roles[document["document_id"]]]
            for field, source in document["fields"].items():
                raw = source["raw_value"] if isinstance(source, dict) else source
                displayed = "" if raw is None else str(raw)
                if displayed.startswith(("=", "+", "-", "@")):
                    displayed = "'" + displayed
                expected_rows[sheet][(document["document_id"], field)] = displayed

        def cell_text(cell) -> str:
            return "".join(element.text or "" for element in cell.findall(".//s:t", NS))

        with zipfile.ZipFile(output / "reconciliation-workbook.xlsx") as archive:
            self.assertIsNone(archive.testzip())
            names = archive.namelist()
            self.assertFalse(any("externalLink" in name or "vbaproject.bin" in name.casefold() for name in names))
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            actual_sheets = {sheet.attrib["name"] for sheet in workbook.findall("./s:sheets/s:sheet", NS)}
            relations = {
                relation.attrib["Id"]: relation.attrib["Target"]
                for relation in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            }
            sheet_names = {
                "xl/" + relations[sheet.attrib[f"{{{NS['r']}}}id"]]: sheet.attrib["name"]
                for sheet in workbook.findall("./s:sheets/s:sheet", NS)
            }
            self.assertEqual(actual_sheets.intersection(ROLE_SHEETS), expected_sheets)
            self.assertTrue({"MATCH_RESULTS", "SOURCE_INDEX", "RUN_LOG"}.issubset(actual_sheets))
            all_text = []
            for name in names:
                if name.endswith(".rels"):
                    self.assertNotIn(b'TargetMode="External"', archive.read(name))
                if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                    sheet = ET.fromstring(archive.read(name))
                    self.assertEqual(sheet.findall(".//s:f", NS), [])
                    self.assertIsNotNone(sheet.find("./s:autoFilter", NS))
                    self.assertIsNotNone(sheet.find("./s:sheetViews/s:sheetView/s:pane", NS))
                    self.assertEqual(sheet.find("./s:pageSetup", NS).attrib["fitToWidth"], "1")
                    self.assertEqual(sheet.find("./s:pageSetup", NS).attrib["orientation"], "landscape")
                    sheet_name = sheet_names[name]
                    if sheet_name in expected_rows:
                        rows = sheet.findall("./s:sheetData/s:row", NS)[1:]
                        observed_rows = {}
                        for row in rows:
                            cells = {
                                cell.attrib["r"].rstrip("0123456789"): cell
                                for cell in row.findall("./s:c", NS)
                            }
                            key = (cell_text(cells["A"]), cell_text(cells["E"]))
                            self.assertNotIn(key, observed_rows)
                            observed_rows[key] = cell_text(cells["F"])
                        # Reconcile every raw source field to its actual role
                        # worksheet, not merely to the JSON record counts.
                        self.assertEqual(observed_rows, expected_rows[sheet_name])
                    for cell in sheet.findall(".//s:c", NS):
                        text = cell_text(cell)
                        all_text.append(text)
                        if text.startswith("000"):
                            self.assertEqual(cell.attrib.get("t"), "inlineStr")
            self.assertTrue(any(text.startswith("000") for text in all_text))
            self.assertIn("'" + FORMULA_TEXT, all_text)

    def exact_profile(self, profile: str) -> None:
        documents, rule_ids, role_sheets, expected_fields = exact_reconciliation_case(profile)
        snapshots = {}
        for platform in PLATFORMS:
            with self.subTest(platform=platform, profile=profile):
                root = self.workspace(platform)
                output, manifest, result, package, records, _ = self.workflow(platform, root, profile, documents)
                self.assertEqual(manifest["status"], WORKFLOW_READINESS_STATUS)
                self.assertEqual(result["status"], "PASS")
                self.assertEqual({link["rule_id"] for link in result["links"]}, rule_ids)
                self.assertEqual(len(result["links"]), len(rule_ids))
                self.assertEqual({link["status"] for link in result["links"]}, {"EXACT_MATCH"})
                self.assertNotEqual(package["human_approval_status"], "APPROVED")
                by_role = {record["role"]: record for record in records}
                self.assertEqual(set(by_role), set(role_sheets))
                for role, fields in expected_fields.items():
                    for field, expected in fields.items():
                        self.assertEqual(by_role[role]["fields"][field], expected)
                self.assert_workbook_safety(output, role_sheets, documents, records)
                snapshots[platform] = tree_hashes(output)
        self.assert_same_outputs(snapshots)

    def test_packaged_pr_po_exact(self) -> None:
        self.exact_profile("PR_PO")

    def test_packaged_pr_po_grn_invoice_exact(self) -> None:
        self.exact_profile("PR_PO_GRN_INVOICE")

    def test_packaged_invoice_payment_request_bank_exact(self) -> None:
        self.exact_profile("INVOICE_PAYMENT_BANK_SETTLEMENT")

    def test_packaged_outbound_issue_customer_receipt_exact(self) -> None:
        self.exact_profile("OUTBOUND_INVOICE_GOODS_ISSUE_CUSTOMER_RECEIPT")

    def test_packaged_inventory_count_book_stock_exact(self) -> None:
        self.exact_profile("INVENTORY_COUNT_BOOK_STOCK")

    def test_packaged_contract_acceptance_invoice_request_default_branch(self) -> None:
        self.exact_profile("CONTRACT_ACCEPTANCE_INVOICE_PAYMENT_REQUEST")

    def split_partial(self, *, overallocated: bool) -> None:
        quantities = ("60", "50") if overallocated else ("40", "60")
        documents = [fixture_document("po")]
        for index, quantity in enumerate(quantities):
            receipt, invoice = fixture_document("grn"), fixture_document("invoice")
            receipt["document_id"] = f"GRN-00077{7 + index}"
            receipt["fields"].update(grn_number=f"00077{7 + index}", delivered_quantity=quantity)
            invoice["document_id"] = f"INV-00088{8 + index}"
            invoice["fields"].update(
                invoice_number=f"00088{8 + index}", grn_number=f"00077{7 + index}",
                quantity=quantity, total_amount=str(Decimal(quantity) * 10),
            )
            documents.extend([receipt, invoice])
        policy = read_json(FIXTURES / "phase2-reconciliation/approved-partial-policy.json")
        snapshots = {}
        for platform in PLATFORMS:
            with self.subTest(platform=platform, overallocated=overallocated):
                root = self.workspace(platform)
                output, manifest, result, package, records, _ = self.workflow(
                    platform, root, "PO_GRN_INVOICE", documents, policy,
                )
                self.assertEqual(Counter(record["role"] for record in records), {"PO": 1, "GRN": 2, "INVOICE": 2})
                self.assertEqual(sum(Decimal(record["fields"]["quantity"]) for record in records if record["role"] == "GRN"), Decimal("110" if overallocated else "100"))
                self.assertEqual(sum(Decimal(record["fields"]["amount"]) for record in records if record["role"] == "INVOICE"), Decimal("1100" if overallocated else "1000"))
                if overallocated:
                    self.assertEqual(manifest["status"], "READY_FOR_HUMAN_REVIEW")
                    self.assertIn("PARTIAL_OVER_ALLOCATION", {item["discrepancy_code"] for item in result["discrepancies"]})
                    affected = [link for link in result["links"] if link["rule_id"] in {"po-to-grn", "po-to-invoice"}]
                    self.assertTrue(affected)
                    self.assertEqual({link["status"] for link in affected}, {"HUMAN_REVIEW_REQUIRED"})
                else:
                    self.assertEqual(manifest["status"], WORKFLOW_READINESS_STATUS)
                    self.assertEqual(result["status"], "PASS_WITH_WARNINGS")
                    self.assertEqual(Counter((link["rule_id"], link["status"]) for link in result["links"]), {
                        ("po-to-grn", "PARTIAL_MATCH"): 2,
                        ("po-to-invoice", "PARTIAL_MATCH"): 2,
                        ("grn-to-invoice", "EXACT_MATCH"): 2,
                    })
                    self.assertEqual(len(result["allocations"]), 6)
                    self.assertEqual(package["status"], "READY_FOR_HUMAN_REVIEW")
                self.assert_workbook_safety(
                    output, {"PO": "PURCHASE_ORDERS", "GRN": "GOODS_RECEIPTS", "INVOICE": "INVOICES"},
                    documents, records,
                )
                snapshots[platform] = tree_hashes(output)
        self.assert_same_outputs(snapshots)

    def test_packaged_two_receipts_two_invoices_approved_partial(self) -> None:
        self.split_partial(overallocated=False)

    def test_packaged_two_receipts_two_invoices_overallocation_requires_review(self) -> None:
        self.split_partial(overallocated=True)

    def test_packaged_reconciliation_refuses_overwrite_without_changing_output(self) -> None:
        documents, _, _, _ = exact_reconciliation_case("PR_PO")
        for platform in PLATFORMS:
            with self.subTest(platform=platform):
                root = self.workspace(platform)
                output, _, _, _, _, args = self.workflow(platform, root, "PR_PO", documents)
                before = tree_hashes(output)
                completed = self.run_helper(platform, root, "prepare_reconciliation_workbook.py", *args, returncode=2)
                self.assertIn("refusing overwrite", completed.stderr)
                self.assertEqual(tree_hashes(output), before)

    def test_archive_preflight_rejects_unsafe_paths_types_and_collisions(self) -> None:
        root = self.workspace("preflight")
        cases = {
            "traversal": [(f"{SKILL_ID}/../escape", stat.S_IFREG | 0o644)],
            "absolute": [(f"/{SKILL_ID}/escape", stat.S_IFREG | 0o644)],
            "backslash": [(f"{SKILL_ID}/bad\\name", stat.S_IFREG | 0o644)],
            "symlink": [(f"{SKILL_ID}/link", stat.S_IFLNK | 0o777)],
            "case-collision": [(f"{SKILL_ID}/A", stat.S_IFREG | 0o644), (f"{SKILL_ID}/a", stat.S_IFREG | 0o644)],
            "prefix-collision": [(f"{SKILL_ID}/a", stat.S_IFREG | 0o644), (f"{SKILL_ID}/a/b", stat.S_IFREG | 0o644)],
        }
        for name, members in cases.items():
            with self.subTest(case=name):
                path = root / f"{name}.zip"
                with zipfile.ZipFile(path, "w") as archive:
                    for member_name, mode in members:
                        info = zipfile.ZipInfo(member_name, ARCHIVE_TIMESTAMP)
                        info.create_system = 3
                        info.external_attr = mode << 16
                        archive.writestr(info, b"synthetic unsafe-archive fixture")
                with self.assertRaises(ValueError):
                    safe_archive_payload(path, sha256(path.read_bytes()))
        self.assertFalse((root / "escape").exists())


if __name__ == "__main__":
    unittest.main()
