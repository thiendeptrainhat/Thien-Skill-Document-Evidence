# Evidence, provenance, confidence và human review

## Evidence model

OCR/extracted data là derivative của source, không phải evidence độc lập. Một evidence record cần source/custodian, received/captured context, copy role, hash/size/page count, classification/restrictions, reliability basis, custody/redaction/review status và related object references.

Không tự gọi một copy là original, certified, admissible hoặc authentic.

## Reliability classes

| Class | Diễn giải giới hạn |
|---|---|
| `ORIGINAL_SYSTEM_RECORD` | Record trực tiếp từ system theo controlled process đã ghi |
| `ORIGINAL_DIGITAL_DOCUMENT` | Byte object được tạo/nhận như source gốc theo provenance hiện có |
| `PHYSICAL_DOCUMENT_SCAN` | Scan của vật lý; không tự xác thực vật lý |
| `CERTIFIED_COPY` | Chỉ dùng khi certification có source và scope được ghi |
| `CONTROLLED_SYSTEM_EXPORT` | Export có method/time/operator/control record |
| `WORKING_COPY` | Derivative để xử lý |
| `THIRD_PARTY_DOCUMENT` | Source bên thứ ba; independence/completeness cần đánh giá |
| `SCREENSHOT` | Có nguy cơ thiếu context/metadata |
| `OCR_DERIVED_DATA` | Phụ thuộc source và adapter |
| `USER_PROVIDED_COPY` | Provenance theo representation của người cung cấp |
| `UNVERIFIED_OR_INCOMPLETE_COPY` | Thiếu provenance/completeness hoặc có conflict |
| `UNKNOWN_ORIGIN` | Không đủ để phân loại |

Reliability assessment xem provenance, completeness, byte integrity/hash, version, source independence, date/context, consistency, corroboration và alteration risk. Không chuyển thành legal admissibility conclusion.

## Provenance levels

Mỗi material value nên truy nguyên theo chuỗi:

`package/run → document occurrence → content hash → page → region/snippet → adapter/method → extracted field → validation/review → output cell/row`

Region ghi coordinate system và page dimensions. Nếu chỉ có snippet/page, ghi region unavailable; không bịa bounding box.

Source snippet phải ngắn đủ kiểm chứng và tuân thủ confidentiality/copyright. Không đưa secret/PII ngoài intended output.

## Chain of custody

Custody log chỉ phản ánh event thật: received, registered, hashed, copied, transferred, accessed, extracted, redacted, reviewed, returned, archived, exported.

Mỗi event cần event/evidence ID, from/to person/location/role, datetime/timezone, purpose/action, tool/version, before/after hash khi thực sự tính, working-copy flag, authorization reference, performer, optional witness/reviewer và notes.

- Không điền người/chứng kiến/approval giả.
- Hash working copy khác original có thể hợp lệ nếu transformation được ghi.
- Missing event không được “khôi phục” bằng suy đoán.
- Chain log không tự chứng minh admissibility hoặc compliance.

## Confidence framework

Tách các dimension: classification, OCR, layout, extraction, normalization, validation, match và overall.

Mỗi dimension có thể dùng:

```yaml
availability: AVAILABLE | UNAVAILABLE | NOT_APPLICABLE
raw_score: number | null
scale: string | null
band: HIGH | MEDIUM | LOW | UNKNOWN
basis: string
```

Không tạo raw score khi engine không cung cấp. Numeric score nội bộ chỉ dùng khi methodology, calibration/threshold và limitations được ghi. Nhiều cùng-source signals không tự tăng confidence.

## Critical fields

Theo document/use case, critical có thể gồm document/vendor/customer/tax/account/PO/contract number, dates, currency, total/tax/line amount/quantity, signature/approval presence hoặc clause/obligation material.

Critical failure phải hiện trong `critical_field_failures`; overall summary không che status. Nếu intended use thay đổi, critical-field set phải được review.

## Human-review triggers

- critical confidence low/unknown hoặc field illegible/obscured;
- engine disagreement hoặc candidate conflict;
- ambiguous date/locale/currency/sign;
- cross-field validation fail;
- missing/truncated/reordered page hoặc incomplete table;
- bank/tax/identity conflict;
- handwritten material correction;
- material clause/obligation/addendum relationship;
- many-to-many/ambiguous match hoặc amount không reconcile;
- exact investigation transcription/redaction release.

## Review queue contract

```yaml
review_item_id: string
document_id: string
evidence_id: string | null
object_reference: string
issue_type: string
raw_value: any
candidate_values: [any]
source_page: integer | null
source_region: object | null
reason_for_review: string
decision_impact: string
risk_level: HIGH | MEDIUM | LOW | UNRATED
reviewer: string | null
review_decision: string | null
reviewed_value: any
review_note: string | null
reviewed_at: datetime | null
second_review_required: boolean
approval_status: PENDING | APPROVED | REJECTED | NOT_APPLICABLE
```

Allowed decisions: accept, correct, mark illegible/not present/not applicable/conflicting, request better copy, escalate, require specialist review. “Reject document” cần scope/owner; không đồng nghĩa fake/invalid.

Human correction thêm version/audit trail và reviewer source; không xóa machine candidates.

## Fact/inference classification

Phân biệt: verified document fact, extracted source text, OCR-derived text, metadata-based statement, source-based statement, management/third-party representation, machine classification, assumption, professional inference, conflicting evidence, unresolved issue, human-verified value và preliminary conclusion.

Skill không tự tạo `FINAL_APPROVED_CONCLUSION`. `VERIFIED` chỉ dùng đúng phạm vi action/source review được ghi, không phải universal truth.

## Investigation support

Giữ supporting và contradictory evidence; không hợp nhất contradiction im lặng. Dùng pseudonymized/internal IDs khi output không được phép nêu danh tính. Không tự mở rộng source, gọi người là suspect, xác định deception, fraud, authenticity hoặc culpability.

Evidence package outbound giữ `DRAFT — REQUIRES HUMAN APPROVAL` và recipient/classification/authorization rõ.

## QA

- mọi evidence/document/field relationship resolve;
- original/working/redacted/derived roles nhất quán;
- hash method/basis đúng object;
- no invented custody/review/approval;
- confidence unknown không biến thành zero/high;
- critical failures và contradictions visible;
- review correction giữ history;
- restricted data không rò sang unrestricted artifact.
