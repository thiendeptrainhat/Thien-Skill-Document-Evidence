# Handoff — Kế hoạch cập nhật Thien Skill Document Evidence

## 1. Trạng thái handoff

- Ngày lập: 2026-08-27
- Repository: `https://github.com/thiendeptrainhat/Thien-Skill-Document-Evidence`
- Nhánh hiện tại: `main`
- Commit nền: `42489dc` — `docs: expand installation and feature guide`
- Phiên bản hiện tại: `1.0.0`
- Trạng thái kế hoạch: `DRAFT — CHỜ NGƯỜI DÙNG ĐÁNH GIÁ LẠI`
- Trạng thái triển khai: `NOT_STARTED`
- Không xem tài liệu này là phê duyệt để sửa skill, đổi version, commit, tag hoặc push.

## 2. Mục đích của handoff

Tài liệu này chuyển đầy đủ bối cảnh và kế hoạch sang một phiên làm việc mới. Phiên mới cần đánh giá lại kế hoạch với người dùng trước khi triển khai, không tự suy đoán các lựa chọn còn mở.

Skill phải tiếp tục được phát triển theo hướng:

- một skill duy nhất;
- dễ cài đặt trên Claude, ChatGPT và Codex;
- core workflow không phụ thuộc cứng vào tên tool, runtime, OCR engine hoặc cloud vendor cụ thể;
- tận dụng năng lực native của host trước;
- giữ các script deterministic hiện có như công cụ hỗ trợ tùy chọn, không biến chúng thành dependency bắt buộc trên mọi nền tảng.

## 3. Ba mục tiêu bắt buộc của người dùng

1. Chuyển đổi tài liệu từ PDF, ảnh scan và ảnh chụp sang Word, Excel, PowerPoint, JSON và Markdown.
2. Chuẩn bị dữ liệu đầu vào cho hệ thống RAG dưới dạng Markdown hoặc định dạng tương đương.
3. Đọc receipt, invoice, hợp đồng, PO, PR, GRN, đề nghị thanh toán và sao kê ngân hàng từ thư mục dự án hoặc file đính kèm; tạo danh sách reconciliation trên Excel để thực hiện three-way, four-way hoặc matching tương đương.

## 4. Kết luận phân tích đã thống nhất

### 4.1 Năng lực native của nền tảng

Không cần đóng gói OCR/layout/vision engine riêng làm dependency bắt buộc.

Quy tắc đích:

1. Dùng native PDF/image/vision của host trước.
2. Dùng text extraction hoặc render trang thành ảnh nếu host cần.
3. Chỉ dùng external OCR/document-processing service khi native route không khả dụng, chất lượng không đạt hoặc người dùng chủ động yêu cầu.
4. Việc người dùng đính kèm file vào host hiện tại được xem là cho phép xử lý bằng native capability của chính host đó; không hỏi lại về native processing.
5. Phải xin phép trước khi gửi file hoặc dữ liệu sang dịch vụ thứ ba ngoài host hiện tại.

Nguồn nền tảng đã đối chiếu:

- OpenAI Responses API nhận text, image hoặc file input: `https://developers.openai.com/api/reference/cli/resources/responses/methods/create`
- ChatGPT PDF Visual Retrieval phụ thuộc sản phẩm, gói và vị trí tải file: `https://help.openai.com/en/articles/10416312-visual-retrieval-with-pdfs-faq`
- Claude PDF support kết hợp text extraction và ảnh trang nhưng có giới hạn theo nền tảng/cấu hình: `https://platform.claude.com/docs/en/build-with-claude/pdf-support`
- Claude file upload và PDF processing có giới hạn file/page và khác biệt giữa PDF với non-PDF: `https://support.claude.com/en/articles/8241126-upload-files-to-claude`

### 4.2 Cài skill không tự cấp quyền hoặc tool

- Codex có thể duyệt thư mục dự án khi filesystem và authorization cho phép.
- ChatGPT hoặc Claude không được giả định có quyền duyệt một thư mục local tùy ý.
- Khi host chỉ thấy attachments/Project Files, skill chỉ được tuyên bố coverage đối với các file thực sự truy cập được.
- Khả năng hiểu PDF/ảnh không đồng nghĩa host luôn tạo được DOCX, XLSX hoặc PPTX.
- Khi host không có file-creation capability phù hợp, skill phải tạo canonical JSON/Markdown nếu có thể, ghi limitation và không tạo file giả bằng cách đổi extension.

