# Field, table và contract extraction

## Nguyên tắc chung

Extraction tạo record có provenance, không tạo fact đã xác minh. Chọn schema/profile và grain trước; giữ raw source representation, normalized candidate, status, validation và review riêng.

Không trích một danh sách field cố định cho mọi tài liệu. Chỉ tạo field có ý nghĩa theo schema và intended decision; field expected nhưng không có/không đọc được phải có status phù hợp nếu absence material.

## Field workflow

1. Xác định document type/profile/version và critical fields.
2. Tìm candidate theo native/OCR/layout/vision output; giữ page/region/snippet.
3. Ghi raw value chính xác, không tự sửa.
4. Parse/normalize bằng rule có version và locale; failure không làm mất raw.
5. Chạy field-level và cross-field rules.
6. So sánh source khác chỉ khi chúng cùng grain/semantics.
7. Tạo review item nếu critical/ambiguous/conflicting/low-confidence.
8. Chỉ ghi `HUMAN_VERIFIED` khi reviewer, decision, time và source/action được ghi thực.

## Confidence và status

Mỗi confidence dimension có `availability`, optional raw score/scale, band và basis. Không quy đổi score giữa engines khi scale khác. Critical field status có thể buộc overall readiness xuống review/block dù aggregate cao.

Giữ orthogonal semantics khi machine contract hỗ trợ:

- presence: present/not present/not applicable/illegible/obscured/redacted;
- interpretation: direct/ambiguous/conflicting/inferred/derived;
- verification: unverified/machine validated/human verified;
- review: not required/required/pending/completed.

Canonical `field_status` trong SKILL là primary state; `status_flags` có thể giữ dimensions bổ sung.

## Numeric và date rules

- Dùng decimal string ở canonical JSON để tránh binary-float drift; chuyển `Decimal` khi tính.
- Ghi raw separators, sign/parentheses, scale, unit và currency.
- `quantity × unit_price` chỉ so với line amount khi units/price basis/currency tương thích.
- Tax rule phải biết tax base, rate, rounding basis và inclusion/exclusion.
- Amount-in-words là corroborating field; mismatch tạo warning/review, không tự sửa amount.
- Ngày chỉ normalize ISO khi locale/format đủ rõ; giữ timezone cho datetime.
- Due date derivation phải ghi input payment terms, business-calendar rule và status `DERIVED`.

## Table và line-item model

Mỗi physical/logical table có `table_id`, document/page regions, columns, header mapping, method và warnings. Mỗi item row có:

```yaml
line_item_id: string
document_id: string
table_id: string
source_page: integer
source_row: string
sequence: string
row_type: ITEM | SUBTOTAL | TAX | DISCOUNT | CHARGE | FOOTNOTE | GRAND_TOTAL | CONTINUATION | UNKNOWN
raw_cells: object
normalized_fields: object
row_status: string
row_confidence: string
reconciliation_key: string | null
continuation_of: string | null
```

Rules:

- bỏ repeated header khỏi item population bằng evidence-backed rule;
- continuation row phải link explicit, không merge vì “trông giống”;
- page subtotal không cộng lần hai vào grand total;
- blank cell, ditto mark, merged cell, wrapped description và footnote giữ semantics;
- line-item count, included/excluded row types và page coverage phải reconcile;
- không split/merge item nếu không giữ relationship keys và raw cells.

## Invoice profile

Khi xuất hiện và áp dụng, capture:

- identity/status: invoice number/type/symbol/form, issue/invoice/due date, original/copy/replacement/adjustment, authority/lookup code;
- references: PO, contract, delivery/GRN, payment terms, source system;
- seller/buyer: legal/trade name, code, tax/registration ID, address/contact, bank/account/branch;
- line items: code/name/specification/batch/lot/serial/UOM/quantity/unit price/gross/discount/taxable/tax/total, PO/GRN/contract line, project/cost center/location;
- totals: subtotal, discounts, tax by rate, freight/charge/withholding/rounding, before/after tax, paid/due và amount in words;
- approval/presence: prepared/checked/approved, representative, signature/stamp indication và dates.

Không xác nhận tax compliance, invoice validity, signature hoặc bank ownership.

## Purchase-order profile

Capture PO/date/version/status, requisition/quotation/contract refs, buyer/vendor/code, ship/bill-to/location/contact, payment/delivery/incoterm/currency/exchange-rate, approval/budget/cost center/project/plant, line item ordered quantity/UOM/price/discount/tax/value/promised date và total.

