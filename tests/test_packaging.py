"""Regression tests for deterministic, safe cross-platform packaging."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BUILD = load_module(
    "document_evidence_build_skill_packages",
    REPOSITORY / "build/build_skill_packages.py",
)


class PackagingTestCase(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="document-evidence-package-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "project"
        (self.project / "build").mkdir(parents=True)
        (self.project / "platform/openai").mkdir(parents=True)
        (self.project / "platform/claude").mkdir(parents=True)
        shutil.copy2(REPOSITORY / "build/config.json", self.project / "build/config.json")
        shutil.copy2(
            REPOSITORY / "platform/openai/plugin.json",
            self.project / "platform/openai/plugin.json",
        )
        shutil.copy2(
            REPOSITORY / "platform/claude/plugin.json",
            self.project / "platform/claude/plugin.json",
        )
        self.config = json.loads(
            (self.project / "build/config.json").read_text(encoding="utf-8")
        )
        for name in self.config["distribution_files"]:
            destination = self.project / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                f"# {name}\n\nValidated distribution fixture for packaging tests.\n",
                encoding="utf-8",
            )

        self.skill = self.project / str(self.config["canonical_source"])
        (self.skill / "agents").mkdir(parents=True)
        (self.skill / "assets/brand").mkdir(parents=True)
        (self.skill / "references").mkdir()
        (self.skill / "scripts").mkdir()
        (self.skill / "SKILL.md").write_text(
            "---\n"
            f"name: {self.config['skill_id']}\n"
            "description: Extract, verify, reconcile, and package document evidence with traceable provenance and controlled human review.\n"
            "---\n\n"
            "# Document intelligence, evidence, and reconciliation\n\n"
            "Preserve source evidence, disclose uncertainty, and route material exceptions to human review.\n",
            encoding="utf-8",
        )
        for name in self.config["legal_files"]:
            (self.skill / name).write_text(
                f"# {name}\n\nBilingual commercial source-available legal fixture.\n",
                encoding="utf-8",
            )
        (self.skill / "agents/openai.yaml").write_text(
            "interface:\n"
            "  display_name: \"Thien Skill — Document Intelligence, Evidence & Reconciliation\"\n"
            "  short_description: \"Extract and reconcile traceable document evidence\"\n"
            f"  default_prompt: \"Use ${self.config['skill_id']} to build an evidence register.\"\n"
            "  icon_small: \"./assets/brand/icon-small.png\"\n"
            "  icon_large: \"./assets/brand/logo-large.png\"\n"
            "  brand_color: \"#001838\"\n"
            "policy:\n"
            "  allow_implicit_invocation: true\n",
            encoding="utf-8",
        )
        (self.skill / "assets/brand/icon-small.png").write_bytes(
            b"\x89PNG\r\nfixture-small"
        )
        (self.skill / "assets/brand/logo-large.png").write_bytes(
            b"\x89PNG\r\nfixture-large"
        )
        (self.skill / "references/evidence-contract.md").write_text(
            "# Evidence contract\n\nEvery material value retains a source locator.\n",
            encoding="utf-8",
        )
        (self.skill / "scripts/validate_records.py").write_text(
            "#!/usr/bin/env python3\nprint('fixture')\n",
            encoding="utf-8",
        )

    @property
    def skill_id(self) -> str:
        return str(self.config["skill_id"])

    def artifact_relative(self, platform: str) -> str:
        return f"{platform}/{self.config['artifact_names'][platform]}"

    @staticmethod
    def sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def zip_info(
        self,
        name: str,
        *,
        mode: int = stat.S_IFREG | 0o644,
        timestamp: tuple[int, int, int, int, int, int] | None = None,
    ) -> zipfile.ZipInfo:
        if timestamp is None:
            year, month, day = (int(part) for part in self.config["release_date"].split("-"))
            timestamp = (year, month, day, 0, 0, 0)
        info = zipfile.ZipInfo(name, timestamp)
        info.create_system = 3
        info.external_attr = mode << 16
        return info

    def test_config_identity_native_names_and_private_repository(self) -> None:
        config = BUILD.load_config(self.project)
        self.assertEqual(config["skill_id"], "thien-skill-document-evidence")
        self.assertEqual(
            config["display_name"],
            "Thien Skill — Document Intelligence, Evidence & Reconciliation",
        )
        self.assertEqual(config["version"], "1.1.0")
        self.assertEqual(config["status"], "Testing")
        self.assertEqual(config["release_date"], "2026-08-27")
        self.assertEqual(config["repository_status"], "private")
        self.assertNotIn("repository", config)
        self.assertEqual(
            config["distribution_files"],
            [
                "INSTALLATION.md",
                "ACCEPTANCE-REPORT-v1.1.0.md",
                "LEGAL-REVIEW-v1.1.0.md",
            ],
        )
        self.assertEqual(
            config["preserved_dist_versions"],
            ["1.0.0", "1.1.0-rc.1", "1.1.0-rc.2"],
        )
        self.assertEqual(
            config["artifact_names"],
            {
                "openai": "Thien-Skill-Document-Evidence-OpenAI-v1.1.0.zip",
                "claude": "Thien-Skill-Document-Evidence-Claude-v1.1.0.zip",
                "universal": "Thien-Skill-Document-Evidence-Universal-v1.1.0.zip",
            },
        )
        for platform in ("openai", "claude"):
            manifest = json.loads(
                (self.project / f"platform/{platform}/plugin.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertNotIn("repository", manifest)

    def test_config_rejects_non_https_repository(self) -> None:
        config_path = self.project / "build/config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["repository"] = "git@example.invalid:private/repository.git"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(BUILD.PackagingError, "absolute HTTPS URL"):
            BUILD.load_config(self.project)

    def test_render_is_deterministic_and_side_effect_free(self) -> None:
        first = BUILD.render_release(self.project)
        second = BUILD.render_release(self.project)
        self.assertEqual(first, second)
        self.assertFalse((self.project / "dist").exists())

    def test_build_preserves_and_validates_configured_historical_release(self) -> None:
        BUILD.build_release(self.project)
        historical = BUILD._release_paths_for_version(self.config, "1.0.0")
        for relative in historical.values():
            source = REPOSITORY / "dist" / relative
            destination = self.project / "dist" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        before = {
            relative: (self.project / "dist" / relative).read_bytes()
            for relative in historical.values()
        }

        BUILD.build_release(self.project)
        BUILD.build_release(self.project, check=True)
        self.assertEqual(
            before,
            {
                relative: (self.project / "dist" / relative).read_bytes()
                for relative in historical.values()
            },
        )

        parity = self.project / "dist" / historical["parity"]
        parity.write_bytes(parity.read_bytes() + b"\n")
        with self.assertRaisesRegex(BUILD.PackagingError, "preserved release checksum mismatch"):
            BUILD.build_release(self.project, check=True)

    def test_release_manifests_checksums_and_exact_check_mode(self) -> None:
        outputs = BUILD.build_release(self.project)
        version = self.config["version"]
        manifest_name = f"release-manifest-v{version}.json"
        parity_name = f"PARITY-v{version}.json"
        checksum_name = f"SHA256SUMS-v{version}.txt"
        expected = {
            *(self.artifact_relative(platform) for platform in BUILD.PLATFORMS),
            manifest_name,
            parity_name,
            checksum_name,
        }
        self.assertEqual(set(outputs), expected)
        self.assertEqual(BUILD.build_release(self.project, check=True), outputs)

        manifest = json.loads(outputs[manifest_name])
        parity = json.loads(outputs[parity_name])
        self.assertEqual(manifest["status"], "Testing")
        self.assertEqual(manifest["repository_status"], "private")
        self.assertNotIn("repository", manifest)
        self.assertEqual(manifest["parity"]["status"], "PASS")
        self.assertEqual(parity["status"], "PASS")
        self.assertEqual(parity["distribution_files"], self.config["distribution_files"])
        self.assertEqual(manifest["parity"]["core_sha256"], parity["core_sha256"])
        checksum_text = outputs[checksum_name].decode("utf-8")
        for relative, data in outputs.items():
            if relative != checksum_name:
                self.assertIn(f"{self.sha256(data)}  {relative}\n", checksum_text)

        unexpected = self.project / "dist/unmanaged.txt"
        unexpected.write_text("not generated\n", encoding="utf-8")
        with self.assertRaisesRegex(BUILD.PackagingError, "unexpected unmanaged.txt"):
            BUILD.build_release(self.project, check=True)

    def test_exact_check_ignores_regular_finder_metadata_only(self) -> None:
        outputs = BUILD.build_release(self.project)
        metadata_paths = [self.project / "dist/.DS_Store", self.project / "dist/openai/.DS_Store"]
        for path in metadata_paths:
            path.write_bytes(b"synthetic Finder metadata")
        self.assertEqual(BUILD.build_release(self.project, check=True), outputs)
        for path in metadata_paths:
            self.assertEqual(path.read_bytes(), b"synthetic Finder metadata")
        unmanaged = self.project / "dist/openai/.unmanaged"
        unmanaged.write_text("not a release artifact\n", encoding="utf-8")
        with self.assertRaisesRegex(BUILD.PackagingError, "unexpected openai/.unmanaged"):
            BUILD.build_release(self.project, check=True)

    def test_exact_check_does_not_ignore_finder_named_symlink(self) -> None:
        BUILD.build_release(self.project)
        target = self.project / "finder-target"
        target.write_bytes(b"not an ordinary Finder metadata file")
        (self.project / "dist/.DS_Store").symlink_to(target)
        with self.assertRaisesRegex(BUILD.PackagingError, "unexpected .DS_Store"):
            BUILD.build_release(self.project, check=True)
        target.unlink()  # Also reject the now-dangling link in this private fixture.
        with self.assertRaisesRegex(BUILD.PackagingError, "unexpected .DS_Store"):
            BUILD.build_release(self.project, check=True)

    def test_archive_layout_permissions_manifests_legal_and_core_parity(self) -> None:
        outputs = BUILD.render_release(self.project)
        inspected: dict[str, dict[str, object]] = {}
        year, month, day = (int(part) for part in self.config["release_date"].split("-"))
        expected_time = (year, month, day, 0, 0, 0)
        expected_license = (self.skill / "LICENSE.md").read_bytes()
        for platform in BUILD.PLATFORMS:
            payload = outputs[self.artifact_relative(platform)]
            inspected[platform] = BUILD.inspect_archive(payload, self.config, platform)
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                self.assertIsNone(archive.testzip())
                infos = archive.infolist()
                self.assertEqual(
                    [info.filename for info in infos],
                    sorted(info.filename for info in infos),
                )
                for info in infos:
                    self.assertFalse(info.is_dir())
                    self.assertTrue(info.filename.startswith(f"{self.skill_id}/"))
                    self.assertEqual(info.date_time, expected_time)
                    relative = PurePosixPath(info.filename).relative_to(self.skill_id)
                    expected_mode = 0o755 if "scripts" in relative.parts else 0o644
                    self.assertEqual((info.external_attr >> 16) & 0o777, expected_mode)

        openai_files = inspected["openai"]["files"]
        claude_files = inspected["claude"]["files"]
        universal_files = inspected["universal"]["files"]
        for platform in BUILD.PLATFORMS:
            package_files = inspected[platform]["files"]
            for distribution in self.config["distribution_files"]:
                self.assertIn(distribution, package_files)
            self.assertEqual(package_files["LICENSE.md"], expected_license)
            embedded = inspected[platform]["manifest"]
            self.assertEqual(
                set(embedded["files"]),
                set(package_files) - {BUILD.PACKAGE_MANIFEST},
            )

        skill_prefix = f"skills/{self.skill_id}"
        self.assertIn(".codex-plugin/plugin.json", openai_files)
        self.assertIn(f"{skill_prefix}/agents/openai.yaml", openai_files)
        self.assertIn("assets/icon.png", openai_files)
        self.assertIn("assets/logo.png", openai_files)
        self.assertEqual(openai_files[f"{skill_prefix}/LICENSE.md"], expected_license)
        self.assertIn(".claude-plugin/plugin.json", claude_files)
        self.assertFalse(any(path.startswith(f"{skill_prefix}/agents/") for path in claude_files))
        self.assertEqual(claude_files[f"{skill_prefix}/LICENSE.md"], expected_license)
        self.assertIn("SKILL.md", universal_files)
        self.assertFalse(any(path.startswith("agents/") for path in universal_files))
        self.assertFalse(
            any(
                path.startswith((".codex-plugin/", ".claude-plugin/", "skills/"))
                for path in universal_files
            )
        )
        self.assertEqual(
            {BUILD.tree_sha256(inspected[p]["core"]) for p in BUILD.PLATFORMS},
            {inspected["openai"]["manifest"]["core_sha256"]},
        )

        openai_manifest = json.loads(openai_files[".codex-plugin/plugin.json"])
        claude_manifest = json.loads(claude_files[".claude-plugin/plugin.json"])
        self.assertEqual(openai_manifest["skills"], "./skills/")
        self.assertFalse({"mcpServers", "apps", "hooks", "repository"} & set(openai_manifest))
        self.assertNotIn("repository", claude_manifest)
        self.assertIn("claude-code-plugin-manifest", claude_manifest["$schema"])

    def test_builder_rejects_todo_secret_junk_symlink_and_case_collision(self) -> None:
        skill_text = (self.skill / "SKILL.md").read_text(encoding="utf-8")
        (self.skill / "SKILL.md").write_text(
            skill_text.replace("Extract, verify", "TODO: Extract, verify"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(BUILD.PackagingError, "TODO"):
            BUILD.render_release(self.project)
        (self.skill / "SKILL.md").write_text(skill_text, encoding="utf-8")

        secret = self.skill / "references/secret.txt"
        secret.write_text("AKIAABCDEFGHIJKLMNOP\n", encoding="utf-8")
        with self.assertRaisesRegex(BUILD.PackagingError, "AWS access key"):
            BUILD.render_release(self.project)
        secret.unlink()

        junk = self.skill / ".DS_Store"
        junk.write_bytes(b"junk")
        with self.assertRaisesRegex(BUILD.PackagingError, "junk"):
            BUILD.render_release(self.project)
        junk.unlink()

        collision = self.skill / "references/EVIDENCE-CONTRACT.md"
        original = self.skill / "references/evidence-contract.md"
        if collision != original and not collision.exists():
            collision.write_text("collision\n", encoding="utf-8")
            with self.assertRaisesRegex(BUILD.PackagingError, "collision"):
                BUILD.render_release(self.project)
            collision.unlink()

        link = self.skill / "references/license-link.md"
        try:
            link.symlink_to("../LICENSE.md")
        except (OSError, NotImplementedError):
            return
        with self.assertRaisesRegex(BUILD.PackagingError, "symlink"):
            BUILD.render_release(self.project)

    def test_plugin_manifest_identity_and_repository_are_build_gates(self) -> None:
        source = self.project / "platform/openai/plugin.json"
        original = source.read_text(encoding="utf-8")
        manifest = json.loads(original)
        manifest["name"] = "wrong-skill"
        source.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(BUILD.PackagingError, "name mismatch"):
            BUILD.render_release(self.project)

        manifest = json.loads(original)
        manifest["repository"] = "https://example.invalid/private-repository"
        source.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(BUILD.PackagingError, "repository mismatch"):
            BUILD.render_release(self.project)

    def test_archive_inspection_rejects_unsafe_members_metadata_and_size(self) -> None:
        cases: list[tuple[bytes, str, dict[str, object]]] = []

        slip = io.BytesIO()
        with zipfile.ZipFile(slip, "w") as archive:
            archive.writestr(
                self.zip_info(f"{self.skill_id}/../escape.txt"),
                b"escape",
            )
        cases.append((slip.getvalue(), "safe POSIX relative path", self.config))

        linked = io.BytesIO()
        with zipfile.ZipFile(linked, "w") as archive:
            archive.writestr(
                self.zip_info(f"{self.skill_id}/link", mode=stat.S_IFLNK | 0o777),
                b"target",
            )
        cases.append((linked.getvalue(), "symlink", self.config))

        special = io.BytesIO()
        with zipfile.ZipFile(special, "w") as archive:
            archive.writestr(
                self.zip_info(f"{self.skill_id}/pipe", mode=stat.S_IFIFO | 0o644),
                b"",
            )
        cases.append((special.getvalue(), "special file", self.config))

        collision = io.BytesIO()
        with zipfile.ZipFile(collision, "w") as archive:
            archive.writestr(self.zip_info(f"{self.skill_id}/File.txt"), b"one")
            archive.writestr(self.zip_info(f"{self.skill_id}/file.txt"), b"two")
        cases.append((collision.getvalue(), "case-colliding", self.config))

        bad_mode = io.BytesIO()
        with zipfile.ZipFile(bad_mode, "w") as archive:
            archive.writestr(
                self.zip_info(f"{self.skill_id}/private.txt", mode=stat.S_IFREG | 0o600),
                b"private",
            )
        cases.append((bad_mode.getvalue(), "permissions mismatch", self.config))

        bad_time = io.BytesIO()
        with zipfile.ZipFile(bad_time, "w") as archive:
            archive.writestr(
                self.zip_info(
                    f"{self.skill_id}/old.txt",
                    timestamp=(2020, 1, 1, 0, 0, 0),
                ),
                b"old",
            )
        cases.append((bad_time.getvalue(), "timestamp mismatch", self.config))

        oversized_config = dict(self.config)
        oversized_config["max_member_bytes"] = 2
        oversized = io.BytesIO()
        with zipfile.ZipFile(oversized, "w") as archive:
            archive.writestr(self.zip_info(f"{self.skill_id}/large.bin"), b"123")
        cases.append((oversized.getvalue(), "max_member_bytes", oversized_config))

        for payload, message, config in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(BUILD.PackagingError, message):
                    BUILD.inspect_archive(payload, config, "openai")

    def test_archive_tampering_breaks_embedded_hash_verification(self) -> None:
        payload = BUILD.render_release(self.project)[self.artifact_relative("universal")]
        source = zipfile.ZipFile(io.BytesIO(payload))
        rewritten = io.BytesIO()
        with source, zipfile.ZipFile(rewritten, "w") as target:
            for info in source.infolist():
                data = source.read(info)
                if info.filename.endswith("/SKILL.md"):
                    data += b"\ntampered\n"
                target.writestr(info, data)
        with self.assertRaisesRegex(BUILD.PackagingError, "SHA-256 mismatch"):
            BUILD.inspect_archive(rewritten.getvalue(), self.config, "universal")

    def test_openai_archive_passes_plugin_creator_validator_when_available(self) -> None:
        codex_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        validator = codex_root / "skills/.system/plugin-creator/scripts/validate_plugin.py"
        if not validator.is_file() or importlib.util.find_spec("yaml") is None:
            self.skipTest("plugin-creator validator or PyYAML is unavailable")

        payload = BUILD.render_release(self.project)[self.artifact_relative("openai")]
        extraction = Path(self.temporary.name) / "openai-plugin"
        extraction.mkdir()
        BUILD.inspect_archive(payload, self.config, "openai")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            archive.extractall(extraction)
        plugin_root = extraction / self.skill_id
        result = subprocess.run(
            [sys.executable, str(validator), str(plugin_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
