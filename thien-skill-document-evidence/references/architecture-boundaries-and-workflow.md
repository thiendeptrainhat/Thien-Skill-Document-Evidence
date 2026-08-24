# Kiến trúc, ranh giới và workflow

## Mục đích

Tài liệu này định tuyến engagement có nhiều loại tài liệu hoặc nhiều chuyên môn. Skill chỉ sở hữu lớp `document/evidence`: tiếp nhận, biểu diễn working copy, extraction, provenance, validation, document linking, reconciliation candidate và controlled handoff.

## Ranh giới capability

| Capability | Skill thực hiện | Capability/owner khác quyết định |
|---|---|---|
| Tài liệu nguồn | Inventory, integrity preflight, original/working-copy distinction | System owner xác nhận completeness của source system |
| OCR/vision | Chọn route, dùng adapter sẵn có, lưu raw output/provenance | Platform/data owner phê duyệt external processing |
| Structured data | Schema, field/table extraction, validation, export | Data Engineering xây pipeline, master-data certification, warehouse |
| Reconciliation | Match theo key/rule/tolerance được cấp; tạo discrepancy | Business/control owner chốt rule, tolerance và disposition |
| Audit | Chuẩn bị evidence và test attributes | Auditor kết luận sufficiency, control effectiveness, finding/opinion |
| Investigation | Preserve/extract/link theo mandate | Investigator xác lập allegation, findings of fact và conclusion |
| Legal/contract | Trích clause/obligation và source text | Luật sư đánh giá hiệu lực, diễn giải, breach và remedy |
| Authenticity | Ghi signature/stamp/metadata presence | Chuyên gia phù hợp xác thực chữ ký, tài liệu hoặc forensic conclusion |
| Analytics | Tạo canonical rows và evidence references | Analytics/model owner phát hiện pattern hoặc chấm điểm population |
| Reporting | Bàn giao output đã QA cùng limitations | Reporting owner chọn narrative/visualization và audience release |

Nếu capability đích không có skill tương ứng, tạo handoff theo vai trò và dữ liệu cần thiết; không tự mở rộng nhiệm vụ.

## Sáu route

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
5. Chọn extraction route theo capability thực tế; không giả định engine/dependency.
6. Chọn schema/version và extract raw + normalized + provenance.
7. Validate field/table/cross-field; tạo review item cho critical failure.
8. Link/reconcile khi rules và tolerances đã được cung cấp.
9. Xuất artifact phù hợp, kiểm tra row counts, formula safety và package completeness.
10. QA, ghi limitations/partial failures, human approval status và capability-based handoff.

Không chạy route sau như thể route trước đã pass nếu blocker làm mất tính toàn vẹn. Có thể tiếp tục phần độc lập an toàn và ghi coverage gap.

## Input contract tối thiểu

Chỉ yêu cầu trường material cho route hiện tại:

```yaml
task_id: string
engagement_id: string | null
case_id: string | null
objective: string
intended_use: string
document_sources: [path-or-authorized-reference]
authorized_scope: string
data_classification: string
expected_document_types: [string]
expected_fields: [string]
period_and_entities: object | null
matching_rules: object | null
tolerances: object | null
output_format: [json, jsonl, csv, xlsx, markdown]
output_location: path | null
cloud_processing_allowed: boolean | null
local_processing_required: boolean | null
chain_of_custody_required: boolean
redaction_requirements: object | null
available_tools: [string]
human_approval_requirements: [string]
```

Không tự suy ra `cloud_processing_allowed: true`, tolerance, recipient, data rights, governing locale hoặc investigation mandate.

## Output contract tối thiểu

```yaml
task_id: string
extraction_run_id: string
skill_version: string
scope_and_coverage: object
document_inventory: [object]
classification_results: [object]
extracted_fields: [object]
line_items: [object]
document_links: [object]
reconciliation_results: [object]
discrepancies: [object]
evidence_register: [object]
human_review_queue: [object]
security_flags: [object]
assumptions: [string]
limitations: [string]
unresolved_issues: [object]
qa_status: string
human_approval_status: string
artifacts: [object]
```

Một mảng không áp dụng có thể vắng mặt; không tạo record giả để lấp schema. Field material không biết phải có status rõ.

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
