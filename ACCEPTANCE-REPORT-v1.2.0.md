# Acceptance report — v1.2.0

Date: 2026-09-01

Release status: Final identity, QA label `Testing`

Phase 3 disposition: **GO — LOCAL PROMOTION COMPLETE**

## Scope and version decision

This release carries the eight Phase 1 remediations completed in Phase 2 and subjects them to independent source, package-native, retention, behavioral-coverage, and visual QA. The skill version is `1.2.0`, not `1.1.1`, because generic workbook package export now requires a trusted local Python 3 runtime for fresh validation. The provisional top-level extraction-package provenance field was removed: closed extraction schema, package, skill, and reconciliation tool compatibility remain `1.0.0`; release provenance is recorded in the existing `run_manifest.tool_versions` map and in companion workflow manifests.

The frozen `1.1.0` release is not overwritten. Retention preserves `1.0.0`, `1.1.0-rc.2`, and `1.1.0`; the six RC1 distribution artifacts were retired under the three-version cap with exact hashes and recovery commit recorded in `qa/release-1.2.0/retention-retirement.json`.

## QA gates

- Independent source reperform: eight of eight Phase 1 findings have dedicated regression evidence; no open High/Critical source blocker was identified.
- Historical controls: RC2 and 1.1.0 remain byte-pinned; the 1.1.0 oracle no longer depends on current release metadata.
- Full regression: 188 tests, 187 PASS and 1 optional SKIP because PyYAML is unavailable.
- Candidate package-native oracle: 26/26 PASS from the three extracted 1.2.0 ZIPs, including all nine bundled reconciliation profiles, five conversion formats, RAG modes/fail-closed controls, eight Phase 1 remediation paths, readiness/provenance checks, and missing required role → `BLOCKED`.
- Frozen package-native history: 46 PASS across the byte-pinned RC2 and 1.1.0 suites.
- Repository hygiene and `git diff --check`: PASS. Hygiene reports four soft LOC warnings and no blocker, junk/orphan finding, unmanaged distribution artifact, or unallowlisted duplicate.
- XLSX visual QA: PASS for the representative 659-character provenance cell; one of one sheet rendered, row height 210, freeze/filter present, no overlap/material clipping, and zero formula-error matches. See `qa/release-1.2.0/visual-verification.json`.
- Behavioral catalog: 8 `EXECUTED_PASS`, 34 `PARTIAL`, and 22 `NOT_EXECUTED`; coverage is separately dispositioned in `qa/phase3-1.2.0/behavioral-disposition.json`. Specification-only or partially covered scenarios are not promoted to PASS by inference.
- Optional skill-creator quick validation: unavailable because PyYAML is absent; no dependency was installed and this gate must remain reported as SKIP, not PASS.
- Live OpenAI/Claude installation, real OCR/handwriting/bank-statement accuracy, live RAG ingestion/embedding/retrieval, broad native Office fidelity, performance/volume, and external publication remain outside the executed claim.

## Final package gates and promotion decision

Phase 3 materialized all six release outputs, passed a second exact build check, verified five checksum entries, ZIP CRC/layout/permissions, and cross-platform parity across 87 portable-core files. Current and frozen package-native oracles, all nine matching profiles, missing-role `BLOCKED` behavior, readiness ceiling, release provenance, visual evidence, and the complete regression suite passed. Exact counts and hashes are recorded in `qa/release-1.2.0/verification.json`.

Local promotion is therefore **GO** for versioned `dist/` artifacts with QA status `Testing` and automated readiness no higher than `READY_FOR_HUMAN_REVIEW`. This verdict is deliberately narrower than “all objectives achieved”: the behavioral, live-platform, real-document, RAG-system, broad Office-fidelity, and scale gaps above remain explicit residual nonclaims.

No commit, tag, push, publication, marketplace submission, live installation, or external service was performed. `Final` identifies the local versioned release artifact; it is not production approval, platform certification, legal opinion, or human business approval.
