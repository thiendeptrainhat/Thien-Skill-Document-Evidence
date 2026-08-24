#!/usr/bin/env python3
"""Validate JSON/JSONL records and optional package file hashes deterministically.

The bundled validator implements the JSON Schema keywords used by this skill's
schemas, including local/external file references. Remote references, symlinks,
path traversal, implicit type coercion, and source mutation are prohibited.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit


TOOL_NAME = "thien-record-validator"
TOOL_VERSION = "1.0.0"
MAX_SCHEMA_DEPTH = 128


class ValidationToolError(ValueError):
    """Raised for unsafe paths, invalid data files, or unsupported schemas."""


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular_nofollow(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValidationToolError(f"cannot safely open {path}: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValidationToolError(f"source is not a regular file: {path}")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValidationToolError(f"package member is not a regular file: {path}")
        handle = os.fdopen(descriptor, "rb")
        descriptor = -1
        with handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise ValidationToolError(f"cannot hash {path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return digest.hexdigest()


def _absolute_without_resolution(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def resolve_real_root(raw_root: str | Path, *, label: str) -> Path:
    supplied = Path(raw_root).expanduser()
    if supplied.is_symlink():
        raise ValidationToolError(f"{label} must not be a symlink: {supplied}")
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise ValidationToolError(f"cannot resolve {label} {supplied}: {exc}") from exc
    if not root.is_dir():
        raise ValidationToolError(f"{label} is not a directory: {supplied}")
    return root


def resolve_regular_file(root: Path, raw_path: str | Path, *, label: str) -> Path:
    supplied = Path(raw_path).expanduser()
    lexical = supplied if supplied.is_absolute() else root / supplied
    lexical = _absolute_without_resolution(lexical)
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise ValidationToolError(f"{label} escapes authorized root: {raw_path}") from exc
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValidationToolError(f"{label} must not traverse a symlink: {relative}")
    if not lexical.is_file():
        raise ValidationToolError(f"{label} is not a regular file: {raw_path}")
    return lexical


def resolve_output_file(root: Path, raw_path: str | Path) -> Path:
    supplied = Path(raw_path).expanduser()
    lexical = supplied if supplied.is_absolute() else root / supplied
    lexical = _absolute_without_resolution(lexical)
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise ValidationToolError(f"output escapes authorized root: {raw_path}") from exc
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValidationToolError(f"output must not traverse a symlink: {relative}")
    if lexical.is_symlink():
        raise ValidationToolError(f"output must not be a symlink: {relative}")
    if not lexical.parent.is_dir():
        raise ValidationToolError(f"output parent must be an existing directory: {lexical.parent}")
    if lexical.exists() and not lexical.is_file():
        raise ValidationToolError(f"output is not a regular file path: {relative}")
    return lexical


def load_json_bytes(data: bytes, *, label: str) -> object:
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
        raise ValidationToolError(f"{label} must contain valid UTF-8 JSON: {exc}") from exc


def load_input(path: Path, input_format: str) -> tuple[object, bytes]:
    data = read_regular_nofollow(path)
    selected = input_format
    if selected == "auto":
        selected = "jsonl" if path.suffix.casefold() in {".jsonl", ".ndjson"} else "json"
    if selected == "json":
        return load_json_bytes(data, label=path.name), data

    records: list[object] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationToolError(f"{path.name} must be UTF-8 JSONL: {exc}") from exc
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(load_json_bytes(line.encode("utf-8"), label=f"{path.name} line {line_number}"))
        except ValidationToolError as exc:
            raise ValidationToolError(
                f"{path.name} line {line_number} is invalid JSON: {exc}"
            ) from exc
    return records, data


def extract_records(payload: object, records_key: str) -> tuple[list[object], str]:
    if isinstance(payload, dict) and records_key in payload:
        records = payload[records_key]
        if not isinstance(records, list):
            raise ValidationToolError(f"package field {records_key!r} must be an array")
        return records, f"$.{records_key}"
    if isinstance(payload, list):
        return payload, "$"
    return [payload], "$"


def json_equal(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    return left == right


def instance_has_type(instance: object, expected: str) -> bool:
    if expected == "null":
        return instance is None
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    raise ValidationToolError(f"unsupported JSON Schema type: {expected!r}")


def pointer_get(document: object, fragment: str) -> object:
    if fragment in {"", "#"}:
        return document
    raw = fragment[1:] if fragment.startswith("#") else fragment
    if not raw.startswith("/"):
        raise ValidationToolError(f"unsupported JSON reference fragment: {fragment!r}")
    current = document
    for encoded in raw[1:].split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValidationToolError(f"JSON reference fragment does not exist: {fragment!r}")
    return current


class InternalSchemaValidator:
    """Small, non-coercing validator for the schema vocabulary used here."""

    def __init__(self, schema_path: Path, schema_root: Path, *, max_errors: int = 200):
        self.schema_root = schema_root
        self.schema_path = schema_path
        self.max_errors = max_errors
        self.documents: dict[Path, object] = {}
        self.documents[schema_path] = self._load_schema(schema_path)

    def _load_schema(self, path: Path) -> object:
        data = read_regular_nofollow(path)
        schema = load_json_bytes(data, label=f"schema {path.name}")
        if not isinstance(schema, (dict, bool)):
            raise ValidationToolError(f"schema {path.name} must be a JSON object or boolean")
        return schema

    def _resolve_ref(self, raw_ref: str, current_path: Path) -> tuple[object, Path]:
        parsed = urlsplit(raw_ref)
        if parsed.scheme or parsed.netloc:
            raise ValidationToolError(f"remote or URL schema reference is prohibited: {raw_ref}")
        if parsed.query:
            raise ValidationToolError(f"schema reference query is prohibited: {raw_ref}")
        if parsed.path:
            referenced = resolve_regular_file(
                self.schema_root,
                _absolute_without_resolution(current_path.parent / parsed.path),
                label="schema reference",
            )
        else:
            referenced = current_path
        if referenced not in self.documents:
            self.documents[referenced] = self._load_schema(referenced)
        target = pointer_get(self.documents[referenced], f"#{parsed.fragment}" if parsed.fragment else "#")
        return target, referenced

    @staticmethod
    def _error(path: str, keyword: str, message: str) -> dict[str, str]:
        return {"path": path, "keyword": keyword, "message": message}

    def validate(self, instance: object) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        self._validate(instance, self.documents[self.schema_path], "$", self.schema_path, errors, 0)
        return errors[: self.max_errors]

    def _branch_errors(
        self,
        instance: object,
        schema: object,
        path: str,
        current_path: Path,
        depth: int,
    ) -> list[dict[str, str]]:
        branch: list[dict[str, str]] = []
        self._validate(instance, schema, path, current_path, branch, depth + 1)
        return branch

    def _validate(
        self,
        instance: object,
        raw_schema: object,
        path: str,
        current_path: Path,
        errors: list[dict[str, str]],
        depth: int,
    ) -> None:
        if len(errors) >= self.max_errors:
            return
        if depth > MAX_SCHEMA_DEPTH:
            raise ValidationToolError("schema recursion depth limit exceeded")
        if raw_schema is True:
            return
        if raw_schema is False:
            errors.append(self._error(path, "falseSchema", "value is prohibited by schema"))
            return
        if not isinstance(raw_schema, dict):
            raise ValidationToolError("schema node must be an object or boolean")
        schema = raw_schema

        ref = schema.get("$ref")
        if ref is not None:
            if not isinstance(ref, str):
                raise ValidationToolError("$ref must be a string")
            target, target_path = self._resolve_ref(ref, current_path)
            self._validate(instance, target, path, target_path, errors, depth + 1)
            if len(errors) >= self.max_errors:
                return

        if "allOf" in schema:
            branches = schema["allOf"]
            if not isinstance(branches, list):
                raise ValidationToolError("allOf must be an array")
            for branch in branches:
                self._validate(instance, branch, path, current_path, errors, depth + 1)

        if "anyOf" in schema:
            branches = schema["anyOf"]
            if not isinstance(branches, list) or not branches:
                raise ValidationToolError("anyOf must be a non-empty array")
            outcomes = [
                self._branch_errors(instance, branch, path, current_path, depth)
                for branch in branches
            ]
            if not any(not outcome for outcome in outcomes):
                errors.append(self._error(path, "anyOf", "value matches no allowed schema"))

        if "oneOf" in schema:
            branches = schema["oneOf"]
            if not isinstance(branches, list) or not branches:
                raise ValidationToolError("oneOf must be a non-empty array")
            outcomes = [
                self._branch_errors(instance, branch, path, current_path, depth)
                for branch in branches
            ]
            matches = sum(not outcome for outcome in outcomes)
            if matches != 1:
                errors.append(
                    self._error(path, "oneOf", f"value must match exactly one schema; matched {matches}")
                )

        condition = schema.get("if")
        if condition is not None:
            condition_errors = self._branch_errors(
                instance, condition, path, current_path, depth
            )
            selected = schema.get("then") if not condition_errors else schema.get("else")
            if selected is not None:
                self._validate(instance, selected, path, current_path, errors, depth + 1)

        if "not" in schema:
            outcome = self._branch_errors(instance, schema["not"], path, current_path, depth)
            if not outcome:
                errors.append(self._error(path, "not", "value matches a prohibited schema"))

        expected_type = schema.get("type")
        if expected_type is not None:
            candidates = expected_type if isinstance(expected_type, list) else [expected_type]
            if not candidates or any(not isinstance(item, str) for item in candidates):
                raise ValidationToolError("type must be a string or non-empty string array")
            if not any(instance_has_type(instance, item) for item in candidates):
                errors.append(
                    self._error(
                        path,
                        "type",
                        f"expected {' or '.join(candidates)}, got {type(instance).__name__}",
                    )
                )
                return

        if "const" in schema and not json_equal(instance, schema["const"]):
            errors.append(self._error(path, "const", f"expected constant {schema['const']!r}"))
        if "enum" in schema:
            values = schema["enum"]
            if not isinstance(values, list):
                raise ValidationToolError("enum must be an array")
            if not any(json_equal(instance, candidate) for candidate in values):
                errors.append(self._error(path, "enum", f"value {instance!r} is not allowed"))

        if isinstance(instance, dict):
            required = schema.get("required", [])
            if not isinstance(required, list):
                raise ValidationToolError("required must be an array")
            for key in required:
                if not isinstance(key, str):
                    raise ValidationToolError("required entries must be strings")
                if key not in instance:
                    errors.append(
                        self._error(path, "required", f"missing required property {key!r}")
                    )
            properties = schema.get("properties", {})
            if not isinstance(properties, dict):
                raise ValidationToolError("properties must be an object")
            for key in sorted(instance):
                child_path = f"{path}.{key}" if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) else f"{path}[{key!r}]"
                if key in properties:
                    self._validate(
                        instance[key], properties[key], child_path, current_path, errors, depth + 1
                    )
                else:
                    additional = schema.get("additionalProperties", True)
                    if additional is False:
                        errors.append(
                            self._error(child_path, "additionalProperties", "unexpected property")
                        )
                    elif isinstance(additional, dict) or isinstance(additional, bool):
                        self._validate(
                            instance[key], additional, child_path, current_path, errors, depth + 1
                        )
            if "minProperties" in schema and len(instance) < schema["minProperties"]:
                errors.append(self._error(path, "minProperties", "object has too few properties"))
            if "maxProperties" in schema and len(instance) > schema["maxProperties"]:
                errors.append(self._error(path, "maxProperties", "object has too many properties"))

        if isinstance(instance, list):
            if "minItems" in schema and len(instance) < schema["minItems"]:
                errors.append(self._error(path, "minItems", "array has too few items"))
            if "maxItems" in schema and len(instance) > schema["maxItems"]:
                errors.append(self._error(path, "maxItems", "array has too many items"))
            if schema.get("uniqueItems") is True:
                seen: set[bytes] = set()
                for index, value in enumerate(instance):
                    encoded = canonical_json_bytes(value)
                    if encoded in seen:
                        errors.append(
                            self._error(f"{path}[{index}]", "uniqueItems", "duplicate array item")
                        )
                    seen.add(encoded)
            items = schema.get("items")
            if items is not None:
                for index, value in enumerate(instance):
                    self._validate(
                        value, items, f"{path}[{index}]", current_path, errors, depth + 1
                    )

        if isinstance(instance, str):
            if "minLength" in schema and len(instance) < schema["minLength"]:
                errors.append(self._error(path, "minLength", "string is too short"))
            if "maxLength" in schema and len(instance) > schema["maxLength"]:
                errors.append(self._error(path, "maxLength", "string is too long"))
            pattern = schema.get("pattern")
            if pattern is not None:
                if not isinstance(pattern, str):
                    raise ValidationToolError("pattern must be a string")
                try:
                    matched = re.search(pattern, instance)
                except re.error as exc:
                    raise ValidationToolError(f"invalid schema regex pattern: {exc}") from exc
                if matched is None:
                    errors.append(self._error(path, "pattern", "string does not match pattern"))
            if schema.get("format") == "date":
                if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", instance) is None:
                    errors.append(self._error(path, "format", "invalid date string"))
                else:
                    try:
                        date.fromisoformat(instance)
                    except ValueError:
                        errors.append(self._error(path, "format", "invalid date string"))
            if schema.get("format") == "date-time":
                rfc3339 = re.fullmatch(
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}"
                    r"(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})",
                    instance,
                )
                try:
                    parsed_datetime = datetime.fromisoformat(
                        instance.replace("z", "+00:00").replace("Z", "+00:00")
                    )
                except ValueError:
                    errors.append(self._error(path, "format", "invalid date-time string"))
                else:
                    if rfc3339 is None or parsed_datetime.tzinfo is None:
                        errors.append(self._error(path, "format", "invalid date-time string"))

        if isinstance(instance, (int, float)) and not isinstance(instance, bool):
            if "minimum" in schema and instance < schema["minimum"]:
                errors.append(self._error(path, "minimum", "number is below minimum"))
            if "maximum" in schema and instance > schema["maximum"]:
                errors.append(self._error(path, "maximum", "number is above maximum"))
            if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
                errors.append(
                    self._error(path, "exclusiveMinimum", "number is not above exclusive minimum")
                )
            if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
                errors.append(
                    self._error(path, "exclusiveMaximum", "number is not below exclusive maximum")
                )


def safe_manifest_relative(raw_path: str) -> PurePosixPath:
    if not raw_path or "\\" in raw_path or "\x00" in raw_path:
        raise ValidationToolError(f"unsafe package member path: {raw_path!r}")
    path = PurePosixPath(raw_path)
    if (
        path.is_absolute()
        or re.match(r"^[A-Za-z]:", raw_path)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValidationToolError(f"unsafe package member path: {raw_path!r}")
    return path


def verify_package_files(payload: object, package_root: Path) -> list[dict[str, str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
        raise ValidationToolError("--package-root requires input object field `files`")
    errors: list[dict[str, str]] = []
    for relative, expected_value in sorted(payload["files"].items()):
        if not isinstance(relative, str):
            raise ValidationToolError("package files keys must be strings")
        safe = safe_manifest_relative(relative)
        expected = expected_value
        if isinstance(expected_value, dict):
            expected = expected_value.get("sha256")
        if not isinstance(expected, str) or re.fullmatch(r"[A-Fa-f0-9]{64}", expected) is None:
            errors.append(
                {
                    "path": f"$.files[{relative!r}]",
                    "keyword": "sha256",
                    "message": "expected a 64-character SHA-256 digest",
                }
            )
            continue
        try:
            target = resolve_regular_file(
                package_root,
                _absolute_without_resolution(package_root.joinpath(*safe.parts)),
                label="package member",
            )
        except ValidationToolError as exc:
            errors.append(
                {
                    "path": f"$.files[{relative!r}]",
                    "keyword": "file",
                    "message": str(exc),
                }
            )
            continue
        actual = sha256_file(target)
        if actual.casefold() != expected.casefold():
            errors.append(
                {
                    "path": f"$.files[{relative!r}]",
                    "keyword": "sha256",
                    "message": f"SHA-256 mismatch: expected {expected.casefold()}, got {actual}",
                }
            )
    return errors


def build_validation_report(
    *,
    input_bytes: bytes,
    schema_bytes: bytes,
    records: list[object],
    record_path: str,
    validator: InternalSchemaValidator,
    package_errors: Iterable[dict[str, str]] = (),
) -> dict[str, object]:
    errors: list[dict[str, object]] = []
    valid_count = 0
    for index, record in enumerate(records):
        record_errors = validator.validate(record)
        if not record_errors:
            valid_count += 1
        for error in record_errors:
            errors.append(
                {
                    "record_index": index,
                    "record_path": f"{record_path}[{index}]",
                    **error,
                }
            )
    for error in package_errors:
        errors.append({"record_index": None, "record_path": "$", **error})
    errors.sort(
        key=lambda error: (
            -1 if error["record_index"] is None else int(error["record_index"]),
            str(error["path"]),
            str(error["keyword"]),
            str(error["message"]),
        )
    )
    input_sha256 = sha256_bytes(input_bytes)
    schema_sha256 = sha256_bytes(schema_bytes)
    domain = {
        "record_count": len(records),
        "valid_count": valid_count,
        "invalid_count": len(records) - valid_count,
        "package_error_count": sum(error["record_index"] is None for error in errors),
        "errors": errors,
    }
    domain_sha256 = sha256_bytes(canonical_json_bytes(domain))
    run_id = "validation-" + sha256_bytes(
        canonical_json_bytes(
            {"input_sha256": input_sha256, "schema_sha256": schema_sha256}
        )
    )[:24]
    return {
        "schema_version": "1.0.0",
        "report_type": "SCHEMA_AND_PACKAGE_VALIDATION",
        "status": "PASS" if not errors else "FAIL",
        "run_manifest": {
            "run_id": run_id,
            "tool": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "timestamp": "NOT_RECORDED_FOR_DETERMINISTIC_OUTPUT",
            "input_sha256": input_sha256,
            "schema_sha256": schema_sha256,
            "domain_results_sha256": domain_sha256,
            "deterministic": True,
            "validator_engine": "INTERNAL_DRAFT_2020_SUBSET",
        },
        "summary": {key: value for key, value in domain.items() if key != "errors"},
        "errors": errors,
        "decision_scope": "STRUCTURAL_VALIDATION_ONLY",
    }


def reject_output_alias(path: Path, protected_paths: Iterable[Path]) -> None:
    if not path.exists():
        return
    for protected in protected_paths:
        try:
            aliases = os.path.samefile(path, protected)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValidationToolError(
                f"cannot verify output/input inode separation: {exc}"
            ) from exc
        if aliases:
            raise ValidationToolError(
                "output must not replace an input or schema file; output must not alias protected inputs"
            )


def atomic_write(path: Path, data: bytes, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ValidationToolError(f"output already exists; use --overwrite: {path}")
    if path.is_symlink():
        raise ValidationToolError(f"output must not be a symlink: {path}")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ValidationToolError(f"output parent must be an existing real directory: {path.parent}")
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
                raise ValidationToolError(
                    f"output appeared during atomic publication; refusing overwrite: {path}"
                ) from exc
            except OSError as exc:
                raise ValidationToolError(
                    f"cannot atomically publish output without overwrite: {path}: {exc}"
                ) from exc
            temporary.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    script_schema_root = Path(__file__).resolve().parents[1] / "schemas"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="JSON or JSONL input below --root")
    parser.add_argument("--root", default=".", help="authorized input/package root")
    parser.add_argument(
        "--schema",
        default="common/document-record.schema.json",
        help="schema path below --schema-root",
    )
    parser.add_argument(
        "--schema-root",
        default=str(script_schema_root),
        help="authorized local schema root; remote references are prohibited",
    )
    parser.add_argument("--format", choices=("auto", "json", "jsonl"), default="auto")
    parser.add_argument("--records-key", default="records")
    parser.add_argument(
        "--package-root",
        help="optional directory whose files are verified against input `files` hashes",
    )
    parser.add_argument("--max-errors", type=int, default=200)
    parser.add_argument("--output", type=Path, help="optional report path below --root")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.max_errors <= 0:
            raise ValidationToolError("--max-errors must be positive")
        root = resolve_real_root(args.root, label="authorized root")
        input_path = resolve_regular_file(root, args.input, label="input")
        payload, input_bytes = load_input(input_path, args.format)
        records, record_path = extract_records(payload, args.records_key)

        schema_root = resolve_real_root(args.schema_root, label="schema root")
        schema_path = resolve_regular_file(schema_root, args.schema, label="schema")
        schema_bytes = read_regular_nofollow(schema_path)
        validator = InternalSchemaValidator(
            schema_path, schema_root, max_errors=args.max_errors
        )
        package_errors: list[dict[str, str]] = []
        if args.package_root is not None:
            package_root = resolve_real_root(args.package_root, label="package root")
            package_errors = verify_package_files(payload, package_root)
        report = build_validation_report(
            input_bytes=input_bytes,
            schema_bytes=schema_bytes,
            records=records,
            record_path=record_path,
            validator=validator,
            package_errors=package_errors,
        )
        rendered = (
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        if args.output is None or args.dry_run:
            sys.stdout.buffer.write(rendered)
        else:
            output_path = resolve_output_file(root, args.output)
            reject_output_alias(output_path, (input_path, schema_path))
            atomic_write(output_path, rendered, overwrite=args.overwrite)
            print(
                json.dumps(
                    {
                        "status": "WRITTEN",
                        "validation_status": report["status"],
                        "output": str(output_path),
                        "sha256": sha256_bytes(rendered),
                    },
                    sort_keys=True,
                )
            )
        return 0 if report["status"] == "PASS" else 1
    except (ValidationToolError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
