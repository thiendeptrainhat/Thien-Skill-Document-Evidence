#!/usr/bin/env python3
"""Prepare deterministic reconciliation inputs and a review workbook.

The helper inventories only requested JSON files below an authorized root,
isolates per-file parsing failures, classifies accessible structured records
against a declared matching profile, invokes the existing deterministic
reconciler, and publishes a no-overwrite workflow directory. It uses only the
Python standard library and bundled sibling helpers; it does not call a model,
network service, OCR engine, or external document processor.

Accepted source JSON is either a single structured document, an object with a
``documents`` array, or an existing canonical extraction package. A structured
document has ``document_id``, ``document_type`` and ``fields``. Field values may
be primitives or objects with raw_value, normalized_value, display_value,
data_type, provenance and human_review_required.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import ctypes
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import io
import errno
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from typing import Any, Iterable, Mapping, NamedTuple
import zipfile
from xml.sax.saxutils import escape as xml_escape


TOOL_NAME = "thien-reconciliation-workbook-preparer"
TOOL_VERSION = "1.0.0"
SCRIPT_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_ROOT.parent
SCHEMA_ROOT = SKILL_ROOT / "schemas"
PROFILE_ROOT = SKILL_ROOT / "assets" / "reconciliation-profiles"
PROFILE_SCHEMA = SCHEMA_ROOT / "common" / "matching-profile.schema.json"
EXTRACTION_SCHEMA = SCHEMA_ROOT / "common" / "extraction-package.schema.json"
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
FIELD_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DOCUMENT_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
DECIMAL_RE = re.compile(r"^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
FORMULA_PREFIXES = ("=", "+", "-", "@")
OUTPUT_STATUSES = [
    "EXACT_MATCH",
    "WITHIN_TOLERANCE",
    "STRONG_CANDIDATE",
    "PARTIAL_MATCH",
    "AMBIGUOUS_MATCH",
    "CONFLICTING_MATCH",
    "UNMATCHED",
    "NOT_APPLICABLE",
    "HUMAN_REVIEW_REQUIRED",
]
ALLOWED_DATA_TYPES = {
    "TEXT", "INTEGER", "DECIMAL", "PERCENTAGE", "CURRENCY_AMOUNT", "DATE",
    "DATETIME", "BOOLEAN", "IDENTIFIER", "BANK_ACCOUNT", "TAX_IDENTIFIER",
    "PHONE", "EMAIL", "ADDRESS", "QUANTITY", "UNIT_OF_MEASURE", "CLAUSE_TEXT",
    "REFERENCE", "LIST", "TABLE", "JSON_OBJECT",
}
NUMERIC_DATA_TYPES = {"INTEGER", "DECIMAL", "PERCENTAGE", "CURRENCY_AMOUNT", "QUANTITY"}
ALLOWED_DATA_CLASSIFICATIONS = {
    "PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "INVESTIGATION_RESTRICTED",
    "LEGAL_SENSITIVE", "PERSONAL_DATA", "SENSITIVE_PERSONAL_DATA", "HEALTH_DATA",
    "CHILD_RELATED_DATA", "SECURITY_SENSITIVE", "MARKET_SENSITIVE", "UNKNOWN",
}
SIMPLE_DOCUMENT_KEYS = {
    "schema_version", "document_id", "record_id", "document_type", "role", "fields",
    "evidence_ids", "source_reference", "data_classification", "limitations",
}
FIELD_VALUE_KEYS = {
    "raw_value", "normalized_value", "display_value", "data_type", "provenance",
    "human_review_required", "notes",
}


class WorkflowError(ValueError):
    """Raised for unsafe paths, invalid policy, or invalid workflow contracts."""


def _load_sibling(name: str, filename: str):
    path = SCRIPT_ROOT / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load bundled helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VALIDATE = _load_sibling("thien_phase2_validate_records", "validate_records.py")
RECONCILE = _load_sibling("thien_phase2_reconcile_records", "reconcile_records.py")


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def pretty_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_id(prefix: str, value: object, *, length: int = 24) -> str:
    return f"{prefix}-{sha256_bytes(canonical_json_bytes(value))[:length]}"


def _absolute_without_resolution(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def resolve_root(raw_root: str | Path) -> Path:
    supplied = Path(raw_root).expanduser()
    if supplied.is_symlink():
        raise WorkflowError(f"authorized root must not be a symlink: {supplied}")
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise WorkflowError(f"cannot resolve authorized root {supplied}: {exc}") from exc
    if not root.is_dir():
        raise WorkflowError(f"authorized root is not a directory: {supplied}")
    return root


def safe_path_below_root(
    root: Path,
    raw_path: str | Path,
    *,
    label: str,
    allow_missing_leaf: bool = False,
) -> Path:
    supplied = Path(raw_path).expanduser()
    lexical = supplied if supplied.is_absolute() else root / supplied
    lexical = _absolute_without_resolution(lexical)
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise WorkflowError(f"{label} escapes authorized root: {raw_path}") from exc
    cursor = root
    parts = relative.parts if not allow_missing_leaf else relative.parts[:-1]
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise WorkflowError(f"{label} must not traverse a symlink: {relative}")
    if lexical.is_symlink():
        raise WorkflowError(f"{label} must not be a symlink: {relative}")
    return lexical


def portable_reference(root: Path, path: Path) -> str:
    return PurePosixPath(path.relative_to(root).as_posix()).as_posix()


def read_regular_nofollow(path: Path, *, label: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise WorkflowError(f"{label} is not a regular file")
        handle = os.fdopen(descriptor, "rb")
        descriptor = -1
        with handle:
            return handle.read()
    except OSError as exc:
        raise WorkflowError(f"cannot safely read {label}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load_json_object_bytes(data: bytes, *, label: str) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate object key {key!r}")
            result[key] = value
        return result

    def reject_nonfinite(raw: str) -> object:
        raise ValueError(f"non-finite JSON number {raw!r}")

    try:
        return json.loads(
            data,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise WorkflowError(f"{label} must be valid UTF-8 JSON: {exc}") from exc


def load_profile(profile_id: str) -> tuple[dict[str, object], bytes, Path]:
    if not IDENTIFIER_RE.fullmatch(profile_id):
        raise WorkflowError("profile id is invalid")
    matches: list[tuple[dict[str, object], bytes, Path]] = []
    for path in sorted(PROFILE_ROOT.glob("*.json")):
        data = read_regular_nofollow(path, label=f"profile {path.name}")
        payload = load_json_object_bytes(data, label=f"profile {path.name}")
        if isinstance(payload, dict) and payload.get("profile_id") == profile_id:
            matches.append((payload, data, path))
    if len(matches) != 1:
        raise WorkflowError(f"expected exactly one bundled matching profile for {profile_id}, found {len(matches)}")
    profile, data, path = matches[0]
    validate_profile(profile)
    return profile, data, path


def load_custom_profile(root: Path, raw_path: str | Path) -> tuple[dict[str, object], bytes, Path]:
    path = safe_path_below_root(root, raw_path, label="profile")
    if not path.is_file():
        raise WorkflowError(f"profile is not a regular file: {raw_path}")
    data = read_regular_nofollow(path, label="profile")
    payload = load_json_object_bytes(data, label="profile")
    if not isinstance(payload, dict):
        raise WorkflowError("profile must be a JSON object")
    validate_profile(payload)
    return payload, data, path


def validate_profile(profile: Mapping[str, object]) -> None:
    validator = VALIDATE.InternalSchemaValidator(PROFILE_SCHEMA, SCHEMA_ROOT)
    errors = validator.validate(dict(profile))
    if errors:
        first = errors[0]
        raise WorkflowError(
            f"matching profile schema validation failed at {first['path']}: {first['message']}"
        )
    roles = profile["roles"]
    rules = profile["match_rules"]
    aggregations = profile["aggregation_rules"]
    assert isinstance(roles, list) and isinstance(rules, list) and isinstance(aggregations, list)
    role_by_id: dict[str, Mapping[str, object]] = {}
    sheets: set[str] = set()
    aliases: dict[str, str] = {}
    for raw_role in roles:
        assert isinstance(raw_role, dict)
        role_id = str(raw_role["role_id"])
        if role_id in role_by_id:
            raise WorkflowError(f"matching profile has duplicate role_id: {role_id}")
        sheet = str(raw_role["output_sheet"])
        if sheet in sheets:
            raise WorkflowError(f"matching profile has duplicate output_sheet: {sheet}")
        sheets.add(sheet)
        role_by_id[role_id] = raw_role
        variants = raw_role.get("field_mapping_variants", {})
        if not isinstance(variants, dict):
            raise WorkflowError(f"role {role_id}.field_mapping_variants must be an object")
        declared_types = {str(item) for item in raw_role["document_types"]}
        base_mappings = raw_role["field_mappings"]
        assert isinstance(base_mappings, dict)
        for document_type, variant in variants.items():
            if document_type not in declared_types:
                raise WorkflowError(f"role {role_id} has a mapping variant for undeclared document type {document_type}")
            if not isinstance(variant, dict) or not variant:
                raise WorkflowError(f"role {role_id}/{document_type} mapping variant must be a non-empty object")
            unknown_canonical = sorted(set(variant) - set(base_mappings))
            if unknown_canonical:
                raise WorkflowError(
                    f"role {role_id}/{document_type} variant maps undeclared canonical fields: {', '.join(unknown_canonical)}"
                )
        for alias in [role_id, *raw_role["role_aliases"]]:
            alias_text = str(alias)
            prior = aliases.get(alias_text)
            if prior is not None and prior != role_id:
                raise WorkflowError(f"role alias {alias_text} maps to multiple roles")
            aliases[alias_text] = role_id
    rule_ids: set[str] = set()
    for raw_rule in rules:
        assert isinstance(raw_rule, dict)
        rule_id = str(raw_rule["rule_id"])
        if rule_id in rule_ids:
            raise WorkflowError(f"matching profile has duplicate rule_id: {rule_id}")
        rule_ids.add(rule_id)
        left = str(raw_rule["left_role"])
        right = str(raw_rule["right_role"])
        if left not in role_by_id or right not in role_by_id or left == right:
            raise WorkflowError(f"rule {rule_id} references invalid roles")
        left_mappings = role_by_id[left]["field_mappings"]
        right_mappings = role_by_id[right]["field_mappings"]
        assert isinstance(left_mappings, dict) and isinstance(right_mappings, dict)
        component_ids: set[str] = set()
        for component in raw_rule["components"]:
            assert isinstance(component, dict)
            component_id = str(component["component_id"])
            if component_id in component_ids:
                raise WorkflowError(f"rule {rule_id} has duplicate component_id: {component_id}")
            component_ids.add(component_id)
            if component["left_field"] not in left_mappings or component["right_field"] not in right_mappings:
                raise WorkflowError(f"rule {rule_id}/{component_id} lacks an explicit role field mapping")
            tolerance = component["tolerance_source"]
            assert isinstance(tolerance, dict)
            comparator = str(component["comparator"])
            if comparator in {"IDENTIFIER_EXACT", "EXACT_TEXT", "NORMALIZED_TEXT", "BOOLEAN_EXACT", "SET_CONTAINS"}:
                if tolerance["mode"] != "NOT_APPLICABLE" or tolerance["unit"] != "NOT_APPLICABLE":
                    raise WorkflowError(f"rule {rule_id}/{component_id} declares tolerance for a non-tolerance comparator")
            elif tolerance["mode"] == "NOT_APPLICABLE":
                raise WorkflowError(f"rule {rule_id}/{component_id} must declare an external tolerance source")
            if tolerance["mode"] == "NOT_APPLICABLE":
                if tolerance["unit"] != "NOT_APPLICABLE" or tolerance["approval_reference_required"] is not False:
                    raise WorkflowError(f"rule {rule_id}/{component_id} has an incoherent non-applicable tolerance source")
            elif tolerance["unit"] == "NOT_APPLICABLE" or tolerance["approval_reference_required"] is not True:
                raise WorkflowError(f"rule {rule_id}/{component_id} external tolerance must require a unit and approval reference")
            expected_units = {
                "DATE_WINDOW": {"CALENDAR_DAYS"},
                "DECIMAL_RELATIVE": {"RELATIVE_PERCENT"},
                "DECIMAL_ABSOLUTE": {"ABSOLUTE_AMOUNT", "QUANTITY"},
            }.get(comparator)
            if expected_units is not None and tolerance["unit"] not in expected_units:
                raise WorkflowError(
                    f"rule {rule_id}/{component_id} comparator {comparator} is incompatible "
                    f"with tolerance unit {tolerance['unit']}"
                )
        many_to_many = raw_rule["cardinality"] == "MANY_TO_MANY_WITH_EXPLICIT_BRIDGE"
        if many_to_many != isinstance(raw_rule["explicit_bridge"], dict):
            raise WorkflowError(f"rule {rule_id} explicit bridge does not match cardinality")
        if many_to_many:
            bridge_role_id = str(raw_rule["explicit_bridge"]["bridge_role"])
            if bridge_role_id not in role_by_id:
                raise WorkflowError(f"rule {rule_id} bridge role is undeclared")
            bridge_mappings = role_by_id[bridge_role_id]["field_mappings"]
            assert isinstance(bridge_mappings, dict)
            unknown_bridge_fields = sorted(
                set(raw_rule["explicit_bridge"]["allocation_key_fields"]) - set(bridge_mappings)
            )
            if unknown_bridge_fields:
                raise WorkflowError(
                    f"rule {rule_id} bridge fields lack mappings on {bridge_role_id}: "
                    f"{', '.join(unknown_bridge_fields)}"
                )
        partial = raw_rule["partial_handling"]
        assert isinstance(partial, dict)
        if partial["mode"] == "REQUIRE_APPROVED_RUN_POLICY":
            if partial["allowed_relation"] == "NOT_APPLICABLE" or partial["policy_source"] == "NOT_APPLICABLE":
                raise WorkflowError(f"rule {rule_id} approved partial handling lacks relation or policy source")
        elif partial["allowed_relation"] != "NOT_APPLICABLE" or partial["policy_source"] != "NOT_APPLICABLE":
            raise WorkflowError(f"rule {rule_id} non-allow partial handling must be NOT_APPLICABLE")
    aggregation_ids: set[str] = set()
    for aggregation in aggregations:
        assert isinstance(aggregation, dict)
        aggregation_id = str(aggregation["aggregation_id"])
        aggregation_role_id = str(aggregation["role_id"])
        if aggregation_id in aggregation_ids or aggregation_role_id not in role_by_id:
            raise WorkflowError(f"invalid or duplicate aggregation: {aggregation_id}")
        aggregation_mappings = role_by_id[aggregation_role_id]["field_mappings"]
        assert isinstance(aggregation_mappings, dict)
        aggregation_inputs = {
            *aggregation["group_by_fields"],
            str(aggregation["value_field"]),
        }
        unknown_aggregation_fields = sorted(aggregation_inputs - set(aggregation_mappings))
        if unknown_aggregation_fields:
            raise WorkflowError(
                f"aggregation {aggregation_id} fields lack mappings on {aggregation_role_id}: "
                f"{', '.join(unknown_aggregation_fields)}"
            )
        aggregation_ids.add(aggregation_id)
    mode_role_counts = {"TWO_WAY": 2, "THREE_WAY": 3, "FOUR_WAY": 4}
    expected_role_count = mode_role_counts.get(str(profile["mode"]))
    if expected_role_count is not None and len(roles) != expected_role_count:
        raise WorkflowError(
            f"profile mode {profile['mode']} requires exactly {expected_role_count} declared roles"
        )
    basis = profile["comparison_basis"]
    assert isinstance(basis, dict)
    for basis_name, field_key in (("date", "role_date_fields"), ("currency", "role_currency_fields")):
        section = basis[basis_name]
        assert isinstance(section, dict)
        role_fields = section[field_key]
        assert isinstance(role_fields, dict)
        unknown_roles = sorted(set(role_fields) - set(role_by_id))
        if unknown_roles:
            raise WorkflowError(
                f"comparison_basis.{basis_name} references undeclared roles: {', '.join(unknown_roles)}"
            )
        for role_id, canonical_field in role_fields.items():
            mappings = role_by_id[str(role_id)]["field_mappings"]
            assert isinstance(mappings, dict)
            if canonical_field not in mappings:
                raise WorkflowError(
                    f"comparison_basis.{basis_name} field {canonical_field} lacks a mapping on role {role_id}"
                )
    date_window_components = [
        (str(rule["rule_id"]), component)
        for rule in rules
        for component in rule["components"]
        if component["comparator"] == "DATE_WINDOW"
    ]
    date_basis = basis["date"]
    assert isinstance(date_basis, dict)
    if date_window_components and date_basis["window_source"] != "REQUIRE_APPROVED_RUN_INPUT":
        raise WorkflowError("DATE_WINDOW components require comparison_basis.date.window_source approval")
    date_fields = date_basis["role_date_fields"]
    assert isinstance(date_fields, dict)
    for rule in rules:
        for component in rule["components"]:
            if component["comparator"] != "DATE_WINDOW":
                continue
            left_role = str(rule["left_role"])
            right_role = str(rule["right_role"])
            if date_fields.get(left_role) != component["left_field"] or date_fields.get(right_role) != component["right_field"]:
                raise WorkflowError(
                    f"rule {rule['rule_id']}/{component['component_id']} DATE_WINDOW fields must match comparison_basis.date"
                )
    materialize_config(profile, None, validate_only=True)


def _strict_object(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WorkflowError(f"{label} must be an object")
    unexpected = sorted(set(value) - keys)
    if unexpected:
        raise WorkflowError(f"{label} has unsupported keys: {', '.join(unexpected)}")
    return value


def validate_policy_overrides(payload: object) -> dict[str, object]:
    if payload is None:
        return {}
    overrides = _strict_object(payload, {"schema_version", "approval", "tolerances", "partial_policies"}, "policy overrides")
    if overrides.get("schema_version") != "1.0.0":
        raise WorkflowError("policy overrides.schema_version must be 1.0.0")
    approval = _strict_object(overrides.get("approval"), {"status", "owner", "approval_reference"}, "policy overrides.approval")
    if set(approval) != {"status", "owner", "approval_reference"}:
        raise WorkflowError("policy overrides.approval is incomplete")
    if approval["status"] not in {"NOT_REQUESTED", "PENDING", "APPROVED", "REJECTED", "UNKNOWN"}:
        raise WorkflowError("policy overrides.approval.status is invalid")
    if approval["status"] == "APPROVED" and not all(
        isinstance(approval.get(key), str) and bool(str(approval[key]).strip())
        for key in ("owner", "approval_reference")
    ):
        raise WorkflowError("approved policy overrides require owner and approval_reference")
    tolerances = overrides.get("tolerances")
    partial = overrides.get("partial_policies")
    if not isinstance(tolerances, dict) or not isinstance(partial, dict):
        raise WorkflowError("policy overrides tolerances and partial_policies must be objects")
    return overrides


def materialize_config(
    profile: Mapping[str, object],
    policy_overrides: Mapping[str, object] | None,
    *,
    validate_only: bool = False,
) -> dict[str, object]:
    overrides = validate_policy_overrides(policy_overrides) if policy_overrides is not None else {}
    comparison_basis = profile["comparison_basis"]
    assert isinstance(comparison_basis, dict)
    date_basis = comparison_basis["date"]
    currency_basis = comparison_basis["currency"]
    assert isinstance(date_basis, dict) and isinstance(currency_basis, dict)
    approval = overrides.get("approval", {"status": "NOT_REQUESTED", "owner": None, "approval_reference": None})
    tolerances = overrides.get("tolerances", {})
    partial_overrides = overrides.get("partial_policies", {})
    assert isinstance(approval, dict) and isinstance(tolerances, dict) and isinstance(partial_overrides, dict)
    known_tolerances: set[str] = set()
    known_partial: set[str] = set()
    roles = []
    for raw_role in profile["roles"]:
        assert isinstance(raw_role, dict)
        roles.append({
            "role_id": raw_role["role_id"],
            "source_kind": raw_role["source_kind"],
            "document_types": list(raw_role["document_types"]),
            "required": raw_role["required"],
            "field_mappings": dict(raw_role["field_mappings"]),
        })
    link_rules = []
    for raw_rule in profile["match_rules"]:
        assert isinstance(raw_rule, dict)
        rule_id = str(raw_rule["rule_id"])
        components = []
        for raw_component in raw_rule["components"]:
            assert isinstance(raw_component, dict)
            component_id = str(raw_component["component_id"])
            override_key = f"{rule_id}.{component_id}"
            source = raw_component["tolerance_source"]
            assert isinstance(source, dict)
            if source["mode"] == "NOT_APPLICABLE":
                if override_key in tolerances:
                    raise WorkflowError(f"tolerance override is not applicable: {override_key}")
                tolerance = {
                    "status": "NOT_APPLICABLE", "value": None, "unit": "NOT_APPLICABLE",
                    "basis": None, "owner": None, "approval_reference": None,
                    "approval_status": "NOT_REQUESTED",
                }
            elif override_key in tolerances:
                known_tolerances.add(override_key)
                supplied = _strict_object(
                    tolerances[override_key],
                    {"value", "basis", "owner", "approval_reference", "approval_status"},
                    f"tolerance override {override_key}",
                )
                if set(supplied) != {"value", "basis", "owner", "approval_reference", "approval_status"}:
                    raise WorkflowError(f"tolerance override {override_key} is incomplete")
                tolerance = {
                    "status": "PROVIDED", "value": supplied["value"], "unit": source["unit"],
                    "basis": supplied["basis"], "owner": supplied["owner"],
                    "approval_reference": supplied["approval_reference"],
                    "approval_status": supplied["approval_status"],
                }
            else:
                tolerance = {
                    "status": "NOT_PROVIDED", "value": None, "unit": source["unit"],
                    "basis": None, "owner": None, "approval_reference": None,
                    "approval_status": "NOT_REQUESTED",
                }
            components.append({
                "component_id": raw_component["component_id"],
                "left_field": raw_component["left_field"],
                "right_field": raw_component["right_field"],
                "comparator": raw_component["comparator"],
                "normalizers": list(raw_component["normalizers"]),
                "required": raw_component["required"],
                "candidate_only": raw_component["candidate_only"],
                "tolerance": tolerance,
            })
        partial_declaration = raw_rule["partial_handling"]
        assert isinstance(partial_declaration, dict)
        if rule_id in partial_overrides:
            known_partial.add(rule_id)
            if partial_declaration["mode"] != "REQUIRE_APPROVED_RUN_POLICY":
                raise WorkflowError(f"partial override is not allowed by profile rule {rule_id}")
            supplied_partial = _strict_object(
                partial_overrides[rule_id],
                {"mode", "allowed_relation", "aggregation_id", "basis", "owner", "approval_reference", "approval_status"},
                f"partial override {rule_id}",
            )
            required_partial = {"mode", "allowed_relation", "aggregation_id", "basis", "owner", "approval_reference", "approval_status"}
            if set(supplied_partial) != required_partial:
                raise WorkflowError(f"partial override {rule_id} is incomplete")
            if supplied_partial["mode"] != "ALLOW_WHEN_DOCUMENTED":
                raise WorkflowError(f"partial override {rule_id} must use ALLOW_WHEN_DOCUMENTED")
            if supplied_partial["allowed_relation"] != partial_declaration["allowed_relation"]:
                raise WorkflowError(f"partial override {rule_id} changes the profile's allowed relation")
            partial_policy = dict(supplied_partial)
        else:
            mode = str(partial_declaration["mode"])
            partial_policy = {
                "mode": "DISALLOW" if mode == "DISALLOW" else "HUMAN_REVIEW_REQUIRED",
                "allowed_relation": "NOT_APPLICABLE",
                "aggregation_id": None,
                "basis": None,
                "owner": None,
                "approval_reference": None,
                "approval_status": "NOT_REQUESTED",
            }
        link_rules.append({
            "rule_id": raw_rule["rule_id"],
            "left_role": raw_rule["left_role"],
            "right_role": raw_rule["right_role"],
            "cardinality": raw_rule["cardinality"],
            "components": components,
            "partial_policy": partial_policy,
            "missing_field_policy": raw_rule["missing_field_policy"],
            "multiple_candidate_policy": raw_rule["multiple_candidate_policy"],
        })
    unknown_tolerances = sorted(set(tolerances) - known_tolerances)
    unknown_partial = sorted(set(partial_overrides) - known_partial)
    if unknown_tolerances:
        raise WorkflowError("unknown or non-applicable tolerance overrides: " + ", ".join(unknown_tolerances))
    if unknown_partial:
        raise WorkflowError("unknown or non-applicable partial overrides: " + ", ".join(unknown_partial))
    config = {
        "schema_version": "1.0.0",
        "config_id": f"matching-profile.{profile['profile_id']}",
        "config_version": profile["profile_version"],
        "mode": profile["mode"],
        "grain": profile["grain"],
        "roles": roles,
        "link_rules": link_rules,
        "aggregation_rules": [dict(item) for item in profile["aggregation_rules"]],
        "currency_policy": {
            "mode": currency_basis["comparison_mode"], "approved_rate_source": None,
            "approval_reference": None, "approval_status": "NOT_REQUESTED",
        },
        "date_policy": {
            "input_representation": date_basis["input_representation"], "locale": None, "timezone": None,
            "ambiguous_date_policy": date_basis["ambiguous_date_policy"],
        },
        "output_statuses": list(OUTPUT_STATUSES),
        "human_approval": dict(approval),
    }
    try:
        RECONCILE.validate_config(config)
    except RECONCILE.ReconciliationError as exc:
        label = "profile materialization" if validate_only else "materialized reconciliation config"
        raise WorkflowError(f"{label} is invalid: {exc}") from exc
    return config


def _enumerate_directory(root: Path, directory: Path) -> tuple[list[Path], list[dict[str, object]]]:
    files: list[Path] = []
    failures: list[dict[str, object]] = []
    pending = [directory]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name)
        except OSError as exc:
            failures.append({
                "source_reference": portable_reference(root, current),
                "sha256": None,
                "size_bytes": None,
                "status": "FAILED",
                "document_count": 0,
                "classified_record_count": 0,
                "issue": f"directory could not be enumerated: {exc}",
            })
            continue
        for entry in entries:
            path = Path(entry.path)
            try:
                if entry.is_symlink():
                    failures.append({
                        "source_reference": portable_reference(root, path),
                        "sha256": None,
                        "size_bytes": None,
                        "status": "FAILED",
                        "document_count": 0,
                        "classified_record_count": 0,
                        "issue": "symlink was not followed",
                    })
                elif entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    files.append(path)
                else:
                    failures.append({
                        "source_reference": portable_reference(root, path),
                        "sha256": None,
                        "size_bytes": None,
                        "status": "SKIPPED",
                        "document_count": 0,
                        "classified_record_count": 0,
                        "issue": "not a regular file",
                    })
            except OSError as exc:
                failures.append({
                    "source_reference": portable_reference(root, path),
                    "sha256": None,
                    "size_bytes": None,
                    "status": "FAILED",
                    "document_count": 0,
                    "classified_record_count": 0,
                    "issue": f"filesystem metadata unavailable: {exc}",
                })
    return sorted(files, key=lambda path: portable_reference(root, path)), failures


def enumerate_inputs(root: Path, requested: Iterable[str | Path]) -> tuple[list[Path], list[dict[str, object]]]:
    files: dict[str, Path] = {}
    source_index: list[dict[str, object]] = []
    for raw in sorted({str(value) for value in requested}):
        path = safe_path_below_root(root, raw, label="input")
        if not path.exists():
            source_index.append({
                "source_reference": portable_reference(root, path), "sha256": None,
                "size_bytes": None, "status": "FAILED", "document_count": 0,
                "classified_record_count": 0, "issue": "requested input does not exist",
            })
        elif path.is_file():
            files[portable_reference(root, path)] = path
        elif path.is_dir():
            discovered, failures = _enumerate_directory(root, path)
            for candidate in discovered:
                files[portable_reference(root, candidate)] = candidate
            source_index.extend(failures)
        else:
            source_index.append({
                "source_reference": portable_reference(root, path), "sha256": None,
                "size_bytes": None, "status": "SKIPPED", "document_count": 0,
                "classified_record_count": 0, "issue": "requested input is not a regular file or directory",
            })
    return [files[key] for key in sorted(files)], source_index


def infer_data_type(field_name: str, value: object) -> str:
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, list):
        return "LIST"
    if isinstance(value, dict):
        return "JSON_OBJECT"
    if any(token in field_name for token in ("amount", "total", "balance", "price")):
        return "CURRENCY_AMOUNT"
    if any(token in field_name for token in ("quantity", "qty")):
        return "QUANTITY"
    if field_name.endswith("_date") or field_name in {"date", "count_date"}:
        return "DATE"
    if any(token in field_name for token in ("account",)):
        return "BANK_ACCOUNT" if isinstance(value, (str, type(None))) else "TEXT"
    if any(token in field_name for token in ("number", "_id", "code", "reference")):
        return "IDENTIFIER" if isinstance(value, (str, type(None))) else "TEXT"
    return "TEXT"


def formula_like(value: object) -> bool:
    if isinstance(value, str):
        return value.startswith(FORMULA_PREFIXES)
    if isinstance(value, list):
        return any(formula_like(item) for item in value)
    if isinstance(value, dict):
        return any(formula_like(item) for item in value.values())
    return False


def normalized_field(field_name: str, value: object, document_id: str) -> dict[str, object]:
    wrapper = isinstance(value, dict) and bool(set(value).intersection(FIELD_VALUE_KEYS))
    if wrapper:
        unexpected = sorted(set(value) - FIELD_VALUE_KEYS)
        if unexpected:
            raise WorkflowError(f"field {field_name} has unsupported wrapper keys: {', '.join(unexpected)}")
        raw = value.get("raw_value")
        normalized = value.get("normalized_value", raw)
        display = value.get("display_value", normalized)
        data_type = value.get("data_type", infer_data_type(field_name, normalized))
        provenance = value.get("provenance", {})
        review_required = value.get("human_review_required", False)
        notes = value.get("notes", [])
    else:
        raw = value
        normalized = value
        display = value
        data_type = infer_data_type(field_name, normalized)
        provenance = {}
        review_required = False
        notes = []
    if data_type not in ALLOWED_DATA_TYPES:
        raise WorkflowError(f"field {field_name}.data_type is unsupported")
    if data_type in {"IDENTIFIER", "BANK_ACCOUNT", "TAX_IDENTIFIER", "PHONE", "REFERENCE"} and any(
        item is not None and not isinstance(item, str) for item in (raw, normalized, display)
    ):
        raise WorkflowError(f"field {field_name} identifier values must remain strings")
    if not isinstance(provenance, dict):
        raise WorkflowError(f"field {field_name}.provenance must be an object")
    allowed_provenance = {"source_page", "source_region", "bounding_box", "source_snippet"}
    unexpected_provenance = sorted(set(provenance) - allowed_provenance)
    if unexpected_provenance:
        raise WorkflowError(f"field {field_name}.provenance has unsupported keys: {', '.join(unexpected_provenance)}")
    source_page = provenance.get("source_page", "NOT_APPLICABLE")
    if not ((isinstance(source_page, int) and not isinstance(source_page, bool) and source_page >= 1) or source_page in {"UNKNOWN", "NOT_APPLICABLE"}):
        raise WorkflowError(f"field {field_name}.provenance.source_page is invalid")
    source_region = provenance.get("source_region", f"structured-json:{field_name}")
    if not isinstance(source_region, str) or not source_region:
        raise WorkflowError(f"field {field_name}.provenance.source_region is invalid")
    snippet = provenance.get("source_snippet")
    if snippet is None:
        snippet = json.dumps(raw, ensure_ascii=False, sort_keys=True) if not isinstance(raw, str) else raw
    if not isinstance(snippet, str):
        snippet = json.dumps(snippet, ensure_ascii=False, sort_keys=True)
    if not isinstance(review_required, bool) or not isinstance(notes, list) or any(not isinstance(item, str) or not item for item in notes):
        raise WorkflowError(f"field {field_name} review metadata is invalid")
    return {
        "raw_value": raw,
        "normalized_value": normalized,
        "display_value": display,
        "effective_value": normalized if normalized is not None else raw,
        "data_type": data_type,
        "provenance": {
            "document_id": document_id,
            "evidence_id": None,
            "source_page": source_page,
            "source_region": source_region,
            "bounding_box": provenance.get("bounding_box"),
            "source_snippet": snippet,
        },
        "human_review_required": review_required,
        "formula_injection_flag": formula_like(raw) or formula_like(normalized) or formula_like(display),
        "notes": list(notes),
    }


def parse_simple_document(raw: object, *, source_reference: str, ordinal: int) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise WorkflowError(f"document {ordinal} must be an object")
    unexpected = sorted(set(raw) - SIMPLE_DOCUMENT_KEYS)
    if unexpected:
        raise WorkflowError(f"document {ordinal} has unsupported keys: {', '.join(unexpected)}")
    supplied_id = raw.get("document_id", raw.get("record_id"))
    if not isinstance(supplied_id, str) or not IDENTIFIER_RE.fullmatch(supplied_id):
        raise WorkflowError(f"document {ordinal}.document_id is invalid")
    document_type = raw.get("document_type")
    if not isinstance(document_type, str) or not DOCUMENT_TYPE_RE.fullmatch(document_type):
        raise WorkflowError(f"document {ordinal}.document_type is invalid")
    role_hint = raw.get("role")
    if role_hint is not None and (not isinstance(role_hint, str) or not DOCUMENT_TYPE_RE.fullmatch(role_hint)):
        raise WorkflowError(f"document {ordinal}.role is invalid")
    fields = raw.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise WorkflowError(f"document {ordinal}.fields must be a non-empty object")
    normalized_fields: dict[str, dict[str, object]] = {}
    for field_name in sorted(fields):
        if not isinstance(field_name, str) or not FIELD_RE.fullmatch(field_name):
            raise WorkflowError(f"document {ordinal} has invalid field name: {field_name!r}")
        normalized_fields[field_name] = normalized_field(field_name, fields[field_name], supplied_id)
    evidence_ids = raw.get("evidence_ids", [])
    if not isinstance(evidence_ids, list) or any(not isinstance(item, str) or not IDENTIFIER_RE.fullmatch(item) for item in evidence_ids):
        raise WorkflowError(f"document {ordinal}.evidence_ids is invalid")
    classifications = raw.get("data_classification", ["UNKNOWN"])
    if not isinstance(classifications, list) or any(not isinstance(item, str) for item in classifications):
        raise WorkflowError(f"document {ordinal}.data_classification is invalid")
    limitations = raw.get("limitations", [])
    if not isinstance(limitations, list) or any(not isinstance(item, str) or not item for item in limitations):
        raise WorkflowError(f"document {ordinal}.limitations is invalid")
    # Fingerprint the declared business content, not occurrence identity or
    # provenance. Distinct source occurrences/IDs can therefore be retained
    # while still being flagged as exact structured-content duplicate candidates.
    canonical_for_hash = {
        "document_type": document_type,
        "fields": {
            field_name: details["raw_value"]
            for field_name, details in sorted(normalized_fields.items())
        },
    }
    return {
        "source_document_id": supplied_id,
        "document_id": supplied_id,
        "document_type": document_type,
        "role_hint": role_hint,
        "fields": normalized_fields,
        "provided_evidence_ids": list(evidence_ids),
        "data_classification": list(classifications) or ["UNKNOWN"],
        "source_reference": source_reference,
        "declared_source_reference": raw.get("source_reference"),
        "content_sha256": sha256_bytes(canonical_json_bytes(canonical_for_hash)),
        "limitations": list(limitations),
        "role": None,
    }


def documents_from_extraction_package(payload: Mapping[str, object], *, source_reference: str) -> list[dict[str, object]]:
    inventory = payload.get("document_inventory")
    fields = payload.get("extracted_fields")
    if not isinstance(inventory, list) or not isinstance(fields, list):
        raise WorkflowError("canonical extraction package requires document_inventory and extracted_fields arrays")
    fields_by_document: defaultdict[str, dict[str, object]] = defaultdict(dict)
    for field in fields:
        if not isinstance(field, dict) or not isinstance(field.get("document_id"), str) or not isinstance(field.get("field_name"), str):
            raise WorkflowError("canonical extracted field record is malformed")
        fields_by_document[str(field["document_id"])][str(field["field_name"])] = {
            "raw_value": field.get("values", {}).get("raw_value") if isinstance(field.get("values"), dict) else None,
            "normalized_value": field.get("values", {}).get("normalized_value") if isinstance(field.get("values"), dict) else None,
            "display_value": field.get("values", {}).get("display_value") if isinstance(field.get("values"), dict) else None,
            "data_type": field.get("data_type", "TEXT"),
            "provenance": {
                key: field.get("provenance", {}).get(key)
                for key in ("source_page", "source_region", "bounding_box", "source_snippet")
                if isinstance(field.get("provenance"), dict) and key in field["provenance"]
            },
            "human_review_required": bool(field.get("human_review", {}).get("required")) if isinstance(field.get("human_review"), dict) else False,
            "notes": list(field.get("notes", [])) if isinstance(field.get("notes"), list) else [],
        }
    documents = []
    for item in inventory:
        if not isinstance(item, dict):
            raise WorkflowError("canonical document inventory record is malformed")
        classification = item.get("classification")
        if not isinstance(classification, dict):
            raise WorkflowError("canonical document inventory classification is missing")
        document_id = item.get("document_id")
        document_type = classification.get("document_type")
        document = {
            "document_id": document_id,
            "document_type": document_type,
            "fields": fields_by_document.get(str(document_id), {}),
            "evidence_ids": item.get("evidence_ids", []),
            "data_classification": item.get("data_classification", ["UNKNOWN"]),
            "limitations": ["Imported from a canonical extraction package; source binary was not reopened by this helper."],
        }
        documents.append(parse_simple_document(document, source_reference=source_reference, ordinal=len(documents)))
    if not documents:
        raise WorkflowError("canonical extraction package contains no document records")
    return documents


def parse_source_payload(payload: object, *, source_reference: str) -> list[dict[str, object]]:
    if isinstance(payload, dict) and "document_inventory" in payload and "extracted_fields" in payload:
        return documents_from_extraction_package(payload, source_reference=source_reference)
    if isinstance(payload, dict) and "documents" in payload:
        if set(payload) - {"schema_version", "documents", "package_id", "limitations"}:
            unexpected = sorted(set(payload) - {"schema_version", "documents", "package_id", "limitations"})
            raise WorkflowError("document collection has unsupported keys: " + ", ".join(unexpected))
        raw_documents = payload["documents"]
        if not isinstance(raw_documents, list) or not raw_documents:
            raise WorkflowError("documents must be a non-empty array")
        return [
            parse_simple_document(item, source_reference=source_reference, ordinal=index)
            for index, item in enumerate(raw_documents)
        ]
    if isinstance(payload, list):
        if not payload:
            raise WorkflowError("document array must not be empty")
        return [
            parse_simple_document(item, source_reference=source_reference, ordinal=index)
            for index, item in enumerate(payload)
        ]
    return [parse_simple_document(payload, source_reference=source_reference, ordinal=0)]


def inventory_and_parse(
    root: Path,
    requested: Iterable[str | Path],
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, dict[str, object]]]:
    paths, source_index = enumerate_inputs(root, requested)
    documents: list[dict[str, object]] = []
    file_metadata: dict[str, dict[str, object]] = {}
    for path in paths:
        reference = portable_reference(root, path)
        if path.suffix.casefold() != ".json":
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            source_index.append({
                "source_reference": reference, "sha256": None, "size_bytes": size,
                "status": "SKIPPED", "document_count": 0, "classified_record_count": 0,
                "issue": "unsupported input type; this offline helper accepts structured JSON only",
            })
            continue
        try:
            data = read_regular_nofollow(path, label=f"input {reference}")
            digest = sha256_bytes(data)
            payload = load_json_object_bytes(data, label=f"input {reference}")
            parsed = parse_source_payload(payload, source_reference=reference)
        except WorkflowError as exc:
            source_index.append({
                "source_reference": reference, "sha256": None, "size_bytes": None,
                "status": "FAILED", "document_count": 0, "classified_record_count": 0,
                "issue": str(exc),
            })
            continue
        file_metadata[reference] = {"sha256": digest, "size_bytes": len(data), "filename": path.name}
        for document in parsed:
            document["source_file_sha256"] = digest
            document["source_file_size"] = len(data)
            document["source_filename"] = path.name
            documents.append(document)
        source_index.append({
            "source_reference": reference, "sha256": digest, "size_bytes": len(data),
            "status": "PROCESSED", "document_count": len(parsed),
            "classified_record_count": 0, "issue": None,
        })
    source_index.sort(key=lambda item: (str(item["source_reference"]), str(item["status"])))
    documents.sort(key=lambda item: (str(item["source_reference"]), str(item["source_document_id"]), str(item["content_sha256"])))
    return documents, source_index, file_metadata


def assign_unique_document_ids(documents: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for document in documents:
        groups[str(document["source_document_id"])].append(document)
    for source_id, group in sorted(groups.items()):
        if len(group) == 1:
            group[0]["document_id"] = source_id
            continue
        for index, document in enumerate(sorted(group, key=lambda item: (str(item["source_reference"]), str(item["content_sha256"])))):
            suffix = sha256_bytes(canonical_json_bytes({
                "source_reference": document["source_reference"],
                "content_sha256": document["content_sha256"],
                "ordinal": index,
            }))[:10]
            base = source_id[:140]
            document["document_id"] = f"{base}.dup-{suffix}"
            document["fields"] = dict(document["fields"])
            document["fields"]["source_document_id"] = normalized_field(
                "source_document_id", source_id, str(document["document_id"])
            )
    return documents


def classify_documents(
    documents: list[dict[str, object]],
    profile: Mapping[str, object],
    source_index: list[dict[str, object]],
) -> list[dict[str, object]]:
    type_map: defaultdict[str, list[str]] = defaultdict(list)
    alias_map: dict[str, str] = {}
    required_roles: set[str] = set()
    for role in profile["roles"]:
        assert isinstance(role, dict)
        role_id = str(role["role_id"])
        if role["required"]:
            required_roles.add(role_id)
        for document_type in role["document_types"]:
            type_map[str(document_type)].append(role_id)
        for alias in [role_id, *role["role_aliases"]]:
            alias_map[str(alias)] = role_id
    issues: list[dict[str, object]] = []
    counts: defaultdict[str, int] = defaultdict(int)
    for document in documents:
        hint = document.get("role_hint")
        candidates = type_map.get(str(document["document_type"]), [])
        role: str | None = None
        if hint is not None:
            role = alias_map.get(str(hint))
            if role is None or role not in candidates:
                issues.append({
                    "issue_code": "INVALID_ROLE_HINT", "document_id": document["document_id"],
                    "source_reference": document["source_reference"],
                    "detail": f"role hint {hint!r} is not declared for document type {document['document_type']}",
                    "status": "HUMAN_REVIEW_REQUIRED",
                })
                role = None
        elif len(candidates) == 1:
            role = candidates[0]
        elif len(candidates) > 1:
            issues.append({
                "issue_code": "AMBIGUOUS_ROLE_CLASSIFICATION", "document_id": document["document_id"],
                "source_reference": document["source_reference"],
                "detail": f"document type maps to multiple roles: {', '.join(sorted(candidates))}",
                "status": "HUMAN_REVIEW_REQUIRED",
            })
        else:
            issues.append({
                "issue_code": "UNCLASSIFIED_DOCUMENT", "document_id": document["document_id"],
                "source_reference": document["source_reference"],
                "detail": f"document type {document['document_type']} is not accepted by profile {profile['profile_id']}",
                "status": "HUMAN_REVIEW_REQUIRED",
            })
        document["role"] = role
        if role is not None:
            counts[role] += 1
    missing = sorted(required_roles - set(counts))
    for role in missing:
        issues.append({
            "issue_code": "MISSING_REQUIRED_ROLE", "document_id": None,
            "source_reference": None, "detail": f"required role has no classified record: {role}",
            "status": "HUMAN_REVIEW_REQUIRED",
        })
    content_groups: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    source_id_groups: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for document in documents:
        content_groups[str(document["content_sha256"])].append(document)
        source_id_groups[str(document["source_document_id"])].append(document)
    for digest, group in sorted(content_groups.items()):
        if len(group) > 1:
            issues.append({
                "issue_code": "DUPLICATE_CONTENT", "document_id": None,
                "source_reference": None,
                "detail": f"{len(group)} document records share content hash sha256:{digest}",
                "status": "HUMAN_REVIEW_REQUIRED",
                "document_ids": sorted(str(item["document_id"]) for item in group),
            })
    for source_id, group in sorted(source_id_groups.items()):
        if len(group) > 1:
            issues.append({
                "issue_code": "DUPLICATE_RECORD_ID", "document_id": None,
                "source_reference": None,
                "detail": f"source document_id {source_id} occurred {len(group)} times; deterministic internal IDs were assigned",
                "status": "HUMAN_REVIEW_REQUIRED",
                "document_ids": sorted(str(item["document_id"]) for item in group),
            })
    classified_by_source: defaultdict[str, int] = defaultdict(int)
    for document in documents:
        if document["role"] is not None:
            classified_by_source[str(document["source_reference"])] += 1
    for item in source_index:
        item["classified_record_count"] = classified_by_source[str(item["source_reference"])]
    issues.sort(key=lambda item: (str(item["issue_code"]), str(item.get("source_reference")), str(item.get("document_id")), str(item["detail"])))
    return issues


def make_evidence_id(document: Mapping[str, object]) -> str:
    return stable_id("evidence", {
        "document_id": document["document_id"],
        "source_reference": document["source_reference"],
        "content_sha256": document["content_sha256"],
    })


_MISSING = object()


def mapped_source_value(source_values: Mapping[str, object], field_path: object) -> object:
    """Resolve an exact flat field first, then a declared dotted object path."""

    if not isinstance(field_path, str):
        return _MISSING
    if field_path in source_values:
        return source_values[field_path]
    cursor: object = source_values
    for segment in field_path.split("."):
        if not isinstance(cursor, Mapping) or segment not in cursor:
            return _MISSING
        cursor = cursor[segment]
    return cursor


def reconciliation_records(
    documents: list[dict[str, object]],
    profile: Mapping[str, object],
) -> list[dict[str, object]]:
    role_by_id = {str(role["role_id"]): role for role in profile["roles"]}
    records = []
    for document in documents:
        if document["role"] is None:
            continue
        evidence_id = make_evidence_id(document)
        source_values = {
            field_name: details["effective_value"]
            for field_name, details in sorted(document["fields"].items())
        }
        fields = dict(source_values)
        role = role_by_id[str(document["role"])]
        mappings = role["field_mappings"]
        variants = role.get("field_mapping_variants", {})
        assert isinstance(mappings, dict) and isinstance(variants, dict)
        variant = variants.get(str(document["document_type"]), {})
        assert isinstance(variant, dict)
        for canonical_field, source_field_default in mappings.items():
            declared_sources = variant.get(canonical_field, source_field_default)
            source_fields = declared_sources if isinstance(declared_sources, list) else [declared_sources]
            for source_field in source_fields:
                value = mapped_source_value(source_values, source_field)
                if value is not _MISSING:
                    fields[str(canonical_field)] = value
                    break
        records.append({
            "record_id": document["document_id"],
            "role": document["role"],
            "fields": fields,
            "source_reference": document["source_reference"],
            "evidence_ids": [evidence_id],
        })
    records.sort(key=lambda item: (str(item["role"]), str(item["record_id"])))
    return records


def unknown_confidence() -> dict[str, object]:
    return {"score": None, "band": "UNKNOWN", "source": "UNKNOWN"}


def make_document_record(
    document: Mapping[str, object],
    package_id: str,
    profile: Mapping[str, object],
    duplicate_groups: Mapping[str, list[str]],
) -> dict[str, object]:
    evidence_id = make_evidence_id(document)
    relationships = []
    for related in duplicate_groups.get(str(document["content_sha256"]), []):
        if related == document["document_id"]:
            continue
        relationships.append({
            "relationship_type": "EXACT_DUPLICATE", "related_document_id": related,
            "method": "Canonical structured-document SHA-256 equality",
            "confidence": {"score": 1, "band": "HIGH", "source": "RULE_CALCULATED"},
            "review_status": "PENDING",
        })
    classifications = [
        item for item in document["data_classification"] if item in ALLOWED_DATA_CLASSIFICATIONS
    ] or ["UNKNOWN"]
    limitations = [
        "Structured JSON was accessible to this helper; the underlying original business document was not independently reopened.",
        *document["limitations"],
    ]
    if document.get("declared_source_reference"):
        limitations.append("A source-declared reference was treated as untrusted data; coverage uses the actual accessible input path.")
    return {
        "schema_version": "1.0.0", "record_version": 1,
        "document_id": document["document_id"],
        "content_id": f"sha256:{document['content_sha256']}",
        "evidence_ids": [evidence_id], "package_id": package_id,
        "file": {
            "original_filename": document["source_filename"],
            "source_reference": document["source_reference"],
            "extension": ".json", "declared_mime_type": "application/json",
            "detected_mime_type": "application/json", "size_bytes": document["source_file_size"],
            "checksum": {"algorithm": "SHA-256", "digest": document["source_file_sha256"], "computed_at": "UNKNOWN", "object_role": "ORIGINAL"},
        },
        "copy_role": "ORIGINAL",
        "integrity": {
            "read_status": "READABLE", "extension_mime_status": "MATCH",
            "password_protected": False, "encrypted": False,
            "active_content": {"javascript": "NOT_TESTED", "macro": "NOT_TESTED", "embedded_files": "NOT_TESTED", "external_links": "NOT_TESTED"},
            "page_count": {"observed": None, "declared": None},
            "page_completeness_status": "NOT_TESTED", "processing_eligibility": "ELIGIBLE_WITH_LIMITATIONS",
            "issues": [],
        },
        "classification": {
            "document_type": document["document_type"],
            "profile_id": f"matching.{str(profile['profile_id']).casefold()}",
            "profile_version": profile["profile_version"],
            "status": "CLASSIFIED" if document["role"] is not None else "HUMAN_REVIEW_REQUIRED",
            "method": "RULE_BASED",
            "confidence": {"score": 1, "band": "HIGH", "source": "RULE_CALCULATED", "methodology": "Explicit document_type mapped against the selected matching profile"},
            "candidate_types": [document["document_type"]],
        },
        "processing": {"native_text_status": "AVAILABLE", "selected_route": "NATIVE_TEXT", "adapter_run_ids": [], "status": "SUCCEEDED_WITH_WARNINGS"},
        "relationships": sorted(relationships, key=lambda item: str(item["related_document_id"])),
        "data_classification": sorted(set(classifications)), "security_flags": [],
        "review_status": "PENDING", "assumptions": [], "limitations": limitations,
    }


def make_evidence_record(document: Mapping[str, object]) -> dict[str, object]:
    evidence_id = make_evidence_id(document)
    classifications = [
        item for item in document["data_classification"] if item in ALLOWED_DATA_CLASSIFICATIONS
    ] or ["UNKNOWN"]
    return {
        "schema_version": "1.0.0", "record_version": 1,
        "evidence_id": evidence_id, "document_id": document["document_id"],
        "engagement_id": None, "case_id": None, "evidence_type": "UNVERIFIED_COPY",
        "title": f"Accessible structured source for {document['source_document_id']}",
        "source": {"source_type": "FILE_SYSTEM", "source_reference": document["source_reference"], "provided_by": None, "received_by": None, "custodian": None},
        "acquisition": {"received_at": "UNKNOWN", "captured_at": "NOT_APPLICABLE", "method": "Authorized local structured JSON inventory", "authorization_reference": None},
        "locations": {"original_location_reference": document["source_reference"], "working_copy_location_reference": None},
        "checksum": {"algorithm": "SHA-256", "digest": document["source_file_sha256"], "computed_at": "UNKNOWN", "object_role": "ORIGINAL"},
        "copy_role": "ORIGINAL",
        "reliability": {
            "classification": "UNVERIFIED_COPY", "assessment_status": "NOT_ASSESSED",
            "basis": ["The accessible structured source was read and hashed."],
            "corroborating_evidence_ids": [],
            "limitations": ["Checksum equality does not prove authenticity, completeness, authorization, or admissibility."],
        },
        "custody_status": "NOT_REQUIRED", "data_classification": sorted(set(classifications)),
        "access_restrictions": [], "redaction_status": "UNKNOWN", "related_objects": [],
        "review_status": "PENDING",
        "claim_limits": {"checksum_proves_authenticity": False, "record_proves_admissibility": False, "ocr_is_independent_evidence": False},
        "notes": [],
    }


def make_extracted_fields(
    documents: list[dict[str, object]],
    run_id: str,
    profile: Mapping[str, object],
) -> list[dict[str, object]]:
    records = []
    for document in documents:
        evidence_id = make_evidence_id(document)
        for field_name, details in sorted(document["fields"].items()):
            provenance = dict(details["provenance"])
            provenance["document_id"] = document["document_id"]
            provenance["evidence_id"] = evidence_id
            review_required = bool(details["human_review_required"])
            records.append({
                "schema_version": "1.0.0", "record_version": 1,
                "field_id": stable_id("field", {"document_id": document["document_id"], "field_name": field_name}),
                "document_id": document["document_id"], "evidence_id": evidence_id,
                "profile_id": f"matching.{str(profile['profile_id']).casefold()}",
                "profile_version": profile["profile_version"],
                "field_name": field_name, "field_label": field_name.replace("_", " ").title(),
                "field_group": "reconciliation_input",
                "values": {"raw_value": details["raw_value"], "normalized_value": details["normalized_value"], "display_value": details["display_value"]},
                "data_type": details["data_type"], "unit": None, "currency": None,
                "field_status": "HUMAN_REVIEW_REQUIRED" if review_required else "UNVERIFIED",
                "status_flags": ["HUMAN_REVIEW_REQUIRED"] if review_required else ["UNVERIFIED"],
                "provenance": provenance,
                "extraction": {"method": "IMPORTED_STRUCTURED_DATA", "adapter_name": TOOL_NAME, "adapter_version": TOOL_VERSION, "run_id": run_id, "normalization_rules": []},
                "confidence": {key: unknown_confidence() for key in ("ocr", "layout", "extraction", "normalization", "validation", "overall")},
                "validation": {"status": "NOT_TESTED", "rules_applied": [], "results": []},
                "human_review": {"required": review_required, "status": "PENDING" if review_required else "NOT_REQUIRED", "reviewer": None, "reviewed_value": None, "reviewed_at": None, "decision": None, "note": None},
                "formula_injection_flag": details["formula_injection_flag"],
                "notes": list(details["notes"]),
            })
    records.sort(key=lambda item: (str(item["document_id"]), str(item["field_name"])))
    return records


def make_document_links(
    result: Mapping[str, object],
    documents: list[dict[str, object]],
) -> list[dict[str, object]]:
    source_by_id = {str(document["document_id"]): str(document["source_reference"]) for document in documents}
    records = []
    for link in result["links"]:
        assert isinstance(link, dict)
        left = str(link["left_record_id"])
        right = str(link["right_record_id"])
        records.append({
            "link_id": link["link_id"], "left_document_id": left, "right_document_id": right,
            "match_status": link["status"],
            "match_keys": sorted(str(item["comparison_id"]) for item in link["comparisons"]),
            "method": "Bundled deterministic reconciliation config",
            "confidence": unknown_confidence(),
            "source_references": sorted({source_by_id.get(left, "UNKNOWN"), source_by_id.get(right, "UNKNOWN")}),
            "human_review_status": "PENDING" if link["status"] in {"PARTIAL_MATCH", "HUMAN_REVIEW_REQUIRED"} else "NOT_REQUIRED",
        })
    records.sort(key=lambda item: str(item["link_id"]))
    return records


def make_field_dictionary(documents: list[dict[str, object]], profile: Mapping[str, object]) -> list[dict[str, object]]:
    types: defaultdict[str, set[str]] = defaultdict(set)
    formula_fields: set[str] = set()
    for document in documents:
        for field_name, details in document["fields"].items():
            types[field_name].add(str(details["data_type"]))
            if details["formula_injection_flag"]:
                formula_fields.add(field_name)
    return [
        {
            "field_name": field_name,
            "business_definition": f"Structured matching input field {field_name}; interpretation remains source/profile specific.",
            "data_type": " | ".join(sorted(types[field_name])), "required": False,
            "normalization": ["Raw and normalized values retained separately"],
            "null_and_status_meaning": "Null is not zero; validation and review status are recorded separately.",
            "source_profile": str(profile["profile_id"]),
            "validation_rules": ["No implicit type coercion", "Identifier text preserves leading zeros"],
            "sensitivity": "Formula-like text detected and kept non-executable" if field_name in formula_fields else "Follow source package classification",
        }
        for field_name in sorted(types)
    ]


class Cell(NamedTuple):
    value: object
    kind: str = "text"


def _xlsx_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, bool):
        text = "TRUE" if value else "FALSE"
    elif isinstance(value, (int, float, Decimal)):
        text = str(value)
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    text = "".join(character if character in "\t\n\r" or ord(character) >= 32 else "�" for character in text)
    if len(text) > 32767:
        raise WorkflowError("workbook cell exceeds Excel's 32,767-character limit; no silent truncation was performed")
    return text


def _safe_xlsx_text(value: object) -> str:
    text = _xlsx_text(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def _column_name(index: int) -> str:
    result = ""
    number = index + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _date_serial(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return str((parsed - date(1899, 12, 30)).days)


def _precise_number(value: object) -> str | None:
    if not isinstance(value, str) or DECIMAL_RE.fullmatch(value) is None:
        return None
    significant = len(value.lstrip("+-").replace(".", "").lstrip("0"))
    if significant > 15:
        return None
    try:
        decimal = Decimal(value)
    except InvalidOperation:
        return None
    if not decimal.is_finite():
        return None
    return format(decimal, "f")


def _cell_xml(reference: str, cell: Cell, *, header: bool = False) -> str:
    style = 1 if header else 0
    if cell.kind == "number":
        number = _precise_number(cell.value)
        if number is not None:
            return f'<c r="{reference}" s="2"><v>{xml_escape(number)}</v></c>'
    if cell.kind == "date":
        serial = _date_serial(cell.value)
        if serial is not None:
            return f'<c r="{reference}" s="3"><v>{serial}</v></c>'
    text = _safe_xlsx_text(cell.value)
    preserve = ' xml:space="preserve"' if text != text.strip() or "\n" in text else ""
    return f'<c r="{reference}" s="{style}" t="inlineStr"><is><t{preserve}>{xml_escape(text)}</t></is></c>'


def _sheet_xml(headers: list[str], rows: list[list[Cell]]) -> bytes:
    all_rows = [[Cell(header) for header in headers], *rows]
    row_xml = []
    for row_index, row in enumerate(all_rows, start=1):
        cells = "".join(
            _cell_xml(f"{_column_name(column_index)}{row_index}", cell, header=row_index == 1)
            for column_index, cell in enumerate(row)
        )
        row_xml.append(f'<row r="{row_index}">{cells}</row>')
    last_column = _column_name(max(len(headers) - 1, 0))
    last_row = len(all_rows)
    widths = []
    for column_index, header in enumerate(headers):
        populated = [header]
        populated.extend(
            _xlsx_text(row[column_index].value)
            for row in rows
            if column_index < len(row)
        )
        longest = max(
            len(line)
            for value in populated
            for line in (value.splitlines() or [""])
        )
        width = min(48, max(12, longest + 2))
        widths.append(
            f'<col min="{column_index + 1}" max="{column_index + 1}" width="{width}" customWidth="1"/>'
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetPr><pageSetUpPr fitToPage="1" autoPageBreaks="0"/></sheetPr>'
        f'<dimension ref="A1:{last_column}{last_row}"/>'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<cols>{"".join(widths)}</cols><sheetData>{"".join(row_xml)}</sheetData>'
        f'<autoFilter ref="A1:{last_column}{last_row}"/>'
        '<printOptions horizontalCentered="0" verticalCentered="0"/>'
        '<pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>'
        '<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
        '</worksheet>'
    )
    return xml.encode("utf-8")


def _zip_entry(name: str, data: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    info.create_system = 3
    return info, data


def build_xlsx(sheets: list[tuple[str, list[str], list[list[Cell]]]]) -> bytes:
    if not sheets:
        raise WorkflowError("workbook requires at least one sheet with actual workflow data")
    names = [name for name, _, _ in sheets]
    if len(names) != len(set(names)) or any(len(name) > 31 for name in names):
        raise WorkflowError("workbook sheet names must be unique and at most 31 characters")
    content_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, len(sheets) + 1)
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f'{content_overrides}</Types>'
    ).encode("utf-8")
    package_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    ).encode("utf-8")
    workbook_sheets = "".join(
        f'<sheet name="{xml_escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(names, start=1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{workbook_sheets}</sheets><calcPr calcMode="manual"/></workbook>'
    ).encode("utf-8")
    workbook_relationships = "".join(
        f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, len(sheets) + 1)
    ) + (
        f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{workbook_relationships}</Relationships>'
    ).encode("utf-8")
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy-mm-dd"/></numFmts>'
        '<fonts count="2"><font><sz val="11"/><name val="Aptos"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF001838"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="4">'
        '<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
        '<xf numFmtId="49" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyNumberFormat="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>'
        '<xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right" vertical="top"/></xf>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="center" vertical="top"/></xf>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    ).encode("utf-8")
    entries: list[tuple[str, bytes]] = [
        ("[Content_Types].xml", content_types), ("_rels/.rels", package_rels),
        ("xl/_rels/workbook.xml.rels", workbook_rels), ("xl/styles.xml", styles),
        ("xl/workbook.xml", workbook),
    ]
    for index, (_, headers, rows) in enumerate(sheets, start=1):
        entries.append((f"xl/worksheets/sheet{index}.xml", _sheet_xml(headers, rows)))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(entries):
            info, payload = _zip_entry(name, data)
            archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return buffer.getvalue()


def workbook_sheets(
    profile: Mapping[str, object],
    documents: list[dict[str, object]],
    source_index: list[dict[str, object]],
    result: Mapping[str, object],
    issues: list[dict[str, object]],
) -> list[tuple[str, list[str], list[list[Cell]]]]:
    sheets: list[tuple[str, list[str], list[list[Cell]]]] = []
    role_by_id = {str(role["role_id"]): role for role in profile["roles"]}
    by_role: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for document in documents:
        if document["role"] is not None:
            by_role[str(document["role"])].append(document)
    role_headers = [
        "record_id", "source_document_id", "document_type", "source_reference", "field_name",
        "raw_value", "normalized_value", "effective_value", "data_type", "source_page",
        "source_region", "source_snippet", "formula_injection_flag", "evidence_id",
    ]
    for role_id in sorted(by_role, key=lambda item: str(role_by_id[item]["output_sheet"])):
        rows: list[list[Cell]] = []
        for document in sorted(by_role[role_id], key=lambda item: str(item["document_id"])):
            evidence_id = make_evidence_id(document)
            for field_name, details in sorted(document["fields"].items()):
                data_type = str(details["data_type"])
                normalized_kind = "number" if data_type in NUMERIC_DATA_TYPES else "date" if data_type == "DATE" else "text"
                provenance = details["provenance"]
                rows.append([
                    Cell(document["document_id"]), Cell(document["source_document_id"]),
                    Cell(document["document_type"]), Cell(document["source_reference"]), Cell(field_name),
                    Cell(details["raw_value"]), Cell(details["normalized_value"], normalized_kind),
                    Cell(details["effective_value"], normalized_kind), Cell(data_type),
                    Cell(provenance["source_page"]), Cell(provenance["source_region"]),
                    Cell(provenance["source_snippet"]), Cell(details["formula_injection_flag"]), Cell(evidence_id),
                ])
        if rows:
            sheets.append((str(role_by_id[role_id]["output_sheet"]), role_headers, rows))
    if source_index:
        headers = ["source_reference", "sha256", "size_bytes", "status", "document_count", "classified_record_count", "issue"]
        rows = [[Cell(item.get(header)) for header in headers] for item in source_index]
        sheets.append(("SOURCE_INDEX", headers, rows))
    match_headers = [
        "pair_id", "rule_id", "left_record_id", "right_record_id", "pair_status",
        "component_id", "left_field", "right_field", "left_raw_value", "right_raw_value",
        "left_normalized_value", "right_normalized_value", "difference", "tolerance",
        "component_status", "reason_code",
    ]
    match_rows: list[list[Cell]] = []
    for pair in result["pair_results"]:
        for comparison in pair["comparisons"]:
            match_rows.append([
                Cell(pair["pair_id"]), Cell(pair["rule_id"]), Cell(pair["left_record_id"]),
                Cell(pair["right_record_id"]), Cell(pair["status"]), Cell(comparison["comparison_id"]),
                Cell(comparison["left_field"]), Cell(comparison["right_field"]),
                Cell(comparison.get("left_value")), Cell(comparison.get("right_value")),
                Cell(comparison.get("normalized_left")), Cell(comparison.get("normalized_right")),
                Cell(comparison.get("difference")), Cell(comparison.get("tolerance")),
                Cell(comparison["status"]), Cell(comparison["reason_code"]),
            ])
    if match_rows:
        sheets.append(("MATCH_RESULTS", match_headers, match_rows))
    discrepancy_headers = ["discrepancy_id", "discrepancy_code", "rule_id", "status", "details", "decision_scope"]
    discrepancy_rows = [[Cell(item.get(header)) for header in discrepancy_headers] for item in result["discrepancies"]]
    if discrepancy_rows:
        sheets.append(("DISCREPANCIES", discrepancy_headers, discrepancy_rows))
    review_headers = ["issue_code", "document_id", "source_reference", "detail", "status"]
    review_rows = [[Cell(item.get(header)) for header in review_headers] for item in issues]
    for discrepancy in result["discrepancies"]:
        review_rows.append([
            Cell(discrepancy["discrepancy_code"]), Cell(discrepancy.get("details", {}).get("record_id") if isinstance(discrepancy.get("details"), dict) else None),
            Cell(None), Cell(discrepancy.get("details")), Cell(discrepancy["status"]),
        ])
    if review_rows:
        sheets.append(("HUMAN_REVIEW", review_headers, review_rows))
    manifest = result["run_manifest"]
    summary = result["summary"]
    run_headers = ["event", "value"]
    run_rows = [
        [Cell("tool"), Cell(f"{TOOL_NAME} v{TOOL_VERSION}")],
        [Cell("profile"), Cell(f"{profile['profile_id']}@{profile['profile_version']}")],
        [Cell("run_id"), Cell(manifest["run_id"])],
        [Cell("execution_timestamp"), Cell("NOT_RECORDED_FOR_DETERMINISTIC_OUTPUT")],
        [Cell("coverage"), Cell("ONLY_ACCESSIBLE_REQUESTED_INPUTS")],
        [Cell("input_sha256"), Cell(manifest["input_sha256"])],
        [Cell("config_sha256"), Cell(manifest["config_sha256"])],
        [Cell("record_count"), Cell(summary["record_count"])],
        [Cell("status"), Cell(result["status"])],
        [Cell("decision_scope"), Cell(result["decision_scope"])],
    ]
    sheets.append(("RUN_LOG", run_headers, run_rows))
    return sheets


def build_workbook_package(
    documents: list[dict[str, object]],
    profile: Mapping[str, object],
    result: Mapping[str, object],
    config: Mapping[str, object],
    source_index: list[dict[str, object]],
    issues: list[dict[str, object]],
    xlsx_sha256: str,
) -> dict[str, object]:
    package = RECONCILE.canonical_package_view(result)
    package_id = str(package["package_id"])
    content_groups: defaultdict[str, list[str]] = defaultdict(list)
    for document in documents:
        content_groups[str(document["content_sha256"])].append(str(document["document_id"]))
    duplicate_groups = {key: sorted(value) for key, value in content_groups.items() if len(value) > 1}
    document_inventory = [make_document_record(document, package_id, profile, duplicate_groups) for document in documents]
    evidence_register = [make_evidence_record(document) for document in documents]
    extracted_fields = make_extracted_fields(documents, str(package["run_id"]), profile)
    document_links = make_document_links(result, documents)
    limitations = list(package["limitations"])
    limitations.extend([
        "Coverage is limited to requested files that were accessible below the authorized root; no broader folder or attachment coverage is claimed.",
        "Structured JSON inputs were used; source business documents were not re-extracted or visually verified by this offline helper.",
        "No tolerance or materiality value was inferred. Missing approved run policy remains an exception or human-review condition.",
    ])
    if any(item["status"] in {"FAILED", "SKIPPED"} for item in source_index):
        limitations.append("One or more requested or enumerated inputs failed or were skipped; see SOURCE_INDEX and workflow-manifest.json.")
    if issues:
        limitations.append("Preparation issues require accountable human review; see HUMAN_REVIEW and workflow-manifest.json.")
    package.update({
        "document_inventory": document_inventory,
        "evidence_register": evidence_register,
        "extracted_fields": extracted_fields,
        "document_links": document_links,
        "field_dictionary": make_field_dictionary(documents, profile),
        "outputs": [{
            "output_id": "reconciliation-workbook", "format": "XLSX",
            "location_reference": "reconciliation-workbook.xlsx",
            "checksum": {"algorithm": "SHA-256", "digest": xlsx_sha256, "computed_at": "UNKNOWN", "object_role": "DERIVATIVE"},
            "record_count": len([document for document in documents if document["role"] is not None]),
            "data_classification": ["UNKNOWN"],
        }],
        "limitations": sorted(set(limitations)),
    })
    manifest = package["run_manifest"]
    assert isinstance(manifest, dict)
    manifest["source_content_ids"] = sorted({f"sha256:{document['source_file_sha256']}" for document in documents})
    manifest["config_checksums"] = {"reconciliation_config": sha256_bytes(pretty_json_bytes(config))}
    manifest["record_counts"] = {
        "accessible_source_files": sum(item["status"] == "PROCESSED" for item in source_index),
        "source_index_entries": len(source_index),
        "documents": len(document_inventory),
        "classified_records": len([document for document in documents if document["role"] is not None]),
        "extracted_fields": len(extracted_fields),
        "document_links": len(document_links),
        "reconciliation_results": len(package["reconciliation_results"]),
        "discrepancies": len(package["discrepancies"]),
        "preparation_issues": len(issues),
    }
    manifest["execution_history"] = [
        {"step_id": "accessible-source-inventory", "status": "PARTIAL" if any(item["status"] != "PROCESSED" for item in source_index) else "SUCCEEDED", "method_change": None, "timestamp": "UNKNOWN"},
        {"step_id": "profile-role-classification", "status": "PARTIAL" if issues else "SUCCEEDED", "method_change": None, "timestamp": "UNKNOWN"},
        {"step_id": "deterministic-reconciliation", "status": "SUCCEEDED", "method_change": None, "timestamp": "UNKNOWN"},
        {"step_id": "reconciliation-workbook-build", "status": "SUCCEEDED", "method_change": None, "timestamp": "UNKNOWN"},
    ]
    package["qa_status"] = "CONDITIONAL" if issues or result["status"] == "CONDITIONAL" else result["status"]
    package["status"] = "READY_FOR_HUMAN_REVIEW"
    package["human_approval_status"] = config["human_approval"]["status"]
    return package


def validate_workbook_package(package: Mapping[str, object], package_bytes: bytes) -> dict[str, object]:
    schema_bytes = read_regular_nofollow(EXTRACTION_SCHEMA, label="extraction package schema")
    validator = VALIDATE.InternalSchemaValidator(EXTRACTION_SCHEMA, SCHEMA_ROOT)
    report = VALIDATE.build_validation_report(
        input_bytes=package_bytes,
        schema_bytes=schema_bytes,
        records=[dict(package)],
        record_path="$",
        validator=validator,
    )
    if report["status"] != "PASS":
        first = report["errors"][0] if report["errors"] else {"path": "$", "message": "unknown validation failure"}
        raise WorkflowError(f"generated workbook package failed schema validation at {first['path']}: {first['message']}")
    return report


def workflow_readiness_status(
    reconciliation_status: object,
    preparation_issues: Iterable[object],
) -> str:
    """Fail closed: only clean PASS outcomes qualify for limited use."""

    issues = list(preparation_issues)
    if not issues and reconciliation_status in {"PASS", "PASS_WITH_WARNINGS"}:
        return "READY_FOR_LIMITED_USE"
    return "READY_FOR_HUMAN_REVIEW"


def build_workflow(
    root: Path,
    requested_inputs: Iterable[str | Path],
    profile: Mapping[str, object],
    profile_bytes: bytes,
    policy_overrides: Mapping[str, object] | None = None,
    *,
    max_pairs: int = 1_000_000,
) -> tuple[dict[str, bytes], dict[str, object]]:
    validate_profile(profile)
    if max_pairs <= 0:
        raise WorkflowError("max_pairs must be positive")
    config = materialize_config(profile, policy_overrides)
    documents, source_index, _ = inventory_and_parse(root, requested_inputs)
    assign_unique_document_ids(documents)
    issues = classify_documents(documents, profile, source_index)
    records = reconciliation_records(documents, profile)
    records_package = {
        "schema_version": "1.0.0",
        "package_id": stable_id("pkg", {"profile": profile["profile_id"], "records": records}),
        "records": records,
    }
    records_bytes = pretty_json_bytes(records_package)
    config_bytes = pretty_json_bytes(config)
    try:
        result = RECONCILE.reconcile(
            records_package,
            config,
            input_bytes=records_bytes,
            config_bytes=config_bytes,
            max_pairs=max_pairs,
        )
    except RECONCILE.ReconciliationError as exc:
        raise WorkflowError(f"deterministic reconciliation failed: {exc}") from exc
    sheet_specs = workbook_sheets(profile, documents, source_index, result, issues)
    xlsx_bytes = build_xlsx(sheet_specs)
    workbook_package = build_workbook_package(
        documents, profile, result, config, source_index, issues, sha256_bytes(xlsx_bytes)
    )
    workbook_package_bytes = pretty_json_bytes(workbook_package)
    validation_report = validate_workbook_package(workbook_package, workbook_package_bytes)
    files: dict[str, bytes] = {
        "matching-profile.json": pretty_json_bytes(profile),
        "records.json": records_bytes,
        "reconciliation-config.json": config_bytes,
        "reconciliation-result.json": pretty_json_bytes(result),
        "reconciliation-workbook.xlsx": xlsx_bytes,
        "workbook-package.json": workbook_package_bytes,
        "workbook-package.validation.json": pretty_json_bytes(validation_report),
    }
    failed_count = sum(item["status"] == "FAILED" for item in source_index)
    skipped_count = sum(item["status"] == "SKIPPED" for item in source_index)
    scope = {
        "mode": "FILESYSTEM_AUTHORIZED_ROOT",
        "claim_scope": "ACCESSIBLE_REQUESTED_INPUTS_ONLY",
        "requested_inputs": sorted({str(value) for value in requested_inputs}),
        "source_index_entry_count": len(source_index),
        "processed_file_count": sum(item["status"] == "PROCESSED" for item in source_index),
        "failed_file_count": failed_count,
        "skipped_file_count": skipped_count,
        "document_count": len(documents),
        "classified_record_count": len(records),
        "coverage_statement": "Only requested files successfully enumerated and read below the authorized root are represented; inaccessible, failed, skipped, attachment-external, or unrequested files are outside the claim.",
    }
    manifest = {
        "schema_version": "1.0.0",
        "manifest_type": "RECONCILIATION_WORKFLOW_PACKAGE",
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "profile": {"profile_id": profile["profile_id"], "profile_version": profile["profile_version"], "sha256": sha256_bytes(profile_bytes)},
        "run_id": result["run_manifest"]["run_id"],
        "status": workflow_readiness_status(result["status"], issues),
        "source_scope": scope,
        "source_index": source_index,
        "preparation_issues": issues,
        "reconciliation_status": result["status"],
        "workbook_sheets": [name for name, _, _ in sheet_specs],
        "files": {name: {"sha256": sha256_bytes(data), "size_bytes": len(data)} for name, data in sorted(files.items())},
        "compatibility": {
            "validate_command": "python3 -B scripts/validate_records.py workbook-package.json --schema common/extraction-package.schema.json --output workbook-package.revalidation.json",
            "reconcile_command": "python3 -B scripts/reconcile_records.py records.json reconciliation-config.json --output reconciliation-result.json",
            "standard_builder_command": "node scripts/build_workbook.mjs --package workbook-package.json --schema-validation-report workbook-package.validation.json --output standard-reconciliation-workbook.xlsx",
            "note": "The included reconciliation-workbook.xlsx is dependency-free and role-sheet aware; the standard builder command remains available when its optional host runtime dependency is present.",
        },
        "limitations": [
            "No external OCR, model, network, embedding, vector database, or vendor service was invoked.",
            "No tolerance or materiality was inferred; only approved policy overrides are materialized.",
            "The XLSX is a deterministic review artifact, not original evidence or an automatic business decision.",
            "Visual workbook QA and host-specific installation remain outside this helper's execution claim.",
            "Many-to-many profiles require an explicit bridge/allocation adapter; this helper does not auto-resolve ambiguous many-to-many allocations.",
        ],
    }
    files["workflow-manifest.json"] = pretty_json_bytes(manifest)
    return files, manifest


def publish_directory(root: Path, raw_output: str | Path, files: Mapping[str, bytes]) -> Path:
    output = safe_path_below_root(root, raw_output, label="output directory", allow_missing_leaf=True)
    if output.exists() or output.is_symlink():
        raise WorkflowError(f"output directory already exists; refusing overwrite: {output}")
    parent = output.parent
    if not parent.is_dir() or parent.is_symlink():
        raise WorkflowError(f"output parent must be an existing real directory: {parent}")
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=parent))
    os.chmod(staging, 0o700)
    created: list[Path] = []
    try:
        for name, data in sorted(files.items()):
            if PurePosixPath(name).name != name or name in {"", ".", ".."}:
                raise WorkflowError(f"unsafe output member name: {name!r}")
            target = staging / name
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            descriptor = os.open(target, flags, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    descriptor = -1
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            created.append(target)
        _rename_directory_noreplace(staging, output)
        return output
    except Exception:
        for target in reversed(created):
            try:
                target.unlink()
            except OSError:
                pass
        try:
            staging.rmdir()
        except OSError:
            pass
        raise


def _rename_directory_noreplace(source: Path, target: Path) -> None:
    """Atomically publish a staged directory without replacing a raced target."""

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    target_bytes = os.fsencode(target)
    system = os.uname().sysname
    if system == "Darwin" and hasattr(libc, "renamex_np"):
        rename_excl = 0x00000004
        result = libc.renamex_np(
            ctypes.c_char_p(source_bytes), ctypes.c_char_p(target_bytes), ctypes.c_uint(rename_excl)
        )
    elif hasattr(libc, "renameat2"):
        at_fdcwd = -100
        rename_noreplace = 1
        result = libc.renameat2(
            ctypes.c_int(at_fdcwd), ctypes.c_char_p(source_bytes),
            ctypes.c_int(at_fdcwd), ctypes.c_char_p(target_bytes),
            ctypes.c_uint(rename_noreplace),
        )
    else:
        raise WorkflowError(
            "atomic no-replace directory publication is unavailable on this runtime; no final directory was created"
        )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise WorkflowError(
            f"output directory appeared during atomic publication; refusing overwrite: {target}"
        )
    raise WorkflowError(
        f"atomic no-replace directory publication failed: {os.strerror(error_number)}"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="authorized filesystem root")
    profile = parser.add_mutually_exclusive_group(required=True)
    profile.add_argument("--profile-id", help="bundled profile ID such as PO_GRN_INVOICE")
    profile.add_argument("--profile-file", help="custom matching profile JSON below --root")
    parser.add_argument("--input", action="append", required=True, help="requested file or directory below --root; repeat as needed")
    parser.add_argument("--policy-overrides", help="optional approved policy override JSON below --root")
    parser.add_argument("--output-dir", required=True, help="new no-overwrite output directory below --root")
    parser.add_argument("--max-pairs", type=int, default=1_000_000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        root = resolve_root(args.root)
        output = safe_path_below_root(root, args.output_dir, label="output directory", allow_missing_leaf=True)
        if output.exists() or output.is_symlink():
            raise WorkflowError(f"output directory already exists; refusing overwrite: {output}")
        if args.profile_id:
            profile, profile_bytes, _ = load_profile(args.profile_id)
        else:
            profile, profile_bytes, _ = load_custom_profile(root, args.profile_file)
        overrides = None
        if args.policy_overrides:
            override_path = safe_path_below_root(root, args.policy_overrides, label="policy overrides")
            if not override_path.is_file():
                raise WorkflowError("policy overrides is not a regular file")
            overrides = load_json_object_bytes(read_regular_nofollow(override_path, label="policy overrides"), label="policy overrides")
            if not isinstance(overrides, dict):
                raise WorkflowError("policy overrides must be a JSON object")
        files, manifest = build_workflow(
            root, args.input, profile, profile_bytes, overrides, max_pairs=args.max_pairs
        )
        published = publish_directory(root, args.output_dir, files)
        print(json.dumps({
            "status": manifest["status"],
            "reconciliation_status": manifest["reconciliation_status"],
            "output_directory": str(published),
            "file_count": len(files),
            "processed_file_count": manifest["source_scope"]["processed_file_count"],
            "failed_file_count": manifest["source_scope"]["failed_file_count"],
            "classified_record_count": manifest["source_scope"]["classified_record_count"],
        }, ensure_ascii=False, sort_keys=True))
        return 0
    except (WorkflowError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
