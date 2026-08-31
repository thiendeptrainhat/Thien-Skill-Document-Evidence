#!/usr/bin/env node
/**
 * Build a formula-safe XLSX view from a canonical extraction package.
 *
 * Runtime adapter: requires @oai/artifact-tool to be available in the host.
 * The script never installs dependencies, calls the network, follows source
 * links, or modifies its JSON input. Output is atomic and no-overwrite by
 * default.
 */

import fs from "node:fs/promises";
import { constants as fsConstants } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const VERSION = "1.0.0";
const BRAND = {
  navy: "#001838",
  blue: "#123A67",
  gold: "#D5B45B",
  pale: "#E9EEF5",
  ink: "#132238",
  white: "#FFFFFF",
};

const SHEETS = [
  {
    name: "01_DOCUMENT_INDEX",
    key: "document_inventory",
    table: "DocumentIndexTable",
    columns: [
      "document_id", "content_id", "evidence_ids", "package_id",
      "original_filename", "source_reference", "extension", "declared_mime_type",
      "detected_mime_type", "size_bytes", "sha256", "copy_role", "read_status",
      "extension_mime_status", "password_protected", "encrypted", "javascript_status",
      "macro_status", "embedded_files_status", "external_links_status", "observed_pages",
      "declared_pages", "page_completeness_status", "processing_eligibility",
      "document_type", "profile_id", "profile_version", "classification_status",
      "classification_confidence", "selected_route", "processing_status",
      "data_classification", "security_flags", "review_status", "assumptions", "limitations",
    ],
  },
  {
    name: "02_DOCUMENT_FIELDS",
    key: "extracted_fields",
    table: "DocumentFieldsTable",
    columns: [
      "field_id", "document_id", "evidence_id", "profile_id", "profile_version",
      "field_name", "field_label", "field_group", "raw_value", "normalized_value",
      "display_value", "data_type", "unit", "currency", "field_status", "status_flags",
      "source_page", "source_region", "bounding_box", "source_snippet",
      "extraction_method", "adapter_name", "adapter_version", "run_id",
      "normalization_rules", "confidence", "overall_confidence", "validation_result",
      "validation_details", "human_review_required", "human_review_status",
      "reviewed_value", "review_decision", "formula_injection_flag", "notes",
    ],
  },
  {
    name: "03_LINE_ITEMS",
    key: "line_items",
    table: "LineItemsTable",
    columns: [
      "line_item_id", "document_id", "evidence_id", "profile_id", "profile_version",
      "table_id", "logical_sequence", "source_pages", "source_rows", "raw_cells",
      "field_ids", "validation_status", "row_confidence", "reconciliation_key",
      "human_review_status", "notes",
    ],
  },
  {
    name: "08_CONTRACT_CLAUSES",
    key: "contract_clauses",
    table: "ContractClausesTable",
    columns: [
      "clause_id", "document_id", "contract_id", "clause_number", "clause_title",
      "clause_type", "clause_text_raw", "clause_text_normalized", "page_start",
      "page_end", "source_reference", "party_affected", "cross_references", "amended_by",
      "supersedes", "extraction_confidence",
      "human_review_status", "legal_review_required",
    ],
  },
  {
    name: "09_CONTRACT_OBLIGATIONS",
    key: "contract_obligations",
    table: "ContractObligationsTable",
    columns: [
      "obligation_id", "contract_id", "clause_id", "obligated_party",
      "beneficiary_party", "action_required", "object_or_deliverable", "trigger",
      "condition", "start_date", "due_date", "recurrence", "evidence_required",
      "consequence_of_nonperformance", "status", "source_reference",
      "extraction_confidence", "human_review_status",
    ],
  },
  {
    name: "11_DOCUMENT_LINKS",
    key: "document_links",
    table: "DocumentLinksTable",
    columns: [
      "link_id", "left_document_id", "right_document_id", "match_status", "match_keys",
      "method", "confidence", "source_references", "human_review_status",
    ],
  },
  {
    name: "12_RECONCILIATION",
    key: "reconciliation_results",
    table: "ReconciliationTable",
    columns: [
      "reconciliation_id", "run_id", "config_id", "config_version", "mode", "grain",
      "participants", "rule_results", "status", "quality_status", "reason",
      "supporting_evidence_ids", "human_review_required", "human_review_status",
      "reviewer", "decision", "reviewed_at", "limitations",
    ],
  },
  {
    name: "13_DISCREPANCIES",
    key: "discrepancies",
    table: "DiscrepanciesTable",
    columns: [
      "discrepancy_id", "document_package_id", "document_ids", "field_or_rule",
      "values", "difference", "tolerance", "discrepancy_type", "severity",
      "possible_explanations", "supporting_evidence_ids", "validation_status", "owner",
      "human_review_status", "handoff_target",
    ],
  },
  {
    name: "14_EVIDENCE_REGISTER",
    key: "evidence_register",
    table: "EvidenceRegisterTable",
    columns: [
      "evidence_id", "case_id", "engagement_id", "document_id", "evidence_type",
      "title", "source_type", "source_reference", "provided_by", "received_by", "custodian",
      "received_at", "captured_at", "acquisition_method", "authorization_reference",
      "original_location_reference", "working_copy_location_reference", "checksum_algorithm",
      "checksum_digest", "checksum_computed_at", "checksum_object_role", "copy_role",
      "reliability_classification", "reliability_assessment_status", "reliability_basis",
      "reliability_limitations", "custody_status", "data_classification",
      "access_restrictions", "redaction_status", "related_objects", "review_status",
      "claim_limits", "notes",
    ],
  },
  {
    name: "15_CHAIN_OF_CUSTODY",
    key: "chain_of_custody",
    table: "ChainOfCustodyTable",
    columns: [
      "custody_event_id", "evidence_id", "event_type", "from_person_or_location",
      "to_person_or_location", "event_datetime", "timezone", "purpose",
      "action_performed", "tool_used", "tool_version", "checksum_before",
      "checksum_after", "working_copy_created", "authorization_reference",
      "performed_by", "witness_or_reviewer", "notes",
    ],
  },
  {
    name: "17_HUMAN_REVIEW",
    key: "human_review_queue",
    table: "HumanReviewTable",
    columns: [
      "review_item_id", "document_id", "evidence_id", "field_id", "issue_type",
      "raw_value", "candidate_values", "source_reference", "reason_for_review",
      "risk_level", "reviewer", "reviewed_value", "review_decision", "review_note",
      "reviewed_at", "second_review_required", "status", "approval_status",
    ],
  },
];

