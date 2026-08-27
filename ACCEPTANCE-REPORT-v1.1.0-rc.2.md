# BÁO CÁO NGHIỆM THU PHASE 2 / PHASE 2 ACCEPTANCE REPORT — VERSION 1.1.0-rc.2

engagement_mode: `ADVISORY_IMPLEMENTATION_AND_RELEASE_QA`
prior_advisory_involvement: `YES — SAME PRIMARY AGENT REVIEWED PHASE_1 AND COORDINATED PHASE_2`
self_review_risk: `PRESENT`
independence_threat: `SELF_REVIEW`
safeguards: `AUTOMATED_CONTRACT_AND_ADVERSARIAL_TESTS; DETERMINISTIC_BUILD; FAULT_INJECTION; SYNTHETIC_RENDER_SMOKE; HISTORICAL_ARTIFACT_HASH_GATE; SEPARATE_AGENT_TECHNICAL_REVIEW`
reviewer_independence: `SEPARATE AGENT PEER TECHNICAL REVIEW ONLY — NOT HUMAN INDEPENDENT APPROVAL`

**Trạng thái sản phẩm:** `Testing`  
**Readiness:** `READY_FOR_HUMAN_REVIEW — PHASE 2 IMPLEMENTATION COMPLETE`  
**Ngày đánh giá:** `2026-08-27`  
**Phạm vi:** offline deterministic conversion, RAG package, extensible reconciliation workflow, synthetic fixtures, release metadata và RC2 packages  
**Ngoài phạm vi:** live installation/ingestion trên ChatGPT, Codex, Claude hoặc RAG target; dữ liệu thật; production approval; human independent approval; Phase 3 cross-platform acceptance

## Kết luận

Release candidate `1.1.0-rc.2` hoàn thành Phase 2 Implementation theo ba vertical slice:

- canonical content → deterministic JSON/Markdown/DOCX/XLSX/PPTX, kèm artifact manifest và closed conversion-run sidecar;
- canonical content → schema-valid DOCUMENT/COLLECTION RAG source package, optional target-configured chunks và passive media/path validation;
- structured folder/package → named/custom matching profile → deterministic reconciliation result, validated package và role-aware XLSX review workbook.

Runtime release provenance `1.1.0-rc.2` được tách khỏi source canonical provenance và khỏi tool/schema/config compatibility `1.0.0`. Không có mandatory OCR model, API key, mạng hoặc vendor dependency. Helper không tự suy tolerance/materiality, không auto-allocate many-to-many và không tự phê duyệt business decision. Readiness của release vẫn bị chặn ở human review; `READY_FOR_LIMITED_USE` trong một workflow manifest chỉ mô tả technical run trên exact structured inputs, không phải product/platform/transaction approval.

Ba ZIP OpenAI, Claude và Universal được sinh từ cùng canonical source bằng deterministic builder. Package structure, embedded manifests, portable-core parity, SHA-256 và preservation gate cho `1.0.0` cùng `1.1.0-rc.1` phải cùng PASS trước bàn giao.

## Implementation được nghiệm thu

### Conversion

- Input qua `canonical-content.schema.json` và semantic invariants trước render.
- DOCX semantic-editable; XLSX structured-data có typed contract fields, formula safety, giới hạn 32.767 code points/cell và print setup; PPTX intent/profile pair fail-closed.
- `EDITABLE_PRESENTATION` paginate text/table/image mà không mất nội dung hoặc đẩy shape khỏi canvas; table cells dùng direct text/background formatting để không phụ thuộc built-in table-style fallback của viewer.
- `VISUAL_FIDELITY_BEST_EFFORT` dùng pipeline geometry-aware riêng, yêu cầu captured bounding boxes/page dimensions; không alias sang editable layout.
- Artifact, manifest và `conversion-run.json` được stage; từng replacement là atomic và lỗi publication được bắt sẽ rollback create/overwrite. Không tuyên bố power-loss transaction trên nhiều filesystem rename.

### RAG package

- Default không chunk; `chunks.jsonl` chỉ được tạo khi `--target-id` và `--chunk-config` cùng được cung cấp.
- Root `rag-package.json` điều khiển per-document Markdown/metadata/payload manifest; collection giữ membership riêng.
- Asset bắt buộc dưới `assets/`; reserved/exact/case/prefix collision, path escape, symlink/hardlink alias và checksum mismatch bị chặn.
- PNG dùng bounded IDAT decompression/pixel/scanline/filter checks; JPEG/WebP có structure/signature checks; SVG dùng passive allowlist và chặn active/external content.
- Package `PASS` chỉ là structural build scope. Live ingestion, embeddings, index và retrieval quality vẫn `NOT_TESTED`.

### Reconciliation

