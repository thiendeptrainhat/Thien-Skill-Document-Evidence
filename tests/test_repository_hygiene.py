"""Regression tests for repository junk, duplicate, and size-budget controls."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build/check_repository_hygiene.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("phase2_repository_hygiene", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load repository hygiene gate from {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = load_gate()


def policy() -> dict[str, object]:
    return {
        "max_repository_bytes": 4096,
        "max_dist_bytes": 2048,
        "max_regular_file_bytes": 1024,
        "max_dist_file_bytes": 1024,
        "max_brand_asset_bytes": 1024,
        "source_soft_line_limit": 4,
        "source_hard_line_limit": 8,
        "max_preserved_dist_versions": 2,
        "forbidden_names": [
            ".DS_Store",
            ".env",
            ".git",
            "__pycache__",
            "coverage.xml",
            "node_modules",
        ],
        "forbidden_prefixes": [".coverage.", ".env."],
        "forbidden_suffixes": [".log", ".pyc", ".tmp"],
        "allowed_generated_binary_paths": [],
        "allowed_duplicate_groups": [],
    }


class RepositoryHygieneTests(unittest.TestCase):
    def test_current_repository_passes_with_explicit_soft_limit_warnings(self) -> None:
        report = GATE.check_repository(ROOT)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["duplicate_groups"], 7)
        self.assertEqual(report["preserved_dist_versions"], 3)
        self.assertTrue(
            any("render_canonical_artifacts.py" in item for item in report["warnings"])
        )

    def test_junk_symlink_empty_directory_and_generated_office_output_fail(self) -> None:
        with tempfile.TemporaryDirectory(prefix="repository-hygiene-") as raw:
            root = Path(raw)
            (root / "empty").mkdir()
            (root / ".DS_Store").write_bytes(b"finder")
            (root / "run.log").write_text("log\n", encoding="utf-8")
            (root / "output.xlsx").write_bytes(b"generated")
            target = root / "target.txt"
            target.write_text("target\n", encoding="utf-8")
            try:
                (root / "link.txt").symlink_to(target)
            except (OSError, NotImplementedError):
                pass
            report = GATE.evaluate_repository(root, policy(), [])
            self.assertEqual(report["status"], "FAIL")
            joined = "\n".join(report["errors"])
            self.assertIn("metadata/cache", joined)
            self.assertIn("temporary/generated suffix", joined)
            self.assertIn("generated Office artifact", joined)
            self.assertIn("empty directory", joined)
            if (root / "link.txt").is_symlink():
                self.assertIn("symlink is not allowed", joined)

    def test_size_line_duplicate_and_retention_budgets_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="repository-hygiene-") as raw:
            root = Path(raw)
            (root / "large.bin").write_bytes(b"x" * 1025)
            (root / "large.py").write_text("line\n" * 9, encoding="utf-8")
            (root / "copy-a.txt").write_text("duplicate\n", encoding="utf-8")
            (root / "copy-b.txt").write_text("duplicate\n", encoding="utf-8")
            report = GATE.evaluate_repository(root, policy(), ["1.0.0", "1.1.0", "1.2.0"])
            self.assertEqual(report["status"], "FAIL")
            joined = "\n".join(report["errors"])
            self.assertIn("file exceeds 1024-byte budget", joined)
            self.assertIn("source exceeds hard line limit 8", joined)
            self.assertIn("unexpected byte-identical duplicate group", joined)
            self.assertIn("retention cap 2", joined)

    def test_ignored_secrets_coverage_and_nested_git_metadata_fail(self) -> None:
        with tempfile.TemporaryDirectory(prefix="repository-hygiene-") as raw:
            root = Path(raw)
            (root / ".env.production").write_text("TOKEN=secret\n", encoding="utf-8")
            (root / ".coverage.worker").write_text("coverage\n", encoding="utf-8")
            (root / "coverage.xml").write_text("<coverage/>\n", encoding="utf-8")
            generated_cache = root / "cache.tmp"
            generated_cache.mkdir()
            (generated_cache / "data.json").write_text("{}\n", encoding="utf-8")
            nested_git = root / "canonical" / ".git"
            nested_git.mkdir(parents=True)
            (nested_git / "config").write_text("metadata\n", encoding="utf-8")

            report = GATE.evaluate_repository(root, policy(), [])

            self.assertEqual(report["status"], "FAIL")
            joined = "\n".join(report["errors"])
            self.assertIn(".env.production", joined)
            self.assertIn(".coverage.worker", joined)
            self.assertIn("coverage.xml", joined)
            self.assertIn("cache.tmp/data.json", joined)
            self.assertIn("canonical/.git/config", joined)

    def test_walk_errors_fail_closed(self) -> None:
        error = PermissionError("simulated unreadable directory")
        error.filename = "blocked"

        def failing_walk(root, *, topdown, followlinks, onerror):
            del root, topdown, followlinks
            onerror(error)
            return iter(())

        with mock.patch.object(GATE.os, "walk", side_effect=failing_walk):
            with self.assertRaisesRegex(GATE.HygieneError, "cannot scan repository path"):
                GATE.evaluate_repository(Path("."), policy(), [])

    def test_root_git_file_for_linked_worktree_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory(prefix="repository-hygiene-") as raw:
            root = Path(raw)
            (root / ".git").write_text(
                "gitdir: /safe/external/worktree/metadata\n",
                encoding="utf-8",
            )
            (root / "source.txt").write_text("source\n", encoding="utf-8")

            report = GATE.evaluate_repository(root, policy(), [])

            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["files"], 1)

    def test_policy_loader_rejects_unsafe_duplicate_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="repository-hygiene-") as raw:
            root = Path(raw)
            (root / "build").mkdir()
            bad = policy()
            bad["allowed_duplicate_groups"] = [["safe.txt", "../escape.txt"]]
            (root / "build/config.json").write_text(
                json.dumps(
                    {"repository_hygiene": bad, "preserved_dist_versions": []},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(GATE.HygieneError, "safe POSIX relative path"):
                GATE.load_policy(root)


if __name__ == "__main__":
    unittest.main()