### 4.3 Thành phần bắt buộc và không bắt buộc

Phải bổ sung vào skill:

- capability-aware input and output routing;
- ba task profile gắn trực tiếp với ba mục tiêu;
- output contract và QA cho DOCX, XLSX, PPTX, JSON và Markdown;
- RAG-source package trung lập nền tảng;
- schema/profile cho Purchase Requisition, Payment Request và Bank Statement;
- reconciliation profile cho các chuỗi nghiệp vụ yêu cầu;
- provenance tối thiểu, raw/normalized separation, review queue và exception handling;
- formula-injection protection, original-preservation và document-content-as-untrusted-data;
- acceptance test cho hành vi và artifact thực tế.

Không đưa vào core như dependency bắt buộc:

- OCR model riêng;
- cloud OCR vendor cụ thể;
- embedding model;
- vector database hoặc RAG connector cụ thể;
- thư viện DOCX/PPTX cụ thể;
- monolithic batch runner bắt buộc;
- tolerance nghiệp vụ hard-code;
- xác thực chữ ký/chứng từ;
- kết luận fraud, pháp lý, audit hoặc control effectiveness.

Chỉ kích hoạt khi phù hợp:

- chain of custody đầy đủ;
- investigation gate;
- redaction;
- forensic-style integrity checks;
- field-level bounding boxes;
- dual-engine comparison;
- chunked JSONL;
- external processing;
- batch automation dành riêng cho host có filesystem.

## 5. Kiến trúc đích

```text
Folder / Attachments
        |
        v
Capability detection + authorized source inventory
        |
        v
Native PDF/Image/Vision của host
        |
        v
Canonical document package
        |
        +--> Convert --> DOCX / XLSX / PPTX / JSON / MD
        |
        +--> RAG --> document.md + metadata.json + manifest.json
        |               + optional chunks.jsonl
        |
        +--> Reconcile --> three-way / four-way / custom --> XLSX
```

Nguyên tắc kiến trúc:

- Một canonical package làm nguồn chung cho các nhánh output.
- Không cần một full layout IR bắt buộc cho mọi tác vụ.
- Canonical representation cần giữ tối thiểu heading, paragraph, table, image/caption, page/source locator và reading order khi host cung cấp được.
- Bounding box chỉ bắt buộc khi use case hoặc adapter hỗ trợ và cần đến độ chính xác vùng.

## 6. Kế hoạch đề xuất: ba phase trong một skill

Không khuyến nghị triển khai tất cả trong một phase lớn. Ba phase cho phép tách contract, implementation và cross-platform acceptance. Đây vẫn là một skill duy nhất và một repository duy nhất.

### Phase 1 — Kiến trúc, routing và contracts

Mục tiêu: hoàn thiện public behavior và schema mà chưa phụ thuộc vào tool cụ thể.

#### 6.1 Task profiles

Bổ sung ba entry profile:

```yaml
task_profile:
  - CONVERT_DOCUMENT
  - PREPARE_RAG_SOURCE
  - RECONCILE_DOCUMENT_SET
```

Các route hiện tại như `INTAKE_INTEGRITY`, `CLASSIFY_EXTRACT`, `STRUCTURE_VALIDATE`, `LINK_RECONCILE`, `EVIDENCE_DISCLOSURE`, `REVIEW_REPERFORM` trở thành lifecycle/internal routes bên dưới task profile, không buộc người dùng phải hiểu chúng.

#### 6.2 Capability routing

Dự kiến thêm:

- `references/platform-capability-routing.md`

Nội dung chính:

- source access: local folder, attachment, Project File, authorized reference;
- native-first PDF/image processing;
- file-creation capability detection;
- fallback và limitation behavior;
- không tuyên bố đã scan toàn bộ folder nếu host không có filesystem;
- không phụ thuộc cứng vào tên skill/tool của OpenAI hoặc Claude.

#### 6.3 Conversion output contracts

Dự kiến thêm:

- `references/conversion-output-profiles.md`

Các profile:

| Format | Profile |
|---|---|
| DOCX | `SEMANTIC_EDITABLE`, `LAYOUT_PRESERVING` |
| XLSX | `STRUCTURED_DATA`, `RECONCILIATION_WORKBOOK` |
| PPTX | `EDITABLE_PRESENTATION`, `PAGE_AS_SLIDE` |
| JSON | `CANONICAL_PACKAGE`, `SIMPLIFIED_RECORDS` |
| Markdown | `HUMAN_READABLE`, `RAG_SOURCE` |

