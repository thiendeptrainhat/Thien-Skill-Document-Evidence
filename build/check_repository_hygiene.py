#!/usr/bin/env python3
"""Fail-closed repository hygiene and size-budget gate.

The gate scans the actual working tree, not only tracked files or archive
members. It never deletes or rewrites content. Intentional large artifacts and
byte-identical copies are controlled by the explicit policy in build/config.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path("build/config.json")
SOURCE_SUFFIXES = {".mjs", ".py"}
GENERATED_BINARY_SUFFIXES = {".docx", ".pptx", ".xlsx", ".xls"}


class HygieneError(ValueError):
    """Raised when repository content violates a hygiene invariant."""


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise HygieneError(f"{label} must be a positive integer")
    return value


def _safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise HygieneError(f"{label} must be a safe POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HygieneError(f"{label} must be a safe POSIX relative path")
    if path.as_posix() != value:
        raise HygieneError(f"{label} must be a normalized POSIX relative path")
    return value


def load_policy(root: Path = ROOT) -> tuple[dict[str, object], list[str]]:
    config_path = Path(root) / CONFIG_PATH
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HygieneError(f"cannot read valid policy from {config_path}: {exc}") from exc
    if not isinstance(config, dict):
        raise HygieneError("build/config.json must be a JSON object")
    raw = config.get("repository_hygiene")
    if not isinstance(raw, dict):
        raise HygieneError("build/config.json must define repository_hygiene")

    required_integers = (
        "max_repository_bytes",
        "max_dist_bytes",
        "max_regular_file_bytes",
        "max_dist_file_bytes",
        "max_brand_asset_bytes",
        "source_soft_line_limit",
        "source_hard_line_limit",
        "max_preserved_dist_versions",
    )
    policy = dict(raw)
    for key in required_integers:
        policy[key] = _positive_int(policy.get(key), f"repository_hygiene.{key}")
    if int(policy["source_soft_line_limit"]) >= int(policy["source_hard_line_limit"]):
        raise HygieneError("source_soft_line_limit must be below source_hard_line_limit")

    for key in ("forbidden_names", "forbidden_prefixes", "forbidden_suffixes"):
        values = policy.get(key)
        if not isinstance(values, list) or not values or any(
            not isinstance(value, str) or not value for value in values
        ):
            raise HygieneError(f"repository_hygiene.{key} must be a non-empty string array")
        if len(values) != len(set(values)):
            raise HygieneError(f"repository_hygiene.{key} entries must be unique")

    allowed_binaries = policy.get("allowed_generated_binary_paths")
    if not isinstance(allowed_binaries, list):
        raise HygieneError("allowed_generated_binary_paths must be an array")
    policy["allowed_generated_binary_paths"] = [
        _safe_relative(value, "allowed_generated_binary_paths entry")
        for value in allowed_binaries
    ]

    duplicate_groups = policy.get("allowed_duplicate_groups")
    if not isinstance(duplicate_groups, list):
        raise HygieneError("allowed_duplicate_groups must be an array")
    normalized_groups: list[list[str]] = []
    for index, group in enumerate(duplicate_groups):
        if not isinstance(group, list) or len(group) < 2:
            raise HygieneError(f"allowed_duplicate_groups[{index}] must contain at least two paths")
        normalized = sorted(
            _safe_relative(value, f"allowed_duplicate_groups[{index}] entry")
            for value in group
        )
        if len(normalized) != len(set(normalized)):
            raise HygieneError(f"allowed_duplicate_groups[{index}] contains duplicate paths")
        normalized_groups.append(normalized)
    if len({tuple(group) for group in normalized_groups}) != len(normalized_groups):
        raise HygieneError("allowed_duplicate_groups entries must be unique")
    policy["allowed_duplicate_groups"] = normalized_groups

    preserved = config.get("preserved_dist_versions", [])
    if not isinstance(preserved, list) or any(not isinstance(value, str) for value in preserved):
        raise HygieneError("preserved_dist_versions must be a string array")
    return policy, preserved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _line_count(path: Path) -> int:
    data = path.read_bytes()
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def _walk(root: Path) -> tuple[list[Path], list[Path], list[Path]]:
    files: list[Path] = []
    symlinks: list[Path] = []
    empty_directories: list[Path] = []
    def fail_on_walk_error(error: OSError) -> None:
        location = error.filename or str(root)
        raise HygieneError(f"cannot scan repository path {location}: {error}")

    for current, directories, filenames in os.walk(
        root,
        topdown=True,
        followlinks=False,
        onerror=fail_on_walk_error,
    ):
        current_path = Path(current)
        if current_path == root:
            directories[:] = sorted(name for name in directories if name != ".git")
            filenames = sorted(name for name in filenames if name != ".git")
        else:
            directories[:] = sorted(directories)
            filenames = sorted(filenames)
        for name in list(directories):
            path = current_path / name
            if path.is_symlink():
                symlinks.append(path)
                directories.remove(name)
        for name in filenames:
            path = current_path / name
            if path.is_symlink():
                symlinks.append(path)
            else:
                files.append(path)
        if current_path != root and not directories and not filenames:
            empty_directories.append(current_path)
    return files, symlinks, empty_directories


def evaluate_repository(
    root: Path,
    policy: Mapping[str, object],
    preserved_versions: Iterable[str],
) -> dict[str, object]:
    root = Path(root).resolve()
    if not root.is_dir():
        raise HygieneError(f"repository root is not a directory: {root}")
    files, symlinks, empty_directories = _walk(root)
    errors: list[str] = []
    warnings: list[str] = []
    total_bytes = 0
    dist_bytes = 0
    hashes: dict[str, list[str]] = {}
    forbidden_names = set(policy["forbidden_names"])
    forbidden_prefixes = tuple(str(value) for value in policy["forbidden_prefixes"])
    forbidden_suffixes = tuple(str(value) for value in policy["forbidden_suffixes"])
    allowed_binaries = set(policy["allowed_generated_binary_paths"])

    for path in symlinks:
        errors.append(f"symlink is not allowed: {path.relative_to(root).as_posix()}")
    for path in empty_directories:
        errors.append(f"empty directory is not allowed: {path.relative_to(root).as_posix()}")

    for path in files:
        relative = path.relative_to(root).as_posix()
        metadata = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            errors.append(f"special file is not allowed: {relative}")
            continue
        parts = PurePosixPath(relative).parts
        if any(
            part in forbidden_names or part.startswith(forbidden_prefixes)
            for part in parts
        ):
            errors.append(f"forbidden repository metadata/cache path: {relative}")
        if any(
            part.endswith("~")
            or PurePosixPath(part).suffix.casefold() in forbidden_suffixes
            for part in parts
        ):
            errors.append(f"forbidden temporary/generated suffix: {relative}")
        if path.suffix.casefold() in GENERATED_BINARY_SUFFIXES and relative not in allowed_binaries:
            errors.append(f"generated Office artifact is not allowlisted: {relative}")

        size = metadata.st_size
        total_bytes += size
        if parts and parts[0] == "dist":
            dist_bytes += size
            limit = int(policy["max_dist_file_bytes"])
        elif relative.startswith("thien-skill-document-evidence/assets/brand/"):
            limit = int(policy["max_brand_asset_bytes"])
        else:
            limit = int(policy["max_regular_file_bytes"])
        if size > limit:
            errors.append(f"file exceeds {limit}-byte budget: {relative} ({size} bytes)")

        if path.suffix.casefold() in SOURCE_SUFFIXES:
            lines = _line_count(path)
            if lines > int(policy["source_hard_line_limit"]):
                errors.append(
                    f"source exceeds hard line limit {policy['source_hard_line_limit']}: "
                    f"{relative} ({lines} lines)"
                )
            elif lines > int(policy["source_soft_line_limit"]):
                warnings.append(
                    f"source exceeds soft review limit {policy['source_soft_line_limit']}: "
                    f"{relative} ({lines} lines)"
                )

        digest = _sha256(path)
        hashes.setdefault(digest, []).append(relative)

    if total_bytes > int(policy["max_repository_bytes"]):
        errors.append(
            f"repository exceeds {policy['max_repository_bytes']}-byte budget: {total_bytes} bytes"
        )
    if dist_bytes > int(policy["max_dist_bytes"]):
        errors.append(f"dist exceeds {policy['max_dist_bytes']}-byte budget: {dist_bytes} bytes")

    preserved = list(preserved_versions)
    if len(preserved) > int(policy["max_preserved_dist_versions"]):
        errors.append(
            "preserved_dist_versions exceeds explicit retention cap "
            f"{policy['max_preserved_dist_versions']}: {len(preserved)}"
        )

    allowed_groups = {
        tuple(sorted(group)) for group in policy["allowed_duplicate_groups"]
    }
    observed_groups = sorted(
        tuple(sorted(paths)) for paths in hashes.values() if len(paths) > 1
    )
    unexpected_groups = [group for group in observed_groups if group not in allowed_groups]
    for group in unexpected_groups:
        errors.append("unexpected byte-identical duplicate group: " + ", ".join(group))

    return {
        "status": "PASS" if not errors else "FAIL",
        "files": len(files),
        "total_bytes": total_bytes,
        "dist_bytes": dist_bytes,
        "duplicate_groups": len(observed_groups),
        "preserved_dist_versions": len(preserved),
        "warnings": sorted(warnings),
        "errors": sorted(errors),
    }


def check_repository(root: Path = ROOT) -> dict[str, object]:
    policy, preserved = load_policy(root)
    report = evaluate_repository(root, policy, preserved)
    if report["status"] != "PASS":
        raise HygieneError("repository hygiene gate failed: " + "; ".join(report["errors"]))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify repository junk and size budgets.")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root to inspect")
    args = parser.parse_args(argv)
    try:
        report = check_repository(args.root)
    except (OSError, HygieneError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