Amendment/cancellation là version/state relationship; không overwrite prior PO.

## Goods-receipt/delivery/acceptance profile

Capture GRN/receipt/posting date, PO/delivery/invoice refs, vendor/receiving entity, plant/warehouse/storage, vehicle/driver/receiver/inspector, item/batch/lot/serial, ordered/delivered/accepted/rejected/damaged quantity, UOM, quality/inspection, weights/timestamps, exception note và signature/stamp presence.

Received quantity không tự chứng minh acceptance hoặc service completion; giữ document type và observed terms.

## Payment/bank profile

Capture request/voucher/payment/value/posting dates, payer/beneficiary/banks/accounts/branch/SWIFT, payment/transaction/bank references, linked invoice/PO/contract refs, amount/currency/exchange-rate/fee/withholding/net, purpose, approval/authorization, signature presence, bank confirmation/reversal/settlement status.

Bank/account fields là sensitive; masked output vẫn phải liên kết tới restricted raw record. Không tự xác nhận account ownership hoặc payment finality.

## Receipt/expense profile

Capture receipt/merchant/tax/address/date/time, employee/claim/category/description, line amounts/tax/tip/total/currency, payment method/card-last-four, travel/project/cost center/approver và image-quality/duplicate-fingerprint candidates.

Multiple receipts trong một ảnh cần segmentation records và uncertainty; không ghép totals giữa logical documents.

## Contract extraction

### Contract identity và versions

Capture contract ID/number/title/type, master/tender refs, version/addendum, execution/effective/start/expiry/renewal/notice/termination dates, governing language và raw governing-law/dispute text. Không legal interpretation.

Liên kết base/addendum/schedule bằng explicit `document_link`; changed field/clause tạo supersession relationship với source pages. Không rewrite base record thành “current contract” nếu chưa xác định precedence.

### Parties

Capture legal/trade names, registration/tax IDs, addresses, representatives/titles/signatory indications, contacts, roles, parent/guarantor/subcontractor. Party extraction không xác nhận authority hoặc corporate identity.

### Clause register

Mỗi clause gồm ID, contract/document, number/title/type, raw/normalized text, page range/snippet, affected party, domain, amount/date/trigger/cross-reference, amended-by/supersedes, extraction confidence, human/legal review status.

Clause type có thể gồm commercial, SLA/service credit/penalty, warranty, confidentiality/data/security, IP, indemnity/liability/insurance, audit/records, anti-bribery/sanctions/compliance, assignment/change, force majeure, termination/suspension/dispute. Taxonomy là classification, không legal conclusion.

### Obligation register

Mỗi obligation cần:

- obligated/beneficiary party;
- action và object/deliverable;
- trigger/condition/start/due rule/recurrence/notice;
- SLA/threshold/amount/currency;
- evidence/approval/dependency;
- source clause/page/snippet;
- consequence/remedy raw text;
- confidence, status và human review.

Không tự đánh dấu compliant, breached, enforceable, overdue hoặc waived nếu chưa có operational evidence và authorized rule/owner.

### Signature/execution presence

Capture blocks, party, printed name/title/date, signature/stamp/witness/notary/e-sign indication và incomplete block. Dùng `PRESENT/NOT_PRESENT/ILLEGIBLE/UNKNOWN`; không kết luận executed/valid chỉ từ detection.

## Cross-field validation library

Chỉ chạy rule có input/rounding/locale basis:

- line sum ↔ subtotal;
- tax base × rate ↔ tax amount;
- subtotal − discount + tax + charges ↔ total;
- quantity × unit price ↔ line amount;
- page totals ↔ grand total;
- words ↔ numeric amount;
- due date ↔ payment terms;
- currency consistency;
- buyer/seller role consistency;
- PO/reference format;
- account consistency trong package;
- signature date vs document date khi business rule yêu cầu.

Kết quả `NOT_TESTED` nếu thiếu rule/input; không dùng `PASS` vì không phát hiện lỗi.

## Human-review payload

Review item cần document/evidence/field/line/clause ID, issue type, raw và candidates, page/region/image reference, reason/impact/risk, expected decision vocabulary, reviewer/second-review/approval status. Correction thêm reviewed value; không xóa extracted candidate hoặc audit trail.