Nếu lựa chọn DOCX/PPTX làm thay đổi đáng kể kết quả mà người dùng chưa nêu, skill phải hỏi; không tự giả định.

#### 6.4 Schema mới và sửa schema routing

Dự kiến thêm:

- `schemas/document-types/purchase-requisition.json`
- `schemas/document-types/payment-request.json`
- `schemas/document-types/bank-statement.json`

`bank-statement.json` phải hỗ trợ statement-level metadata và transaction-level rows: account, statement period, opening/closing balance, transaction date, value date, debit/credit, amount, currency, reference, counterparty, description và running balance khi có.

Phải sửa các đường dẫn schema đang không khớp tên file thật trong:

- `references/classification-and-schema-routing.md`

Ví dụ hiện tài liệu dùng tên dạng `invoice.schema.json`, trong khi file thật là `invoice.json`.

#### 6.5 Phase 1 exit gate

- Ba mục tiêu được route đúng.
- Native capability là mặc định; external OCR là optional.
- Mỗi format có output contract và failure behavior.
- PR, Payment Request và Bank Statement có schema/profile riêng.
- Không tạo breaking change nếu có thể tránh.

### Phase 2 — Artifacts, deterministic helpers và workflow tích hợp

Mục tiêu: tạo output thực tế và kết nối ba task profile với canonical package.

#### 6.6 Conversion execution

Core instruction cần dùng cách diễn đạt trung lập:

```text
Use the best available document, spreadsheet, presentation,
file-creation, rendering and validation capabilities of the host.
```

Không hard-code tên tool. Nếu host thiếu capability:

1. tạo canonical JSON hoặc Markdown nếu khả thi;
2. ghi `NOT_EXECUTED` cho artifact không thể tạo;
3. nêu limitation và next handoff;
4. không đổi extension để giả file.

#### 6.7 RAG package

Profile mặc định:

```text
rag-package/
|-- document.md
|-- metadata.json
`-- manifest.json
```

Profile ingestion-ready tùy chọn:

```text
rag-package/
|-- document.md
|-- metadata.json
|-- chunks.jsonl
`-- manifest.json
```

Yêu cầu tối thiểu:

- heading hierarchy;
- page/source markers;
- table preservation;
- captions/footnotes khi material;
- phân biệt source text với AI note;
- loại header/footer lặp không mang nội dung;
- giữ identifier và leading zero;
- `document_id`, source filename/hash, document type, language, page range, extraction method, version, review status và classification khi có.

Chỉ tạo `chunks.jsonl` khi người dùng yêu cầu hoặc target RAG đã được cung cấp. Không tự chọn embedding model, vector database, tokenizer, chunk size hoặc overlap khi chưa có yêu cầu đích.

Dự kiến cân nhắc thêm:

- `references/rag-source-package.md`
- `schemas/common/rag-package.schema.json`
- `assets/templates/rag-metadata.json`
- `assets/templates/rag-manifest.json`
- `scripts/build_rag_package.py` — optional, offline, deterministic, không gọi model/mạng.

#### 6.8 Reconciliation profiles

Dự kiến hỗ trợ:

```text
PR <-> PO
PO <-> GRN <-> Invoice
PR <-> PO <-> GRN <-> Invoice
Contract/PO <-> GRN/Acceptance <-> Invoice <-> Payment Request
Invoice/Payment Request <-> Bank Transaction
Contract/PO <-> GRN <-> Invoice <-> Bank Payment
CUSTOM_N_WAY
```

Mỗi profile phải xác định hoặc yêu cầu người dùng xác định:

- required/optional roles;
- business grain;
- match keys và cardinality;
- date/currency basis;
- partial delivery/invoice/payment behavior;
- many-to-many allocation;
- duplicate behavior;
- missing-document behavior;
- tolerance và approval source;
- review/escalation rule.

Không hard-code tolerance hoặc materiality.

#### 6.9 Workbook reconciliation

Dự kiến mở rộng output với các sheet có điều kiện:

- `PURCHASE_REQUISITIONS`
- `PURCHASE_ORDERS`
- `GOODS_RECEIPTS`
- `INVOICES`
- `PAYMENT_REQUESTS`
- `BANK_TRANSACTIONS`
- `MATCH_RESULTS`
- `DISCREPANCIES`
- `HUMAN_REVIEW`
- `SOURCE_INDEX`
- `RUN_LOG`