- `matching-profile.schema.json` giữ `profile_kind` mở nhưng semantic validation khóa unique IDs/sheets/rules, role references, mapping variants, mode/count, comparator/tolerance unit, aggregation và date/currency basis.
- Có 7 profile bắt buộc và 2 additive profile cho outbound/customer receipt và inventory.
- End-to-end synthetic runs bao phủ `PR → PO` và `Invoice → Payment Request → Bank Transaction`; Contract/PO và GRN/Acceptance alternatives, partial policy, cumulative over-allocation, duplicate content, missing role/per-file failure cũng được test.
- Workbook chỉ tạo role/control sheets có dữ liệu, giữ raw/normalized/provenance, identifier leading zero, typed amount/date, freeze/filter và untrusted formula prefix dưới dạng literal.
- Many-to-many bridge được validate nhưng giữ review-only; helper không tự phân bổ.

## Validation evidence

| Gate | Trạng thái | Ghi chú |
|---|---|---|
| Conversion targeted regression | `PASS` | 14/14 tests PASS; gồm 3-file rollback fault injection, cell limit, pagination và geometry path |
| RAG targeted regression | `PASS` | 16/16 tests PASS; gồm reserved collision, active SVG, media spoofing và bounded PNG IDAT PoCs |
| Reconciliation targeted regression | `PASS` | 15/15 tests PASS; 9 profiles, mapping/basis/partial/duplicate/atomic publish và PR/payment/bank exit gates |
| Full automated regression suite | `PASS_WITH_WARNING` | 97 tests run: 96 PASS; 1 optional plugin-creator/PyYAML validator test SKIP vì dependency không có trong runtime |
| Behavioral catalog | `STRUCTURAL_PASS; EXECUTION_NOT_TESTED` | `DE-001` đến `DE-064` được kiểm là specification-only và đầy đủ; không entry nào được unit test nâng từ `NOT_TESTED` thành behavioral execution PASS |
| Separate-agent technical closure | `PASS_WITH_LIMITATIONS` | RAG/conversion 30/30 targeted retest; reconciliation engine/review 19/19; không phải human independent approval |
| Synthetic DOCX render/import smoke | `PASS` | LibreOffice import/export PDF thành công; heading, paragraph, table, image/caption hiện diện |
| Synthetic PPTX render/import/overflow smoke | `PASS` | Bundled renderer mở được; slide overflow test PASS; cùng fixture render đủ title, paragraph, table text, image và caption trên 3 LibreOffice user profiles cô lập |
| Synthetic conversion XLSX render smoke | `PASS_WITH_WARNING` | LibreOffice mở/export một trang landscape; mọi cột hiện diện nhưng print view của wide structured sheet khá dày |
| Synthetic reconciliation XLSX render smoke | `PASS_WITH_WARNING` | LibreOffice mở/export năm sheet có dữ liệu, không horizontal page split; wide field/match sheets bị thu nhỏ trong print view |
| RAG package generation/checksums | `PASS` | Actual fixture build tạo root control + per-document payload/assets; schema và descriptor checksum PASS |
| OpenAI/Claude/Universal deterministic package build | `PASS` | Ba ZIP RC2 được builder tạo và `--check` xác minh exact release state |
| Portable-core parity và SHA-256 manifest | `PASS` | `PARITY-v1.1.0-rc.2.json` PASS; release manifest/checksum sinh deterministic |
| Historical `1.0.0` và `1.1.0-rc.1` preservation | `PASS` | Configured historical manifests/checksums/archive structure được xác minh và không ghi đè |
| Live ChatGPT/OpenAI installation | `NOT_TESTED` | Người dùng yêu cầu chỉ tạo gói cài đặt |
| Live Codex installation | `NOT_TESTED` | Người dùng yêu cầu chỉ tạo gói cài đặt |
| Live Claude installation | `NOT_TESTED` | Người dùng yêu cầu chỉ tạo gói cài đặt |
| Live RAG target ingestion/retrieval | `NOT_TESTED` | Không có target runtime được phê duyệt trong Phase 2 |
| Real PDF/image OCR/extraction accuracy | `NOT_TESTED` | Tests dùng synthetic structured/canonical fixtures; raw files cần upstream host adapter |

## Residual gates cho Phase 3

1. Live-install và invocation test trên Codex, ChatGPT và Claude; không suy platform PASS từ ZIP validation.
2. Cross-platform matrix với receipt/image, scanned PDF, DOCX/PPTX conversion, RAG target, folder/attachment equivalents, partial payment/delivery và missing/blurred pages.
3. Human review trên tài liệu thật đã được phép dùng, đặc biệt source fidelity, locale/date/currency, bank sign convention, print/readability và workflow coverage.
4. Target-specific RAG ingestion/retrieval test; package structural PASS không chứng minh retrieval quality.
5. Qualified human review trước external commercial, production, legal, audit, investigation hoặc payment/inventory decision use.

Tài liệu này không phải phê duyệt cuối cùng, legal opinion, audit opinion, forensic certification, fraud finding, document-authenticity conclusion hoặc platform certification. Các report/artifact `1.0.0` và `1.1.0-rc.1` là hồ sơ lịch sử, không bị thay thế hay viết lại bởi RC2.
