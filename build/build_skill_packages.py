#!/usr/bin/env python3
"""Build and verify deterministic native-plugin and portable skill packages.

The repository keeps one canonical skill. This builder derives an OpenAI
skills-only plugin, a Claude skill plugin, and a Universal raw Agent Skill.
It never edits the canonical tree and renders every artifact in memory before
an atomic write to ``dist/``.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Mapping
import unicodedata
from urllib.parse import urlparse
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path("build/config.json")
PLATFORMS = ("openai", "claude", "universal")
PLATFORM_LABELS = {"openai": "OpenAI", "claude": "Claude", "universal": "Universal"}
PACKAGE_MANIFEST = "PACKAGE-MANIFEST.json"
SKILL_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
JUNK_NAMES = {".DS_Store", "__pycache__", ".pytest_cache", ".git"}
JUNK_SUFFIXES = {".pyc", ".pyo"}
TEXT_SUFFIXES = {
    ".csv", ".html", ".ipynb", ".json", ".md", ".py", ".r", ".sh", ".sql",
    ".toml", ".tsv", ".txt", ".xml", ".yaml", ".yml",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "API key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
}


class PackagingError(ValueError):
    """Raised when canonical input or a generated release is unsafe or invalid."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def tree_sha256(files: Mapping[str, bytes]) -> str:
    """Hash path/content pairs independently of timestamps and host permissions."""

    digest = hashlib.sha256()
    for relative in sorted(files):
        path_bytes = relative.encode("utf-8")
        content = files[relative]
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _require_string(config: Mapping[str, object], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PackagingError(f"config field {key!r} must be a non-empty string")
    return value


def _safe_relative(value: str, label: str) -> PurePosixPath:
    if not value or "\\" in value or "\x00" in value:
        raise PackagingError(f"{label} must use a safe POSIX relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PackagingError(f"{label} must use a safe POSIX relative path: {value!r}")
    if path.as_posix() != value or re.match(r"^[A-Za-z]:", value):
        raise PackagingError(f"{label} must be a normalized POSIX relative path: {value!r}")
    return path


def _safe_filename(value: str, label: str) -> str:
    path = _safe_relative(value, label)
    if len(path.parts) != 1:
        raise PackagingError(f"{label} must be one safe filename component")
    return value


def load_config(project_root: Path = ROOT) -> dict[str, object]:
    path = Path(project_root) / CONFIG_PATH
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackagingError(f"cannot read valid config at {path}: {exc}") from exc
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise PackagingError("build/config.json must be a schema_version 1 JSON object")

    skill_id = _require_string(config, "skill_id")
    if len(skill_id) > 64 or not SKILL_ID_RE.fullmatch(skill_id):
        raise PackagingError("skill_id must be at most 64 lowercase letters, digits, and hyphens")
    for key in (
        "display_name", "artifact_basename", "version", "status", "release_date",
        "repository_status", "canonical_source", "license_name",
    ):
        _require_string(config, key)
    if config["status"] != "Testing":
        raise PackagingError("this 1.0.0 release must retain status Testing")
    if config["repository_status"] != "private":
        raise PackagingError("repository_status must be private")
    repository = config.get("repository")
    if repository is not None:
        if not isinstance(repository, str) or not repository.strip():
            raise PackagingError("repository must be omitted or be a non-empty HTTPS URL")
        parsed_repository = urlparse(repository)
        if parsed_repository.scheme != "https" or not parsed_repository.netloc:
            raise PackagingError("repository must be omitted or be an absolute HTTPS URL")
    _safe_filename(str(config["artifact_basename"]), "artifact_basename")
    if not SEMVER_RE.fullmatch(str(config["version"])):
        raise PackagingError(f"version is not valid SemVer: {config['version']!r}")
    try:
        date.fromisoformat(str(config["release_date"]))
    except ValueError as exc:
        raise PackagingError("release_date must be YYYY-MM-DD") from exc
    canonical = _safe_relative(str(config["canonical_source"]), "canonical_source")
    if canonical.name != skill_id or len(canonical.parts) != 1:
        raise PackagingError("canonical_source must be the root folder named exactly skill_id")

    legal_files = config.get("legal_files")
    if not isinstance(legal_files, list) or not legal_files:
        raise PackagingError("legal_files must be a non-empty array")
    if any(not isinstance(value, str) for value in legal_files):
        raise PackagingError("every legal_files entry must be a string")
    legal = [_safe_relative(str(value), "legal_files entry").as_posix() for value in legal_files]
    if len(set(legal)) != len(legal) or "LICENSE.md" not in legal:
        raise PackagingError("legal_files must be unique and include LICENSE.md")
    config["legal_files"] = legal

    distribution_files = config.get("distribution_files")
    if not isinstance(distribution_files, list) or not distribution_files:
        raise PackagingError("distribution_files must be a non-empty array")
    if any(not isinstance(value, str) for value in distribution_files):
        raise PackagingError("every distribution_files entry must be a string")
    distribution = [
        _safe_relative(str(value), "distribution_files entry").as_posix()
        for value in distribution_files
    ]
    if len(set(distribution)) != len(distribution):
        raise PackagingError("distribution_files must be unique")
    config["distribution_files"] = distribution

    brand_assets = config.get("brand_assets")
    if not isinstance(brand_assets, dict) or set(brand_assets) != {"icon", "logo"}:
        raise PackagingError("brand_assets must define exactly icon and logo")
    for key, value in brand_assets.items():
        if not isinstance(value, str):
            raise PackagingError(f"brand_assets.{key} must be a string")
        _safe_relative(value, f"brand_assets.{key}")

    plugin_sources = config.get("plugin_sources")
    if not isinstance(plugin_sources, dict) or set(plugin_sources) != {"openai", "claude"}:
        raise PackagingError("plugin_sources must define exactly openai and claude")
    for platform, value in plugin_sources.items():
        if not isinstance(value, str):
            raise PackagingError(f"plugin_sources.{platform} must be a string")
        source = _safe_relative(value, f"plugin_sources.{platform}")
        if source.parts[:2] != ("platform", platform):
            raise PackagingError(f"plugin_sources.{platform} must stay below platform/{platform}/")

    artifact_names = config.get("artifact_names")
    if not isinstance(artifact_names, dict) or set(artifact_names) != set(PLATFORMS):
        raise PackagingError("artifact_names must define exactly openai, claude, and universal")
    expected = {
        platform: (
            f"{config['artifact_basename']}-{PLATFORM_LABELS[platform]}-v{config['version']}.zip"
        )
        for platform in PLATFORMS
    }
    for platform, expected_name in expected.items():
        if artifact_names.get(platform) != expected_name:
            raise PackagingError(f"artifact_names.{platform} must be exactly {expected_name!r}")
        _safe_filename(expected_name, f"artifact_names.{platform}")

    for key, default in (
        ("max_member_bytes", 16_777_216),
        ("max_archive_bytes", 50_000_000),
        ("max_uncompressed_bytes", 160_000_000),
    ):
        value = config.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise PackagingError(f"config field {key!r} must be a positive integer")
        config[key] = value
    return config


def _unquote_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise PackagingError(f"invalid quoted YAML scalar: {value!r}") from exc
        if not isinstance(parsed, str):
            raise PackagingError("expected a string YAML scalar")
        return parsed
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def parse_skill_frontmatter(data: bytes) -> dict[str, str]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise PackagingError("SKILL.md must be UTF-8") from exc
    if not lines or lines[0].strip() != "---":
        raise PackagingError("SKILL.md must start with YAML frontmatter")
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as exc:
        raise PackagingError("SKILL.md frontmatter is not closed") from exc
    values: dict[str, str] = {}
    index = 1
    while index < end:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]*(.*))?$", lines[index])
        if not match:
            index += 1
            continue
        key, raw = match.group(1), (match.group(2) or "").strip()
        if raw in {"|", "|-", "|+", ">", ">-", ">+"}:
            block: list[str] = []
            index += 1
            while index < end and (not lines[index].strip() or lines[index][0].isspace()):
                block.append(lines[index].strip())
                index += 1
            values[key] = ("\n" if raw.startswith("|") else " ").join(block).strip()
            continue
        values[key] = _unquote_yaml_scalar(raw)
        index += 1
    return values


