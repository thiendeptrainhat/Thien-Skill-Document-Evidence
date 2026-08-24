# Structured output, workbook, redaction và handoff

## Canonical package trước presentation

Canonical JSON/JSONL giữ document/evidence/field/table/clause/obligation/link/reconciliation/discrepancy/review/custody/redaction/run objects và foreign IDs. Excel/CSV là views/deliverables, không thay source/canonical package.

Mỗi export ghi package/run/schema/config versions, row counts, source references, created time/tool version, exclusions/warnings và SHA-256 khi cần reproducibility.

## Workbook standard

Workbook `.xlsx` không macro, không external link không cần thiết, không embedded executable và không merged cells trong data sheets. Mỗi applicable data sheet dùng one-row-one-object grain, header/filter/freeze pane, typed number/date columns, identifier text, raw/normalized/status/provenance/review fields và unique table name.

Các sheet chuẩn, chỉ tạo khi có ý nghĩa:

1. `00_README`
2. `01_DOCUMENT_INDEX`
3. `02_DOCUMENT_FIELDS`
4. `03_LINE_ITEMS`
5. `04_PARTIES`
6. `05_DATES_REFERENCES`
7. `06_TAX_CHARGES`
8. `07_PAYMENT_BANK`
9. `08_CONTRACT_CLAUSES`
10. `09_CONTRACT_OBLIGATIONS`
11. `10_SIGNATURE_APPROVAL`
12. `11_DOCUMENT_LINKS`
13. `12_RECONCILIATION`
14. `13_DISCREPANCIES`
15. `14_EVIDENCE_REGISTER`
16. `15_CHAIN_OF_CUSTODY`
17. `16_FIELD_DICTIONARY`
18. `17_HUMAN_REVIEW`
19. `18_QA_RESULTS`
20. `19_RUN_LOG`

`README`, index, field dictionary và run log có thể luôn có trong template. Không tạo hàng giả để tránh sheet rỗng.

## Type và display rules

- IDs/accounts/tax/material/PO/invoice/contract/reference codes: text, giữ leading zero.
- Numeric amount/quantity/percentage: typed number khi canonical decimal có thể chuyển chính xác trong Excel precision; raw decimal string vẫn được giữ hoặc traceable.
- Date/datetime: typed value chỉ khi unambiguous; format `yyyy-mm-dd` hoặc `yyyy-mm-dd hh:mm:ss`.
- Amount và currency, quantity và UOM ở cột riêng.
- Không dùng locale-specific punctuation trong number-format code.
- Source page/region/document/evidence/run ID luôn có ở table material.

## Formula-injection protection

Untrusted string bắt đầu bằng `=`, `+`, `-` hoặc `@` không được ghi như formula. Ghi literal an toàn (ví dụ apostrophe/display-safe encoding theo library), giữ `raw_value` trong canonical package và field/column `formula_injection_flag: true`.

Không để hyperlink/URL từ source thành active link mặc định. Workbook formula chỉ dùng cho audit-friendly calculations do builder tạo; không lấy formula từ input. Không có external workbook references.

## Field dictionary

Mỗi column có sheet, column, business definition, grain, data type, required/optional, null/status semantics, normalization, source/provenance, validation rule, sensitivity/masking và example synthetic hoặc empty representation.

## Volume và row limits

Không cắt record để vừa Excel. Nếu bất kỳ sheet vượt giới hạn/practical usability:

1. tạo control workbook với summary, counts, dictionary, file linkage, exceptions/sample review theo approved rule;
2. xuất detailed CSV/JSONL/Parquet hoặc database handoff;
3. ghi exact row counts/hashes và linkage;
4. nếu sidecar/output path không được phép, `BLOCKED` trước khi ghi.

Không gọi một sample là full population.

## Workbook QA

