# Classification, schema routing và common field contract

## Taxonomy có thể mở rộng

| Domain | Document types tiêu biểu |
|---|---|
| Procurement/Payables | Requisition, RFQ, quotation, bid evaluation, PO, contract/addendum, delivery note, packing list, GRN, acceptance, invoice/tax invoice, debit/credit note, payment request/approval, bank/remittance advice |
| Sales/Receivables | Sales order, delivery/proof of delivery, sales invoice, customer receipt/confirmation, return/credit note |
| Inventory/Logistics | Goods issue/receipt/transfer, warehouse slip, weighbridge ticket, transport document, bill of lading, airway bill, customs declaration, inspection/quality certificate |
| Finance/Banking | Bank statement/confirmation, cash receipt/payment voucher, journal voucher, reconciliation statement, loan/interest/FX advice |
| HR/Expense | Employment contract, payroll, timesheet, expense claim, receipt, travel/overtime authorization, attendance, employee master form |
| Legal/Contractual | Master/service/supply/lease/loan agreement, NDA, appendix, change order, termination/settlement/legal notice, board/management approval |
| Investigation/Evidence | Submission, screenshot, email/chat/log export, transaction evidence, custody form, external confirmation, forensic report supplied by an authorized source |

Taxonomy label không xác thực nội dung hoặc status pháp lý. Khi một file chứa nhiều logical documents, ghi segmentation candidates và uncertainty; không ép một `document_id` nếu business grain cần nhiều logical records.

## Schema route

| Classification | Schema mặc định |
|---|---|
| Invoice, tax invoice, debit/credit invoice | `schemas/document-types/invoice.schema.json` |
| Purchase order/amendment | `purchase-order.schema.json` |
| GRN, receipt, warehouse/delivery acceptance | `goods-receipt.schema.json` hoặc generic + type extension |
| Payment request/voucher, bank/remittance advice | `payment-document.schema.json` |
| Receipt/expense claim | `receipt-expense.schema.json` |
| Contract/master/addendum | `contract.schema.json` với version relationship |
| Không đủ hoặc type khác | `generic-document.schema.json` |

Schema chuyên biệt mở rộng common `$defs`; không sao chép semantics mâu thuẫn. Chọn schema version tại extraction-run start và ghi vào từng record.

## Schema lifecycle

- Version dùng SemVer; breaking field/enum/meaning change tăng major.
- Thêm optional field không đổi semantics có thể tăng minor.
- Fix description/validation không đổi contract có thể tăng patch.
- Không sửa output cũ tại chỗ; giữ schema version và migration/normalization log.
- Unknown field từ source có thể đi vào `extensions` với namespace; không tự đổi common model.
- Khi document không khớp required discriminator, giữ generic/unclassified và review.

## Common document record

Tối thiểu hỗ trợ:

```yaml
document_id: string
evidence_id: string | null
package_id: string | null
document_type: string
document_subtype: string | null
document_number: string | null
document_date: string | null
language: [string]
currency: string | null
parties: [object]
references: [object]
total_amount: number | null
total_pages: integer | null
page_completeness_status: string
source_reference: string
sha256: string | null
version: string | null
superseded_by: string | null
duplicate_group_id: string | null
extraction_status: string
overall_confidence: string
review_status: string
data_classification: string
```

`null` chỉ dùng cùng semantics từ schema; field material vắng/không đọc được phải có extracted-field record/status nếu quyết định cần phân biệt.

## Extracted field contract

Mỗi field gồm:

- identity: `field_id`, `document_id`, optional `evidence_id`, `schema_id`, `schema_version`;
- semantics: `field_name`, label/group, `data_type`, unit/currency;
- values: `raw_value`, `normalized_value`, `display_value`;
- status: controlled `field_status`;
- provenance: page, region/bounding box coordinate system, snippet, method, adapter/run;
- confidence: OCR/extraction/normalization/validation/overall hoặc `null/UNKNOWN`;
- validation: rules applied, result, messages;
- review: required, reviewer, reviewed value/time/decision;
- notes/assumptions without changing source value.

