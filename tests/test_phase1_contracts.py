"""Contract tests for the additive Phase 1 task, content, artifact and RAG schemas."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "thien-skill-document-evidence"
SCHEMAS = SKILL / "schemas"


def load_validator_module():
    path = SKILL / "scripts" / "validate_records.py"
    spec = importlib.util.spec_from_file_location("phase1_contract_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load validator from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VALIDATE = load_validator_module()


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def validator(name: str):
    return VALIDATE.InternalSchemaValidator(SCHEMAS / "common" / name, SCHEMAS)


def checksum(digest_character: str = "a") -> dict[str, object]:
    return {
        "algorithm": "SHA-256",
        "digest": digest_character * 64,
        "computed_at": "UNKNOWN",
        "object_role": "DERIVATIVE",
    }


def provenance(*, captured: bool = False) -> dict[str, object]:
    return {
        "source_page": 1,
        "source_region": "page-1",
        "source_snippet": "Source text",
        "geometry_status": "CAPTURED" if captured else "NOT_AVAILABLE",
        "bounding_box": (
            {
                "coordinate_system": "PDF_POINT",
                "x": 10,
                "y": 20,
                "width": 200,
                "height": 30,
                "page_width": 612,
                "page_height": 792,
            }
            if captured
            else None
        ),
    }


def rag_file(path: str, media_type: str) -> dict[str, object]:
    return {
        "path": path,
        "media_type": media_type,
        "creation_status": "CREATED",
        "qa_status": "PASS",
        "checksum": checksum(),
        "limitations": [],
    }


def rag_document(document_id: str = "doc-001") -> dict[str, object]:
    return {
        "document_id": document_id,
        "directory": document_id,
        "status": "PASS",
        "document_markdown": rag_file("document.md", "text/markdown"),
        "metadata": rag_file("metadata.json", "application/json"),
        "manifest": rag_file("manifest.json", "application/json"),
        "assets": [],
        "chunks": None,
        "limitations": [],
    }


def semantic_content_errors(content: dict[str, object]) -> list[str]:
    """Model the semantic checks named by the Phase 1 canonical contract."""

    errors: list[str] = []
    blocks = content.get("blocks")
    if not isinstance(blocks, list):
        return ["blocks must be a list"]

    block_ids = [block.get("block_id") for block in blocks]
    reading_order = [block.get("reading_order") for block in blocks]
    if len(block_ids) != len(set(block_ids)):
        errors.append("block_id values must be unique")
    if len(reading_order) != len(set(reading_order)):
        errors.append("reading_order values must be unique")
    if any(
        not isinstance(left, int)
        or not isinstance(right, int)
        or left >= right
        for left, right in zip(reading_order, reading_order[1:])
    ):
        errors.append("reading_order must be strictly increasing in array order")

    known_ids = {value for value in block_ids if isinstance(value, str)}
    parents = {
        block.get("block_id"): block.get("parent_block_id")
        for block in blocks
        if isinstance(block.get("block_id"), str)
    }
    for block_id, parent_id in parents.items():
        if parent_id is not None and parent_id not in known_ids:
            errors.append(f"dangling parent_block_id for {block_id}")
            continue
        seen = {block_id}
        cursor = parent_id
        while cursor is not None:
            if cursor in seen:
                errors.append(f"cyclic parent_block_id for {block_id}")
                break
            seen.add(cursor)
            cursor = parents.get(cursor)

    for block in blocks:
        if block.get("block_type") == "CAPTION":
            if block.get("target_block_id") not in known_ids:
                errors.append(f"dangling caption target for {block.get('block_id')}")
        if block.get("block_type") == "TABLE":
            columns = block.get("columns")
            rows = block.get("rows")
            if isinstance(columns, list) and isinstance(rows, list):
                if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
                    errors.append(f"table row width mismatch for {block.get('block_id')}")
        provenance_value = block.get("provenance")
        if not isinstance(provenance_value, dict):
            continue
        box = provenance_value.get("bounding_box")
        if isinstance(box, dict):
            if box.get("x", 0) + box.get("width", 0) > box.get("page_width", 0):
                errors.append(f"horizontal bounding-box overflow for {block.get('block_id')}")
            if box.get("y", 0) + box.get("height", 0) > box.get("page_height", 0):
                errors.append(f"vertical bounding-box overflow for {block.get('block_id')}")
    return errors


class Phase1ContractTests(unittest.TestCase):
    COMPANION_SCHEMAS = {
        "task-request.schema.json",
        "canonical-content.schema.json",
        "artifact-manifest.schema.json",
        "rag-package.schema.json",
    }

    def test_companion_schemas_are_additive_and_independently_versioned(self) -> None:
        common = SCHEMAS / "common"
        for name in sorted(self.COMPANION_SCHEMAS):
            with self.subTest(name=name):
                schema = load_json(common / name)
                self.assertEqual(schema["$id"], name)
                self.assertEqual(
                    schema["properties"]["schema_version"]["const"], "1.0.0"
                )
                self.assertEqual(
                    schema["properties"]["skill_id"]["const"],
                    "thien-skill-document-evidence",
                )
                self.assertIn("skill_release_version", schema["required"])

        extraction = load_json(common / "extraction-package.schema.json")
        reconciliation = load_json(common / "reconciliation-config.schema.json")
        self.assertEqual(
            extraction["properties"]["schema_version"]["const"], "1.0.0"
        )
        self.assertNotIn("skill_release_version", extraction["properties"])
        extraction_validator = validator("extraction-package.schema.json")
        legacy_package = load_json(ROOT / "tests" / "fixtures" / "workbook-package.json")
        self.assertEqual(extraction_validator.validate(legacy_package), [])
        release_aware_package = copy.deepcopy(legacy_package)
        release_aware_package["run_manifest"]["tool_versions"][
            "thien-skill-document-evidence"
        ] = "1.2.0"
        self.assertEqual(extraction_validator.validate(release_aware_package), [])
        invalid_top_level_release = copy.deepcopy(release_aware_package)
        invalid_top_level_release["skill_release_version"] = "1.2.0"
        self.assertTrue(extraction_validator.validate(invalid_top_level_release))
        self.assertEqual(
            reconciliation["properties"]["schema_version"]["const"], "1.0.0"
        )
        legacy = load_json(SCHEMAS / "document-types" / "payment-bank.json")
        self.assertEqual(legacy["document_type"], "PAYMENT_BANK_DOCUMENT")
        self.assertEqual(legacy["version"], "1.0.0")

        task_schema = load_json(common / "task-request.schema.json")
        self.assertEqual(
            task_schema["properties"]["task_profile"]["enum"],
            [
                "CONVERT_DOCUMENT",
                "PREPARE_RAG_SOURCE",
                "RECONCILE_DOCUMENT_SET",
            ],
        )
        role_schema = task_schema["$defs"]["reconciliationRequest"]["properties"][
            "document_roles"
        ]["items"]["properties"]["role_id"]
        self.assertNotIn("enum", role_schema)

    def test_phase1_behavioral_catalog_is_complete_and_specification_only(self) -> None:
        catalog = load_json(ROOT / "tests" / "behavioral_cases.json")
        self.assertEqual(catalog["skill_version"], "1.2.0")
        self.assertEqual(catalog["catalog_status"], "SPECIFICATION_ONLY")
        cases = catalog["cases"]
        self.assertEqual(
            [case["scenario_id"] for case in cases],
            [f"DE-{number:03d}" for number in range(1, 65)],
        )
        self.assertTrue(
            all(case["execution_status"] == "NOT_TESTED" for case in cases)
        )

    def test_new_document_profiles_validate_and_are_internally_consistent(self) -> None:
        profile_validator = VALIDATE.InternalSchemaValidator(
            SCHEMAS / "common" / "document-profile.schema.json", SCHEMAS
        )
        expected = {
            "purchase-requisition.json": "PURCHASE_REQUISITION",
            "payment-request.json": "PAYMENT_REQUEST",
            "bank-statement.json": "BANK_STATEMENT",
        }
        for name, document_type in expected.items():
            with self.subTest(name=name):
                profile = load_json(SCHEMAS / "document-types" / name)
                self.assertEqual(profile_validator.validate(profile), [])
                self.assertEqual(profile["document_type"], document_type)
                self.assertEqual(profile["version"], "1.0.0")

                header = {
                    definition["field_name"]: definition
                    for definition in profile["field_definitions"]
                }
                lines = {
                    definition["field_name"]: definition
                    for definition in profile["line_item_definitions"]
                }
                self.assertEqual(
                    set(header),
                    set(profile["required_fields"]) | set(profile["optional_fields"]),
                )
                self.assertFalse(
                    set(profile["required_fields"]) & set(profile["optional_fields"])
                )
                for field_name in profile["required_fields"]:
                    self.assertTrue(header[field_name]["required"], field_name)
                for field_name in profile["optional_fields"]:
                    self.assertFalse(header[field_name]["required"], field_name)
                known_fields = set(header) | set(lines)
                for rule in profile["validation_rules"]:
                    self.assertTrue(set(rule["fields"]) <= known_fields, rule["rule_id"])
                for key in profile["reconciliation_keys"]:
                    self.assertTrue(set(key["fields"]) <= known_fields, key["key_id"])

    def test_task_profiles_are_exclusive_and_matching_roles_are_extensible(self) -> None:
        task_validator = validator("task-request.schema.json")
        conversion = {
            "schema_version": "1.0.0",
            "skill_id": "thien-skill-document-evidence",
            "skill_release_version": "1.1.0-rc.2",
            "request_id": "request-convert-001",
            "task_profile": "CONVERT_DOCUMENT",
            "source_document_ids": ["doc-001"],
            "conversion": {
                "output_format": "DOCX",
                "output_profile": "SEMANTIC_EDITABLE",
                "presentation_intent": "NOT_APPLICABLE",
                "ambiguity_status": "NOT_AMBIGUOUS",
            },
            "rag": None,
            "reconciliation": None,
            "requested_by": None,
            "assumptions": [],
            "limitations": [],
        }
        self.assertEqual(task_validator.validate(conversion), [])

        wrong_default = copy.deepcopy(conversion)
        wrong_default["conversion"]["output_profile"] = "STRUCTURED_DATA"
        self.assertTrue(task_validator.validate(wrong_default))

        reconciliation = {
            "schema_version": "1.0.0",
            "skill_id": "thien-skill-document-evidence",
            "skill_release_version": "1.1.0-rc.2",
            "request_id": "request-reconcile-001",
            "task_profile": "RECONCILE_DOCUMENT_SET",
            "source_document_ids": ["sales-invoice-001", "issue-001", "pod-001"],
            "conversion": None,
            "rag": None,
            "reconciliation": {
                "matching_profile_id": "profile.outbound-fulfilment-v1",
                "document_roles": [
                    {"document_id": "sales-invoice-001", "role_id": "OUTBOUND_INVOICE"},
                    {"document_id": "issue-001", "role_id": "GOODS_ISSUE"},
                    {"document_id": "pod-001", "role_id": "CUSTOMER_RECEIPT"},
                ],
                "role_registry_reference": "roles/customer-fulfilment.json",
                "config_reference": "config/outbound-match.json",
            },
            "requested_by": "reviewer-001",
            "assumptions": [],
            "limitations": [],
        }
        self.assertEqual(task_validator.validate(reconciliation), [])

        mixed_profile = copy.deepcopy(reconciliation)
        mixed_profile["conversion"] = conversion["conversion"]
        self.assertTrue(task_validator.validate(mixed_profile))

        ambiguous_pptx = copy.deepcopy(conversion)
        ambiguous_pptx["conversion"] = {
            "output_format": "PPTX",
            "output_profile": None,
            "presentation_intent": "AMBIGUOUS",
            "ambiguity_status": "CLARIFICATION_REQUIRED",
        }
        self.assertEqual(task_validator.validate(ambiguous_pptx), [])
        ambiguous_pptx["conversion"]["output_profile"] = "EDITABLE_PRESENTATION"
        self.assertTrue(task_validator.validate(ambiguous_pptx))

        presentation = copy.deepcopy(conversion)
        presentation["conversion"] = {
            "output_format": "PPTX",
            "output_profile": "EDITABLE_PRESENTATION",
            "presentation_intent": "PRESENTATION",
            "ambiguity_status": "NOT_AMBIGUOUS",
        }
        self.assertEqual(task_validator.validate(presentation), [])
        presentation["conversion"]["output_profile"] = "PAGE_AS_SLIDE"
        self.assertTrue(task_validator.validate(presentation))

        faithful = copy.deepcopy(conversion)
        faithful["conversion"] = {
            "output_format": "PPTX",
            "output_profile": "PAGE_AS_SLIDE",
            "presentation_intent": "FAITHFUL_PAGE_CONVERSION",
            "ambiguity_status": "NOT_AMBIGUOUS",
        }
        self.assertEqual(task_validator.validate(faithful), [])
        faithful["conversion"]["output_profile"] = "EDITABLE_PRESENTATION"
        self.assertTrue(task_validator.validate(faithful))

        fidelity = copy.deepcopy(conversion)
        fidelity["conversion"] = {
            "output_format": "PPTX",
            "output_profile": "VISUAL_FIDELITY_BEST_EFFORT",
            "presentation_intent": "VISUAL_FIDELITY",
            "ambiguity_status": "NOT_AMBIGUOUS",
        }
        self.assertEqual(task_validator.validate(fidelity), [])

        pptx_without_presentation_intent = copy.deepcopy(fidelity)
        pptx_without_presentation_intent["conversion"]["presentation_intent"] = (
            "NOT_APPLICABLE"
        )
        self.assertTrue(task_validator.validate(pptx_without_presentation_intent))

        invalid_release = copy.deepcopy(conversion)
        invalid_release["skill_release_version"] = "release-candidate"
        self.assertTrue(task_validator.validate(invalid_release))

    def test_canonical_content_supports_semantics_order_and_conditional_geometry(self) -> None:
        content_validator = validator("canonical-content.schema.json")
        content = {
            "schema_version": "1.0.0",
            "skill_id": "thien-skill-document-evidence",
            "skill_release_version": "1.1.0-rc.2",
            "content_id": "content-001",
            "document_id": "doc-001",
            "source_content_id": f"sha256:{'b' * 64}",
            "source_hash_status": "COMPUTED_ORIGINAL_BYTES",
            "fidelity_mode": "SEMANTIC",
            "reading_order_status": "VERIFIED",
            "structural_validation_status": "PASS",
            "blocks": [
                {
                    "block_id": "block-001",
                    "block_type": "HEADING",
                    "reading_order": 1,
                    "parent_block_id": None,
                    "text": "Heading",
                    "level": 1,
                    "provenance": provenance(captured=True),
                },
                {
                    "block_id": "block-002",
                    "block_type": "PARAGRAPH",
                    "reading_order": 2,
                    "parent_block_id": "block-001",
                    "text": "Paragraph text.",
                    "provenance": provenance(),
                },
                {
                    "block_id": "block-003",
                    "block_type": "TABLE",
                    "reading_order": 3,
                    "parent_block_id": "block-001",
                    "columns": ["Item", "Amount"],
                    "rows": [["A", "100"], ["B", None]],
                    "provenance": provenance(),
                },
                {
                    "block_id": "block-004",
                    "block_type": "IMAGE",
                    "reading_order": 4,
                    "parent_block_id": "block-001",
                    "asset_reference": "assets/figure-1.png",
                    "media_type": "image/png",
                    "asset_checksum": checksum("c"),
                    "alt_text": "Chart",
                    "provenance": provenance(),
                },
                {
                    "block_id": "block-005",
                    "block_type": "CAPTION",
                    "reading_order": 5,
                    "parent_block_id": "block-001",
                    "text": "Figure 1",
                    "target_block_id": "block-004",
                    "provenance": provenance(),
                },
            ],
            "limitations": [],
        }
        self.assertEqual(content_validator.validate(content), [])
        self.assertEqual(semantic_content_errors(content), [])
        self.assertEqual(
            [block["reading_order"] for block in content["blocks"]], [1, 2, 3, 4, 5]
        )

        invalid_geometry = copy.deepcopy(content)
        invalid_geometry["blocks"][0]["provenance"]["bounding_box"] = None
        self.assertTrue(content_validator.validate(invalid_geometry))

        incomplete_table = copy.deepcopy(content)
        del incomplete_table["blocks"][2]["rows"]
        self.assertTrue(content_validator.validate(incomplete_table))

        unsafe_asset_path = copy.deepcopy(content)
        unsafe_asset_path["blocks"][3]["asset_reference"] = "file:/tmp/figure.png"
        self.assertTrue(content_validator.validate(unsafe_asset_path))

        geometry_aware = copy.deepcopy(content)
        geometry_aware["fidelity_mode"] = "GEOMETRY_AWARE"
        for block in geometry_aware["blocks"]:
            block["provenance"] = provenance(captured=True)
        self.assertEqual(content_validator.validate(geometry_aware), [])
        geometry_aware["blocks"][1]["provenance"] = provenance()
        self.assertTrue(content_validator.validate(geometry_aware))

        missing_page_dimensions = copy.deepcopy(content)
        del missing_page_dimensions["blocks"][0]["provenance"]["bounding_box"][
            "page_width"
        ]
        self.assertTrue(content_validator.validate(missing_page_dimensions))

        invalid_normalized = copy.deepcopy(content)
        invalid_normalized["blocks"][0]["provenance"]["bounding_box"] = {
            "coordinate_system": "NORMALIZED_0_1",
            "x": 1.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.2,
            "page_width": 1,
            "page_height": 1,
        }
        self.assertTrue(content_validator.validate(invalid_normalized))

        unavailable_hash = copy.deepcopy(content)
        unavailable_hash["source_hash_status"] = "UNAVAILABLE"
        unavailable_hash["source_content_id"] = None
        unavailable_hash["limitations"] = [
            "The host exposed no stable byte representation for hashing."
        ]
        self.assertEqual(content_validator.validate(unavailable_hash), [])
        unavailable_hash["limitations"] = []
        self.assertTrue(content_validator.validate(unavailable_hash))

        accessible_hash = copy.deepcopy(content)
        accessible_hash["source_hash_status"] = "COMPUTED_ACCESSIBLE_REPRESENTATION"
        accessible_hash["limitations"] = [
            "SHA-256 covers the host-provided PDF representation, not original bytes."
        ]
        self.assertEqual(content_validator.validate(accessible_hash), [])
        accessible_hash["source_content_id"] = None
        self.assertTrue(content_validator.validate(accessible_hash))
        accessible_hash = copy.deepcopy(content)
        accessible_hash["source_hash_status"] = "COMPUTED_ACCESSIBLE_REPRESENTATION"
        self.assertTrue(content_validator.validate(accessible_hash))

        duplicate_order = copy.deepcopy(content)
        duplicate_order["blocks"][1]["reading_order"] = 1
        self.assertEqual(content_validator.validate(duplicate_order), [])
        self.assertTrue(semantic_content_errors(duplicate_order))

        dangling_parent = copy.deepcopy(content)
        dangling_parent["blocks"][1]["parent_block_id"] = "missing-block"
        self.assertTrue(semantic_content_errors(dangling_parent))

        cyclic_parent = copy.deepcopy(content)
        cyclic_parent["blocks"][0]["parent_block_id"] = "block-002"
        self.assertTrue(semantic_content_errors(cyclic_parent))

        bad_table_width = copy.deepcopy(content)
        bad_table_width["blocks"][2]["rows"][0] = ["A"]
        self.assertTrue(semantic_content_errors(bad_table_width))

        dangling_caption = copy.deepcopy(content)
        dangling_caption["blocks"][4]["target_block_id"] = "missing-block"
        self.assertTrue(semantic_content_errors(dangling_caption))

        overflow = copy.deepcopy(content)
        overflow["blocks"][0]["provenance"]["bounding_box"]["x"] = 500
        overflow["blocks"][0]["provenance"]["bounding_box"]["width"] = 200
        self.assertTrue(semantic_content_errors(overflow))

    def test_artifact_manifest_covers_all_phase1_formats_and_statuses(self) -> None:
        artifact_validator = validator("artifact-manifest.schema.json")
        media_types = {
            "JSON": "application/json",
            "JSONL": "application/x-ndjson",
            "CSV": "text/csv",
            "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "PARQUET": "application/vnd.apache.parquet",
            "MD": "text/markdown",
            "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "PPTX": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        manifest = {
            "schema_version": "1.0.0",
            "skill_id": "thien-skill-document-evidence",
            "skill_release_version": "1.1.0-rc.2",
            "manifest_id": "manifest-001",
            "package_id": "package-001",
            "task_profile": "CONVERT_DOCUMENT",
            "generated_at": "UNKNOWN",
            "status": "PASS_WITH_WARNINGS",
            "artifacts": [
                {
                    "artifact_id": f"artifact-{index:03d}",
                    "artifact_role": "PRIMARY_CONTENT",
                    "format": artifact_format,
                    "media_type": media_type,
                    "location_reference": f"outputs/file-{index:03d}.{artifact_format.lower()}",
                    "checksum": checksum("d"),
                    "creation_status": "CREATED",
                    "qa_status": "NOT_TESTED",
                    "record_count": None,
                    "source_document_ids": ["doc-001"],
                    "limitations": [],
                }
                for index, (artifact_format, media_type) in enumerate(
                    media_types.items(), start=1
                )
            ],
            "limitations": ["Visual fidelity was not independently reviewed."],
            "human_review_status": "REQUIRED",
        }
        self.assertEqual(artifact_validator.validate(manifest), [])
        self.assertEqual(
            {artifact["format"] for artifact in manifest["artifacts"]}, set(media_types)
        )

        contradictory = copy.deepcopy(manifest)
        contradictory["artifacts"][0]["creation_status"] = "NOT_CREATED"
        self.assertTrue(artifact_validator.validate(contradictory))

        pass_without_qa = copy.deepcopy(manifest)
        pass_without_qa["status"] = "PASS"
        self.assertTrue(artifact_validator.validate(pass_without_qa))

        fully_validated = copy.deepcopy(manifest)
        fully_validated["status"] = "PASS"
        for artifact in fully_validated["artifacts"]:
            artifact["qa_status"] = "PASS"
        self.assertEqual(artifact_validator.validate(fully_validated), [])

        empty_sources = copy.deepcopy(manifest)
        empty_sources["artifacts"][0]["source_document_ids"] = []
        self.assertTrue(artifact_validator.validate(empty_sources))

        wrong_media_type = copy.deepcopy(manifest)
        wrong_media_type["artifacts"][0]["media_type"] = "text/plain"
        self.assertTrue(artifact_validator.validate(wrong_media_type))

        for unsafe_path in (
            "C:/temp/file.json",
            "./file.json",
            "a//file.json",
            "file:/tmp/payload",
            "https:payload",
            "name:stream",
            "CON.txt",
            "outputs/trailing.",
        ):
            with self.subTest(unsafe_path=unsafe_path):
                unsafe = copy.deepcopy(manifest)
                unsafe["artifacts"][0]["location_reference"] = unsafe_path
                self.assertTrue(artifact_validator.validate(unsafe))

    def test_rag_package_defaults_collection_manifest_and_optional_chunks(self) -> None:
        rag_validator = validator("rag-package.schema.json")
        package = {
            "schema_version": "1.0.0",
            "skill_id": "thien-skill-document-evidence",
            "skill_release_version": "1.1.0-rc.2",
            "package_id": "rag-package-001",
            "package_kind": "DOCUMENT",
            "status": "PASS",
            "documents": [rag_document()],
            "collection_manifest": None,
            "limitations": [],
        }
        self.assertEqual(rag_validator.validate(package), [])
        document = package["documents"][0]
        self.assertEqual(document["document_markdown"]["path"], "document.md")
        self.assertEqual(document["metadata"]["path"], "metadata.json")
        self.assertEqual(document["manifest"]["path"], "manifest.json")
        self.assertIsNone(document["chunks"])

        wrong_default = copy.deepcopy(package)
        wrong_default["documents"][0]["document_markdown"]["path"] = "source.md"
        self.assertTrue(rag_validator.validate(wrong_default))

        chunked = copy.deepcopy(package)
        chunked["documents"][0]["chunks"] = {
            "path": "chunks.jsonl",
            "media_type": "application/x-ndjson",
            "creation_status": "CREATED",
            "qa_status": "PASS",
            "checksum": checksum("e"),
            "target_id": "vector-store-a",
            "chunking_config_checksum": "f" * 64,
            "limitations": [],
        }
        self.assertEqual(rag_validator.validate(chunked), [])
        del chunked["documents"][0]["chunks"]["chunking_config_checksum"]
        self.assertTrue(rag_validator.validate(chunked))

        pending_chunk = copy.deepcopy(package)
        pending_chunk["documents"][0]["chunks"] = {
            "path": "chunks.jsonl",
            "media_type": "application/x-ndjson",
            "creation_status": "NOT_CREATED",
            "qa_status": "NOT_TESTED",
            "checksum": None,
            "target_id": "vector-store-a",
            "chunking_config_checksum": "f" * 64,
            "limitations": ["Chunk generation is pending."],
        }
        self.assertTrue(rag_validator.validate(pending_chunk))
        pending_chunk["status"] = "PASS_WITH_WARNINGS"
        pending_chunk["documents"][0]["status"] = "PASS_WITH_WARNINGS"
        self.assertEqual(rag_validator.validate(pending_chunk), [])

        pending_asset = copy.deepcopy(package)
        pending_asset["documents"][0]["assets"] = [
            {
                "path": "assets/figure-1.png",
                "media_type": "image/png",
                "creation_status": "NOT_CREATED",
                "qa_status": "NOT_TESTED",
                "checksum": None,
                "limitations": ["Asset extraction is pending."],
            }
        ]
        self.assertTrue(rag_validator.validate(pending_asset))

        collection = copy.deepcopy(package)
        collection["package_kind"] = "COLLECTION"
        collection["documents"].append(rag_document("doc-002"))
        collection["collection_manifest"] = rag_file(
            "collection-manifest.json", "application/json"
        )
        self.assertEqual(rag_validator.validate(collection), [])

        missing_required_file = copy.deepcopy(package)
        missing_required_file["documents"][0]["document_markdown"].update(
            {
                "creation_status": "NOT_CREATED",
                "qa_status": "NOT_TESTED",
                "checksum": None,
            }
        )
        self.assertTrue(rag_validator.validate(missing_required_file))
        missing_required_file["status"] = "PASS_WITH_WARNINGS"
        missing_required_file["documents"][0]["status"] = "PASS_WITH_WARNINGS"
        self.assertEqual(rag_validator.validate(missing_required_file), [])

        wrong_media_type = copy.deepcopy(package)
        wrong_media_type["documents"][0]["document_markdown"]["media_type"] = (
            "text/plain"
        )
        self.assertTrue(rag_validator.validate(wrong_media_type))

        for unsafe_directory in (
            "C:/temp",
            "./doc",
            "collection//doc",
            "file:/tmp/payload",
            "https:payload",
            "name:stream",
            "NUL",
            "collection/trailing ",
        ):
            with self.subTest(unsafe_directory=unsafe_directory):
                unsafe = copy.deepcopy(package)
                unsafe["documents"][0]["directory"] = unsafe_directory
                self.assertTrue(rag_validator.validate(unsafe))


if __name__ == "__main__":
    unittest.main()