- file mở/import được;
- sheet/table names hợp lệ và không trùng;
- expected vs exported counts/totals tie;
- identifiers/leading zeros preserved;
- no input formula/external link/VBA;
- no merged data cell;
- headers readable, filter/freeze panes và number/date formats đúng;
- formula error scan không có `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#N/A` ngoài test cố ý;
- visual render của mọi sheet có dữ liệu không bị clipping nghiêm trọng;
- restricted raw fields không xuất hiện ở unrestricted workbook.

## Redaction

Original luôn giữ nguyên. Redaction tạo derivative và log; full/partial masking, pseudonymization, role/page/field redaction phải dựa vào recipient/purpose/approval.

Target có thể gồm ID/passport, bank/card/account, phone/email/address, salary/health, whistleblower/investigation identity, signature image, sensitive price, credential/token/security detail.

Redaction phải loại content khỏi output representation, không chỉ phủ một lớp nhìn thấy. Cần kiểm tra copy/search/extract/metadata/layer/annotation/attachment theo format. Nếu runtime không chứng minh được removal, chỉ tạo redaction specification/log và ghi `NOT_EXECUTED`; không tuyên bố đã redacted.

Redaction log:

```yaml
redaction_id: string
source_document_id: string
output_document_id: string | null
page_and_region: object
category: string
method: string
reason_and_policy: string
mapping_reference: string | null
performed_by: string | null
performed_at: datetime | null
reviewed_by: string | null
approval_reference: string | null
verification_status: NOT_EXECUTED | PENDING | VERIFIED | FAILED
```

Mapping file là restricted và không nằm trong general disclosure package. Không tự gửi redacted set.

## Handoff profiles

- **Data Engineering:** canonical package, schemas/dictionary, IDs/provenance, counts, quality/unresolved items, sidecar requirements.
- **Analytics:** structured document/line/payment data, relationships/evidence refs, coverage/quality, unresolved matches; không fraud labels.
- **Internal Audit:** expected/sample evidence, extracted attributes, approvals/presence, match/discrepancy, reliability/missing evidence; không audit conclusion.
- **Investigation:** case-gated register/custody, exact/contradictory values, chronology-ready dates, source snippets, original/working/redacted status; no allegation conclusion.
- **Legal:** raw clause/obligation/version/source text và unresolved interpretations; no legal opinion.
- **QA:** methodology/config/schema, source mapping, workbook/canonical package, counts/confidence/review/security/limitations.
- **Reporting:** chỉ QA-cleared structured outputs, definitions và limitations; reporting không đổi extracted values.

Mỗi handoff dùng contract ở `architecture-boundaries-and-workflow.md`, giữ data classification/recipient/approval và status tối đa `READY_FOR_HUMAN_REVIEW`.

## Script behavior

Package export dùng gate hai bước, không bỏ qua full schema contract:

1. chạy `validate_records.py PACKAGE.json --schema common/extraction-package.schema.json --schema-root SCHEMAS --output REPORT.json` dưới authorized root;
2. chạy `build_workbook.mjs --package PACKAGE.json --schema-validation-report REPORT.json --output RESULT.xlsx`.

Builder phải đối chiếu PASS status, zero errors, input SHA-256 và bundled schema SHA-256 trước write. Sau đó giữ stdout/dry-run khi phù hợp, atomic write, no-overwrite mặc định, deterministic sheet/row order, typed normalized amount/unambiguous ISO date, identifier text, formula-safe source text và row-count checks. Dependency thiếu phải fail rõ; không tự cài package hoặc tạo file giả. Vì XLSX exporter là runtime adapter, kiểm tra OOXML cuối phải xác nhận freeze pane, filter, no formula/macro/external relationship và visual readability. Nếu host exporter không giữ freeze/filter, chạy `python3 scripts/finalize_workbook.py --root AUTHORIZED_DIR --input INPUT.xlsx --output FINAL.xlsx`; adapter standard-library này luôn tạo output khác input, no-overwrite mặc định và từ chối package active/không an toàn. Nếu finalization hoặc visual QA không PASS thì đánh dấu QA failure, không tuyên bố hoàn tất.