Không tạo sheet/hàng giả chỉ để lấp template. Phải giữ identifier dạng text, typed amount/date khi unambiguous, raw/normalized values, provenance và formula-injection protection.

#### 6.10 Folder và attachment workflow

```text
Host có filesystem:
  inventory folder -> process each file -> isolate per-file failure
  -> canonical package -> output/reconciliation

Host chỉ có attachments/Project Files:
  inventory accessible files only -> process -> record coverage
  -> canonical package -> output/reconciliation
```

Không bắt buộc thêm một monolithic runner. Các script hiện có tiếp tục làm deterministic helper:

- `scripts/document_inventory.py`
- `scripts/validate_records.py`
- `scripts/reconcile_records.py`
- `scripts/build_workbook.mjs`
- `scripts/finalize_workbook.py`

#### 6.11 Phase 2 exit gate

- Mỗi output được tạo khi host có capability tương ứng.
- RAG package được sinh từ canonical extraction.
- Folder hoặc attachments tạo được reconciliation workbook trong phạm vi truy cập.
- PR, Payment Request và Bank Statement được phân loại, extract và match đúng role.
- Không có mandatory external OCR, API key hoặc vendor dependency.

### Phase 3 — Cross-platform QA, packaging và release

Mục tiêu: xác minh portable behavior trên Codex, ChatGPT và Claude trước khi tuyên bố đáp ứng đầy đủ.

#### 6.12 Test matrix

| Scenario | Codex | ChatGPT | Claude |
|---|---:|---:|---:|
| Ảnh receipt -> JSON/XLSX | Required | Required | Required |
| PDF scan nhiều trang -> DOCX | Required | Required | Required |
| PDF -> PPTX editable | Required | Required | Required |
| PDF -> RAG Markdown | Required | Required | Required |
| Folder nhiều chứng từ | Full filesystem test | Attachment/ZIP equivalent | Attachment/Project equivalent |
| PO-GRN-Invoice matching | Required | Required | Required |
| Four-way có payment/bank | Required | Required | Required |
| Partial delivery/payment | Required | Required | Required |
| Trang mờ/thiếu | Review queue | Review queue | Review queue |

Không được đánh dấu PASS cho platform chưa được thử thực tế. Dùng `NOT_TESTED` hoặc `READY_FOR_HUMAN_VALIDATION` phù hợp.

#### 6.13 Synthetic fixture set

Fixture tối thiểu:

- 1 PR;
- 1 PO;
- 2 GRN giao từng phần;
- 2 invoices;
- 1 payment request;
- 1 bank statement;
- 1 receipt;
- 1 contract;
- 1 mismatch có chủ đích;
- 1 duplicate candidate;
- 1 trường mờ/không chắc chắn.

Ưu tiên synthetic fixture để không đưa dữ liệu thật hoặc dữ liệu cá nhân vào repository.

#### 6.14 Acceptance criteria theo mục tiêu

**Mục tiêu 1 — Conversion**

- output mở được bằng ứng dụng tương ứng;
- không bỏ content/trang/table âm thầm;
- DOCX/PPTX được render và kiểm tra;
- identifiers và số liệu trọng yếu được giữ;
- không tuyên bố layout-preserving/pixel-perfect nếu chưa kiểm chứng.

**Mục tiêu 2 — RAG**

- Markdown có cấu trúc và provenance;
- metadata liên kết đúng source;
- tables không mất hàng trọng yếu;
- manifest phản ánh đủ artifacts;
- nếu chunked, mỗi chunk có stable ID và source locator;
- không có embeddings/vector claims nếu chưa thực hiện.

**Mục tiêu 3 — Reconciliation**

- input file count tie với source index;
- line-item count/totals tie;
- status theo đúng config;
- allocations không vượt available quantity/amount;
- unmatched, ambiguous, duplicate, missing và conflicting records xuất hiện trong workbook;
- cùng input/config tạo cùng domain result, trừ run metadata được phép thay đổi.

#### 6.15 Release work

- cập nhật `README.md` về cài đặt và ba use case;
- cập nhật `ACCEPTANCE-REPORT.md` bằng kết quả thực tế;
- chạy `quick_validate.py` của `skill-creator`;
- kiểm tra JSON Schema và internal links;
- kiểm thử script và artifact;
- đồng bộ bản cài local sau khi source repository pass;
- chỉ commit/tag/push khi người dùng yêu cầu hoặc phê duyệt bước triển khai/release.

## 7. Version strategy

Phiên bản hiện tại là `1.0.0`.