function usage() {
  return [
    "Usage:",
    "  node build_workbook.mjs --package PACKAGE.json --schema-validation-report REPORT.json --output RESULT.xlsx [options]",
    "  node build_workbook.mjs --template --output TEMPLATE.xlsx [options]",
    "",
    "Options:",
    "  --template              Build an empty, documented workbook template.",
    "  --schema-validation-report REPORT.json",
    "                          Required PASS report from validate_records.py for package export.",
    "  --overwrite             Replace the exact output file if it exists.",
    "  --dry-run               Validate and build in memory without writing files.",
    "  --preview-dir DIR       Render every created sheet to PNG for visual QA.",
    "  --help                   Show this help.",
    "",
    "The script does not install dependencies or call the network.",
    "Package export re-runs the bundled validator; set DOCUMENT_EVIDENCE_PYTHON only when python3 is not on PATH.",
  ].join("\n");
}

function parseArgs(argv) {
  const args = { template: false, overwrite: false, dryRun: false };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--help") args.help = true;
    else if (value === "--template") args.template = true;
    else if (value === "--overwrite") args.overwrite = true;
    else if (value === "--dry-run") args.dryRun = true;
    else if (["--package", "--output", "--preview-dir", "--schema-validation-report"].includes(value)) {
      const next = argv[index + 1];
      if (!next || next.startsWith("--")) throw new Error(`${value} requires a value`);
      const key = value.slice(2)
        .replace("preview-dir", "previewDir")
        .replace("schema-validation-report", "schemaValidationReport");
      args[key] = next;
      index += 1;
    } else throw new Error(`unknown argument: ${value}`);
  }
  if (!args.help) {
    if (!args.output) throw new Error("--output is required");
    if (args.template === Boolean(args.package)) {
      throw new Error("choose exactly one of --template or --package PACKAGE.json");
    }
    if (args.package && !args.schemaValidationReport) {
      throw new Error("--schema-validation-report is required with --package");
    }
    if (args.template && args.schemaValidationReport) {
      throw new Error("--schema-validation-report is not used with --template");
    }
    if (args.dryRun && args.previewDir) {
      throw new Error("--dry-run cannot be combined with --preview-dir");
    }
  }
  return args;
}

const PACKAGE_REQUIRED_KEYS = [
  "schema_version", "package_id", "package_version", "skill_id", "skill_version",
  "run_id", "engagement_id", "case_id", "route", "status", "run_manifest",
  "document_inventory", "evidence_register", "runtime_adapter_results",
  "extracted_fields", "line_items", "contract_clauses", "contract_obligations",
  "document_links", "reconciliation_results", "discrepancies", "human_review_queue",
  "chain_of_custody", "redaction_log", "field_dictionary", "outputs",
  "critical_field_failures", "security_flags", "assumptions", "limitations",
  "qa_status", "human_approval_status",
];
const PACKAGE_KEYS = [...PACKAGE_REQUIRED_KEYS];

const PACKAGE_ARRAY_KEYS = [
  "document_inventory", "evidence_register", "runtime_adapter_results",
  "extracted_fields", "line_items", "contract_clauses", "contract_obligations",
  "document_links", "reconciliation_results", "discrepancies", "human_review_queue",
  "chain_of_custody", "redaction_log", "field_dictionary", "outputs",
  "critical_field_failures", "security_flags", "assumptions", "limitations",
];

const PACKAGE_OBJECT_ARRAY_KEYS = PACKAGE_ARRAY_KEYS.filter(
  (key) => !["security_flags", "assumptions", "limitations"].includes(key),
);

const READINESS_STATUSES = new Set([
  "DRAFT", "READY_FOR_QA", "READY_FOR_HUMAN_VALIDATION", "READY_FOR_RECONCILIATION",
  "READY_FOR_LIMITED_USE", "READY_FOR_HUMAN_REVIEW", "BLOCKED", "NOT_EXECUTED",
]);

function assertPackage(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("package must be a JSON object");
  }
  const missing = PACKAGE_REQUIRED_KEYS.filter((key) => value[key] === undefined);
  if (missing.length > 0) throw new Error(`package is missing required keys: ${missing.join(", ")}`);
  const unexpected = Object.keys(value).filter((key) => !PACKAGE_KEYS.includes(key));
  if (unexpected.length > 0) throw new Error(`package has unexpected keys: ${unexpected.join(", ")}`);
  if (value.schema_version !== "1.0.0") throw new Error("package.schema_version must be 1.0.0");
  if (value.skill_id !== "thien-skill-document-evidence") {
    throw new Error("package.skill_id must be thien-skill-document-evidence");
  }
  if (value.skill_version !== VERSION) throw new Error(`package.skill_version must be ${VERSION}`);
  if (!READINESS_STATUSES.has(value.status)) throw new Error("package.status is not an allowed readiness state");
  if (!value.run_manifest || typeof value.run_manifest !== "object" || Array.isArray(value.run_manifest)) {
    throw new Error("package.run_manifest must be an object");
  }
  for (const key of PACKAGE_ARRAY_KEYS) {
    if (!Array.isArray(value[key])) throw new Error(`package.${key} must be an array`);
  }
  for (const key of PACKAGE_OBJECT_ARRAY_KEYS) {
    for (const record of value[key]) {
      if (!record || typeof record !== "object" || Array.isArray(record)) {
        throw new Error(`every package.${key} record must be an object`);
      }
    }
  }
}

function sha256(data) {
  return createHash("sha256").update(data).digest("hex");
}

function fileIdentity(stat) {
  return { device: stat.dev, inode: stat.ino };
}

function sameFileIdentity(left, right) {
  return left.device === right.device && left.inode === right.inode;
}

