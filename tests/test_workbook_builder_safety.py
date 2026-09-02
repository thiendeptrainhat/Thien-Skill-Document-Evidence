from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "thien-skill-document-evidence" / "scripts" / "build_workbook.mjs"
PACKAGE_FIXTURE = ROOT / "tests" / "fixtures" / "workbook-package.json"
REPORT_FIXTURE = ROOT / "tests" / "fixtures" / "workbook-package.validation.json"


FAKE_ARTIFACT_TOOL = r'''"use strict";
const fs = require("node:fs");

function makeFormat() {
  return new Proxy({}, {
    get(_target, property) {
      if (property === "autofitRows") return () => {};
      return undefined;
    },
    set() { return true; },
  });
}

function makeRange() {
  const format = makeFormat();
  return new Proxy({}, {
    get(_target, property) {
      if (property === "format") return format;
      if (property === "merge") return () => {};
      return undefined;
    },
    set() { return true; },
  });
}

function makeSheet(name) {
  return {
    name,
    freezePanes: { freezeRows() {} },
    tables: { add() { return {}; } },
    getRange() { return makeRange(); },
    showGridLines: true,
  };
}

exports.Workbook = {
  create() {
    const items = [];
    return {
      worksheets: {
        items,
        add(name) {
          const sheet = makeSheet(name);
          items.push(sheet);
          return sheet;
        },
      },
      async render() {
        const raceTarget = process.env.PREVIEW_RACE_TARGET;
        if (raceTarget && !fs.existsSync(raceTarget)) {
          fs.writeFileSync(raceTarget, "preview-race-sentinel", { flag: "wx" });
        }
        const bytes = Uint8Array.from([137, 80, 78, 71]);
        return { async arrayBuffer() { return bytes.buffer; } };
      },
    };
  },
};

exports.SpreadsheetFile = {
  async exportXlsx() {
    return {
      async save(target) {
        fs.writeFileSync(target, "fake-xlsx", { flag: "wx" });
        const raceTarget = process.env.WORKBOOK_RACE_TARGET;
        if (raceTarget && !fs.existsSync(raceTarget)) {
          fs.writeFileSync(raceTarget, "workbook-race-sentinel", { flag: "wx" });
        }
      },
    };
  },
};
'''


class WorkbookBuilderSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("Node.js is unavailable")

    def _install_fake_artifact_tool(self, temporary: Path) -> Path:
        module = temporary / "node_modules" / "@oai" / "artifact-tool"
        module.mkdir(parents=True)
        (module / "package.json").write_text(
            json.dumps(
                {
                    "name": "@oai/artifact-tool",
                    "version": "0.0.0-test",
                    "main": "index.js",
                    "type": "commonjs",
                }
            ),
            encoding="utf-8",
        )
        (module / "index.js").write_text(FAKE_ARTIFACT_TOOL, encoding="utf-8")
        return temporary / "node_modules"

    def _run(
        self,
        arguments: list[str],
        *,
        node_modules: Path | None = None,
        extra_environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        if node_modules is not None:
            prior = environment.get("NODE_PATH")
            environment["NODE_PATH"] = str(node_modules) + (os.pathsep + prior if prior else "")
        if extra_environment:
            environment.update(extra_environment)
        return subprocess.run(
            [self.node, str(SCRIPT), *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_output_requires_xlsx_extension_before_dependency_loading(self) -> None:
        result = self._run(["--template", "--output", "result.xls"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("--output must use the .xlsx extension", result.stderr)
        self.assertNotIn("artifact-tool is unavailable", result.stderr)

    def test_overwrite_rejects_package_and_report_hardlink_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temporary:
            temporary = Path(raw_temporary)
            package = temporary / "package.json"
            report = temporary / "report.json"
            shutil.copyfile(PACKAGE_FIXTURE, package)
            shutil.copyfile(REPORT_FIXTURE, report)

            for protected, expected_label in (
                (package, "--package"),
                (report, "--schema-validation-report"),
            ):
                output = temporary / f"{expected_label.removeprefix('--')}.xlsx"
                try:
                    os.link(protected, output)
                except OSError as error:
                    self.skipTest(f"hard links are unavailable: {error}")
                before = protected.read_bytes()
                result = self._run(
                    [
                        "--package",
                        str(package),
                        "--schema-validation-report",
                        str(report),
                        "--output",
                        str(output),
                        "--overwrite",
                    ]
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(f"output must not alias {expected_label}", result.stderr)
                self.assertEqual(protected.read_bytes(), before)
                self.assertEqual(output.read_bytes(), before)

    def test_overwrite_rejects_exact_package_and_report_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temporary:
            temporary = Path(raw_temporary)
            package = temporary / "package.xlsx"
            package.write_bytes(PACKAGE_FIXTURE.read_bytes())
            report = temporary / "report.xlsx"
            report_data = json.loads(REPORT_FIXTURE.read_text(encoding="utf-8"))
            report_data["run_manifest"]["input_sha256"] = hashlib.sha256(
                package.read_bytes()
            ).hexdigest()
            report.write_text(json.dumps(report_data), encoding="utf-8")

            for output, expected_label in (
                (package, "--package"),
                (report, "--schema-validation-report"),
            ):
                result = self._run(
                    [
                        "--package",
                        str(package),
                        "--schema-validation-report",
                        str(report),
                        "--output",
                        str(output),
                        "--overwrite",
                    ]
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(f"output must not be the same path as {expected_label}", result.stderr)

    def test_no_overwrite_refuses_target_created_after_initial_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temporary:
            temporary = Path(raw_temporary)
            node_modules = self._install_fake_artifact_tool(temporary)
            output = temporary / "result.xlsx"
            result = self._run(
                ["--template", "--output", str(output)],
                node_modules=node_modules,
                extra_environment={"WORKBOOK_RACE_TARGET": str(output)},
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("output exists; use --overwrite", result.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), "workbook-race-sentinel")

    def test_no_overwrite_publishes_and_overwrite_replaces_regular_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temporary:
            temporary = Path(raw_temporary)
            node_modules = self._install_fake_artifact_tool(temporary)
            output = temporary / "result.xlsx"
            first = self._run(
                ["--template", "--output", str(output)],
                node_modules=node_modules,
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), "fake-xlsx")

            output.write_text("old-workbook", encoding="utf-8")
            replacement = self._run(
                ["--template", "--output", str(output), "--overwrite"],
                node_modules=node_modules,
            )
            self.assertEqual(replacement.returncode, 0, replacement.stdout + replacement.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), "fake-xlsx")

    def test_preview_no_overwrite_preserves_late_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temporary:
            temporary = Path(raw_temporary)
            node_modules = self._install_fake_artifact_tool(temporary)
            preview_directory = temporary / "previews"
            preview_directory.mkdir()
            preview_target = preview_directory / "00_README.png"
            output = temporary / "result.xlsx"
            result = self._run(
                [
                    "--template",
                    "--output",
                    str(output),
                    "--preview-dir",
                    str(preview_directory),
                ],
                node_modules=node_modules,
                extra_environment={"PREVIEW_RACE_TARGET": str(preview_target)},
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("preview exists; use --overwrite", result.stderr)
            self.assertEqual(
                preview_target.read_text(encoding="utf-8"),
                "preview-race-sentinel",
            )
            self.assertFalse(output.exists())

    def test_release_provenance_uses_existing_run_manifest_map(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temporary:
            temporary = Path(raw_temporary)
            node_modules = self._install_fake_artifact_tool(temporary)
            package_data = json.loads(PACKAGE_FIXTURE.read_text(encoding="utf-8"))
            package_data["run_manifest"]["tool_versions"][
                "thien-skill-document-evidence"
            ] = "1.2.1"
            package = temporary / "release-aware-package.json"
            package.write_text(
                json.dumps(package_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            report = temporary / "release-aware-package.validation.json"
            validation = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "thien-skill-document-evidence/scripts/validate_records.py"),
                    package.name,
                    "--root",
                    str(temporary),
                    "--schema-root",
                    str(ROOT / "thien-skill-document-evidence/schemas"),
                    "--schema",
                    "common/extraction-package.schema.json",
                    "--output",
                    report.name,
                ],
                cwd=temporary,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

            output = temporary / "result.xlsx"
            result = self._run(
                [
                    "--package",
                    str(package),
                    "--schema-validation-report",
                    str(report),
                    "--output",
                    str(output),
                ],
                node_modules=node_modules,
                extra_environment={"DOCUMENT_EVIDENCE_PYTHON": sys.executable},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), "fake-xlsx")


if __name__ == "__main__":
    unittest.main()