Khuyến nghị:

- dùng `1.1.0-rc` trong Phase 1–2;
- phát hành `1.1.0` nếu mọi thay đổi chỉ thêm optional task profile, schema và artifact, đồng thời tương thích canonical package cũ;
- chỉ nâng `2.0.0` nếu thay required fields, enum hoặc semantics làm package/config/output cũ không còn hợp lệ.

Ưu tiên giữ backward compatibility và hướng tới `1.1.0`.

## 8. Nhận định readiness hiện tại

- JSON/XLSX extraction và deterministic reconciliation từ structured package: mạnh nhất.
- Native host vision giúp pipeline raw PDF/image có thể vận hành trong phiên tương tác.
- DOCX/PPTX/Markdown hiện chưa có output contract và acceptance đầy đủ.
- RAG hiện chưa có package profile chính thức.
- PR, Payment Request và Bank Statement chưa có schema tách biệt đầy đủ.
- Folder scanning chỉ bảo đảm khi host có quyền filesystem.

Đánh giá tổng hợp hiện tại:

- `READY_WITH_CONDITIONS` khi chấp nhận native capabilities của host;
- chưa đủ cơ sở tuyên bố universal deterministic end-to-end;
- acceptance report hiện chỉ nên tối đa `READY_FOR_HUMAN_REVIEW` hoặc trạng thái tương đương đã được chứng minh.

## 9. Các quyết định cần người dùng đánh giá trước khi triển khai

Phiên mới không được tự chọn các điểm sau nếu người dùng chưa phê duyệt:

1. Có chấp thuận kế hoạch ba phase hay muốn gộp phase nào không?
2. Có chấp thuận mục tiêu version `1.1.0` với backward compatibility không?
3. DOCX mặc định có nên là `SEMANTIC_EDITABLE`, hay luôn hỏi giữa semantic và layout-preserving?
4. PPTX mặc định có nên là `EDITABLE_PRESENTATION`, hay luôn hỏi giữa editable và page-as-slide?
5. RAG mặc định có chấp thuận `document.md + metadata.json + manifest.json`, còn `chunks.jsonl` chỉ tạo khi được yêu cầu không?
6. Phase 3 dùng hoàn toàn synthetic fixtures hay người dùng sẽ cung cấp thêm bộ tài liệu thực đã khử/ẩn dữ liệu?
7. Có cần duy trì các workflow evidence/investigation/redaction hiện tại trong cùng skill dưới dạng conditional references không?

## 10. Hướng dẫn cho phiên tiếp theo

1. Đọc toàn bộ `HANDOFF.md` này.
2. Đọc toàn bộ skill-creator `SKILL.md` và target `thien-skill-document-evidence/SKILL.md` trước khi sửa.
3. Kiểm tra `git status`, branch, HEAD và version; không giả định repository vẫn ở trạng thái nêu tại đầu tài liệu.
4. Trình bày lại các quyết định mở ở Mục 9 cho người dùng đánh giá.
5. Chỉ lập implementation plan cuối cùng sau khi nhận các quyết định cần thiết.
6. Không triển khai Phase 2 hoặc Phase 3 như thể Phase 1 đã được phê duyệt.
7. Không ghi đè thay đổi không liên quan của người dùng.
8. Sau mỗi phase, chạy validation/behavioral tests tương xứng và cập nhật acceptance evidence trước khi sang phase tiếp theo.

## 11. Các file hiện hữu quan trọng cần rà soát khi triển khai

- `thien-skill-document-evidence/SKILL.md`
- `thien-skill-document-evidence/references/architecture-boundaries-and-workflow.md`
- `thien-skill-document-evidence/references/extraction-routing-and-preprocessing.md`
- `thien-skill-document-evidence/references/classification-and-schema-routing.md`
- `thien-skill-document-evidence/references/field-table-contract-extraction.md`
- `thien-skill-document-evidence/references/reconciliation-and-package-linking.md`
- `thien-skill-document-evidence/references/output-redaction-and-handoff.md`
- `thien-skill-document-evidence/references/acceptance-scenarios.md`
- `thien-skill-document-evidence/schemas/common/extraction-package.schema.json`
- `thien-skill-document-evidence/schemas/common/reconciliation-config.schema.json`
- `thien-skill-document-evidence/schemas/document-types/`
- `thien-skill-document-evidence/assets/templates/`
- `thien-skill-document-evidence/scripts/`
- `README.md`
- `ACCEPTANCE-REPORT.md`