async function readRegularFile(target, label) {
  const resolvedPath = path.resolve(target);
  const before = await fs.lstat(resolvedPath, { bigint: true });
  if (!before.isFile() || before.isSymbolicLink()) {
    throw new Error(`${label} must be a regular non-symlink file`);
  }

  const noFollow = fsConstants.O_NOFOLLOW ?? 0;
  let handle;
  try {
    handle = await fs.open(resolvedPath, fsConstants.O_RDONLY | noFollow);
  } catch (error) {
    if (error && ["ELOOP", "EMLINK"].includes(error.code)) {
      throw new Error(`${label} must be a regular non-symlink file`);
    }
    throw error;
  }
  try {
    const opened = await handle.stat({ bigint: true });
    if (!opened.isFile() || !sameFileIdentity(fileIdentity(before), fileIdentity(opened))) {
      throw new Error(`${label} changed while it was being opened`);
    }
    return {
      bytes: await handle.readFile(),
      identity: fileIdentity(opened),
      resolvedPath,
    };
  } finally {
    await handle.close();
  }
}

async function assertSchemaValidationReport(packageBytes, reportBytes) {
  const report = JSON.parse(reportBytes.toString("utf8"));
  const schemaPath = fileURLToPath(new URL(
    "../schemas/common/extraction-package.schema.json",
    import.meta.url,
  ));
  const schemaBytes = (
    await readRegularFile(schemaPath, "canonical extraction-package schema")
  ).bytes;
  const failures = [];
  if (report.status !== "PASS") failures.push("status is not PASS");
  if (!Array.isArray(report.errors) || report.errors.length !== 0) {
    failures.push("errors is absent or non-empty");
  }
  if (report.report_type !== "SCHEMA_AND_PACKAGE_VALIDATION") {
    failures.push("report_type is not SCHEMA_AND_PACKAGE_VALIDATION");
  }
  if (report.run_manifest?.input_sha256 !== sha256(packageBytes)) {
    failures.push("input SHA-256 does not match package bytes");
  }
  if (report.run_manifest?.schema_sha256 !== sha256(schemaBytes)) {
    failures.push("schema SHA-256 does not match bundled extraction-package schema");
  }
  if (report.summary?.invalid_count !== 0 || report.summary?.package_error_count !== 0) {
    failures.push("validator summary contains invalid/package errors");
  }
  if (report.summary?.record_count !== 1 || report.summary?.valid_count !== 1) {
    failures.push("validator summary does not cover exactly one valid package");
  }
  if (failures.length > 0) {
    throw new Error(`schema validation report rejected: ${failures.join("; ")}`);
  }
  return report;
}

function pythonCandidates() {
  if (process.env.DOCUMENT_EVIDENCE_PYTHON) {
    return [{ command: process.env.DOCUMENT_EVIDENCE_PYTHON, prefix: [] }];
  }
  if (process.platform === "win32") {
    return [
      { command: "py", prefix: ["-3"] },
      { command: "python3", prefix: [] },
      { command: "python", prefix: [] },
    ];
  }
  return [
    { command: "python3", prefix: [] },
    { command: "python", prefix: [] },
  ];
}

function runValidatorProcess(argumentsList) {
  const unavailable = [];
  for (const candidate of pythonCandidates()) {
    const result = spawnSync(
      candidate.command,
      [...candidate.prefix, ...argumentsList],
      {
        encoding: "utf8",
        maxBuffer: 8 * 1024 * 1024,
        windowsHide: true,
      },
    );
    if (result.error?.code === "ENOENT") {
      unavailable.push(candidate.command);
      continue;
    }
    if (result.error) {
      throw new Error(`bundled schema validator could not start: ${result.error.message}`);
    }
    return result;
  }
  throw new Error(
    "bundled schema validation requires Python 3; no interpreter was found "
    + `(tried: ${unavailable.join(", ")}). Set DOCUMENT_EVIDENCE_PYTHON to a trusted Python 3 executable`,
  );
}

async function assertTrustedSchemaValidation(packageInput) {
  const validatorPath = fileURLToPath(new URL("./validate_records.py", import.meta.url));
  const schemaRoot = fileURLToPath(new URL("../schemas", import.meta.url));
  const schemaPath = path.join(schemaRoot, "common", "extraction-package.schema.json");
  await readRegularFile(validatorPath, "bundled schema validator");
  const schemaBytes = (
    await readRegularFile(schemaPath, "canonical extraction-package schema")
  ).bytes;
  const realPackagePath = await fs.realpath(packageInput.resolvedPath);
  const packageRoot = path.dirname(realPackagePath);
  const result = runValidatorProcess([
    "-B",
    validatorPath,
    realPackagePath,
    "--root",
    packageRoot,
    "--schema",
    "common/extraction-package.schema.json",
    "--schema-root",
    schemaRoot,
    "--records-key",
    "__document_evidence_root_package__",
    "--dry-run",
  ]);

  let report;
  try {
    report = JSON.parse(result.stdout);
  } catch (error) {
    const detail = result.stderr.trim() || error.message;
    throw new Error(`bundled schema validator returned invalid evidence: ${detail}`);
  }

  const failures = [];
  if (result.signal !== null) failures.push(`terminated by signal ${result.signal}`);
  if (result.status !== 0) failures.push(`exited with status ${result.status}`);
  if (report.status !== "PASS") failures.push("status is not PASS");
  if (!Array.isArray(report.errors) || report.errors.length !== 0) {
    failures.push("errors is absent or non-empty");
  }
  if (report.run_manifest?.tool !== "thien-record-validator") {
    failures.push("unexpected validator tool identity");
  }
  if (report.run_manifest?.validator_engine !== "INTERNAL_DRAFT_2020_SUBSET") {
    failures.push("unexpected validator engine identity");
  }
  if (report.run_manifest?.input_sha256 !== sha256(packageInput.bytes)) {
    failures.push("validated input SHA-256 does not match package bytes");
  }
  if (report.run_manifest?.schema_sha256 !== sha256(schemaBytes)) {
    failures.push("validated schema SHA-256 does not match bundled schema");
  }
  if (report.summary?.invalid_count !== 0 || report.summary?.package_error_count !== 0) {
    failures.push("validator summary contains invalid/package errors");
  }
  if (report.summary?.record_count !== 1 || report.summary?.valid_count !== 1) {
    failures.push("validator summary does not cover exactly one valid package");
  }
  if (failures.length > 0) {
    const firstErrors = Array.isArray(report.errors)
      ? report.errors.slice(0, 3).map((item) => (
        `${item.path || item.record_path || "$"}: ${item.message || item.keyword || "validation error"}`
      ))
      : [];
    const detail = [...failures, ...firstErrors].join("; ");
    throw new Error(`bundled schema validation rejected package: ${detail}`);
  }
  return report;
}

