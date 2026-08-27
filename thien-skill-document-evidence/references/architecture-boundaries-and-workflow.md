# Kiến trúc, ranh giới và workflow

## Mục đích

Tài liệu này định tuyến engagement có nhiều loại tài liệu hoặc nhiều chuyên môn. Skill sở hữu lớp `document/evidence`: tiếp nhận, biểu diễn original/working copy, canonical semantic content, extraction, provenance, validation, document conversion, RAG source packaging, document linking, deterministic reconciliation candidate và controlled handoff.

Task request phải chọn một trong ba profile ở `schemas/common/task-request.schema.json`: `CONVERT_DOCUMENT`, `PREPARE_RAG_SOURCE` hoặc `RECONCILE_DOCUMENT_SET`. Chi tiết capability discovery và fallback nằm tại `platform-capability-routing.md`. Các companion contract mới bổ sung cho extraction package v1.0; không thay thế hoặc âm thầm sửa output cũ.

Companion objects ghi riêng `skill_id: thien-skill-document-evidence` và `skill_release_version` để truy vết release đang chạy, kể cả prerelease/RC. `schema_version: 1.0.0` của companion contract là version của machine contract, không phải release version. Extraction package, reconciliation config và script/tool constants v1.0.0 hiện hữu được giữ như compatibility contract/tool version; không relabel chúng thành RC và không dùng chúng làm bằng chứng duy nhất về release provenance.

## Ranh giới capability

| Capability | Skill thực hiện | Capability/owner khác quyết định |
|---|---|---|
| Tài liệu nguồn | Inventory, integrity preflight, original/working-copy distinction | System owner xác nhận completeness của source system |
| OCR/vision | Chọn route, dùng adapter sẵn có, lưu raw output/provenance | Platform/data owner phê duyệt external processing |
| Conversion | Tạo canonical content và artifact theo output profile/capability thực tế | User/recipient chốt intended use và trade-off editability/fidelity |
| RAG source | Tạo Markdown/metadata/manifest/assets có traceability | RAG owner chọn chunking, embeddings, index, ingestion và retrieval evaluation |
| Structured data | Schema, field/table extraction, validation, export | Data Engineering xây pipeline, master-data certification, warehouse |
| Reconciliation | Match theo key/rule/tolerance được cấp; tạo discrepancy | Business/control owner chốt rule, tolerance và disposition |
| Audit | Chuẩn bị evidence và test attributes | Auditor kết luận sufficiency, control effectiveness, finding/opinion |
| Investigation | Preserve/extract/link theo mandate | Investigator xác lập allegation, findings of fact và conclusion |
| Legal/contract | Trích clause/obligation và source text | Luật sư đánh giá hiệu lực, diễn giải, breach và remedy |
| Authenticity | Ghi signature/stamp/metadata presence | Chuyên gia phù hợp xác thực chữ ký, tài liệu hoặc forensic conclusion |
| Analytics | Tạo canonical rows và evidence references | Analytics/model owner phát hiện pattern hoặc chấm điểm population |
| Reporting | Bàn giao output đã QA cùng limitations | Reporting owner chọn narrative/visualization và audience release |

Nếu capability đích không có skill/runtime tương ứng, tạo canonical handoff theo vai trò và dữ liệu cần thiết; không tự cài dependency, mở rộng nhiệm vụ hoặc tuyên bố platform certification.

## Task profiles và workflow branch

| Task profile | Workflow chính | Output contract |
|---|---|---|
| `CONVERT_DOCUMENT` | Intake → classify/parse → canonical content → render/export → QA | `canonical-content.schema.json` + `artifact-manifest.schema.json` |
| `PREPARE_RAG_SOURCE` | Intake → classify/parse → canonical content → RAG package → package QA | `rag-package.schema.json` + artifact manifest |
| `RECONCILE_DOCUMENT_SET` | Intake → classify/extract → structure/validate → link/reconcile → output QA | Extraction package v1.0 + reconciliation config/result |

Evidence register, chain of custody, investigation controls và redaction là conditional overlays. Chúng chỉ được kích hoạt khi task request, mandate, recipients và authorization yêu cầu; không phải output mặc định của conversion hoặc RAG preparation.

## Sáu operational route

Sáu route dưới đây là lifecycle controls có thể dùng trong task profile phù hợp; không phải mọi task đều chạy mọi route. `EVIDENCE_DISCLOSURE` chỉ áp dụng khi engagement cần evidence/custody/redaction/disclosure controls.

