#!/usr/bin/env python3
"""Run deterministic, configuration-driven reconciliation over JSON records.

Only allowlisted comparators and normalizers are supported. Numeric comparison
uses Decimal strings; configuration cannot contain executable code, SQL,
regular expressions, fuzzy confirmation, shell actions, or URL actions.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Iterable, Mapping
import unicodedata


TOOL_NAME = "thien-record-reconciler"
TOOL_VERSION = "1.0.0"
MISSING = object()
DECIMAL_PATTERN = re.compile(r"^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
FIELD_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")
MAX_DECIMAL_CHARACTERS = 10_000

COMPARATORS = {
    "IDENTIFIER_EXACT",
    "EXACT_TEXT",
    "NORMALIZED_TEXT",
    "DECIMAL_ABSOLUTE",
    "DECIMAL_RELATIVE",
    "DATE_WINDOW",
    "BOOLEAN_EXACT",
    "SET_CONTAINS",
}
NORMALIZERS = {
    "NONE",
    "TRIM_OUTER_WHITESPACE",
    "COLLAPSE_WHITESPACE",
    "UNICODE_NFKC",
    "CASEFOLD",
    "IDENTIFIER_PRESERVE",
    "DECIMAL_CANONICAL_STRING",
}
CARDINALITIES = {
    "ONE_TO_ONE",
    "ONE_TO_MANY",
    "MANY_TO_ONE",
    "MANY_TO_MANY_WITH_EXPLICIT_BRIDGE",
}
QUALIFYING_STATUSES = {"EXACT_MATCH", "WITHIN_TOLERANCE", "PARTIAL_MATCH"}
CONTRACT_DISCREPANCY_TYPES = {
    "MISSING_DOCUMENT",
    "MISSING_PAGE",
    "MISSING_FIELD",
    "AMOUNT_MISMATCH",
    "QUANTITY_MISMATCH",
    "PRICE_MISMATCH",
    "TAX_MISMATCH",
    "DATE_MISMATCH",
    "PARTY_MISMATCH",
    "BANK_ACCOUNT_MISMATCH",
    "REFERENCE_MISMATCH",
    "SIGNATURE_MISSING",
    "APPROVAL_MISSING",
    "DUPLICATE_DOCUMENT",
    "VERSION_CONFLICT",
    "SYSTEM_DOCUMENT_MISMATCH",
    "UNRESOLVED_OCR",
    "AMBIGUOUS_MATCH",
    "CURRENCY_MISMATCH",
}
BANK_ACCOUNT_FIELDS = {
    "account_number",
    "bank_account",
    "bank_account_number",
    "beneficiary_account",
    "beneficiary_account_number",
    "beneficiary_bank_account",
    "payee_account",
    "payee_bank_account",
}

ROOT_CONFIG_KEYS = {
    "schema_version",
    "config_id",
    "config_version",
    "mode",
    "grain",
    "roles",
    "link_rules",
    "aggregation_rules",
    "currency_policy",
    "date_policy",
    "output_statuses",
    "human_approval",
}
RULE_KEYS = {
    "rule_id",
    "left_role",
    "right_role",
    "cardinality",
    "components",
    "partial_policy",
    "missing_field_policy",
    "multiple_candidate_policy",
}
COMPARISON_KEYS = {
    "component_id",
    "left_field",
    "right_field",
    "comparator",
    "normalizers",
    "required",
    "candidate_only",
    "tolerance",
}
TOLERANCE_KEYS = {
    "status",
    "value",
    "unit",
    "basis",
    "owner",
    "approval_reference",
    "approval_status",
}
PARTIAL_KEYS = {
    "mode",
    "allowed_relation",
    "aggregation_id",
    "basis",
    "owner",
    "approval_reference",
    "approval_status",
}


class ReconciliationError(ValueError):
    """Raised for unsafe paths, malformed records, or unsupported configuration."""


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _absolute_without_resolution(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def resolve_root(raw_root: str | Path) -> Path:
    supplied = Path(raw_root).expanduser()
    if supplied.is_symlink():
        raise ReconciliationError(f"authorized root must not be a symlink: {supplied}")
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise ReconciliationError(f"cannot resolve authorized root {supplied}: {exc}") from exc
    if not root.is_dir():
        raise ReconciliationError(f"authorized root is not a directory: {supplied}")
    return root


def resolve_file(root: Path, raw_path: str | Path, *, label: str) -> Path:
    supplied = Path(raw_path).expanduser()
    lexical = supplied if supplied.is_absolute() else root / supplied
    lexical = _absolute_without_resolution(lexical)
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise ReconciliationError(f"{label} escapes authorized root: {raw_path}") from exc
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ReconciliationError(f"{label} must not traverse a symlink: {relative}")
    if not lexical.is_file():
        raise ReconciliationError(f"{label} is not a regular file: {raw_path}")
    return lexical


def resolve_output_file(root: Path, raw_path: str | Path) -> Path:
    supplied = Path(raw_path).expanduser()
    lexical = supplied if supplied.is_absolute() else root / supplied
    lexical = _absolute_without_resolution(lexical)
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise ReconciliationError(f"output escapes authorized root: {raw_path}") from exc
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ReconciliationError(f"output must not traverse a symlink: {relative}")
    if lexical.is_symlink():
        raise ReconciliationError(f"output must not be a symlink: {relative}")
    if not lexical.parent.is_dir():
        raise ReconciliationError(f"output parent must be an existing directory: {lexical.parent}")
    if lexical.exists() and not lexical.is_file():
        raise ReconciliationError(f"output is not a regular file path: {relative}")
    return lexical


def read_regular_nofollow(path: Path, *, label: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ReconciliationError(f"{label} is not a regular file")
        handle = os.fdopen(descriptor, "rb")
        descriptor = -1
        with handle:
            return handle.read()
    except OSError as exc:
        raise ReconciliationError(f"cannot safely read {label}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load_json_object(path: Path, *, label: str) -> tuple[dict[str, object], bytes]:
    data = read_regular_nofollow(path, label=label)
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
        payload = json.loads(
            data,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReconciliationError(f"{label} must be valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReconciliationError(f"{label} must be a JSON object")
    return payload, data


def reject_unknown_keys(payload: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ReconciliationError(f"{label} contains unsupported keys: {', '.join(unknown)}")


def require_string(payload: Mapping[str, object], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReconciliationError(f"{label}.{key} must be a non-empty string")
    return value


def approved_policy(policy: object, global_approval: str) -> bool:
    if not isinstance(policy, dict):
        return False
    if "status" in policy and policy.get("status") != "PROVIDED":
        return False
    return (
        global_approval == "APPROVED"
        and policy.get("approval_status") == "APPROVED"
        and all(
            isinstance(policy.get(key), str) and bool(str(policy[key]).strip())
            for key in ("basis", "owner", "approval_reference")
        )
    )


def parse_decimal_string(value: object, *, label: str) -> Decimal:
    if (
        not isinstance(value, str)
        or len(value) > MAX_DECIMAL_CHARACTERS
        or DECIMAL_PATTERN.fullmatch(value) is None
    ):
        raise ReconciliationError(
            f"{label} must be a canonical decimal string; numeric coercion is prohibited"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ReconciliationError(f"{label} is not a finite decimal string") from exc


def decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ReconciliationError("non-finite Decimal value is prohibited")
    if value == 0:
        return "0"
    return format(value, "f")


def decimal_working_precision(values: Iterable[Decimal], *, extra: int = 16) -> int:
    materialized = list(values)
    if not materialized:
        return 28
    integer_digits = max(max(value.adjusted() + 1, 1) for value in materialized)
    scale = max(max(-value.as_tuple().exponent, 0) for value in materialized)
    carry = len(str(len(materialized))) + 1
    return max(28, integer_digits + scale + carry + extra)


def decimal_sum(values: Iterable[Decimal]) -> Decimal:
    materialized = list(values)
    with localcontext() as context:
        context.prec = decimal_working_precision(materialized)
        return sum(materialized, Decimal(0))


def validate_config(config: dict[str, object]) -> dict[str, object]:
    """Validate the checked-in reconciliation-config schema contract and normalize it for execution."""

    reject_unknown_keys(config, ROOT_CONFIG_KEYS, "config")
    required_root = ROOT_CONFIG_KEYS
    missing_root = sorted(required_root - set(config))
    if missing_root:
        raise ReconciliationError("config is missing required keys: " + ", ".join(missing_root))
    for key in ("schema_version", "config_id", "config_version", "mode", "grain"):
        require_string(config, key, "config")
    if config["schema_version"] != "1.0.0":
        raise ReconciliationError("config.schema_version must be '1.0.0'")
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(config["config_version"])) is None:
        raise ReconciliationError("config.config_version must be semantic x.y.z")
    if config["mode"] not in {
        "TWO_WAY", "THREE_WAY", "FOUR_WAY", "ERP_DOCUMENT", "CUSTOM_DETERMINISTIC"
    }:
        raise ReconciliationError("config.mode is unsupported")
    if config["grain"] not in {
        "DOCUMENT", "LINE_ITEM", "PAYMENT_ALLOCATION", "MIXED_WITH_EXPLICIT_ROLLUP"
    }:
        raise ReconciliationError("config.grain is unsupported")

    currency = config.get("currency_policy")
    if not isinstance(currency, dict):
        raise ReconciliationError("config.currency_policy must be an object")
    reject_unknown_keys(
        currency,
        {"mode", "approved_rate_source", "approval_reference", "approval_status"},
        "config.currency_policy",
    )
    if set(currency) != {
        "mode", "approved_rate_source", "approval_reference", "approval_status"
    }:
        raise ReconciliationError("config.currency_policy is incomplete")
    if currency.get("approval_status") not in {
        "NOT_REQUESTED", "PENDING", "APPROVED", "REJECTED", "UNKNOWN"
    }:
        raise ReconciliationError("config.currency_policy.approval_status is invalid")
    if currency.get("mode") != "EXACT_CURRENCY_ONLY":
        raise ReconciliationError(
            "deterministic core supports EXACT_CURRENCY_ONLY; currency conversion requires an external approved adapter"
        )

    date_policy = config.get("date_policy")
    if not isinstance(date_policy, dict):
        raise ReconciliationError("config.date_policy must be an object")
    reject_unknown_keys(
        date_policy,
        {"input_representation", "locale", "timezone", "ambiguous_date_policy"},
        "config.date_policy",
    )
    if set(date_policy) != {
        "input_representation", "locale", "timezone", "ambiguous_date_policy"
    }:
        raise ReconciliationError("config.date_policy is incomplete")
    if date_policy.get("input_representation") not in {
        "ISO_8601", "SOURCE_WITH_EXPLICIT_LOCALE", "UNRESOLVED"
    }:
        raise ReconciliationError("config.date_policy.input_representation is invalid")
    if date_policy.get("ambiguous_date_policy") != "HUMAN_REVIEW_REQUIRED":
        raise ReconciliationError("ambiguous dates must require human review")
    if date_policy.get("input_representation") == "SOURCE_WITH_EXPLICIT_LOCALE" and not (
        isinstance(date_policy.get("locale"), str) and str(date_policy["locale"]).strip()
    ):
        raise ReconciliationError("explicit-locale dates require config.date_policy.locale")
    if any(
        value is not None and not isinstance(value, str)
        for value in (date_policy.get("locale"), date_policy.get("timezone"))
    ):
        raise ReconciliationError("config.date_policy locale/timezone must be strings or null")

    human = config.get("human_approval")
    if not isinstance(human, dict):
        raise ReconciliationError("config.human_approval must be an object")
    reject_unknown_keys(human, {"status", "owner", "approval_reference"}, "config.human_approval")
    if set(human) != {"status", "owner", "approval_reference"}:
        raise ReconciliationError("config.human_approval is incomplete")
    global_approval = human.get("status")
    if global_approval not in {"NOT_REQUESTED", "PENDING", "APPROVED", "REJECTED", "UNKNOWN"}:
        raise ReconciliationError("config.human_approval.status is invalid")
    if global_approval == "APPROVED" and not all(
        isinstance(human.get(key), str) and bool(str(human[key]).strip())
        for key in ("owner", "approval_reference")
    ):
        raise ReconciliationError("approved global policy requires owner and approval_reference")

    expected_statuses = {
        "EXACT_MATCH", "WITHIN_TOLERANCE", "STRONG_CANDIDATE", "PARTIAL_MATCH",
        "AMBIGUOUS_MATCH", "CONFLICTING_MATCH", "UNMATCHED", "NOT_APPLICABLE",
        "HUMAN_REVIEW_REQUIRED",
    }
    output_statuses = config.get("output_statuses")
    if (
        not isinstance(output_statuses, list)
        or len(output_statuses) != len(expected_statuses)
        or any(not isinstance(item, str) for item in output_statuses)
        or set(output_statuses) != expected_statuses
    ):
        raise ReconciliationError("config.output_statuses must contain each supported status exactly once")

    raw_roles = config.get("roles")
    if not isinstance(raw_roles, list) or len(raw_roles) < 2:
        raise ReconciliationError("config.roles must contain at least two role objects")
    roles: list[dict[str, object]] = []
    role_by_id: dict[str, dict[str, object]] = {}
    for index, raw_role in enumerate(raw_roles):
        if not isinstance(raw_role, dict):
            raise ReconciliationError(f"config.roles[{index}] must be an object")
        reject_unknown_keys(
            raw_role,
            {"role_id", "source_kind", "document_types", "required", "field_mappings"},
            f"config.roles[{index}]",
        )
        role_id = require_string(raw_role, "role_id", f"config.roles[{index}]")
        if not IDENTIFIER_PATTERN.fullmatch(role_id) or role_id in role_by_id:
            raise ReconciliationError(f"invalid or duplicate role_id: {role_id}")
        if raw_role.get("source_kind") not in {"DOCUMENT", "SYSTEM_RECORD"}:
            raise ReconciliationError(f"config.roles[{index}].source_kind is invalid")
        if not isinstance(raw_role.get("required"), bool):
            raise ReconciliationError(f"config.roles[{index}].required must be boolean")
        document_types = raw_role.get("document_types")
        if not isinstance(document_types, list) or any(not isinstance(item, str) for item in document_types):
            raise ReconciliationError(f"config.roles[{index}].document_types must be strings")
        mappings = raw_role.get("field_mappings")
        if not isinstance(mappings, dict):
            raise ReconciliationError(f"config.roles[{index}].field_mappings must be an object")
        for canonical_field, source_field in mappings.items():
            if (
                not isinstance(canonical_field, str)
                or not FIELD_PATTERN.fullmatch(canonical_field)
                or not isinstance(source_field, str)
                or not FIELD_PATTERN.fullmatch(source_field)
            ):
                raise ReconciliationError(f"config.roles[{index}] contains an invalid field mapping")
        role = {
            "role": role_id,
            "role_id": role_id,
            "source_kind": raw_role["source_kind"],
            "document_types": list(document_types),
            "required": raw_role["required"],
            "field_mappings": dict(mappings),
        }
        roles.append(role)
        role_by_id[role_id] = role

    aggregations = config.get("aggregation_rules")
    if not isinstance(aggregations, list):
        raise ReconciliationError("config.aggregation_rules must be an array")
    normalized_aggregations: list[dict[str, object]] = []
    aggregation_ids: set[str] = set()
    for index, aggregation in enumerate(aggregations):
        if not isinstance(aggregation, dict):
            raise ReconciliationError(f"config.aggregation_rules[{index}] must be an object")
        allowed = {
            "aggregation_id", "role_id", "group_by_fields", "value_field", "operation", "result_field"
        }
        reject_unknown_keys(aggregation, allowed, f"config.aggregation_rules[{index}]")
        if set(aggregation) != allowed:
            raise ReconciliationError(f"config.aggregation_rules[{index}] is incomplete")
        aggregation_id = require_string(aggregation, "aggregation_id", f"aggregation {index}")
        role_id = require_string(aggregation, "role_id", f"aggregation {aggregation_id}")
        if aggregation_id in aggregation_ids or role_id not in role_by_id:
            raise ReconciliationError(f"invalid aggregation identity or role: {aggregation_id}")
        aggregation_ids.add(aggregation_id)
        groups = aggregation.get("group_by_fields")
        if (
            not isinstance(groups, list)
            or not groups
            or any(not isinstance(item, str) for item in groups)
            or len(set(groups)) != len(groups)
        ):
            raise ReconciliationError(f"aggregation {aggregation_id} group_by_fields is invalid")
        for field in [*groups, aggregation.get("value_field"), aggregation.get("result_field")]:
            if not isinstance(field, str) or not FIELD_PATTERN.fullmatch(field):
                raise ReconciliationError(f"aggregation {aggregation_id} has an invalid field")
        role_mappings = role_by_id[role_id]["field_mappings"]
        assert isinstance(role_mappings, dict)
        for field in [*groups, aggregation.get("value_field")]:
            if field not in role_mappings:
                raise ReconciliationError(
                    f"aggregation {aggregation_id} field {field} lacks an explicit role mapping"
                )
        if aggregation.get("operation") not in {
            "SUM_DECIMAL", "COUNT_RECORDS", "MIN_DECIMAL", "MAX_DECIMAL"
        }:
            raise ReconciliationError(f"aggregation {aggregation_id} operation is invalid")
        normalized_aggregations.append(dict(aggregation))

    raw_rules = config.get("link_rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ReconciliationError("config.link_rules must be a non-empty array")
    rules: list[dict[str, object]] = []
    seen_rule_ids: set[str] = set()
    for rule_index, raw_rule in enumerate(raw_rules):
        if not isinstance(raw_rule, dict):
            raise ReconciliationError(f"config.link_rules[{rule_index}] must be an object")
        reject_unknown_keys(raw_rule, RULE_KEYS, f"config.link_rules[{rule_index}]")
        if set(raw_rule) != RULE_KEYS:
            raise ReconciliationError(f"config.link_rules[{rule_index}] is incomplete")
        rule_id = require_string(raw_rule, "rule_id", f"config.link_rules[{rule_index}]")
        if not IDENTIFIER_PATTERN.fullmatch(rule_id) or rule_id in seen_rule_ids:
            raise ReconciliationError(f"invalid or duplicate rule_id: {rule_id}")
        seen_rule_ids.add(rule_id)
        left_role = require_string(raw_rule, "left_role", f"rule {rule_id}")
        right_role = require_string(raw_rule, "right_role", f"rule {rule_id}")
        if left_role not in role_by_id or right_role not in role_by_id:
            raise ReconciliationError(f"rule {rule_id} references an undeclared role")
        cardinality = raw_rule.get("cardinality")
        if cardinality not in CARDINALITIES:
            raise ReconciliationError(f"rule {rule_id} has unsupported cardinality")
        missing_policy = raw_rule.get("missing_field_policy")
        if missing_policy not in {"UNMATCHED", "BLOCK_RULE", "HUMAN_REVIEW_REQUIRED"}:
            raise ReconciliationError(f"rule {rule_id} missing_field_policy is invalid")
        if raw_rule.get("multiple_candidate_policy") != "AMBIGUOUS_MATCH":
            raise ReconciliationError(f"rule {rule_id} must use AMBIGUOUS_MATCH")

        partial = raw_rule.get("partial_policy")
        if not isinstance(partial, dict):
            raise ReconciliationError(f"rule {rule_id}.partial_policy must be an object")
        reject_unknown_keys(partial, PARTIAL_KEYS, f"rule {rule_id}.partial_policy")
        if set(partial) != PARTIAL_KEYS:
            raise ReconciliationError(f"rule {rule_id}.partial_policy is incomplete")
        partial_mode = partial.get("mode")
        relation = partial.get("allowed_relation")
        if partial_mode not in {"ALLOW_WHEN_DOCUMENTED", "DISALLOW", "HUMAN_REVIEW_REQUIRED"}:
            raise ReconciliationError(f"rule {rule_id}.partial_policy.mode is invalid")
        allowed_relations = {
            "LEFT_LESS_THAN_OR_EQUAL_RIGHT", "RIGHT_LESS_THAN_OR_EQUAL_LEFT",
            "AGGREGATED_PARTIAL_WITHIN_BASE", "NOT_APPLICABLE",
        }
        if relation not in allowed_relations:
            raise ReconciliationError(f"rule {rule_id}.partial_policy.allowed_relation is invalid")
        if partial.get("approval_status") not in {
            "NOT_REQUESTED", "PENDING", "APPROVED", "REJECTED", "UNKNOWN"
        }:
            raise ReconciliationError(f"rule {rule_id}.partial_policy.approval_status is invalid")
        if partial_mode == "ALLOW_WHEN_DOCUMENTED":
            if relation == "NOT_APPLICABLE":
                raise ReconciliationError(f"rule {rule_id} approved partial policy needs a relation")
            if not all(
                isinstance(partial.get(key), str) and bool(str(partial[key]).strip())
                for key in ("basis", "owner", "approval_reference")
            ):
                raise ReconciliationError(f"rule {rule_id} partial policy lacks documented metadata")
        elif relation != "NOT_APPLICABLE" or partial.get("aggregation_id") is not None:
            raise ReconciliationError(f"rule {rule_id} non-allow partial policy must be NOT_APPLICABLE")
        if relation == "AGGREGATED_PARTIAL_WITHIN_BASE":
            if partial.get("aggregation_id") not in aggregation_ids:
                raise ReconciliationError(f"rule {rule_id} references an unknown aggregation_id")
        elif partial.get("aggregation_id") is not None:
            raise ReconciliationError(f"rule {rule_id} aggregation_id is only for aggregated partial")

        raw_components = raw_rule.get("components")
        if not isinstance(raw_components, list) or not raw_components:
            raise ReconciliationError(f"rule {rule_id} components must be a non-empty array")
        comparisons: list[dict[str, object]] = []
        seen_component_ids: set[str] = set()
        for component_index, raw_component in enumerate(raw_components):
            if not isinstance(raw_component, dict):
                raise ReconciliationError(f"rule {rule_id} component {component_index} must be an object")
            reject_unknown_keys(raw_component, COMPARISON_KEYS, f"rule {rule_id} component {component_index}")
            if set(raw_component) != COMPARISON_KEYS:
                raise ReconciliationError(f"rule {rule_id} component {component_index} is incomplete")
            component_id = require_string(raw_component, "component_id", f"rule {rule_id}")
            if not IDENTIFIER_PATTERN.fullmatch(component_id) or component_id in seen_component_ids:
                raise ReconciliationError(f"rule {rule_id} has invalid or duplicate component_id")
            seen_component_ids.add(component_id)
            left_field = require_string(raw_component, "left_field", f"component {component_id}")
            right_field = require_string(raw_component, "right_field", f"component {component_id}")
            if not FIELD_PATTERN.fullmatch(left_field) or not FIELD_PATTERN.fullmatch(right_field):
                raise ReconciliationError(f"component {component_id} fields are invalid")
            left_mapping = role_by_id[left_role]["field_mappings"]
            right_mapping = role_by_id[right_role]["field_mappings"]
            assert isinstance(left_mapping, dict) and isinstance(right_mapping, dict)
            if left_field not in left_mapping or right_field not in right_mapping:
                raise ReconciliationError(f"component {component_id} lacks an explicit role field mapping")
            comparator = raw_component.get("comparator")
            if comparator not in COMPARATORS:
                raise ReconciliationError(f"component {component_id} uses unsupported comparator")
            normalizers = raw_component.get("normalizers")
            if (
                not isinstance(normalizers, list)
                or any(not isinstance(item, str) for item in normalizers)
                or any(item not in NORMALIZERS for item in normalizers)
                or len(set(normalizers)) != len(normalizers)
                or ("NONE" in normalizers and len(normalizers) != 1)
            ):
                raise ReconciliationError(f"component {component_id} has invalid normalizers")
            if not isinstance(raw_component.get("required"), bool) or not isinstance(
                raw_component.get("candidate_only"), bool
            ):
                raise ReconciliationError(f"component {component_id} boolean flags are invalid")
            tolerance = raw_component.get("tolerance")
            if not isinstance(tolerance, dict):
                raise ReconciliationError(f"component {component_id}.tolerance must be an object")
            reject_unknown_keys(tolerance, TOLERANCE_KEYS, f"component {component_id}.tolerance")
            if set(tolerance) != TOLERANCE_KEYS:
                raise ReconciliationError(f"component {component_id}.tolerance is incomplete")
            tolerance_status = tolerance.get("status")
            if tolerance_status not in {"PROVIDED", "NOT_PROVIDED", "NOT_APPLICABLE"}:
                raise ReconciliationError(f"component {component_id}.tolerance.status is invalid")
            if tolerance.get("approval_status") not in {
                "NOT_REQUESTED", "PENDING", "APPROVED", "REJECTED", "UNKNOWN"
            }:
                raise ReconciliationError(f"component {component_id}.tolerance.approval_status is invalid")
            if tolerance_status == "PROVIDED":
                tolerance_value = parse_decimal_string(
                    tolerance.get("value"), label=f"{rule_id}.{component_id}.tolerance.value"
                )
                if tolerance_value < 0:
                    raise ReconciliationError("tolerance value must be non-negative")
                if not all(
                    isinstance(tolerance.get(key), str) and bool(str(tolerance[key]).strip())
                    for key in ("basis", "owner", "approval_reference")
                ):
                    raise ReconciliationError(f"component {component_id} tolerance lacks metadata")
            elif tolerance.get("value") is not None:
                raise ReconciliationError(f"component {component_id} non-provided tolerance value must be null")
            if tolerance.get("unit") not in {
                "ABSOLUTE_AMOUNT", "RELATIVE_PERCENT", "QUANTITY", "CALENDAR_DAYS",
                "NOT_APPLICABLE",
            }:
                raise ReconciliationError(f"component {component_id}.tolerance.unit is invalid")
            comparisons.append(
                {
                    "comparison_id": component_id,
                    "component_id": component_id,
                    "left_field": left_field,
                    "right_field": right_field,
                    "left_source_field": left_mapping[left_field],
                    "right_source_field": right_mapping[right_field],
                    "left_role": left_role,
                    "right_role": right_role,
                    "comparator": comparator,
                    "normalizers": list(normalizers),
                    "required": raw_component["required"],
                    "candidate_only": raw_component["candidate_only"],
                    "tolerance": dict(tolerance),
                    "partial_policy": dict(partial),
                    "missing_field_policy": missing_policy,
                }
            )
        rules.append(
            {
                "rule_id": rule_id,
                "left_role": left_role,
                "right_role": right_role,
                "cardinality": cardinality,
                "comparisons": comparisons,
                "partial_policy": dict(partial),
                "missing_field_policy": missing_policy,
                "multiple_candidate_policy": "AMBIGUOUS_MATCH",
            }
        )

    normalized = dict(config)
    normalized["roles"] = roles
    normalized["link_rules"] = rules
    normalized["aggregation_rules"] = normalized_aggregations
    normalized["human_approval_status"] = global_approval
    return normalized


def validate_records_package(package: dict[str, object]) -> list[dict[str, object]]:
    records = package.get("records")
    if not isinstance(records, list):
        raise ReconciliationError("input.records must be an array")
    normalized: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for index, raw_record in enumerate(records):
        if not isinstance(raw_record, dict):
            raise ReconciliationError(f"input.records[{index}] must be an object")
        record_id = raw_record.get("record_id")
        role = raw_record.get("role")
        fields = raw_record.get("fields")
        if not isinstance(record_id, str) or not IDENTIFIER_PATTERN.fullmatch(record_id):
            raise ReconciliationError(f"input.records[{index}].record_id is invalid")
        if record_id in seen_ids:
            raise ReconciliationError(f"duplicate record_id: {record_id}")
        seen_ids.add(record_id)
        if not isinstance(role, str) or not IDENTIFIER_PATTERN.fullmatch(role):
            raise ReconciliationError(f"input.records[{index}].role is invalid")
        if not isinstance(fields, dict):
            raise ReconciliationError(f"input.records[{index}].fields must be an object")
        evidence_ids = raw_record.get("evidence_ids", [])
        if (
            not isinstance(evidence_ids, list)
            or any(
                not isinstance(item, str) or not IDENTIFIER_PATTERN.fullmatch(item)
                for item in evidence_ids
            )
            or len(set(evidence_ids)) != len(evidence_ids)
        ):
            raise ReconciliationError(f"input.records[{index}].evidence_ids is invalid")
        normalized.append(
            {
                "record_id": record_id,
                "role": role,
                "fields": fields,
                "source_reference": raw_record.get("source_reference"),
                "evidence_ids": list(evidence_ids),
            }
        )
    normalized.sort(key=lambda record: (str(record["role"]), str(record["record_id"])))
    return normalized


def field_value(fields: Mapping[str, object], dotted: str) -> object:
    current: object = fields
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def normalize_text(value: object, normalizers: Iterable[str], *, label: str) -> str:
    if not isinstance(value, str):
        raise ReconciliationError(f"{label} must be a string; coercion is prohibited")
    result = value
    for normalizer in normalizers:
        if normalizer in {"NONE", "IDENTIFIER_PRESERVE"}:
            continue
        if normalizer == "TRIM_OUTER_WHITESPACE":
            result = result.strip()
        elif normalizer == "UNICODE_NFKC":
            result = unicodedata.normalize("NFKC", result)
        elif normalizer == "CASEFOLD":
            result = result.casefold()
        elif normalizer == "COLLAPSE_WHITESPACE":
            result = " ".join(result.split())
        elif normalizer == "DECIMAL_CANONICAL_STRING":
            result = decimal_text(parse_decimal_string(result, label=label))
        else:
            raise ReconciliationError(f"unsupported normalizer at runtime: {normalizer}")
    return result


def tolerance_metadata(tolerance: object, global_approval: str) -> dict[str, object] | None:
    if not isinstance(tolerance, dict):
        return None
    return {
        "status": tolerance.get("status"),
        "value": tolerance.get("value"),
        "unit": tolerance.get("unit"),
        "basis": tolerance.get("basis"),
        "owner": tolerance.get("owner"),
        "approval_reference": tolerance.get("approval_reference"),
        "approval_status": tolerance.get("approval_status"),
        "applicable": approved_policy(tolerance, global_approval),
    }


def compare_values(
    comparison: Mapping[str, object],
    left_fields: Mapping[str, object],
    right_fields: Mapping[str, object],
    *,
    global_approval: str,
    left_record_id: str | None = None,
    right_record_id: str | None = None,
    aggregation_values: Mapping[tuple[str, str], Decimal] | None = None,
    aggregation_roles: Mapping[str, str] | None = None,
    date_policy: Mapping[str, object] | None = None,
) -> dict[str, object]:
    left_field = str(comparison["left_field"])
    right_field = str(comparison["right_field"])
    left_source_field = str(comparison.get("left_source_field", left_field))
    right_source_field = str(comparison.get("right_source_field", right_field))
    left = field_value(left_fields, left_source_field)
    right = field_value(right_fields, right_source_field)
    required = bool(comparison["required"])
    result: dict[str, object] = {
        "comparison_id": comparison["comparison_id"],
        "left_field": left_field,
        "right_field": right_field,
        "comparator": comparison["comparator"],
        "normalizers": comparison["normalizers"],
        "left_value": None if left is MISSING else left,
        "right_value": None if right is MISSING else right,
        "status": "NOT_APPLICABLE",
        "reason_code": "OPTIONAL_VALUE_MISSING",
        "difference": None,
        "tolerance": tolerance_metadata(comparison.get("tolerance"), global_approval),
    }
    if left is MISSING or right is MISSING or left is None or right is None:
        if required:
            missing_policy = comparison.get("missing_field_policy")
            if missing_policy == "UNMATCHED":
                result["status"] = "UNMATCHED"
                result["reason_code"] = "REQUIRED_VALUE_MISSING_UNMATCHED"
            else:
                result["status"] = "HUMAN_REVIEW_REQUIRED"
                result["reason_code"] = (
                    "REQUIRED_VALUE_MISSING_BLOCKED"
                    if missing_policy == "BLOCK_RULE"
                    else "REQUIRED_VALUE_MISSING"
                )
        return result

    comparator = str(comparison["comparator"])
    normalizers = comparison["normalizers"]
    assert isinstance(normalizers, list)
    if comparator in {"IDENTIFIER_EXACT", "EXACT_TEXT", "NORMALIZED_TEXT"}:
        try:
            normalized_left = normalize_text(left, normalizers, label=left_field)
            normalized_right = normalize_text(right, normalizers, label=right_field)
        except ReconciliationError as exc:
            result["status"] = "HUMAN_REVIEW_REQUIRED"
            result["reason_code"] = "NON_STRING_VALUE"
            result["detail"] = str(exc)
            return result
        result["normalized_left"] = normalized_left
        result["normalized_right"] = normalized_right
        if normalized_left == normalized_right:
            result["status"] = "EXACT_MATCH"
            result["reason_code"] = "TEXT_EQUAL"
        else:
            result["status"] = "CONFLICTING_MATCH"
            result["reason_code"] = "TEXT_DIFFERENCE"
        return result

    if comparator == "BOOLEAN_EXACT":
        if not isinstance(left, bool) or not isinstance(right, bool):
            result["status"] = "HUMAN_REVIEW_REQUIRED"
            result["reason_code"] = "NON_BOOLEAN_VALUE"
        elif left is right:
            result["status"] = "EXACT_MATCH"
            result["reason_code"] = "BOOLEAN_EQUAL"
            result["normalized_left"] = left
            result["normalized_right"] = right
        else:
            result["status"] = "CONFLICTING_MATCH"
            result["reason_code"] = "BOOLEAN_DIFFERENCE"
            result["normalized_left"] = left
            result["normalized_right"] = right
        return result

    if comparator == "SET_CONTAINS":
        if not isinstance(left, list) or not isinstance(right, list):
            result["status"] = "HUMAN_REVIEW_REQUIRED"
            result["reason_code"] = "NON_ARRAY_SET_VALUE"
            return result
        try:
            left_tokens = [canonical_json_bytes(item) for item in left]
            right_tokens = [canonical_json_bytes(item) for item in right]
        except (TypeError, ValueError):
            result["status"] = "HUMAN_REVIEW_REQUIRED"
            result["reason_code"] = "NON_CANONICAL_SET_VALUE"
            return result
        result["normalized_left"] = sorted(token.decode("utf-8") for token in left_tokens)
        result["normalized_right"] = sorted(token.decode("utf-8") for token in right_tokens)
        if set(right_tokens).issubset(set(left_tokens)):
            result["status"] = "EXACT_MATCH"
            result["reason_code"] = "LEFT_SET_CONTAINS_RIGHT"
        else:
            result["status"] = "CONFLICTING_MATCH"
            result["reason_code"] = "LEFT_SET_DOES_NOT_CONTAIN_RIGHT"
        return result

    if comparator in {"DECIMAL_ABSOLUTE", "DECIMAL_RELATIVE"}:
        try:
            left_decimal = parse_decimal_string(left, label=left_field)
            right_decimal = parse_decimal_string(right, label=right_field)
        except ReconciliationError as exc:
            result["status"] = "HUMAN_REVIEW_REQUIRED"
            result["reason_code"] = "NON_DECIMAL_STRING"
            result["detail"] = str(exc)
            return result
        with localcontext() as context:
            context.prec = decimal_working_precision((left_decimal, right_decimal))
            signed_difference = right_decimal - left_decimal
            absolute_difference = abs(signed_difference)
        result["difference"] = {
            "signed": decimal_text(signed_difference),
            "absolute": decimal_text(absolute_difference),
        }
        if absolute_difference == 0:
            result["status"] = "EXACT_MATCH"
            result["reason_code"] = "DECIMAL_EQUAL"
            return result

        tolerance = comparison.get("tolerance")
        tolerance_approved = approved_policy(tolerance, global_approval)
        within_tolerance = False
        if isinstance(tolerance, dict) and tolerance.get("status") == "PROVIDED":
            tolerance_value = parse_decimal_string(
                tolerance.get("value"), label=f"{comparison['comparison_id']}.tolerance.value"
            )
            if comparator == "DECIMAL_ABSOLUTE":
                within_tolerance = absolute_difference <= tolerance_value
            else:
                # The canonical contract fixes the denominator to MAX_ABS so a
                # config cannot silently choose asymmetric percentages.
                denominator = max(abs(left_decimal), abs(right_decimal))
                if denominator == 0:
                    result["status"] = "HUMAN_REVIEW_REQUIRED"
                    result["reason_code"] = "RELATIVE_ZERO_DENOMINATOR"
                    return result
                with localcontext() as context:
                    context.prec = decimal_working_precision(
                        (absolute_difference, denominator, tolerance_value), extra=32
                    )
                    relative_difference = absolute_difference / denominator
                    within_tolerance = absolute_difference <= tolerance_value * denominator
                result["difference"]["relative"] = decimal_text(relative_difference)
        if within_tolerance:
            if tolerance_approved:
                result["status"] = "WITHIN_TOLERANCE"
                result["reason_code"] = "APPROVED_TOLERANCE_APPLIED"
            else:
                result["status"] = "HUMAN_REVIEW_REQUIRED"
                result["reason_code"] = "TOLERANCE_NOT_APPROVED"
            return result

        partial = comparison.get("partial_policy")
        if isinstance(partial, dict):
            relation = partial.get("allowed_relation")
            qualifies = False
            aggregate_context: dict[str, object] | None = None
            if left_decimal >= 0 and right_decimal >= 0:
                if relation == "RIGHT_LESS_THAN_OR_EQUAL_LEFT":
                    qualifies = right_decimal < left_decimal
                elif relation == "LEFT_LESS_THAN_OR_EQUAL_RIGHT":
                    qualifies = left_decimal < right_decimal
                elif relation == "AGGREGATED_PARTIAL_WITHIN_BASE":
                    aggregation_id = partial.get("aggregation_id")
                    aggregate_role = (
                        aggregation_roles.get(str(aggregation_id))
                        if aggregation_roles is not None
                        else None
                    )
                    aggregate: Decimal | None = None
                    base: Decimal | None = None
                    if (
                        aggregate_role == comparison.get("left_role")
                        and left_record_id is not None
                        and aggregation_values is not None
                    ):
                        aggregate = aggregation_values.get((str(aggregation_id), left_record_id))
                        base = right_decimal
                    elif (
                        aggregate_role == comparison.get("right_role")
                        and right_record_id is not None
                        and aggregation_values is not None
                    ):
                        aggregate = aggregation_values.get((str(aggregation_id), right_record_id))
                        base = left_decimal
                    if aggregate is None or base is None:
                        result["status"] = "HUMAN_REVIEW_REQUIRED"
                        result["reason_code"] = "AGGREGATED_PARTIAL_VALUE_UNAVAILABLE"
                        return result
                    qualifies = aggregate <= base
                    aggregate_context = {
                        "aggregation_id": aggregation_id,
                        "aggregated_value": decimal_text(aggregate),
                        "base_value": decimal_text(base),
                    }
            if qualifies:
                if partial.get("mode") == "ALLOW_WHEN_DOCUMENTED" and approved_policy(
                    partial, global_approval
                ):
                    result["status"] = "PARTIAL_MATCH"
                    result["reason_code"] = "APPROVED_PARTIAL_POLICY_APPLIED"
                    result["partial_policy"] = {
                        "mode": partial.get("mode"),
                        "allowed_relation": relation,
                        "aggregation_id": partial.get("aggregation_id"),
                        "basis": partial.get("basis"),
                        "owner": partial.get("owner"),
                        "approval_reference": partial.get("approval_reference"),
                        "approval_status": partial.get("approval_status"),
                    }
                    if aggregate_context is not None:
                        result["partial_policy"].update(aggregate_context)
                else:
                    result["status"] = "HUMAN_REVIEW_REQUIRED"
                    result["reason_code"] = "PARTIAL_POLICY_NOT_APPROVED"
                return result
            if partial.get("mode") == "HUMAN_REVIEW_REQUIRED":
                result["status"] = "HUMAN_REVIEW_REQUIRED"
                result["reason_code"] = "PARTIAL_POLICY_REQUIRES_HUMAN_REVIEW"
                return result

        result["status"] = "CONFLICTING_MATCH"
        result["reason_code"] = "DECIMAL_OUTSIDE_APPROVED_RULE"
        return result

    if comparator == "DATE_WINDOW":
        if date_policy is not None and date_policy.get("input_representation") != "ISO_8601":
            result["status"] = "HUMAN_REVIEW_REQUIRED"
            result["reason_code"] = "DATE_REPRESENTATION_REQUIRES_APPROVED_ADAPTER"
            return result
        if not isinstance(left, str) or not isinstance(right, str):
            result["status"] = "HUMAN_REVIEW_REQUIRED"
            result["reason_code"] = "NON_ISO_DATE_STRING"
            return result
        try:
            left_date = date.fromisoformat(left)
            right_date = date.fromisoformat(right)
        except ValueError:
            result["status"] = "HUMAN_REVIEW_REQUIRED"
            result["reason_code"] = "AMBIGUOUS_OR_INVALID_DATE"
            return result
        days = abs((right_date - left_date).days)
        result["difference"] = {"days": days}
        if days == 0:
            result["status"] = "EXACT_MATCH"
            result["reason_code"] = "DATE_EQUAL"
            return result
        tolerance = comparison.get("tolerance")
        if not isinstance(tolerance, dict) or tolerance.get("status") != "PROVIDED":
            result["status"] = "CONFLICTING_MATCH"
            result["reason_code"] = "DATE_DIFFERENCE_WITHOUT_TOLERANCE"
            return result
        window = parse_decimal_string(
            tolerance.get("value"), label=f"{comparison['comparison_id']}.tolerance.value"
        )
        if window != window.to_integral_value():
            raise ReconciliationError("DATE_WINDOW tolerance must be a whole number of days")
        if Decimal(days) <= window:
            if approved_policy(tolerance, global_approval):
                result["status"] = "WITHIN_TOLERANCE"
                result["reason_code"] = "APPROVED_DATE_WINDOW_APPLIED"
            else:
                result["status"] = "HUMAN_REVIEW_REQUIRED"
                result["reason_code"] = "DATE_WINDOW_NOT_APPROVED"
        else:
            result["status"] = "CONFLICTING_MATCH"
            result["reason_code"] = "DATE_OUTSIDE_APPROVED_WINDOW"
        return result

    raise ReconciliationError(f"unhandled comparator: {comparator}")


def pair_status(comparisons: Iterable[Mapping[str, object]]) -> str:
    statuses = {str(item["status"]) for item in comparisons}
    if "CONFLICTING_MATCH" in statuses:
        return "CONFLICTING_MATCH"
    if "HUMAN_REVIEW_REQUIRED" in statuses:
        return "HUMAN_REVIEW_REQUIRED"
    if "AMBIGUOUS_MATCH" in statuses:
        return "AMBIGUOUS_MATCH"
    if "UNMATCHED" in statuses:
        return "UNMATCHED"
    if "PARTIAL_MATCH" in statuses:
        return "PARTIAL_MATCH"
    if "WITHIN_TOLERANCE" in statuses:
        return "WITHIN_TOLERANCE"
    if statuses <= {"EXACT_MATCH", "NOT_APPLICABLE"} and "EXACT_MATCH" in statuses:
        return "EXACT_MATCH"
    return "NOT_APPLICABLE"


def stable_id(prefix: str, value: object) -> str:
    return f"{prefix}-{sha256_bytes(canonical_json_bytes(value))[:24]}"


def select_pairs(
    pairs: list[dict[str, object]], cardinality: str
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    qualified = [pair for pair in pairs if pair["status"] in QUALIFYING_STATUSES]
    left_counts = Counter(str(pair["left_record_id"]) for pair in qualified)
    right_counts = Counter(str(pair["right_record_id"]) for pair in qualified)
    selected: list[dict[str, object]] = []
    ambiguous: list[dict[str, object]] = []
    for pair in qualified:
        left_count = left_counts[str(pair["left_record_id"])]
        right_count = right_counts[str(pair["right_record_id"])]
        allowed = (
            (cardinality == "ONE_TO_ONE" and left_count == 1 and right_count == 1)
            or (cardinality == "ONE_TO_MANY" and right_count == 1)
            or (cardinality == "MANY_TO_ONE" and left_count == 1)
        )
        if allowed:
            selected.append(pair)
        else:
            ambiguous.append(pair)
    return selected, ambiguous


def make_discrepancy(code: str, rule_id: str | None, details: Mapping[str, object]) -> dict[str, object]:
    basis = {"code": code, "rule_id": rule_id, "details": details}
    return {
        "discrepancy_id": stable_id("disc", basis),
        "discrepancy_code": code,
        "rule_id": rule_id,
        "status": "HUMAN_REVIEW_REQUIRED",
        "details": dict(details),
        "decision_scope": "OBSERVED_DIFFERENCE_OR_ABSENCE",
    }


def comparison_discrepancy_type(comparison: Mapping[str, object]) -> str:
    """Map explicit canonical field names to the checked-in discrepancy taxonomy."""

    fields = {
        str(comparison.get("left_field", "")).casefold(),
        str(comparison.get("right_field", "")).casefold(),
    }
    if fields.intersection(BANK_ACCOUNT_FIELDS):
        return "BANK_ACCOUNT_MISMATCH"
    if fields.intersection({"quantity", "ordered_quantity", "received_quantity", "invoiced_quantity"}):
        return "QUANTITY_MISMATCH"
    if fields.intersection({"unit_price", "price", "unit_cost"}):
        return "PRICE_MISMATCH"
    if fields.intersection({"tax", "tax_amount", "tax_rate", "vat_amount", "vat_rate"}):
        return "TAX_MISMATCH"
    if fields.intersection({"currency", "currency_code"}):
        return "CURRENCY_MISMATCH"
    if fields.intersection({"amount", "gross_amount", "net_amount", "total_amount", "payment_amount"}):
        return "AMOUNT_MISMATCH"
    if str(comparison.get("comparator")) == "DATE_WINDOW" or any(
        field.endswith("_date") or field == "date" for field in fields
    ):
        return "DATE_MISMATCH"
    if fields.intersection({"party", "party_id", "vendor", "vendor_id", "customer", "customer_id"}):
        return "PARTY_MISMATCH"
    if str(comparison.get("comparator")) == "IDENTIFIER_EXACT":
        return "REFERENCE_MISMATCH"
    return "SYSTEM_DOCUMENT_MISMATCH"


def make_contract_discrepancy(
    *,
    package_id: str,
    rule_id: str,
    left_record: Mapping[str, object],
    right_record: Mapping[str, object],
    comparison: Mapping[str, object],
) -> dict[str, object]:
    discrepancy_type = comparison_discrepancy_type(comparison)
    if discrepancy_type not in CONTRACT_DISCREPANCY_TYPES:
        raise ReconciliationError(f"unsupported discrepancy taxonomy value: {discrepancy_type}")
    left_id = str(left_record["record_id"])
    right_id = str(right_record["record_id"])
    left_field = str(comparison["left_field"])
    right_field = str(comparison["right_field"])
    values = {
        "left": {
            "record_id": left_id,
            "field": left_field,
            "raw_value": comparison.get("left_value"),
            "source_reference": left_record.get("source_reference"),
        },
        "right": {
            "record_id": right_id,
            "field": right_field,
            "raw_value": comparison.get("right_value"),
            "source_reference": right_record.get("source_reference"),
        },
    }
    if discrepancy_type == "BANK_ACCOUNT_MISMATCH":
        severity = "HIGH"
        possible_explanations = [
            "The compared source and approved-reference versions may differ.",
            "A capture or transcription difference may require source-level validation.",
        ]
    else:
        severity = "MEDIUM"
        possible_explanations = [
            "The compared source versions or effective dates may differ.",
            "The deterministic field mapping may require authorized validation.",
        ]
    evidence_ids = sorted(
        {
            str(item)
            for record in (left_record, right_record)
            for item in record.get("evidence_ids", [])
        }
    )
    basis = {
        "package_id": package_id,
        "rule_id": rule_id,
        "component_id": comparison["comparison_id"],
        "discrepancy_type": discrepancy_type,
        "document_ids": sorted({left_id, right_id}),
        "values": values,
    }
    return {
        "discrepancy_id": stable_id("discrepancy", basis),
        "document_package_id": package_id,
        "document_ids": sorted({left_id, right_id}),
        "field_or_rule": (
            left_field if left_field == right_field else f"{rule_id}:{left_field}<->{right_field}"
        ),
        "values": values,
        "difference": schema_difference(comparison.get("difference")),
        "tolerance": schema_tolerance(comparison.get("tolerance")),
        "discrepancy_type": discrepancy_type,
        "severity": severity,
        "possible_explanations": possible_explanations,
        "supporting_evidence_ids": evidence_ids,
        "validation_status": "HUMAN_REVIEW_REQUIRED",
        "owner": None,
        "human_review_status": "PENDING",
        "handoff_target": "Authorized business or master-data reviewer",
    }


def compute_aggregations(
    records: list[dict[str, object]],
    roles: list[dict[str, object]],
    aggregation_rules: list[dict[str, object]],
) -> tuple[
    list[dict[str, object]],
    dict[tuple[str, str], Decimal],
    list[dict[str, object]],
]:
    """Compute declared Decimal aggregations without coercion or implicit joins."""

    role_map = {str(role["role_id"]): role for role in roles}
    records_by_role: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        records_by_role[str(record["role"])].append(record)
    results: list[dict[str, object]] = []
    values_by_record: dict[tuple[str, str], Decimal] = {}
    issues: list[dict[str, object]] = []
    for rule in sorted(aggregation_rules, key=lambda item: str(item["aggregation_id"])):
        aggregation_id = str(rule["aggregation_id"])
        role_id = str(rule["role_id"])
        role = role_map[role_id]
        mappings = role["field_mappings"]
        assert isinstance(mappings, dict)
        group_fields = [str(item) for item in rule["group_by_fields"]]
        value_field = str(rule["value_field"])
        groups: defaultdict[tuple[bytes, ...], list[tuple[dict[str, object], list[object], Decimal | None]]] = defaultdict(list)
        for record in records_by_role[role_id]:
            fields = record["fields"]
            assert isinstance(fields, dict)
            raw_group = [field_value(fields, str(mappings[field])) for field in group_fields]
            if any(value is MISSING or value is None for value in raw_group):
                issues.append(
                    {
                        "aggregation_id": aggregation_id,
                        "record_id": record["record_id"],
                        "reason": "AGGREGATION_GROUP_FIELD_MISSING",
                    }
                )
                continue
            try:
                group_key = tuple(canonical_json_bytes(value) for value in raw_group)
            except (TypeError, ValueError):
                issues.append(
                    {
                        "aggregation_id": aggregation_id,
                        "record_id": record["record_id"],
                        "reason": "AGGREGATION_GROUP_VALUE_NOT_CANONICAL_JSON",
                    }
                )
                continue
            numeric_value: Decimal | None = None
            if rule["operation"] != "COUNT_RECORDS":
                raw_value = field_value(fields, str(mappings[value_field]))
                try:
                    numeric_value = parse_decimal_string(
                        raw_value, label=f"{aggregation_id}.{record['record_id']}.{value_field}"
                    )
                except ReconciliationError:
                    issues.append(
                        {
                            "aggregation_id": aggregation_id,
                            "record_id": record["record_id"],
                            "reason": "AGGREGATION_DECIMAL_VALUE_MISSING_OR_INVALID",
                        }
                    )
                    continue
            groups[group_key].append((record, raw_group, numeric_value))
        for group_key in sorted(groups):
            members = groups[group_key]
            operation = str(rule["operation"])
            decimals = [member[2] for member in members if member[2] is not None]
            if operation == "COUNT_RECORDS":
                aggregate = Decimal(len(members))
            elif operation == "SUM_DECIMAL":
                aggregate = decimal_sum(decimals)
            elif operation == "MIN_DECIMAL":
                aggregate = min(decimals)
            elif operation == "MAX_DECIMAL":
                aggregate = max(decimals)
            else:  # validated earlier; defensive fail closed
                raise ReconciliationError(f"unsupported aggregation operation: {operation}")
            record_ids = sorted(str(member[0]["record_id"]) for member in members)
            group_values = members[0][1]
            result = {
                "aggregation_result_id": stable_id(
                    "agg",
                    {
                        "aggregation_id": aggregation_id,
                        "group": [item.decode("utf-8") for item in group_key],
                    },
                ),
                "aggregation_id": aggregation_id,
                "role_id": role_id,
                "group": dict(zip(group_fields, group_values)),
                "operation": operation,
                "result_field": rule["result_field"],
                "value": decimal_text(aggregate),
                "record_ids": record_ids,
                "status": "COMPUTED",
            }
            results.append(result)
            for record_id in record_ids:
                values_by_record[(aggregation_id, record_id)] = aggregate
    results.sort(key=lambda item: str(item["aggregation_result_id"]))
    issues.sort(key=lambda item: (str(item["aggregation_id"]), str(item["record_id"])))
    return results, values_by_record, issues


def apply_partial_allocation_checks(
    links: list[dict[str, object]],
    discrepancies: list[dict[str, object]],
) -> list[dict[str, object]]:
    allocations: list[dict[str, object]] = []
    grouped: defaultdict[tuple[str, str, str], list[tuple[dict[str, object], dict[str, object]]]] = defaultdict(list)
    for link in links:
        for comparison in link["comparisons"]:
            if comparison["status"] != "PARTIAL_MATCH":
                continue
            partial = comparison.get("partial_policy")
            if not isinstance(partial, dict):
                continue
            relation = partial.get("allowed_relation")
            if relation == "AGGREGATED_PARTIAL_WITHIN_BASE":
                # The declared aggregation already accounts for the complete
                # group; emitting per-pair allocations would double count it.
                continue
            left_value = parse_decimal_string(
                comparison["left_value"], label=str(comparison["left_field"])
            )
            right_value = parse_decimal_string(
                comparison["right_value"], label=str(comparison["right_field"])
            )
            right_within_left = relation == "RIGHT_LESS_THAN_OR_EQUAL_LEFT"
            allocated = right_value if right_within_left else left_value
            capacity = left_value if right_within_left else right_value
            capacity_record = (
                str(link["left_record_id"])
                if right_within_left
                else str(link["right_record_id"])
            )
            allocation = {
                "allocation_id": stable_id(
                    "alloc",
                    {
                        "link_id": link["link_id"],
                        "comparison_id": comparison["comparison_id"],
                    },
                ),
                "rule_id": link["rule_id"],
                "source_record_id": link["left_record_id"],
                "target_record_id": link["right_record_id"],
                "field": comparison["right_field"] if right_within_left else comparison["left_field"],
                "allocated_value": decimal_text(allocated),
                "capacity_value": decimal_text(capacity),
                "basis": partial.get("basis"),
                "status": "PARTIAL_MATCH",
            }
            allocations.append(allocation)
            grouped[(capacity_record, str(link["rule_id"]), str(comparison["comparison_id"]))].append(
                (link, allocation)
            )
    for (capacity_record, rule_id, comparison_id), members in sorted(grouped.items()):
        capacity = parse_decimal_string(
            members[0][1]["capacity_value"], label=f"{comparison_id}.capacity"
        )
        allocated = decimal_sum(
            parse_decimal_string(item[1]["allocated_value"], label=f"{comparison_id}.allocated")
            for item in members
        )
        if allocated > capacity:
            for link, allocation in members:
                link["status"] = "HUMAN_REVIEW_REQUIRED"
                link["reason_code"] = "PARTIAL_OVER_ALLOCATION"
                allocation["status"] = "HUMAN_REVIEW_REQUIRED"
            discrepancies.append(
                make_discrepancy(
                    "PARTIAL_OVER_ALLOCATION",
                    rule_id,
                    {
                        "capacity_record_id": capacity_record,
                        "comparison_id": comparison_id,
                        "capacity": decimal_text(capacity),
                        "allocated": decimal_text(allocated),
                    },
                )
            )
    allocations.sort(key=lambda item: str(item["allocation_id"]))
    return allocations


def quality_for_match_status(status: str) -> str:
    if status == "EXACT_MATCH":
        return "PASS"
    if status in {"WITHIN_TOLERANCE", "PARTIAL_MATCH"}:
        return "PASS_WITH_WARNINGS"
    if status in {"STRONG_CANDIDATE", "AMBIGUOUS_MATCH", "HUMAN_REVIEW_REQUIRED"}:
        return "CONDITIONAL"
    if status in {"CONFLICTING_MATCH", "UNMATCHED"}:
        return "FAIL"
    return "NOT_TESTED"


def schema_tolerance(value: object) -> dict[str, object]:
    source = value if isinstance(value, dict) else {}
    return {
        "status": source.get("status", "NOT_APPLICABLE"),
        "value": source.get("value"),
        "unit": source.get("unit", "NOT_APPLICABLE"),
        "basis": source.get("basis"),
        "owner": source.get("owner"),
        "approval_reference": source.get("approval_reference"),
        "approval_status": source.get("approval_status", "NOT_REQUESTED"),
    }


def schema_difference(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and DECIMAL_PATTERN.fullmatch(value):
        return value
    if isinstance(value, dict):
        candidate = value.get("absolute", value.get("days"))
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return str(candidate)
        if isinstance(candidate, str) and DECIMAL_PATTERN.fullmatch(candidate):
            return candidate
    return None


def build_schema_results(
    pair_results: list[dict[str, object]],
    links: list[dict[str, object]],
    records: list[dict[str, object]],
    normalized_config: Mapping[str, object],
    run_id: str,
) -> list[dict[str, object]]:
    """Render one canonical reconciliation-result record per evaluated pair."""

    record_map = {str(record["record_id"]): record for record in records}
    rules = normalized_config["link_rules"]
    roles = normalized_config["roles"]
    assert isinstance(rules, list) and isinstance(roles, list)
    rule_map = {str(rule["rule_id"]): rule for rule in rules}
    role_map = {str(role["role_id"]): role for role in roles}
    link_map = {
        (str(link["rule_id"]), str(link["left_record_id"]), str(link["right_record_id"])): link
        for link in links
    }
    rendered: list[dict[str, object]] = []
    for pair in pair_results:
        rule_id = str(pair["rule_id"])
        left_id = str(pair["left_record_id"])
        right_id = str(pair["right_record_id"])
        rule = rule_map[rule_id]
        left_role = str(rule["left_role"])
        right_role = str(rule["right_role"])
        pair_link = link_map.get((rule_id, left_id, right_id))
        status = str(pair_link["status"] if pair_link is not None else pair["status"])
        reason = str(
            (pair_link or pair).get("reason_code")
            or f"DETERMINISTIC_PAIR_STATUS_{status}"
        )

        participants: list[dict[str, object]] = []
        for role_id, record_id in ((left_role, left_id), (right_role, right_id)):
            role = role_map[role_id]
            source_kind = str(role["source_kind"])
            grain = str(normalized_config["grain"])
            if grain == "LINE_ITEM":
                object_kind = "LINE_ITEM"
            elif grain == "PAYMENT_ALLOCATION":
                object_kind = "PAYMENT_ALLOCATION"
            else:
                object_kind = source_kind
            source_reference = record_map[record_id].get("source_reference")
            participants.append(
                {
                    "role_id": role_id,
                    "object_kind": object_kind,
                    "record_ids": [record_id],
                    "source_references": (
                        [source_reference]
                        if isinstance(source_reference, str) and source_reference.strip()
                        else []
                    ),
                }
            )

        rule_results: list[dict[str, object]] = []
        comparisons = pair["comparisons"]
        assert isinstance(comparisons, list)
        for comparison in comparisons:
            assert isinstance(comparison, dict)
            left_raw = comparison.get("left_value")
            right_raw = comparison.get("right_value")
            rule_results.append(
                {
                    "rule_id": rule_id,
                    "component_id": comparison["comparison_id"],
                    "left_field": comparison["left_field"],
                    "right_field": comparison["right_field"],
                    "comparator": comparison["comparator"],
                    "normalizers": list(comparison["normalizers"]),
                    "left_raw_value": left_raw,
                    "right_raw_value": right_raw,
                    "left_normalized_value": comparison.get("normalized_left", left_raw),
                    "right_normalized_value": comparison.get("normalized_right", right_raw),
                    "difference": schema_difference(comparison.get("difference")),
                    "tolerance": schema_tolerance(comparison.get("tolerance")),
                    "status": comparison["status"],
                    "reason": comparison["reason_code"],
                }
            )
        review_required = status not in {
            "EXACT_MATCH", "WITHIN_TOLERANCE", "PARTIAL_MATCH"
        }
        rendered.append(
            {
                "schema_version": "1.0.0",
                "record_version": 1,
                "reconciliation_id": stable_id(
                    "recon",
                    {
                        "run_id": run_id,
                        "rule_id": rule_id,
                        "left_record_id": left_id,
                        "right_record_id": right_id,
                    },
                ),
                "run_id": run_id,
                "config_id": normalized_config["config_id"],
                "config_version": normalized_config["config_version"],
                "mode": normalized_config["mode"],
                "grain": normalized_config["grain"],
                "participants": participants,
                "rule_results": rule_results,
                "status": status,
                "quality_status": quality_for_match_status(status),
                "reason": reason,
                "supporting_evidence_ids": [],
                "human_review": {
                    "required": review_required,
                    "status": "REQUIRED" if review_required else "NOT_REQUIRED",
                    "reviewer": None,
                    "decision": None,
                    "reviewed_at": None,
                },
                "limitations": [
                    "Deterministic technical comparison only; business interpretation requires accountable human review.",
                    "The result does not establish authenticity, fraud, legality, materiality, or payment authorization.",
                ],
            }
        )
    rendered.sort(key=lambda item: str(item["reconciliation_id"]))
    return rendered


def reconcile(
    package: dict[str, object],
    config: dict[str, object],
    *,
    input_bytes: bytes | None = None,
    config_bytes: bytes | None = None,
    max_pairs: int = 1_000_000,
) -> dict[str, object]:
    if max_pairs <= 0:
        raise ReconciliationError("max_pairs must be positive")
    normalized_config = validate_config(config)
    records = validate_records_package(package)
    effective_input_bytes = input_bytes or canonical_json_bytes(package)
    effective_config_bytes = config_bytes or canonical_json_bytes(config)
    input_sha256 = sha256_bytes(effective_input_bytes)
    config_sha256 = sha256_bytes(effective_config_bytes)
    run_id = "reconciliation-" + sha256_bytes(
        canonical_json_bytes(
            {
                "input_sha256": input_sha256,
                "config_sha256": config_sha256,
                "max_pairs": max_pairs,
            }
        )
    )[:24]
    supplied_package_id = package.get("package_id")
    package_id = (
        supplied_package_id
        if isinstance(supplied_package_id, str)
        and IDENTIFIER_PATTERN.fullmatch(supplied_package_id)
        else f"pkg-{input_sha256[:24]}"
    )
    roles = normalized_config["roles"]
    rules = normalized_config["link_rules"]
    aggregation_rules = normalized_config["aggregation_rules"]
    assert isinstance(roles, list) and isinstance(rules, list) and isinstance(aggregation_rules, list)
    declared_roles = {str(role["role"]): bool(role["required"]) for role in roles}
    unknown_roles = sorted({str(record["role"]) for record in records} - set(declared_roles))
    if unknown_roles:
        raise ReconciliationError("input contains undeclared roles: " + ", ".join(unknown_roles))
    by_role: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        by_role[str(record["role"])].append(record)

    discrepancies: list[dict[str, object]] = []
    discrepancy_register: list[dict[str, object]] = []
    aggregations, aggregation_values, aggregation_issues = compute_aggregations(
        records, roles, aggregation_rules
    )
    aggregation_roles = {
        str(rule["aggregation_id"]): str(rule["role_id"]) for rule in aggregation_rules
    }
    for issue in aggregation_issues:
        discrepancies.append(
            make_discrepancy("AGGREGATION_INPUT_INVALID", None, issue)
        )
    for role, required in sorted(declared_roles.items()):
        if required and not by_role[role]:
            discrepancies.append(
                make_discrepancy(
                    "MISSING_REQUIRED_ROLE",
                    None,
                    {"role": role},
                )
            )

    pair_results: list[dict[str, object]] = []
    links: list[dict[str, object]] = []
    global_approval = str(normalized_config["human_approval_status"])
    pair_count = 0
    for rule in rules:
        rule_id = str(rule["rule_id"])
        left_records = by_role[str(rule["left_role"])]
        right_records = by_role[str(rule["right_role"])]
        potential = len(left_records) * len(right_records)
        pair_count += potential
        if pair_count > max_pairs:
            raise ReconciliationError(
                f"candidate pair count exceeds max_pairs={max_pairs}; narrow the authorized input"
            )
        rule_pairs: list[dict[str, object]] = []
        for left in left_records:
            for right in right_records:
                left_fields = left["fields"]
                right_fields = right["fields"]
                assert isinstance(left_fields, dict) and isinstance(right_fields, dict)
                comparison_results = [
                    compare_values(
                        comparison,
                        left_fields,
                        right_fields,
                        global_approval=global_approval,
                        left_record_id=str(left["record_id"]),
                        right_record_id=str(right["record_id"]),
                        aggregation_values=aggregation_values,
                        aggregation_roles=aggregation_roles,
                        date_policy=normalized_config["date_policy"],
                    )
                    for comparison in rule["comparisons"]
                ]
                status = pair_status(comparison_results)
                pair = {
                    "pair_id": stable_id(
                        "pair",
                        {
                            "rule_id": rule_id,
                            "left": left["record_id"],
                            "right": right["record_id"],
                        },
                    ),
                    "rule_id": rule_id,
                    "left_record_id": left["record_id"],
                    "right_record_id": right["record_id"],
                    "status": status,
                    "comparisons": comparison_results,
                }
                for comparison_result in comparison_results:
                    if comparison_result["status"] != "CONFLICTING_MATCH":
                        continue
                    contract_discrepancy = make_contract_discrepancy(
                        package_id=str(package_id),
                        rule_id=rule_id,
                        left_record=left,
                        right_record=right,
                        comparison=comparison_result,
                    )
                    discrepancy_register.append(contract_discrepancy)
                    discrepancies.append(
                        make_discrepancy(
                            str(contract_discrepancy["discrepancy_type"]),
                            rule_id,
                            {
                                "discrepancy_type": contract_discrepancy["discrepancy_type"],
                                "component_id": comparison_result["comparison_id"],
                                "left_record_id": left["record_id"],
                                "right_record_id": right["record_id"],
                                "left_field": comparison_result["left_field"],
                                "right_field": comparison_result["right_field"],
                                "left_raw_value": comparison_result["left_value"],
                                "right_raw_value": comparison_result["right_value"],
                            },
                        )
                    )
                rule_pairs.append(pair)
                pair_results.append(pair)

        selected, ambiguous = select_pairs(rule_pairs, str(rule["cardinality"]))
        for pair in ambiguous:
            pair["status"] = "AMBIGUOUS_MATCH"
            pair["reason_code"] = "MULTIPLE_CANDIDATES_REQUIRE_HUMAN_REVIEW"
        for pair in selected:
            link = {
                "link_id": stable_id(
                    "link",
                    {
                        "rule_id": rule_id,
                        "left": pair["left_record_id"],
                        "right": pair["right_record_id"],
                    },
                ),
                "rule_id": rule_id,
                "left_record_id": pair["left_record_id"],
                "right_record_id": pair["right_record_id"],
                "status": pair["status"],
                "comparisons": pair["comparisons"],
            }
            links.append(link)
        if ambiguous:
            grouped_left: defaultdict[str, list[str]] = defaultdict(list)
            for pair in ambiguous:
                grouped_left[str(pair["left_record_id"])].append(str(pair["right_record_id"]))
            for left_id, right_ids in sorted(grouped_left.items()):
                discrepancies.append(
                    make_discrepancy(
                        str(rule["multiple_candidate_policy"]),
                        rule_id,
                        {
                            "left_record_id": left_id,
                            "candidate_right_record_ids": sorted(set(right_ids)),
                        },
                    )
                )

        selected_left = {str(link["left_record_id"]) for link in links if link["rule_id"] == rule_id}
        selected_right = {str(link["right_record_id"]) for link in links if link["rule_id"] == rule_id}
        ambiguous_left = {str(pair["left_record_id"]) for pair in ambiguous}
        ambiguous_right = {str(pair["right_record_id"]) for pair in ambiguous}
        for left in left_records:
            record_id = str(left["record_id"])
            if record_id not in selected_left and record_id not in ambiguous_left:
                discrepancies.append(
                    make_discrepancy(
                        "UNMATCHED_LEFT_RECORD",
                        rule_id,
                        {"record_id": record_id, "role": rule["left_role"]},
                    )
                )
        for right in right_records:
            record_id = str(right["record_id"])
            if record_id not in selected_right and record_id not in ambiguous_right:
                discrepancies.append(
                    make_discrepancy(
                        "UNMATCHED_RIGHT_RECORD",
                        rule_id,
                        {"record_id": record_id, "role": rule["right_role"]},
                    )
                )

    allocations = apply_partial_allocation_checks(links, discrepancies)
    pair_results.sort(key=lambda item: (str(item["rule_id"]), str(item["left_record_id"]), str(item["right_record_id"])))
    links.sort(key=lambda item: str(item["link_id"]))
    unique_discrepancies = {
        str(item["discrepancy_id"]): item for item in discrepancies
    }
    discrepancies = [unique_discrepancies[key] for key in sorted(unique_discrepancies)]
    unique_registered = {
        str(item["discrepancy_id"]): item for item in discrepancy_register
    }
    discrepancy_register = [
        unique_registered[key] for key in sorted(unique_registered)
    ]

    warning_link = any(link["status"] in {"WITHIN_TOLERANCE", "PARTIAL_MATCH"} for link in links)
    review_link = any(link["status"] == "HUMAN_REVIEW_REQUIRED" for link in links)
    if discrepancies or review_link:
        run_status = "CONDITIONAL"
    elif warning_link:
        run_status = "PASS_WITH_WARNINGS"
    else:
        run_status = "PASS"

    role_counts = {role: len(by_role[role]) for role in sorted(declared_roles)}
    reconciliation_results = build_schema_results(
        pair_results, links, records, normalized_config, run_id
    )
    domain_results = {
        "status": run_status,
        "role_counts": role_counts,
        "pair_results": pair_results,
        "links": links,
        "allocations": allocations,
        "aggregations": aggregations,
        "discrepancies": discrepancies,
        "discrepancy_register": discrepancy_register,
        "reconciliation_results": reconciliation_results,
    }
    domain_sha256 = sha256_bytes(canonical_json_bytes(domain_results))
    return {
        "schema_version": "1.0.0",
        "result_type": "DETERMINISTIC_RECONCILIATION",
        "status": run_status,
        "package_id": package_id,
        "config": {
            "config_id": normalized_config["config_id"],
            "config_version": normalized_config["config_version"],
            "mode": normalized_config["mode"],
            "grain": normalized_config["grain"],
            "human_approval_status": normalized_config["human_approval_status"],
            "currency_policy": normalized_config["currency_policy"],
        },
        "run_manifest": {
            "run_id": run_id,
            "tool": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "timestamp": "NOT_RECORDED_FOR_DETERMINISTIC_OUTPUT",
            "input_sha256": input_sha256,
            "config_sha256": config_sha256,
            "domain_results_sha256": domain_sha256,
            "deterministic": True,
            "candidate_pair_count": pair_count,
            "max_pairs": max_pairs,
        },
        "summary": {
            "record_count": len(records),
            "role_counts": role_counts,
            "pair_count": len(pair_results),
            "link_count": len(links),
            "allocation_count": len(allocations),
            "aggregation_count": len(aggregations),
            "reconciliation_result_count": len(reconciliation_results),
            "discrepancy_count": len(discrepancies),
            "registered_discrepancy_count": len(discrepancy_register),
        },
        "pair_results": pair_results,
        "links": links,
        "allocations": allocations,
        "aggregations": aggregations,
        "discrepancies": discrepancies,
        "discrepancy_register": discrepancy_register,
        "reconciliation_results": reconciliation_results,
        "decision_scope": "TECHNICAL_RECONCILIATION_ONLY_REQUIRES_HUMAN_BUSINESS_REVIEW",
    }


def canonical_package_view(result: Mapping[str, object]) -> dict[str, object]:
    """Create a strict extraction-package view without changing the default API."""

    manifest = result["run_manifest"]
    summary = result["summary"]
    config = result["config"]
    assert isinstance(manifest, dict) and isinstance(summary, dict) and isinstance(config, dict)
    status = str(result["status"])
    if status == "PASS":
        execution_status = "SUCCEEDED"
    else:
        execution_status = "SUCCEEDED_WITH_WARNINGS"
    readiness = (
        "READY_FOR_HUMAN_REVIEW"
        if status == "CONDITIONAL"
        else "READY_FOR_LIMITED_USE"
    )
    return {
        "schema_version": "1.0.0",
        "package_id": result["package_id"],
        "package_version": "1.0.0",
        "skill_id": "thien-skill-document-evidence",
        "skill_version": TOOL_VERSION,
        "run_id": manifest["run_id"],
        "engagement_id": None,
        "case_id": None,
        "route": "LINK_RECONCILE",
        "status": readiness,
        "run_manifest": {
            "started_at": "UNKNOWN",
            "completed_at": "UNKNOWN",
            "execution_status": execution_status,
            "parent_run_id": None,
            "schema_versions": {
                "extraction_package": "1.0.0",
                "reconciliation_config": "1.0.0",
                "reconciliation_result": "1.0.0",
            },
            "tool_versions": {TOOL_NAME: TOOL_VERSION},
            "source_content_ids": [f"sha256:{manifest['input_sha256']}"],
            "config_checksums": {
                "reconciliation_config": manifest["config_sha256"]
            },
            "record_counts": {
                "input_records": int(summary["record_count"]),
                "reconciliation_results": int(summary["reconciliation_result_count"]),
                "discrepancies": int(summary["registered_discrepancy_count"]),
            },
            "retry_count": 0,
            "execution_history": [
                {
                    "step_id": "deterministic-reconciliation",
                    "status": "SUCCEEDED",
                    "method_change": None,
                    "timestamp": "UNKNOWN",
                }
            ],
        },
        "document_inventory": [],
        "evidence_register": [],
        "runtime_adapter_results": [],
        "extracted_fields": [],
        "line_items": [],
        "contract_clauses": [],
        "contract_obligations": [],
        "document_links": [],
        "reconciliation_results": result["reconciliation_results"],
        "discrepancies": result["discrepancy_register"],
        "human_review_queue": [],
        "chain_of_custody": [],
        "redaction_log": [],
        "field_dictionary": [],
        "outputs": [],
        "critical_field_failures": [],
        "security_flags": [],
        "assumptions": [],
        "limitations": [
            "This package contains deterministic technical comparison outputs; accountable human review remains required for business decisions."
        ],
        "qa_status": status,
        "human_approval_status": (
            "PENDING" if status == "CONDITIONAL" else config["human_approval_status"]
        ),
    }


def select_output_view(result: Mapping[str, object], output_view: str) -> Mapping[str, object]:
    if output_view == "full":
        return result
    if output_view == "package":
        return canonical_package_view(result)
    if output_view == "discrepancies":
        summary = result["summary"]
        manifest = result["run_manifest"]
        assert isinstance(summary, dict) and isinstance(manifest, dict)
        return {
            "schema_version": "1.0.0",
            "output_type": "DETERMINISTIC_DISCREPANCY_REGISTER",
            "package_id": result["package_id"],
            "run_id": manifest["run_id"],
            "status": result["status"],
            "run_manifest": manifest,
            "summary": {
                "registered_discrepancy_count": summary["registered_discrepancy_count"]
            },
            "discrepancies": result["discrepancy_register"],
            "decision_scope": "OBSERVED_DIFFERENCES_REQUIRING_AUTHORIZED_REVIEW",
        }
    raise ReconciliationError(f"unsupported output view: {output_view}")


def reject_output_alias(path: Path, protected_paths: Iterable[Path]) -> None:
    if not path.exists():
        return
    for protected in protected_paths:
        try:
            aliases = os.path.samefile(path, protected)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ReconciliationError(
                f"cannot verify output/input inode separation: {exc}"
            ) from exc
        if aliases:
            raise ReconciliationError(
                "output must not replace an input or configuration file; output must not alias protected inputs"
            )


def atomic_write(path: Path, data: bytes, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ReconciliationError(f"output already exists; use --overwrite: {path}")
    if path.is_symlink():
        raise ReconciliationError(f"output must not be a symlink: {path}")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ReconciliationError(f"output parent must be an existing real directory: {path.parent}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        if overwrite:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise ReconciliationError(
                    f"output appeared during atomic publication; refusing overwrite: {path}"
                ) from exc
            except OSError as exc:
                raise ReconciliationError(
                    f"cannot atomically publish output without overwrite: {path}: {exc}"
                ) from exc
            temporary.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="record package JSON below --root")
    parser.add_argument("config", help="approved reconciliation config JSON below --root")
    parser.add_argument("--root", default=".", help="authorized root for both input files")
    parser.add_argument("--max-pairs", type=int, default=1_000_000)
    parser.add_argument(
        "--output-view",
        choices=("full", "package", "discrepancies"),
        default="full",
        help="full backward-compatible result, canonical package, or discrepancy register",
    )
    parser.add_argument("--output", type=Path, help="optional result path below --root")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        root = resolve_root(args.root)
        input_path = resolve_file(root, args.input, label="input")
        config_path = resolve_file(root, args.config, label="config")
        package, input_bytes = load_json_object(input_path, label="input")
        config, config_bytes = load_json_object(config_path, label="config")
        result = reconcile(
            package,
            config,
            input_bytes=input_bytes,
            config_bytes=config_bytes,
            max_pairs=args.max_pairs,
        )
        selected_view = select_output_view(result, args.output_view)
        rendered = (
            json.dumps(selected_view, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        if args.output is None or args.dry_run:
            sys.stdout.buffer.write(rendered)
        else:
            output_path = resolve_output_file(root, args.output)
            reject_output_alias(output_path, (input_path, config_path))
            atomic_write(output_path, rendered, overwrite=args.overwrite)
            print(
                json.dumps(
                    {
                        "status": "WRITTEN",
                        "reconciliation_status": result["status"],
                        "output": str(output_path),
                        "sha256": sha256_bytes(rendered),
                    },
                    sort_keys=True,
                )
            )
        return 0
    except (ReconciliationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
