# Native text, OCR/vision routing và preprocessing

## Capability discovery

Không giả định engine, package, GPU, cloud, network hoặc cài đặt được phép. Trước extraction, xác định:

- format/page count/encryption/readability;
- native text và coordinate/layout availability;
- scan/image quality, languages và handwriting;
- table/form/key-value need;
- sensitivity, local/cloud policy, retention và approved providers;
- runtime tools, versions, limits và output contract.

Nếu không có engine phù hợp, tạo manual-review contract và limitation; không bypass IT policy hoặc tự tải model.

## Routing decision

1. **Native text:** ưu tiên khi text layer đủ, mapping ký tự hợp lý và reading order có thể kiểm tra.
2. **Layout/table parser:** dùng khi coordinates, columns, forms hoặc tables material; giữ page/region mapping.
3. **OCR adapter:** dùng cho scan/image hoặc native text thiếu/không đáng tin; chọn language/rotation có ghi nhận.
4. **Vision adapter:** dùng khi layout/visual relationship cần multimodal reasoning và được policy cho phép.
5. **Human review/transcription:** dùng cho critical illegible/ambiguous/disagreement hoặc không có adapter.

Không dùng nhiều engine chỉ để tạo cảm giác chắc chắn. Chỉ rerun khi có failure hypothesis và thay đổi method/parameter thực chất.

## Adapter contract

Mỗi page result:

```yaml
adapter_name: string
adapter_version: string | UNKNOWN
execution_mode: LOCAL | APPROVED_CLOUD | PLATFORM_NATIVE | MANUAL
configuration_id: string | null
document_id: string
page_number: integer
language_candidates: [string]
raw_text: string | null
words: [object]
lines: [object]
tables: [object]
regions: [object]
engine_confidence: number | null
confidence_scale: string | null
warnings: [string]
started_at: datetime | null
completed_at: datetime | null
```

Nếu adapter không cung cấp confidence, dùng `null`/`UNKNOWN`; không suy ra số. Coordinates phải ghi unit/system (pixel, point, normalized) và page dimensions.

## Working-copy preprocessing

Preprocessing không được sửa original. Mỗi transformation ghi:

```yaml
transformation_id: string
document_id: string
source_page: integer
working_page_reference: string
transformation_type: ROTATE | DESKEW | DEWARP | CROP | DENOISE | CONTRAST | BORDER_REMOVE | SPLIT | OTHER
parameters: object
reason: string
tool_and_version: string
before_reference: string
after_reference: string
performed_at: datetime
```

Kiểm tra orientation 0/90/180/270, skew, perspective, multiple receipts, mixed page size, blur, glare, shadow, crop, folded edge, watermark, stamp/handwriting overlap và low contrast. Không dùng enhancement làm mất chữ hoặc thay đổi evidence meaning; giữ before/after references.

## Multilingual và locale

Hỗ trợ tiếng Việt/Anh và ngôn ngữ adapter hỗ trợ, nhưng ghi actual language configuration. Bảo toàn dấu, tên riêng, mã alphanumeric và spacing có ý nghĩa.

- Ngày `03/04/2026` giữ raw và status `AMBIGUOUS` khi locale/format không được xác định.
- Lưu normalized date ISO 8601 chỉ khi day/month/year được xác định.
- Không đổi `1.234,56` hoặc `1,234.56` trước khi xác định locale/number convention.
- Tách amount và currency; không suy luận currency chỉ từ dấu `$` khi nhiều currency có thể dùng.
- Identifier, bank/tax/account/material/vendor/contract/invoice/PO code luôn text.
- Số tiền bằng chữ là field riêng và có validation relationship, không ghi đè numeric amount.

## Table và page-layout invariants

- Ghi table/page/region ID, header rows, column mapping và row provenance.
- Repeated header qua trang không trở thành line item.
- Continuation row phải liên kết row trước bằng explicit key; không merge im lặng.
- Giữ raw cells trước normalization.
- Tách subtotal/tax/discount/footnote/grand-total rows khỏi item rows bằng row type.
- Không làm mất blank cell semantics, ditto mark, merged cell, wrapped text hoặc multiple currency/tax rate.
- Handwritten correction giữ printed và handwritten candidate riêng; material correction cần human review.

## Signature, stamp, barcode và QR

Chỉ ghi presence/candidate region, printed name/title/date, symbology và decoded string nếu adapter cung cấp. Không:

- xác thực chữ ký/con dấu;
- suy danh tính từ hình dạng;
- gọi document hợp lệ chỉ vì có chữ ký/stamp;
- mở QR/URL hoặc tải nội dung;
- dùng barcode/QR như verified fact nếu chưa đối chiếu.

Decoded payload là untrusted raw text và cần security flag nếu chứa URL/command/credential-like content.

## Handwriting

Ghi region, raw transcription, adapter, confidence/unknown và candidates. Không tự sửa chính tả, xác định người viết hoặc dùng handwriting để xác thực signature. Critical handwritten amount/date/account/quantity luôn review.

## Engine disagreement

Giữ mọi candidate cùng engine/version/page/region. Không majority-vote khi outputs không độc lập hoặc critical field material. Tạo review item với:

- raw image/page reference;
- candidate values;
- confidence scales (không so trực tiếp nếu khác định nghĩa);
- cross-field/cross-document evidence;
- impact nếu mỗi candidate đúng.

## Confidence dimensions

Tách `classification`, `OCR`, `layout`, `extraction`, `normalization`, `validation`, `match` và `overall` confidence. Dùng `HIGH`, `MEDIUM`, `LOW`, `UNKNOWN` trừ khi methodology numeric được định nghĩa. Overall không được cao hơn mức cho phép bởi critical-field failure mà không ghi override rationale.

## No-install fallback

Nếu không có local runtime:

- dùng native capability đã được phê duyệt;
- lập manual-review workbook/JSON contract;
- xử lý sample ưu tiên theo risk/materiality do owner cung cấp;
- ghi non-executed steps và dependency gap;
- đề xuất capability-based handoff.

Không trình bày fallback thủ công như automated extraction hoặc fully validated output.