def _yaml_scalar(text: str, key: str) -> str | None:
    match = re.search(rf"(?m)^[ \t]*{re.escape(key)}:[ \t]*(.+?)[ \t]*$", text)
    if not match:
        return None
    value = match.group(1).strip()
    if not value or value in {"|", "|-", "|+", ">", ">-", ">+"}:
        return None
    return _unquote_yaml_scalar(value)


def validate_openai_metadata(files: Mapping[str, bytes], config: Mapping[str, object]) -> None:
    relative = "agents/openai.yaml"
    data = files.get(relative)
    if data is None:
        raise PackagingError(f"canonical skill is missing required file {relative}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackagingError(f"{relative} must be UTF-8") from exc
    if not re.search(r"(?m)^interface:[ \t]*$", text):
        raise PackagingError(f"{relative} must define interface metadata")
    values = {key: _yaml_scalar(text, key) for key in ("display_name", "short_description", "default_prompt")}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise PackagingError(f"{relative} is missing non-empty values: {', '.join(missing)}")
    if f"${config['skill_id']}" not in str(values["default_prompt"]):
        raise PackagingError(f"{relative} default_prompt must mention ${config['skill_id']}")
    for key in ("icon_small", "icon_large"):
        icon = _yaml_scalar(text, key)
        if icon is None:
            continue
        normalized = icon[2:] if icon.startswith("./") else icon
        icon_path = _safe_relative(normalized, f"{relative} {key}").as_posix()
        if icon_path not in files:
            raise PackagingError(f"{relative} references missing {key}: {icon}")


def _scan_for_secrets(relative: str, data: bytes) -> None:
    if Path(relative).suffix.lower() not in TEXT_SUFFIXES:
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            raise PackagingError(f"possible {label} found in canonical file {relative}")


def collect_canonical_files(project_root: Path, config: Mapping[str, object]) -> dict[str, bytes]:
    canonical = Path(project_root) / str(config["canonical_source"])
    if canonical.is_symlink() or not canonical.is_dir():
        raise PackagingError(f"canonical skill folder must be a real directory: {canonical}")
    files: dict[str, bytes] = {}
    normalized_paths: dict[str, str] = {}
    for path in sorted(canonical.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(canonical).as_posix()
        if path.is_symlink():
            raise PackagingError(f"canonical symlink is not allowed: {relative}")
        parts = PurePosixPath(relative).parts
        if any(part in JUNK_NAMES for part in parts):
            raise PackagingError(f"canonical tree contains junk path: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise PackagingError(f"canonical entry is not a regular file: {relative}")
        if path.suffix.lower() in JUNK_SUFFIXES:
            raise PackagingError(f"canonical tree contains generated bytecode: {relative}")
        if path.name == PACKAGE_MANIFEST:
            raise PackagingError(f"{PACKAGE_MANIFEST} is generated and must not be canonical")
        normalized = unicodedata.normalize("NFC", relative).casefold()
        if normalized in normalized_paths:
            raise PackagingError(
                f"canonical path collision: {normalized_paths[normalized]!r} and {relative!r}"
            )
        normalized_paths[normalized] = relative
        data = path.read_bytes()
        if len(data) > int(config["max_member_bytes"]):
            raise PackagingError(f"canonical file exceeds max_member_bytes: {relative}")
        _scan_for_secrets(relative, data)
        files[relative] = data

    required = {"SKILL.md", "agents/openai.yaml"}
    required.update(str(item) for item in config["legal_files"])
    brand = config["brand_assets"]
    assert isinstance(brand, dict)
    required.update(str(value) for value in brand.values())
    missing = sorted(required - set(files))
    if missing:
        raise PackagingError(f"canonical skill is missing required files: {', '.join(missing)}")
    for relative in config["legal_files"]:
        if not files[str(relative)].strip():
            raise PackagingError(f"legal file must not be empty: {relative}")

    frontmatter = parse_skill_frontmatter(files["SKILL.md"])
    if frontmatter.get("name") != config["skill_id"]:
        raise PackagingError(
            f"SKILL.md name must be exactly {config['skill_id']!r}; got {frontmatter.get('name')!r}"
        )
    description = frontmatter.get("description", "").strip()
    if not description or "TODO" in description.upper():
        raise PackagingError("SKILL.md description must be complete and must not contain TODO")
    if len(description) > 1024:
        raise PackagingError("SKILL.md description must be at most 1024 characters")
    validate_openai_metadata(files, config)
    total = sum(len(data) for data in files.values())
    if total > int(config["max_uncompressed_bytes"]):
        raise PackagingError(f"canonical content is {total} bytes, above max_uncompressed_bytes")
    return dict(sorted(files.items()))


def _load_plugin_manifest(
    project_root: Path, config: Mapping[str, object], platform: str
) -> dict[str, object]:
    sources = config["plugin_sources"]
    assert isinstance(sources, dict)
    source = Path(project_root) / str(sources[platform])
    if source.is_symlink() or not source.is_file():
        raise PackagingError(f"{platform} plugin source must be a regular file: {source}")
    try:
        manifest = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackagingError(f"invalid {platform} plugin manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise PackagingError(f"{platform} plugin manifest must be a JSON object")
    _validate_plugin_manifest(manifest, config, platform)
    return manifest


def _validate_plugin_manifest(
    manifest: Mapping[str, object], config: Mapping[str, object], platform: str
) -> None:
    if manifest.get("name") != config["skill_id"]:
        raise PackagingError(f"{platform} plugin manifest name mismatch")
    if manifest.get("version") != config["version"]:
        raise PackagingError(f"{platform} plugin manifest version mismatch")
    description = manifest.get("description")
    if not isinstance(description, str) or not description.strip():
        raise PackagingError(f"{platform} plugin manifest description is required")
    if manifest.get("license") != config["license_name"]:
        raise PackagingError(f"{platform} plugin manifest license mismatch")
    configured_repository = config.get("repository")
    if manifest.get("repository") != configured_repository:
        raise PackagingError(f"{platform} plugin manifest repository mismatch")
    author = manifest.get("author")
    if (
        not isinstance(author, dict)
        or not isinstance(author.get("name"), str)
        or not str(author["name"]).strip()
    ):
        raise PackagingError(f"{platform} plugin manifest author.name is required")
    if platform == "openai":
        allowed = {
            "id", "name", "version", "description", "skills", "apps", "mcpServers",
            "interface", "author", "homepage", "repository", "license", "keywords",
        }
        unsupported = sorted(set(manifest) - allowed)
        if unsupported:
            raise PackagingError(
                "OpenAI plugin contains unsupported fields: " + ", ".join(unsupported)
            )
        if manifest.get("skills") != "./skills/":
            raise PackagingError("OpenAI plugin must declare skills as ./skills/")
        if {"mcpServers", "apps", "hooks"} & set(manifest):
            raise PackagingError("OpenAI package must remain a skills-only plugin")
        interface = manifest.get("interface")
        if not isinstance(interface, dict) or interface.get("displayName") != config["display_name"]:
            raise PackagingError("OpenAI plugin interface displayName mismatch")
        for key in ("shortDescription", "longDescription", "developerName", "category"):
            if not isinstance(interface.get(key), str) or not str(interface[key]).strip():
                raise PackagingError(f"OpenAI plugin interface {key} is required")
        capabilities = interface.get("capabilities")
        if (
            not isinstance(capabilities, list)
            or not capabilities
            or any(not isinstance(item, str) or not item.strip() for item in capabilities)
        ):
            raise PackagingError("OpenAI plugin interface capabilities must be non-empty strings")
        prompts = interface.get("defaultPrompt")
        if (
            not isinstance(prompts, list) or not 1 <= len(prompts) <= 3
            or any(not isinstance(item, str) or not item.strip() or len(item) > 128 for item in prompts)
        ):
            raise PackagingError("OpenAI plugin interface defaultPrompt must contain 1-3 short strings")
        for key, expected in (("composerIcon", "./assets/icon.png"), ("logo", "./assets/logo.png")):
            if interface.get(key) != expected:
                raise PackagingError(f"OpenAI plugin interface {key} mismatch")
    else:
        allowed = {
            "$schema", "name", "displayName", "version", "description", "author",
            "homepage", "repository", "license", "keywords",
        }
        unsupported = sorted(set(manifest) - allowed)
        if unsupported:
            raise PackagingError(
                "Claude plugin contains unsupported fields: " + ", ".join(unsupported)
            )
        if manifest.get("displayName") != config["display_name"]:
            raise PackagingError("Claude plugin displayName mismatch")
        schema = manifest.get("$schema")
        if not isinstance(schema, str) or "claude-code-plugin-manifest" not in schema:
            raise PackagingError("Claude plugin manifest schema is missing")


def _decode_packaged_plugin(data: bytes, platform: str) -> dict[str, object]:
    try:
        manifest = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackagingError(f"invalid packaged {platform} plugin manifest") from exc
    if not isinstance(manifest, dict):
        raise PackagingError(f"packaged {platform} plugin manifest must be a JSON object")
    return manifest


def _package_manifest_bytes(
    files: Mapping[str, bytes], config: Mapping[str, object], platform: str,
    core_sha256: str, skill_path: str,
) -> bytes:
    return json_bytes(
        {
            "schema_version": 1,
            "skill_id": config["skill_id"],
            "display_name": config["display_name"],
            "version": config["version"],
            "status": config["status"],
            "platform": platform,
            "released_at": f"{config['release_date']}T00:00:00Z",
            "root_layout": f"{config['skill_id']}/",
            "skill_path": skill_path,
            "package_format": (
                "native-openai-plugin" if platform == "openai" else
                "native-claude-plugin" if platform == "claude" else
                "universal-agent-skill"
            ),
            "license": {
                "name": config["license_name"],
                "file": "LICENSE.md",
                "sha256": sha256_bytes(files["LICENSE.md"]),
            },
            "core_sha256": core_sha256,
            "files": {relative: sha256_bytes(files[relative]) for relative in sorted(files)},
        }
    )


def _zip_time(config: Mapping[str, object]) -> tuple[int, int, int, int, int, int]:
    released = date.fromisoformat(str(config["release_date"]))
    return (released.year, released.month, released.day, 0, 0, 0)


def write_zip_bytes(skill_id: str, files: Mapping[str, bytes], zip_time: tuple[int, ...]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(
        stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True
    ) as archive:
        for relative in sorted(files):
            info = zipfile.ZipInfo(f"{skill_id}/{relative}", zip_time)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if "scripts" in PurePosixPath(relative).parts else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.extra = b""
            info.flag_bits |= 0x800
            archive.writestr(info, files[relative], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return stream.getvalue()


def _portable_core(canonical: Mapping[str, bytes]) -> dict[str, bytes]:
    return {path: data for path, data in canonical.items() if not path.startswith("agents/")}


def _skill_core_from_package(
    files: Mapping[str, bytes], config: Mapping[str, object], platform: str
) -> dict[str, bytes]:
    skill_id = str(config["skill_id"])
    if platform in {"openai", "claude"}:
        prefix = f"skills/{skill_id}/"
        return {
            path[len(prefix):]: data
            for path, data in files.items()
            if path.startswith(prefix)
            and path != f"{prefix}{PACKAGE_MANIFEST}"
            and not path[len(prefix):].startswith("agents/")
        }
    distribution = {str(path) for path in config["distribution_files"]}
    return {
        path: data for path, data in files.items()
        if path != PACKAGE_MANIFEST
        and path not in distribution
        and not path.startswith("agents/")
    }


def _load_distribution_files(
    project_root: Path, config: Mapping[str, object]
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for relative in config["distribution_files"]:
        path = Path(project_root) / str(relative)
        if path.is_symlink() or not path.is_file():
            raise PackagingError(f"distribution file must be a regular file: {path}")
        data = path.read_bytes()
        if not data.strip():
            raise PackagingError(f"distribution file must not be empty: {relative}")
        if len(data) > int(config["max_member_bytes"]):
            raise PackagingError(f"distribution file exceeds max_member_bytes: {relative}")
        _scan_for_secrets(str(relative), data)
        files[str(relative)] = data
    return files


def _make_package_files(
    canonical: Mapping[str, bytes], project_root: Path,
    config: Mapping[str, object], platform: str, core_sha256: str,
) -> dict[str, bytes]:
    skill_id = str(config["skill_id"])
    core = _portable_core(canonical)
    if platform == "universal":
        files = dict(core)
        skill_path = "."
    else:
        included = canonical if platform == "openai" else core
        prefix = f"skills/{skill_id}/"
        files = {f"{prefix}{path}": data for path, data in included.items()}
        manifest = _load_plugin_manifest(project_root, config, platform)
        adapter = ".codex-plugin/plugin.json" if platform == "openai" else ".claude-plugin/plugin.json"
        files[adapter] = json_bytes(manifest)
        for legal in config["legal_files"]:
            files[str(legal)] = canonical[str(legal)]
        if platform == "openai":
            brand = config["brand_assets"]
            assert isinstance(brand, dict)
            files["assets/icon.png"] = canonical[str(brand["icon"])]
            files["assets/logo.png"] = canonical[str(brand["logo"])]
        skill_path = f"skills/{skill_id}"
    for relative, data in _load_distribution_files(project_root, config).items():
        if relative in files:
            raise PackagingError(f"distribution file collides with package content: {relative}")
        files[relative] = data
    files[PACKAGE_MANIFEST] = _package_manifest_bytes(
        files, config, platform, core_sha256, skill_path
    )
    return dict(sorted(files.items()))


def inspect_archive(
    payload: bytes, config: Mapping[str, object], platform: str
) -> dict[str, object]:
    """Fully validate one ZIP without extracting it to the filesystem."""

    if platform not in PLATFORMS:
        raise PackagingError(f"unsupported platform: {platform}")
    if len(payload) > int(config["max_archive_bytes"]):
        raise PackagingError("archive exceeds max_archive_bytes")
    skill_id = str(config["skill_id"])
    files: dict[str, bytes] = {}
    normalized: dict[str, str] = {}
    total = 0
    expected_time = _zip_time(config)
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for info in archive.infolist():
                name = info.filename
                safe = _safe_relative(name, "archive member")
                if len(safe.parts) < 2 or safe.parts[0] != skill_id:
                    raise PackagingError(f"archive member is outside the single {skill_id}/ root: {name}")
                if info.is_dir():
                    raise PackagingError(f"archive contains an unexpected directory entry: {name}")
                if info.date_time != expected_time:
                    raise PackagingError(f"archive member timestamp mismatch: {name}")
                mode = (info.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(mode)
                if file_type == stat.S_IFLNK:
                    raise PackagingError(f"archive symlink is not allowed: {name}")
                if file_type != stat.S_IFREG:
                    raise PackagingError(f"archive special file is not allowed: {name}")
                relative = PurePosixPath(*safe.parts[1:]).as_posix()
                expected_permissions = (
                    0o755 if "scripts" in PurePosixPath(relative).parts else 0o644
                )
                if (mode & 0o777) != expected_permissions:
                    raise PackagingError(f"archive member permissions mismatch: {name}")
                if info.flag_bits & 0x1:
                    raise PackagingError(f"encrypted archive member is not allowed: {name}")
                if info.file_size > int(config["max_member_bytes"]):
                    raise PackagingError(f"archive member exceeds max_member_bytes: {name}")
                total += info.file_size
                if total > int(config["max_uncompressed_bytes"]):
                    raise PackagingError("archive exceeds max_uncompressed_bytes")
                collision_key = unicodedata.normalize("NFC", relative).casefold()
                if relative in files:
                    raise PackagingError(f"duplicate archive member: {relative}")
                if collision_key in normalized:
                    raise PackagingError(
                        f"case-colliding archive members: {normalized[collision_key]!r} and {relative!r}"
                    )
                normalized[collision_key] = relative
                files[relative] = archive.read(info)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise PackagingError(f"invalid ZIP archive: {exc}") from exc

    raw_manifest = files.get(PACKAGE_MANIFEST)
    if raw_manifest is None:
        raise PackagingError(f"archive is missing {PACKAGE_MANIFEST}")
    try:
        manifest = json.loads(raw_manifest)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackagingError(f"invalid embedded {PACKAGE_MANIFEST}") from exc
    if not isinstance(manifest, dict):
        raise PackagingError(f"{PACKAGE_MANIFEST} must be a JSON object")
    for key, expected in (
        ("skill_id", config["skill_id"]), ("version", config["version"]), ("platform", platform)
    ):
        if manifest.get(key) != expected:
            raise PackagingError(f"embedded manifest {key} mismatch")
    declared = manifest.get("files")
    actual = {path: data for path, data in files.items() if path != PACKAGE_MANIFEST}
    if not isinstance(declared, dict) or set(declared) != set(actual):
        raise PackagingError("embedded manifest file inventory mismatch")
    for relative, data in actual.items():
        if declared.get(relative) != sha256_bytes(data):
            raise PackagingError(f"embedded manifest SHA-256 mismatch: {relative}")

    skill_prefix = f"skills/{skill_id}"
    if platform == "openai":
        required = {
            ".codex-plugin/plugin.json", f"{skill_prefix}/SKILL.md",
            f"{skill_prefix}/agents/openai.yaml", "assets/icon.png", "assets/logo.png",
        }
        if not required.issubset(files):
            raise PackagingError("OpenAI native plugin layout is incomplete")
        plugin = _decode_packaged_plugin(files[".codex-plugin/plugin.json"], "openai")
        _validate_plugin_manifest(plugin, config, "openai")
    elif platform == "claude":
        required = {".claude-plugin/plugin.json", f"{skill_prefix}/SKILL.md"}
        if not required.issubset(files):
            raise PackagingError("Claude native plugin layout is incomplete")
        if any(path.startswith(f"{skill_prefix}/agents/") for path in files):
            raise PackagingError("Claude plugin must not contain OpenAI agents metadata")
        plugin = _decode_packaged_plugin(files[".claude-plugin/plugin.json"], "claude")
        _validate_plugin_manifest(plugin, config, "claude")
    else:
        if "SKILL.md" not in files:
            raise PackagingError("Universal Agent Skill is missing SKILL.md")
        if any(path.startswith("agents/") for path in files):
            raise PackagingError("Universal Agent Skill must not contain OpenAI agents metadata")
        if any(path.startswith((".codex-plugin/", ".claude-plugin/", "skills/")) for path in files):
            raise PackagingError("Universal Agent Skill contains a native-plugin adapter")

    core = _skill_core_from_package(files, config, platform)
    core_digest = tree_sha256(core)
    if manifest.get("core_sha256") != core_digest:
        raise PackagingError("embedded manifest core_sha256 mismatch")
    return {"files": files, "manifest": manifest, "core": core}


def render_release(project_root: Path = ROOT) -> dict[str, bytes]:
    project_root = Path(project_root)
    config = load_config(project_root)
    canonical = collect_canonical_files(project_root, config)
    core = _portable_core(canonical)
    core_digest = tree_sha256(core)
    canonical_digest = tree_sha256(canonical)
    outputs: dict[str, bytes] = {}
    artifact_entries: list[dict[str, object]] = []
    inspected: dict[str, dict[str, object]] = {}
    artifact_names = config["artifact_names"]
    assert isinstance(artifact_names, dict)

    for platform in PLATFORMS:
        package_files = _make_package_files(
            canonical, project_root, config, platform, core_digest
        )
        archive = write_zip_bytes(str(config["skill_id"]), package_files, _zip_time(config))
        inspected[platform] = inspect_archive(archive, config, platform)
        relative = f"{platform}/{artifact_names[platform]}"
        outputs[relative] = archive
        artifact_entries.append(
            {
                "platform": platform,
                "format": inspected[platform]["manifest"]["package_format"],
                "path": relative,
                "root_layout": f"{config['skill_id']}/",
                "sha256": sha256_bytes(archive),
                "size_bytes": len(archive),
                "file_count": len(package_files),
            }
        )

    if any(result["core"] != core for result in inspected.values()):
        raise PackagingError("OpenAI/Claude/Universal canonical core divergence")
    if any(tree_sha256(result["core"]) != core_digest for result in inspected.values()):
        raise PackagingError("OpenAI/Claude/Universal core hash divergence")

    parity_name = f"PARITY-v{config['version']}.json"
    outputs[parity_name] = json_bytes(
        {
            "schema_version": 1,
            "skill_id": config["skill_id"],
            "version": config["version"],
            "status": "PASS",
            "core_sha256": core_digest,
            "core_file_count": len(core),
            "canonical_only": sorted(path for path in canonical if path.startswith("agents/")),
            "adapters": {
                "openai": ".codex-plugin/plugin.json",
                "claude": ".claude-plugin/plugin.json",
                "universal": None,
            },
            "ignored_generated_files": [PACKAGE_MANIFEST],
            "distribution_files": list(config["distribution_files"]),
        }
    )
    manifest_name = f"release-manifest-v{config['version']}.json"
    release_manifest: dict[str, object] = {
        "schema_version": 1,
        "skill_id": config["skill_id"],
        "display_name": config["display_name"],
        "version": config["version"],
        "status": config["status"],
        "release_date": config["release_date"],
        "repository_status": config["repository_status"],
        "canonical_source": config["canonical_source"],
        "canonical_sha256": canonical_digest,
        "canonical_file_count": len(canonical),
        "license": config["license_name"],
        "artifacts": artifact_entries,
        "parity": {"status": "PASS", "path": parity_name, "core_sha256": core_digest},
    }
    if config.get("repository") is not None:
        release_manifest["repository"] = config["repository"]
    outputs[manifest_name] = json_bytes(release_manifest)
    checksums = "".join(
        f"{sha256_bytes(outputs[relative])}  {relative}\n" for relative in sorted(outputs)
    ).encode("utf-8")
    outputs[f"SHA256SUMS-v{config['version']}.txt"] = checksums
    return dict(sorted(outputs.items()))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_release(project_root: Path = ROOT, *, check: bool = False) -> dict[str, bytes]:
    """Render a release and atomically write it, or compare all managed dist files."""

    project_root = Path(project_root)
    outputs = render_release(project_root)
    dist = project_root / "dist"
    if check:
        mismatches: list[str] = []
        for relative, expected in outputs.items():
            path = dist.joinpath(*PurePosixPath(relative).parts)
            if not path.is_file():
                mismatches.append(f"missing {relative}")
            elif path.read_bytes() != expected:
                mismatches.append(f"content mismatch {relative}")
        existing = {
            path.relative_to(dist).as_posix()
            for path in dist.rglob("*") if path.is_file()
        } if dist.is_dir() else set()
        unexpected = sorted(existing - set(outputs))
        if unexpected:
            mismatches.append("unexpected " + ", ".join(unexpected))
        if mismatches:
            raise PackagingError("release check failed: " + "; ".join(mismatches))
        return outputs
    for relative, data in outputs.items():
        _atomic_write(dist.joinpath(*PurePosixPath(relative).parts), data)
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build deterministic native OpenAI/Claude plugins and a Universal Agent Skill."
    )
    parser.add_argument(
        "--check", action="store_true",
        help="compare dist byte-for-byte with a fresh in-memory render without writing",
    )
    args = parser.parse_args(argv)
    try:
        outputs = build_release(ROOT, check=args.check)
    except (OSError, PackagingError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    verb = "Verified" if args.check else "Built"
    for relative in outputs:
        print(f"{verb}: dist/{relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
