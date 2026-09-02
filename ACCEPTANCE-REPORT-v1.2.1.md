# Acceptance report — v1.2.1

Date: 2026-09-02

Release status: **Final**

Decision: **GO — CONTROLLED PATCH RELEASE**

## Scope

Version 1.2.1 is a display-identity and distribution-layout patch. The user-facing name changes from `Thien Skill — Document Intelligence, Evidence & Reconciliation` to `Thiện's Skill — Document Intelligence & Reconciliation`. The technical identifier `thien-skill-document-evidence`, artifact basename, schemas, tool contracts, runtime behavior, matching profiles, readiness ceiling, logo pixels and brand hashes remain unchanged from 1.2.0.

The new Display Name is synchronized across canonical UI metadata, OpenAI and Claude plugin manifests, build metadata, registry, legal identity records and current documentation. Historical 1.2.0 ZIP artifacts and embedded evidence retain their original name and bytes; only their outer repository paths and release-index metadata are normalized.

The active distribution layout is `dist/<version>/`. Each version directory is self-contained with three flat ZIP packages, `SHA256SUMS`, `release-manifest.json` and `PARITY.json`. Historical ZIP bytes remain frozen; historical checksum/manifest metadata is re-indexed only to represent the new paths, with old/new path and hash provenance recorded in `qa/release-1.2.1/dist-layout-migration.json`.

## Controlled validation

- Full regression: **170 tests, 169 PASS and 1 optional SKIP** because PyYAML is unavailable; no dependency was installed.
- Candidate package-native oracle: **26/26 PASS** across OpenAI, Claude and Universal ZIPs.
- Frozen 1.2.0 oracle: exact ZIP bytes, normalized checksum inventory, release metadata, ZIP layout/timestamp and original embedded Display Name remain pinned.
- Build gates: deterministic render, second exact check, 5/5 checksum verification, ZIP CRC/layout/permissions and portable-core parity PASS.
- Identity gates: version `1.2.1`, new Display Name and unchanged technical ID are verified in source, manifests and all three ZIPs.
- Distribution-layout gate: all four retained versions are isolated below `dist/<version>/`; no root-level artifacts, platform directories, junk or orphan files remain.
- Repository hygiene and `git diff --check`: PASS, with the four pre-existing soft source-line warnings and no junk/orphan blocker.
- Root/canonical legal pairs remain byte-identical; master license and logo/icon bytes are unchanged.

## Retention and limits

The three preserved historical releases are `1.0.0`, `1.1.0` and `1.2.0`. Six `1.1.0-rc.2` artifacts are retired from active `dist/` and remain recoverable from Git tag `v1.2.0`; exact hashes and sizes are recorded in `qa/release-1.2.1/retention-retirement.json`.

This patch inherits the tested capabilities and residual nonclaims of 1.2.0. It does not claim new OCR accuracy, live RAG quality, broad native Office fidelity, production approval, platform certification, legal opinion or human business approval. Automated readiness remains no higher than `READY_FOR_HUMAN_REVIEW`.

Git commit, push and annotated tag occur only after the byte-level and regression gates pass. This report records package acceptance and does not by itself prove external publication or live installation.
