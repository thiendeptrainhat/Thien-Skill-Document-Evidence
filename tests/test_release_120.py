"""Frozen byte and identity oracle for the final 1.2.0 release."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
SKILL_ID = "thien-skill-document-evidence"
FROZEN_120_DISPLAY_NAME = "Thien Skill — Document Intelligence, Evidence & Reconciliation"
FROZEN_120_DISTRIBUTION = {
    "INSTALLATION.md",
    "ACCEPTANCE-REPORT-v1.2.0.md",
    "LEGAL-REVIEW-v1.2.0.md",
}
FROZEN_120_ARCHIVES = {
    "openai": "1.2.0/Thien-Skill-Document-Evidence-OpenAI-v1.2.0.zip",
    "claude": "1.2.0/Thien-Skill-Document-Evidence-Claude-v1.2.0.zip",
    "universal": "1.2.0/Thien-Skill-Document-Evidence-Universal-v1.2.0.zip",
}
FROZEN_120_SHA256 = {
    "1.2.0/PARITY.json":
        "3e9062661cdddad43be26efc528844fc89a1e3063f5b6f78b7c7432240c4608c",
    "1.2.0/Thien-Skill-Document-Evidence-Claude-v1.2.0.zip":
        "a1ce64711304abf4238428ab9ff1afbda6c0f1a06ddff53b034274d5e540cfe6",
    "1.2.0/Thien-Skill-Document-Evidence-OpenAI-v1.2.0.zip":
        "7ec6d8bca0963d62dab14e10fd89a973023fe7e19678272f79839e0418bcb3ad",
    "1.2.0/release-manifest.json":
        "aa67863065a808522986b12598f2104c354646b2d96a9b27233825126604bc81",
    "1.2.0/Thien-Skill-Document-Evidence-Universal-v1.2.0.zip":
        "d544effcbc375ac22ccaeee6559f950790536582a9cf8cee4ce2f708c4552088",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class FrozenRelease120Tests(unittest.TestCase):
    def test_checksum_inventory_is_literal_and_complete(self) -> None:
        inventory: dict[str, str] = {}
        for line in (DIST / "1.2.0/SHA256SUMS").read_text(
            encoding="utf-8"
        ).splitlines():
            digest, relative = line.split("  ", 1)
            inventory[relative] = digest
        self.assertEqual(
            inventory,
            {
                PurePosixPath(path).name: digest
                for path, digest in FROZEN_120_SHA256.items()
            },
        )
        for relative, expected in FROZEN_120_SHA256.items():
            self.assertEqual(sha256((DIST / relative).read_bytes()), expected)

    def test_release_manifest_and_parity_are_frozen(self) -> None:
        release = read_json(DIST / "1.2.0/release-manifest.json")
        parity = read_json(DIST / "1.2.0/PARITY.json")
        self.assertEqual(release["version"], "1.2.0")
        self.assertEqual(release["release_date"], "2026-09-01")
        self.assertEqual(release["display_name"], FROZEN_120_DISPLAY_NAME)
        self.assertEqual(
            release["canonical_sha256"],
            "8242c3227527c357660395f7de5280d1a08b98fb283d4aeffec0a7155fef1523",
        )
        self.assertEqual(parity["version"], "1.2.0")
        self.assertEqual(parity["status"], "PASS")
        self.assertEqual(parity["core_file_count"], 87)
        self.assertEqual(
            parity["core_sha256"],
            "6b187c90092723c611a186bb14fd3fd5ab47d3bb5aec78dcc78ea56619d499d5",
        )
        self.assertEqual(set(parity["distribution_files"]), FROZEN_120_DISTRIBUTION)

    def test_archives_have_frozen_layout_timestamp_and_identity(self) -> None:
        for platform, relative in FROZEN_120_ARCHIVES.items():
            with self.subTest(platform=platform), zipfile.ZipFile(DIST / relative) as archive:
                self.assertIsNone(archive.testzip())
                members = archive.infolist()
                self.assertTrue(members)
                self.assertTrue(
                    all(member.date_time == (2026, 9, 1, 0, 0, 0) for member in members)
                )
                prefix = f"{SKILL_ID}/"
                self.assertTrue(all(member.filename.startswith(prefix) for member in members))
                skill_prefix = prefix if platform == "universal" else f"{prefix}skills/{SKILL_ID}/"
                self.assertEqual(
                    archive.read(f"{skill_prefix}VERSION").decode("ascii").strip(),
                    "1.2.0",
                )
                package_manifest = json.loads(
                    archive.read(f"{prefix}PACKAGE-MANIFEST.json").decode("utf-8")
                )
                self.assertEqual(package_manifest["version"], "1.2.0")

    def test_old_display_name_is_preserved_only_inside_frozen_release(self) -> None:
        for platform, relative in FROZEN_120_ARCHIVES.items():
            with self.subTest(platform=platform), zipfile.ZipFile(DIST / relative) as archive:
                prefix = f"{SKILL_ID}/"
                skill_prefix = prefix if platform == "universal" else f"{prefix}skills/{SKILL_ID}/"
                skill_text = archive.read(f"{skill_prefix}SKILL.md").decode("utf-8")
                self.assertIn(FROZEN_120_DISPLAY_NAME, skill_text)
                self.assertNotIn("Thiện's Skill — Document Intelligence & Reconciliation", skill_text)


if __name__ == "__main__":
    unittest.main()