### `INTAKE_INTEGRITY`

- **Entry:** Source và phạm vi đọc được phép xác định.
- **Success:** Inventory đầy đủ trong phạm vi; eligibility, integrity/security flags và original/working-copy status rõ.
- **Stop:** Path/source không an toàn, authorization không đủ, encrypted/password file chưa có quyền hợp lệ.
- **Failure:** Không đọc được, extension/signature conflict, hash/read lỗi hoặc coverage không xác định.
- **Handoff:** Owner nguồn cung cấp lại bản hợp lệ; Security/Legal khi source bị hạn chế.

### `CLASSIFY_EXTRACT`

- **Entry:** Intake pass hoặc pass-with-limitation; extraction purpose và tool policy rõ.
- **Success:** Document/page được classify hoặc giữ `UNCLASSIFIED`; raw extraction có engine/run/page provenance.
- **Stop:** External upload chưa được phép, original có nguy cơ bị đổi, active content cần thực thi, output không đủ bảo vệ.
- **Failure:** Không có route khả dụng, OCR/vision disagreement trọng yếu hoặc trang không đọc được.
- **Handoff:** Human transcription/review hoặc chuyên gia format/forensic phù hợp.

### `STRUCTURE_VALIDATE`

- **Entry:** Có raw/native/OCR/vision content và schema phù hợp.
- **Success:** Fields/tables/clauses/obligations đáp ứng contract; validations và review queue được ghi.
- **Stop:** Schema/grain/locale trọng yếu chưa rõ; source provenance mất.
- **Failure:** Critical field không đọc được, table segmentation không ổn định hoặc totals không reconcile.
- **Handoff:** Human reviewer, document owner hoặc schema/data owner.

### `LINK_RECONCILE`

- **Entry:** Có IDs, sides, grain, keys và approved tolerance/rule.
- **Success:** Mỗi record có match/discrepancy status, difference, rationale và source references.
- **Stop:** Không có rule/tolerance cho kết luận material; keys không đủ phân biệt.
- **Failure:** Many-to-many ambiguity, currency/date basis conflict, partial flow chưa được định nghĩa.
- **Handoff:** Business/control owner; Data Engineering nếu volume/normalization vượt local workflow.

### `EVIDENCE_DISCLOSURE`

- **Entry:** Intended use, case/engagement, classification, owner, authorized recipients và custody/redaction requirement rõ.
- **Success:** Evidence register/custody/redaction log phản ánh sự kiện thực; original hash và restricted output được kiểm soát.
- **Stop:** Không có mandate, recipient/scope không rõ, redaction không thể kiểm chứng hoặc mapping không thể bảo vệ.
- **Failure:** Original/working copy lẫn, hash conflict, missing custody event hoặc redaction chỉ che bề mặt.
- **Handoff:** Investigation/Legal/Privacy/Security owner và human approver.

### `REVIEW_REPERFORM`

- **Entry:** Có source, methodology/config, output và phạm vi review.
- **Success:** Reviewer tái tạo inventory/record counts, logic, exceptions và provenance; deviations được phân loại.
- **Stop:** Thiếu source/version/config làm conclusion không thể reperform.
- **Failure:** Source, OCR/layout, schema, normalization, reconciliation, evidence, security hoặc unsupported-conclusion issue.
- **Handoff:** Owner của component lỗi; không tự sửa production/source ngoài phạm vi.

## Lifecycle dùng chung

1. Ghi objective, intended/prohibited use, decision owner và deliverable.
2. Xác nhận authority, source scope, classification, recipients và execution constraints.
3. Bảo toàn original; tạo inventory, identifiers và integrity/security flags.
4. Classify document/package/version; ghi confidence và unresolved items.
5. Chọn parse/extraction route theo capability thực tế; không giả định engine/dependency.
6. Chọn schema/version và tạo raw + normalized + provenance; tạo canonical semantic blocks khi task cần conversion/RAG.
7. Validate content/field/table/cross-field; tạo review item cho critical failure.
8. Branch theo task profile: render conversion artifact; build RAG source package; hoặc link/reconcile theo rules/tolerances đã cấp.
9. Xuất artifact phù hợp và kiểm tra package completeness, source mapping, counts/hashes cùng format-specific safety.
10. QA, ghi limitations/partial failures, human approval status và capability-based handoff. Schema + contract-defined structural invariants, broader semantic/source-fidelity, render/format và live-platform/install checks cần evidence riêng; check chưa thực sự chạy phải là `NOT_TESTED`.