function assertReportMatchesTrustedValidation(suppliedReport, trustedReport) {
  const supplied = JSON.stringify(canonicalize(suppliedReport));
  const trusted = JSON.stringify(canonicalize(trustedReport));
  if (supplied !== trusted) {
    throw new Error(
      "schema validation report rejected: supplied report does not exactly match "
      + "fresh evidence from the bundled validator",
    );
  }
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map((item) => canonicalize(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}

function safeText(value) {
  if (value === null || value === undefined) return null;
  let text;
  if (typeof value === "string") text = value;
  else if (typeof value === "number" || typeof value === "boolean") return value;
  else text = JSON.stringify(canonicalize(value));
  return /^[=+\-@]/.test(text) ? `'${text}` : text;
}

function confidenceValue(confidence) {
  if (!confidence || typeof confidence !== "object") return confidence ?? null;
  return confidence.score ?? confidence.band ?? "UNKNOWN";
}

function checksumDigest(checksum) {
  if (!checksum || typeof checksum !== "object") return checksum ?? null;
  return checksum.digest ?? null;
}

const NUMERIC_DATA_TYPES = new Set([
  "INTEGER", "DECIMAL", "PERCENTAGE", "CURRENCY_AMOUNT", "QUANTITY",
]);

function isValidatedField(record) {
  return ["PASS", "PASS_WITH_WARNING"].includes(record.validation?.status)
    && !["AMBIGUOUS", "CONFLICTING", "HUMAN_REVIEW_REQUIRED"].includes(record.field_status);
}

function preciseExcelNumber(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !/^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value)) {
    return null;
  }
  const significantDigits = value.replace(/^[+-]?0*/, "").replace(".", "").length;
  if (significantDigits > 15) return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function excelDateSerial(value, includeTime) {
  if (typeof value !== "string") return null;
  const pattern = includeTime
    ? /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/
    : /^(\d{4})-(\d{2})-(\d{2})$/;
  const match = value.match(pattern);
  if (!match) return null;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const calendarProbe = new Date(Date.UTC(year, month - 1, day));
  if (calendarProbe.getUTCFullYear() !== year
      || calendarProbe.getUTCMonth() !== month - 1
      || calendarProbe.getUTCDate() !== day) return null;
  if (includeTime && (Number(hourText) > 23 || Number(minuteText) > 59 || Number(secondText) > 59)) {
    return null;
  }
  const instant = includeTime ? Date.parse(value) : Date.parse(`${value}T00:00:00Z`);
  if (!Number.isFinite(instant)) return null;
  return (instant / 86400000) + 25569;
}

function workbookFieldValue(record, valueName) {
  const value = record.values?.[valueName];
  if (valueName === "raw_value" || !isValidatedField(record)) return value;
  if (NUMERIC_DATA_TYPES.has(record.data_type)) {
    return preciseExcelNumber(value) ?? value;
  }
  if (record.data_type === "DATE") {
    return excelDateSerial(value, false) ?? value;
  }
  return value;
}

function compactJson(value) {
  return JSON.stringify(canonicalize(value));
}

function compactList(value) {
  if (!Array.isArray(value)) return value;
  return value.map((item) => (
    item && typeof item === "object" ? compactJson(item) : String(item)
  )).join(" | ");
}

function confidenceSummary(confidence) {
  if (!confidence || typeof confidence !== "object") return confidence ?? null;
  return Object.entries(confidence).map(([name, value]) => (
    `${name}:${confidenceValue(value)}`
  )).join(" | ");
}

function projectRecord(key, record) {
  if (key === "document_inventory") {
    return {
      ...record,
      evidence_ids: compactList(record.evidence_ids),
      original_filename: record.file?.original_filename,
      source_reference: record.file?.source_reference,
      extension: record.file?.extension,
      declared_mime_type: record.file?.declared_mime_type,
      detected_mime_type: record.file?.detected_mime_type,
      size_bytes: record.file?.size_bytes,
      sha256: checksumDigest(record.file?.checksum),
      read_status: record.integrity?.read_status,
      extension_mime_status: record.integrity?.extension_mime_status,
      password_protected: record.integrity?.password_protected,
      encrypted: record.integrity?.encrypted,
      javascript_status: record.integrity?.active_content?.javascript,
      macro_status: record.integrity?.active_content?.macro,
      embedded_files_status: record.integrity?.active_content?.embedded_files,
      external_links_status: record.integrity?.active_content?.external_links,
      observed_pages: record.integrity?.page_count?.observed,
      declared_pages: record.integrity?.page_count?.declared,
      page_completeness_status: record.integrity?.page_completeness_status,
      processing_eligibility: record.integrity?.processing_eligibility,
      document_type: record.classification?.document_type,
      profile_id: record.classification?.profile_id,
      profile_version: record.classification?.profile_version,
      classification_status: record.classification?.status,
      classification_confidence: confidenceValue(record.classification?.confidence),
      selected_route: record.processing?.selected_route,
      processing_status: record.processing?.status,
      data_classification: compactList(record.data_classification),
      security_flags: compactList(record.security_flags),
      assumptions: compactList(record.assumptions),
      limitations: compactList(record.limitations),
    };
  }
  if (key === "extracted_fields") {
    return {
      ...record,
      raw_value: workbookFieldValue(record, "raw_value"),
      normalized_value: workbookFieldValue(record, "normalized_value"),
      display_value: workbookFieldValue(record, "display_value"),
      source_page: record.provenance?.source_page,
      source_region: record.provenance?.source_region,
      bounding_box: record.provenance?.bounding_box,
      source_snippet: record.provenance?.source_snippet,
      extraction_method: record.extraction?.method,
      adapter_name: record.extraction?.adapter_name,
      adapter_version: record.extraction?.adapter_version,
      run_id: record.extraction?.run_id,
      normalization_rules: compactList(record.extraction?.normalization_rules?.map((rule) => (
        `${rule.rule_id}@${rule.rule_version}:${rule.result}${rule.locale ? `:${rule.locale}` : ""}`
      ))),
      confidence: confidenceSummary(record.confidence),
      overall_confidence: confidenceValue(record.confidence?.overall),
      validation_result: record.validation?.status,
      validation_details: compactList(record.validation?.results?.map((result) => (
        `${result.rule_id}:${result.status}:${result.message}`
      ))),
      human_review_required: record.human_review?.required,
      human_review_status: record.human_review?.status,
      reviewed_value: record.human_review?.reviewed_value,
      review_decision: record.human_review?.decision,
      status_flags: compactList(record.status_flags),
      notes: compactList(record.notes),
    };
  }
  if (key === "line_items") {
    return {
      ...record,
      source_pages: compactList(record.source_pages),
      source_rows: compactList(record.source_rows),
      raw_cells: compactJson(record.raw_cells),
      field_ids: compactList(record.field_ids),
      row_confidence: confidenceValue(record.row_confidence),
      reconciliation_key: compactJson(record.reconciliation_key),
      notes: compactList(record.notes),
    };
  }
  if (key === "contract_clauses") {
    return {
      ...record,
      party_affected: compactList(record.party_affected),
      cross_references: compactList(record.cross_references),
      amended_by: compactList(record.amended_by),
      supersedes: compactList(record.supersedes),
      extraction_confidence: confidenceValue(record.extraction_confidence),
    };
  }
  if (key === "contract_obligations") {
    return {
      ...record,
      evidence_required: compactList(record.evidence_required),
      extraction_confidence: confidenceValue(record.extraction_confidence),
    };
  }
  if (key === "document_links") {
    return {
      ...record,
      match_keys: compactList(record.match_keys),
      confidence: confidenceValue(record.confidence),
      source_references: compactList(record.source_references),
    };
  }
  if (key === "evidence_register") {
    return {
      ...record,
      source_type: record.source?.source_type,
      source_reference: record.source?.source_reference,
      provided_by: record.source?.provided_by,
      received_by: record.source?.received_by,
      custodian: record.source?.custodian,
      received_at: record.acquisition?.received_at,
      captured_at: record.acquisition?.captured_at,
      acquisition_method: record.acquisition?.method,
      authorization_reference: record.acquisition?.authorization_reference,
      original_location_reference: record.locations?.original_location_reference,
      working_copy_location_reference: record.locations?.working_copy_location_reference,
      checksum_algorithm: record.checksum?.algorithm,
      checksum_digest: record.checksum?.digest,
      checksum_computed_at: record.checksum?.computed_at,
      checksum_object_role: record.checksum?.object_role,
      reliability_classification: record.reliability?.classification,
      reliability_assessment_status: record.reliability?.assessment_status,
      reliability_basis: compactList(record.reliability?.basis),
      reliability_limitations: compactList(record.reliability?.limitations),
      data_classification: compactList(record.data_classification),
      access_restrictions: compactList(record.access_restrictions),
      related_objects: compactList(record.related_objects),
      claim_limits: compactJson(record.claim_limits),
      notes: compactList(record.notes),
    };
  }
  if (key === "chain_of_custody") {
    return {
      ...record,
      checksum_before: checksumDigest(record.checksum_before),
      checksum_after: checksumDigest(record.checksum_after),
      notes: compactList(record.notes),
    };
  }
  if (key === "reconciliation_results") {
    return {
      ...record,
      participants: compactList(record.participants?.map((participant) => (
        `${participant.role_id}:${compactList(participant.record_ids)}`
      ))),
      rule_results: compactList(record.rule_results?.map((result) => (
        `${result.rule_id}/${result.component_id}:${result.status}:${result.reason}`
      ))),
      supporting_evidence_ids: compactList(record.supporting_evidence_ids),
      human_review_required: record.human_review?.required,
      human_review_status: record.human_review?.status,
      reviewer: record.human_review?.reviewer,
      decision: record.human_review?.decision,
      reviewed_at: record.human_review?.reviewed_at,
      limitations: compactList(record.limitations),
    };
  }
  if (key === "discrepancies") {
    return {
      ...record,
      document_ids: compactList(record.document_ids),
      values: compactJson(record.values),
      tolerance: compactJson(record.tolerance),
      possible_explanations: compactList(record.possible_explanations),
      supporting_evidence_ids: compactList(record.supporting_evidence_ids),
    };
  }
  if (key === "human_review_queue") {
    return {
      ...record,
      candidate_values: compactList(record.candidate_values),
    };
  }
  return record;
}

function coerceCell(column, value) {
  if (value === null || value === undefined) return null;
  const identifier = /(?:^|_)(?:id|number|account|reference|code|sha256|checksum)$/.test(column)
    || ["document_id", "evidence_id", "field_id", "line_item_id"].includes(column);
  if (identifier) return safeText(String(value));
  if (typeof value === "number" || typeof value === "boolean") return value;
  return safeText(value);
}

function matrixFromRecords(records, columns, key) {
  return records.map((record) => {
    if (!record || typeof record !== "object" || Array.isArray(record)) {
      throw new Error("every exported record must be an object");
    }
    const projected = projectRecord(key, record);
    return columns.map((column) => coerceCell(column, projected[column]));
  });
}

function columnName(index) {
  let number = index + 1;
  let name = "";
  while (number > 0) {
    number -= 1;
    name = String.fromCharCode(65 + (number % 26)) + name;
    number = Math.floor(number / 26);
  }
  return name;
}

function styleHeader(range) {
  range.format = {
    fill: BRAND.navy,
    font: { bold: true, color: BRAND.white },
    wrapText: true,
    verticalAlignment: "center",
    borders: { preset: "outside", style: "thin", color: BRAND.blue },
  };
  range.format.rowHeight = 30;
}

function formatDataSheet(sheet, columns, rowCount) {
  const last = columnName(columns.length - 1);
  styleHeader(sheet.getRange(`A1:${last}1`));
  sheet.freezePanes.freezeRows(1);
  sheet.showGridLines = false;
  columns.forEach((column, index) => {
    const letter = columnName(index);
    let width = Math.min(34, Math.max(13, column.length + 3));
    if (/description|snippet|text|reason|note|value|candidate/.test(column)) width = 28;
    if ([
      "confidence", "normalization_rules", "validation_details", "participants",
      "rule_results", "limitations", "notes", "source_references",
    ].includes(column)) width = 34;
    sheet.getRange(`${letter}:${letter}`).format.columnWidth = width;
    if (/(?:^|_)(?:id|number|account|reference|code|sha256|checksum)$/.test(column)) {
      sheet.getRange(`${letter}2:${letter}${Math.max(2, rowCount + 1)}`).format.numberFormat = "@";
    }
    if (/(?:date|_at|datetime)$/.test(column)) {
      sheet.getRange(`${letter}2:${letter}${Math.max(2, rowCount + 1)}`).format.numberFormat = "yyyy-mm-dd";
    }
  });
  if (rowCount > 0) {
    const dataRange = sheet.getRange(`A2:${last}${rowCount + 1}`);
    dataRange.format.wrapText = true;
    dataRange.format.verticalAlignment = "top";
    dataRange.format.autofitRows();
  }
}

function applySemanticCellFormats(sheet, definition, records) {
  if (definition.key !== "extracted_fields" || records.length === 0) return;
  const textIdentifiers = new Set([
    "IDENTIFIER", "BANK_ACCOUNT", "TAX_IDENTIFIER", "PHONE", "REFERENCE",
  ]);
  const valueColumns = ["raw_value", "normalized_value", "display_value"];
  records.forEach((record, index) => {
    const excelRow = index + 2;
    if (textIdentifiers.has(record.data_type)) {
      for (const column of valueColumns) {
        const columnIndex = definition.columns.indexOf(column);
        if (columnIndex < 0) continue;
        const letter = columnName(columnIndex);
        sheet.getRange(`${letter}${excelRow}`).format.numberFormat = "@";
      }
      return;
    }
    const rawIndex = definition.columns.indexOf("raw_value");
    if (rawIndex >= 0 && typeof record.values?.raw_value === "string") {
      sheet.getRange(`${columnName(rawIndex)}${excelRow}`).format.numberFormat = "@";
    }
    if (!isValidatedField(record)) return;
    for (const column of ["normalized_value", "display_value"]) {
      const columnIndex = definition.columns.indexOf(column);
      if (columnIndex < 0) continue;
      const letter = columnName(columnIndex);
      if (NUMERIC_DATA_TYPES.has(record.data_type)) {
        sheet.getRange(`${letter}${excelRow}`).format.numberFormat = record.data_type === "INTEGER"
          ? "0"
          : "#,##0.###############";
      } else if (record.data_type === "DATE") {
        sheet.getRange(`${letter}${excelRow}`).format.numberFormat = "yyyy-mm-dd";
      }
    }
  });
}

function addReadme(workbook, packageData, templateMode) {
  const sheet = workbook.worksheets.add("00_README");
  sheet.showGridLines = false;
  sheet.getRange("A1:H2").merge();
  sheet.getRange("A1").values = [["Document Intelligence, Evidence & Reconciliation"]];
  sheet.getRange("A1:H2").format = {
    fill: BRAND.navy,
    font: { bold: true, color: BRAND.white, size: 18 },
    verticalAlignment: "center",
  };
  const rows = [
    ["Workbook role", templateMode ? "Reusable structure; contains no source records" : "Structured view of a canonical extraction package"],
    ["Skill version", safeText(packageData.skill_version || VERSION)],
    ["Run ID", safeText(packageData.run_id || "NOT_PROVIDED")],
    ["Readiness", safeText(packageData.status || (templateMode ? "TEMPLATE_ONLY" : "READY_FOR_HUMAN_REVIEW"))],
    ["Source of truth", "Original documents and canonical JSON package; this workbook is a review/export view"],
    ["Safety", "No macros or source formulas. Values beginning = + - @ are written as literal text."],
    ["Review", "Critical, ambiguous, conflicting, inferred, derived or low-confidence values require the recorded human review."],
    ["Limits", safeText((packageData.limitations || []).join(" | ") || "See canonical package and acceptance report")],
  ];
  sheet.getRange(`A4:B${rows.length + 3}`).values = rows;
  sheet.getRange("A4:A11").format = { fill: BRAND.pale, font: { bold: true, color: BRAND.ink } };
  sheet.getRange("A4:B11").format.borders = { preset: "inside", style: "thin", color: "#D3DAE5" };
  sheet.getRange("A4:A11").format.columnWidth = 22;
  sheet.getRange("B4:B11").format.columnWidth = 72;
  sheet.getRange("B4:B11").format.wrapText = true;
  return sheet;
}

function addDictionary(workbook, packageData, templateMode) {
  const sheet = workbook.worksheets.add("16_FIELD_DICTIONARY");
  const headers = [
    "field_name", "business_definition", "data_type", "required", "normalization",
    "null_and_status_meaning", "source_profile", "validation_rules", "sensitivity",
  ];
  let dictionary = packageData.field_dictionary || [];
  if (templateMode || dictionary.length === 0) {
    dictionary = [];
    for (const definition of SHEETS) {
      for (const column of definition.columns) {
        dictionary.push({
          field_name: `${definition.key}_${column}`,
          business_definition: `Workbook projection of canonical ${definition.key}: ${column}`,
          data_type: /(?:amount|quantity|price|difference|tolerance|rate)$/.test(column)
            ? "Decimal/number or canonical decimal string"
            : "Text/object as declared by schema",
          required: false,
          normalization: [],
          null_and_status_meaning: "Blank is not a status; use the canonical status vocabulary.",
          source_profile: definition.name,
          validation_rules: [],
          sensitivity: /account|tax|personal|signature|source_snippet/.test(column)
            ? "Review masking and classification before disclosure"
            : "Follow package classification",
        });
      }
    }
  }
  const rows = matrixFromRecords(dictionary, headers, "field_dictionary");
  const matrix = [headers, ...rows];
  sheet.getRange(`A1:I${matrix.length}`).values = matrix;
  styleHeader(sheet.getRange("A1:I1"));
  sheet.freezePanes.freezeRows(1);
  sheet.showGridLines = false;
  sheet.getRange("A:A").format.columnWidth = 34;
  sheet.getRange("B:B").format.columnWidth = 46;
  sheet.getRange("C:C").format.columnWidth = 28;
  sheet.getRange("D:D").format.columnWidth = 12;
  sheet.getRange("E:I").format.columnWidth = 32;
  sheet.getRange(`A2:I${matrix.length}`).format.wrapText = true;
  const table = sheet.tables.add(`A1:I${matrix.length}`, true, "FieldDictionaryTable");
  table.style = "TableStyleMedium2";
  return sheet;
}

function addQaAndRunLog(workbook, packageData, templateMode, counts) {
  const qa = workbook.worksheets.add("18_QA_RESULTS");
  const qaRows = [
    ["check_id", "check_name", "status", "observed", "expected", "notes"],
    ["QA-STRUCTURE", "Workbook structure", "PASS", String(Object.keys(counts).length), ">= 1", "Created from declared sheet contracts"],
    ["QA-SOURCE", "Source package validation", templateMode ? "NOT_TESTED" : "PASS_WITH_WARNING", templateMode ? "No package loaded" : "Canonical top-level contract accepted", "Full JSON Schema validation remains a separate gate", "Do not treat workbook creation as semantic validation"],
    ["QA-FORMULA", "Input formula suppression", "PASS", "All exported input uses value cells", "No input formula/external link", "Untrusted markers remain string values and are escaped when necessary"],
  ];
  qa.getRange(`A1:F${qaRows.length}`).values = qaRows;
  styleHeader(qa.getRange("A1:F1"));
  qa.showGridLines = false;
  qa.freezePanes.freezeRows(1);
  qa.getRange("A:F").format.columnWidth = 28;
  qa.getRange(`A2:F${qaRows.length}`).format.wrapText = true;

  const runLog = workbook.worksheets.add("19_RUN_LOG");
  const rows = [
    ["event", "value"],
    ["builder", `build_workbook.mjs v${VERSION}`],
    ["mode", templateMode ? "TEMPLATE" : "PACKAGE_EXPORT"],
    ["run_id", safeText(packageData.run_id || "NOT_PROVIDED")],
    ["schema_version", safeText(packageData.schema_version || "NOT_PROVIDED")],
    ["package_status", safeText(packageData.status || (templateMode ? "TEMPLATE_ONLY" : "NOT_PROVIDED"))],
    ["qa_status", safeText(packageData.qa_status || (templateMode ? "NOT_TESTED" : "NOT_PROVIDED"))],
    ["human_approval_status", safeText(packageData.human_approval_status || "NOT_REQUESTED")],
    ["source_counts", safeText(counts)],
    ["formula_policy", "NO_INPUT_FORMULAS"],
    ["readiness_cap", "READY_FOR_HUMAN_REVIEW"],
  ];
  runLog.getRange(`A1:B${rows.length}`).values = rows;
  styleHeader(runLog.getRange("A1:B1"));
  runLog.showGridLines = false;
  runLog.getRange("A:A").format.columnWidth = 26;
  runLog.getRange("B:B").format.columnWidth = 72;
  runLog.getRange("B:B").format.wrapText = true;
}

async function buildWorkbook(Workbook, packageData, templateMode) {
  const workbook = Workbook.create();
  const counts = {};
  addReadme(workbook, packageData, templateMode);

  for (const definition of SHEETS) {
    const records = packageData[definition.key] || [];
    counts[definition.key] = records.length;
    if (!templateMode && records.length === 0) continue;
    const sheet = workbook.worksheets.add(definition.name);
    const rows = matrixFromRecords(records, definition.columns, definition.key);
    const matrix = [definition.columns, ...rows];
    const last = columnName(definition.columns.length - 1);
    sheet.getRange(`A1:${last}${matrix.length}`).values = matrix;
    formatDataSheet(sheet, definition.columns, records.length);
    applySemanticCellFormats(sheet, definition, records);
    if (records.length > 0) {
      const table = sheet.tables.add(`A1:${last}${matrix.length}`, true, definition.table);
      table.style = "TableStyleMedium2";
      table.showFilterButton = true;
    }
  }

  counts.field_dictionary = packageData.field_dictionary?.length || 0;
  addDictionary(workbook, packageData, templateMode);
  addQaAndRunLog(workbook, packageData, templateMode, counts);
  return { workbook, counts };
}

function assertNotProtectedPath(target, protectedInputs, label) {
  const resolvedTarget = path.resolve(target);
  for (const input of protectedInputs) {
    if (resolvedTarget === input.resolvedPath) {
      throw new Error(`${label} must not be the same path as ${input.label}: ${resolvedTarget}`);
    }
  }
}

async function assertReplaceableFile(target, overwrite, label, protectedInputs = []) {
  assertNotProtectedPath(target, protectedInputs, label);
  try {
    const stat = await fs.lstat(target, { bigint: true });
    if (stat.isSymbolicLink()) throw new Error(`${label} must not be a symlink: ${target}`);
    if (!stat.isFile()) throw new Error(`${label} exists but is not a regular file: ${target}`);
    const identity = fileIdentity(stat);
    for (const input of protectedInputs) {
      if (sameFileIdentity(identity, input.identity)) {
        throw new Error(`${label} must not alias ${input.label}: ${target}`);
      }
    }
    if (!overwrite) throw new Error(`${label} exists; use --overwrite: ${target}`);
  } catch (error) {
    if (error && error.code === "ENOENT") return;
    throw error;
  }
}

async function ensureRealDirectory(directory, label) {
  await fs.mkdir(directory, { recursive: true });
  const stat = await fs.lstat(directory);
  if (stat.isSymbolicLink() || !stat.isDirectory()) {
    throw new Error(`${label} must be a real directory, not a symlink or file: ${directory}`);
  }
}

async function createSecureTempDirectory(parent, prefix) {
  await ensureRealDirectory(parent, "temporary-file parent");
  const temporaryDirectory = await fs.mkdtemp(path.join(parent, prefix));
  await fs.chmod(temporaryDirectory, 0o700);
  return temporaryDirectory;
}

async function publishStagedFile(staged, target, overwrite, label, protectedInputs) {
  await assertReplaceableFile(target, overwrite, label, protectedInputs);
  if (overwrite) {
    // rename is an atomic same-filesystem replacement. The immediate identity
    // check above prevents replacing a known package/report alias.
    await fs.rename(staged, target);
    return;
  }

  // link is the portable same-filesystem create-if-absent primitive: unlike
  // rename, it cannot replace a target that appears after the preflight check.
  try {
    await fs.link(staged, target);
  } catch (error) {
    if (error && error.code === "EEXIST") {
      throw new Error(`${label} appeared during publication; refusing overwrite: ${target}`);
    }
    throw error;
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    process.stdout.write(`${usage()}\n`);
    return 0;
  }

  const resolvedOutput = path.resolve(args.output);
  if (path.extname(resolvedOutput).toLowerCase() !== ".xlsx") {
    throw new Error("--output must use the .xlsx extension");
  }

  let packageData = {};
  const protectedInputs = [];
  if (args.package) {
    const packageInput = await readRegularFile(args.package, "--package");
    const reportInput = await readRegularFile(
      args.schemaValidationReport,
      "--schema-validation-report",
    );
    const packageBytes = packageInput.bytes;
    packageData = JSON.parse(packageBytes.toString("utf8"));
    assertPackage(packageData);
    const suppliedReport = await assertSchemaValidationReport(packageBytes, reportInput.bytes);
    const trustedReport = await assertTrustedSchemaValidation(packageInput);
    assertReportMatchesTrustedValidation(suppliedReport, trustedReport);
    protectedInputs.push(
      { ...packageInput, label: "--package" },
      { ...reportInput, label: "--schema-validation-report" },
    );
  }

  if (!args.dryRun) {
    await assertReplaceableFile(resolvedOutput, args.overwrite, "output", protectedInputs);
  }

  let artifactTool;
  try {
    artifactTool = await import("@oai/artifact-tool");
  } catch (primaryError) {
    try {
      const require = createRequire(import.meta.url);
      const resolved = require.resolve("@oai/artifact-tool");
      artifactTool = await import(pathToFileURL(resolved).href);
    } catch (fallbackError) {
      throw new Error(
        `@oai/artifact-tool is unavailable in this runtime: ${primaryError.message}; `
        + `NODE_PATH/CommonJS resolution also failed: ${fallbackError.message}`,
      );
    }
  }
  const { SpreadsheetFile, Workbook } = artifactTool;
  const { workbook, counts } = await buildWorkbook(Workbook, packageData, args.template);

  const workbookSummary = workbook.worksheets.items.map((sheet) => ({ name: sheet.name }));

  if (args.previewDir) {
    const previewDir = path.resolve(args.previewDir);
    await ensureRealDirectory(previewDir, "--preview-dir");
    const previewTargets = workbook.worksheets.items.map((sheet) => {
      const safeName = sheet.name.replace(/[^A-Za-z0-9_-]/g, "_");
      return path.join(previewDir, `${safeName}.png`);
    });
    if (new Set(previewTargets).size !== previewTargets.length) {
      throw new Error("worksheet names collide after preview filename sanitization");
    }
    for (const target of previewTargets) {
      await assertReplaceableFile(target, args.overwrite, "preview", protectedInputs);
    }
    const previewTemporaryDirectory = await createSecureTempDirectory(
      previewDir,
      ".document-evidence-preview-",
    );
    try {
      const stagedPreviews = [];
      for (const [index, sheet] of workbook.worksheets.items.entries()) {
        const preview = await workbook.render({ sheetName: sheet.name, autoCrop: "all", scale: 1, format: "png" });
        const staged = path.join(previewTemporaryDirectory, `${index}.png`);
        await fs.writeFile(
          staged,
          new Uint8Array(await preview.arrayBuffer()),
          { flag: "wx", mode: 0o600 },
        );
        stagedPreviews.push(staged);
      }
      for (let index = 0; index < previewTargets.length; index += 1) {
        await publishStagedFile(
          stagedPreviews[index],
          previewTargets[index],
          args.overwrite,
          "preview",
          protectedInputs,
        );
      }
    } finally {
      await fs.rm(previewTemporaryDirectory, { recursive: true, force: true });
    }
  }

  if (!args.dryRun) {
    const output = resolvedOutput;
    const temporaryDirectory = await createSecureTempDirectory(
      path.dirname(output),
      `.${path.basename(output)}.tmp-`,
    );
    const temporary = path.join(temporaryDirectory, "workbook.xlsx");
    try {
      const blob = await SpreadsheetFile.exportXlsx(workbook);
      await blob.save(temporary);
      const temporaryStat = await fs.lstat(temporary);
      if (!temporaryStat.isFile() || temporaryStat.isSymbolicLink()) {
        throw new Error("workbook exporter did not create a regular non-symlink XLSX");
      }
      await publishStagedFile(
        temporary,
        output,
        args.overwrite,
        "output",
        protectedInputs,
      );
    } finally {
      await fs.rm(temporaryDirectory, { recursive: true, force: true });
    }
  }

  process.stdout.write(`${JSON.stringify({
    status: "PASS",
    mode: args.template ? "TEMPLATE" : "PACKAGE_EXPORT",
    output: args.dryRun ? null : path.resolve(args.output),
    counts,
    workbook_summary: workbookSummary,
  }, null, 2)}\n`);
  return 0;
}

try {
  process.exitCode = await main();
} catch (error) {
  process.stderr.write(`ERROR: ${error.message}\n`);
  process.exitCode = 2;
}
