#!/usr/bin/env python3
"""Validate supplied QA contracts using the known vocabulary, without installs.

Ruby/Psych parses the locally installed YAML schemas. The existing repository
validator supplies its documented subset; this adapter adds local URN refs,
contains and prefixItems. This is not independent/full Draft 2020-12 assurance.
The source validator and the supplied schema files are never modified.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SPEC = importlib.util.spec_from_file_location(
    "phase3_record_validator", ROOT / "thien-skill-document-evidence/scripts/validate_records.py"
)
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)
FILES = {
    "qa-intake.json": "qa-intake.schema.yaml",
    "artifact-inventory.json": "artifact-inventory.schema.yaml",
    "review-plan.json": "qa-review-plan.schema.yaml",
    "review-record.json": "review-record.schema.yaml",
    "disposition.json": "qa-disposition-handoff.schema.yaml",
}
KNOWN = {
    "$schema", "$id", "$ref", "$defs", "title", "description", "default", "examples",
    "type", "const", "enum", "allOf", "anyOf", "oneOf", "not", "if", "then", "else",
    "properties", "additionalProperties", "required", "minProperties", "maxProperties",
    "items", "prefixItems", "contains", "minItems", "maxItems", "uniqueItems",
    "minLength", "maxLength", "pattern", "format", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
}


def check_vocabulary(schema: object) -> None:
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise ValueError("Schema node must be an object or boolean")
    unsupported = set(schema) - KNOWN
    if unsupported:
        raise ValueError(f"Unsupported schema keywords: {sorted(unsupported)}")
    for key in ("$defs", "properties"):
        for child in schema.get(key, {}).values():
            check_vocabulary(child)
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        for child in schema.get(key, []):
            check_vocabulary(child)
    for key in ("not", "if", "then", "else", "additionalProperties", "items", "contains"):
        if key in schema:
            check_vocabulary(schema[key])


class ContractValidator(CORE.InternalSchemaValidator):
    def __init__(self, schema: dict, documents: dict):
        self.schema_path = schema["$id"]
        self.schema_root = HERE
        self.max_errors = 200
        self.documents = documents

    def _resolve_ref(self, raw_ref, current_path):
        document_id, separator, fragment = raw_ref.partition("#")
        document_id = document_id or current_path
        if document_id not in self.documents:
            raise ValueError(f"Schema reference not in supplied local registry: {raw_ref}")
        return CORE.pointer_get(self.documents[document_id], "#" + fragment if separator else "#"), document_id

    def _validate(self, instance, raw_schema, path, current_path, errors, depth):
        schema = raw_schema
        if isinstance(schema, dict) and isinstance(instance, list):
            if "contains" in schema and not any(
                not self._branch_errors(item, schema["contains"], f"{path}[{i}]", current_path, depth)
                for i, item in enumerate(instance)
            ):
                errors.append(self._error(path, "contains", "array contains no matching item"))
            if "prefixItems" in schema:
                prefix = schema["prefixItems"]
                for index, item in enumerate(instance):
                    rule = prefix[index] if index < len(prefix) else schema.get("items", True)
                    self._validate(item, rule, f"{path}[{index}]", current_path, errors, depth + 1)
                schema = {key: value for key, value in schema.items() if key not in {"prefixItems", "items"}}
        super()._validate(instance, schema, path, current_path, errors, depth)


def validate(template_dir: Path) -> dict:
    paths = [template_dir / name for name in (*FILES.values(), "common-definitions.schema.yaml")]
    command = [
        "ruby", "-ryaml", "-rjson", "-e",
        "puts JSON.generate(ARGV.map { |p| YAML.safe_load(File.read(p), permitted_classes: [], permitted_symbols: [], aliases: false) })",
        *map(str, paths),
    ]
    loaded = json.loads(subprocess.run(command, check=True, capture_output=True, text=True, timeout=15).stdout)
    documents = {schema["$id"]: schema for schema in loaded}
    if len(documents) != len(loaded):
        raise ValueError("Duplicate schema IDs")
    for schema in loaded:
        check_vocabulary(schema)
    by_file = dict(zip(FILES, loaded))
    parsed = {name: CORE.load_json_bytes((HERE / name).read_bytes(), label=name) for name in FILES}
    errors = {name: ContractValidator(by_file[name], documents).validate(parsed[name]) for name in FILES}
    if any(errors.values()):
        raise AssertionError(json.dumps(errors, ensure_ascii=False, indent=2))

    # Negative controls for conditional semantics added by this adapter.
    cases = []
    invalid = copy.deepcopy(parsed["qa-intake.json"])
    invalid["requested_actions"].append("remediate")
    cases.append(("remediation_without_authority", "qa-intake.json", invalid))
    invalid = copy.deepcopy(parsed["review-plan.json"])
    invalid["control_overlays"] = ["unknown_overlay"]
    cases.append(("invalid_prefix_item", "review-plan.json", invalid))
    invalid = copy.deepcopy(parsed["review-plan.json"])
    invalid["control_overlays"].append("security_privacy_confidentiality")
    cases.append(("additional_prefix_item", "review-plan.json", invalid))
    invalid = copy.deepcopy(parsed["disposition.json"])
    invalid["conditions"] = []
    cases.append(("conditional_readiness_without_conditions", "disposition.json", invalid))
    invalid = copy.deepcopy(parsed["disposition.json"])
    invalid["approval_status"] = "approved_by_authorized_human"
    cases.append(("approval_without_actor_or_record", "disposition.json", invalid))
    for label, name, value in cases:
        if not ContractValidator(by_file[name], documents).validate(value):
            raise AssertionError(f"Negative control was accepted: {label}")
    return {
        "status": "PASS", "contracts_checked": list(FILES), "negative_controls_rejected": len(cases),
        "method": "Existing subset validator + local URN/contains/prefixItems adapter; Ruby YAML parser",
        "limitations": [
            "Not an independent standards-conformance validator or full Draft 2020-12 certification.",
            "URI-reference format is annotation-only; no source_uri instance is used in these records.",
            "PyYAML/jsonschema unavailable; no dependencies were installed.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--templates", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.templates.resolve(strict=True)), ensure_ascii=False, indent=2))