Data types: `TEXT`, `INTEGER`, `DECIMAL`, `PERCENTAGE`, `CURRENCY_AMOUNT`, `DATE`, `DATETIME`, `BOOLEAN`, `IDENTIFIER`, `BANK_ACCOUNT`, `TAX_IDENTIFIER`, `PHONE`, `EMAIL`, `ADDRESS`, `QUANTITY`, `UNIT_OF_MEASURE`, `CLAUSE_TEXT`, `REFERENCE`, `LIST`, `TABLE`, `JSON_OBJECT`.

## Status semantics

| Status | Nghĩa |
|---|---|
| `PRESENT` | Value quan sát được; chưa tự là verified |
| `NOT_PRESENT` | Field được tìm theo scope nhưng không thấy; khác blank OCR |
| `NOT_APPLICABLE` | Schema/rule xác định field không áp dụng |
| `ILLEGIBLE` / `PARTIALLY_ILLEGIBLE` | Source có vùng liên quan nhưng không đọc đủ |
| `OBSCURED` | Che bởi stamp, crop, glare, overlay hoặc vật cản |
| `REDACTED` | Source/working copy cung cấp đã che hoặc output bị che |
| `CONFLICTING` | Có nhiều source/candidate trái nhau |
| `AMBIGUOUS` | Một raw value có nhiều cách hiểu hợp lý |
| `INFERRED` | Suy luận được nêu rõ, không phải source value |
| `DERIVED` | Kết quả phép tính/rule có input references |
| `UNVERIFIED` | Chưa human/source validation |
| `VERIFIED` | Reviewer/source validation thực sự được ghi |
| `HUMAN_REVIEW_REQUIRED` | Không được dùng như settled value cho intended decision |

## Identifier và normalization

- Giữ invoice, PO, contract, vendor/material/employee/tax/account/reference code dưới dạng string.
- Không trim/collapse punctuation/spacing nếu có thể ảnh hưởng identity; nếu tạo match key, giữ raw và rule.
- Casefold, Unicode normalization, diacritic removal, separator removal hoặc zero-padding chỉ tạo derived match key có version.
- Date normalization yêu cầu locale/format evidence.
- Amount normalization yêu cầu decimal/thousand convention, sign, currency và scale.
- Party normalization không tự chứng minh legal-entity identity.

## Document-type coverage

- **Invoice:** header/status, seller/buyer, references, currency/exchange rate, line items, tax/charges/totals, amount in words, approval/signature presence.
- **PO:** requisition/quotation/contract refs, buyer/vendor, ship/bill-to, terms, approval/version, budget/cost center/project/plant, line items và total.
- **Goods receipt:** PO/delivery/invoice refs, warehouse/location/receiver/inspector, batch/lot/serial, ordered/delivered/accepted/rejected/damaged quantity, quality/weight và presence indicators.
- **Payment:** dates, payer/beneficiary/bank/accounts, transaction/bank refs, related invoice/PO/contract, gross/fee/withholding/net, purpose, approval/reversal/settlement.
- **Receipt/expense:** merchant/tax/date/time/employee/claim/category, item amounts/tax/tip/total/currency/payment method/card-last-four, travel/project/cost center/approver và image-quality/duplicate fingerprint.
- **Contract:** identity/version/dates/language/law/dispute raw text, parties/roles, commercial/operational/legal clause groups, signature blocks, clause and obligation registers. Không legal conclusion.

## Schema drift và extension

Khi source chứa field mới:

1. Giữ raw label/value/provenance trong generic extension.
2. Xác định có tương đương field hiện hữu không; không map chỉ vì tên giống.
3. Ghi proposed field, type, status/null semantics, validation và affected schemas.
4. Chỉ nâng schema sau review; không backfill output cũ âm thầm.

## Machine-readable files

JSON Schema Draft 2020-12 trong `schemas/` là contract kiểm tra structure/type/enum. Nó không chứng minh semantic correctness, source authenticity, legal validity hoặc business acceptability. `scripts/validate_records.py` có thể dùng validator runtime sẵn có; nếu dependency thiếu, dừng với hướng dẫn rõ thay vì bỏ validation.