Không chạy route sau như thể route trước đã pass nếu blocker làm mất tính toàn vẹn. Có thể tiếp tục phần độc lập an toàn và ghi coverage gap.

## Input contract tối thiểu

Routing object máy đọc được tuân `schemas/common/task-request.schema.json` và giữ spine sau; chỉ một branch object được dùng theo `task_profile`:

```yaml
schema_version: 1.0.0
skill_id: thien-skill-document-evidence
skill_release_version: semver-including-prerelease
request_id: string
task_profile: CONVERT_DOCUMENT | PREPARE_RAG_SOURCE | RECONCILE_DOCUMENT_SET
source_document_ids: [string]
conversion: object | null
rag: object | null
reconciliation: object | null
requested_by: string | null
assumptions: [string]
limitations: [string]
```

Engagement/intake context liên kết ngoài routing object vẫn phải có các trường material cho route hiện tại: objective/intended use, authorized sources/scope, data classification/recipients, expected document types/fields, period/entities, matching rules/tolerances, output location, cloud/local policy, capability inventory, approval requirements và — chỉ khi áp dụng — case/custody/redaction requirements. Không thêm các field này trái phép vào schema `additionalProperties: false`; lưu trong engagement/extraction/handoff contract có version tương ứng.

Không tự suy ra `cloud_processing_allowed: true`, tolerance, recipient, data rights, governing locale hoặc investigation mandate.

## Output object set

- Extraction/reconciliation dùng `schemas/common/extraction-package.schema.json` và result/config schemas hiện hữu.
- Semantic conversion/RAG dùng `schemas/common/canonical-content.schema.json`.
- Mọi artifact set dùng `schemas/common/artifact-manifest.schema.json`.
- RAG source package dùng `schemas/common/rag-package.schema.json`.
- Handoff liên capability dùng contract ở phần tiếp theo.

Mỗi object giữ schema/version, task/request/run/package IDs, source links, coverage, assumptions, limitations, unresolved issues, QA và human-review/approval status theo schema của chính nó. Các object/mảng không áp dụng tuân null/omission semantics của schema tương ứng; không tạo record giả để lấp schema. Không nhập canonical extraction package, canonical content, artifact manifest và RAG package thành một mega-object không version.

Với artifact/RAG descriptors, `creation_status` (`CREATED`, `NOT_CREATED`, `BLOCKED`) chỉ trả lời file đã được tạo hay chưa; `qa_status` dùng `validationStatus` và trả lời check đã chạy/đạt hay chưa. `CREATED` + `NOT_TESTED` là trạng thái hợp lệ. Top-level/package/document chỉ được `PASS` khi mọi descriptor bắt buộc cho profile đã `CREATED` và `qa_status: PASS`; file existence hoặc checksum đơn lẻ không tạo semantic, render hay platform PASS.

## Handoff contract

```yaml
handoff_id: string
source_capability: document-evidence
target_capability: string
objective: string
scope: string
out_of_scope: [string]
input_objects: [object-reference]
source_references: [object-reference]
data_classification: string
assumptions: [string]
limitations: [string]
quality_checks: [string]
required_methodology: [string]
expected_output_schema: string | null
human_approval_requirements: [string]
status: DRAFT | READY_FOR_HUMAN_REVIEW | BLOCKED
```

## Investigation gate

Trước restricted evidence work cần có tối thiểu:

- `case_id` hoặc matter identifier;
- investigation owner và thẩm quyền/mandate;
- allegation/matter description trung lập, objective, scope và period;
- approved sources, access authorization và classification;
- custody/redaction/recipient requirements;
- Legal/HR/Privacy/Security constraints khi áp dụng.

Nếu thiếu, chỉ thực hiện ordinary document triage với internal/pseudonymized IDs; không gọi cá nhân là suspect, không mở rộng source và không tạo investigation-ready claim.

## Trạng thái thiếu dữ kiện và readiness

Không dùng blank cho semantics. Dùng `UNKNOWN`, `NOT_PROVIDED`, `NOT_APPLICABLE`, `NOT_TESTED`, `AMBIGUOUS`, `CONFLICTING`, `PENDING_HUMAN_CONFIRMATION` hoặc `BLOCKED`.

Readiness không phải quality score. `READY_FOR_HUMAN_REVIEW` nghĩa là artifact đủ để người có thẩm quyền review trong phạm vi và limitations đã ghi; không nghĩa là correct, approved, admissible hoặc production-ready.
