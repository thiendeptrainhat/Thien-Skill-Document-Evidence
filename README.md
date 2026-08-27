<p align="center">
  <img src="./thien-skill-document-evidence/assets/brand/logo-large.png" alt="TDTN logo" width="180">
</p>

# Thien Skill — Document Intelligence, Evidence & Reconciliation

Biến bộ tài liệu rời rạc thành dữ liệu có cấu trúc, tệp có thể sử dụng tiếp và kết quả đối soát có đường dẫn về nguồn. Khi được kích hoạt, skill hướng dẫn agent xử lý theo một quy trình nhất quán: kiểm kê → trích xuất → chuẩn hóa có kiểm soát → kiểm tra → xuất kết quả → bàn giao các điểm cần con người xem xét.

Bản **1.1.0** tập trung vào ba nhu cầu: **chuyển đổi tài liệu**, **chuẩn bị nguồn RAG** và **đối soát nhiều loại chứng từ**. Skill kết hợp hướng dẫn nghiệp vụ, schema dữ liệu, templates và script offline; không phải một OCR engine hay hệ thống phê duyệt tự động.

> GitHub là nơi lưu trữ source và các gói phát hành. Việc clone repository **không tự kích hoạt skill**. Skill chỉ hoạt động sau khi được cài vào đúng vị trí discovery hoặc được nạp như plugin trên ChatGPT/Codex/Claude.

## Trạng thái

| Thuộc tính | Giá trị |
|---|---|
| Skill ID | `thien-skill-document-evidence` |
| Version | `1.1.0` |
| Product status / QA | `Testing` — độc lập với số phiên bản phát hành |
| Readiness ceiling | `READY_FOR_HUMAN_REVIEW` |
| Repository | Private |
| Owner | Tran Ngoc Thien |
| License | Tran Ngoc Thien's Skills Commercial Source-Available License 2.0 |

Bản phát hành `1.1.0` không còn hậu tố RC, kế thừa Phase 2 Implementation và Phase 3 nghiệm thu gói: có CLI offline cho RAG package, conversion artifact và reconciliation package/profile, đồng thời giữ các contract v1.0 tương thích. Chưa live-install trên nền tảng và không được hiểu là production-ready, forensic-certified, legal approval, platform certification hoặc fraud/audit conclusion.

## Đọc nhanh

- [Lợi ích khi kích hoạt](#loi-ich)
- [Ba nhóm tính năng chính](#tinh-nang)
- [Chín matching profiles và khả năng mở rộng](#matching)
- [Quy trình xử lý và đầu vào cần chuẩn bị](#quy-trinh)
- [Ví dụ yêu cầu có thể dùng ngay](#vi-du)
- [Phạm vi đã kiểm thử của 1.1.0](#kiem-thu)
- [Cài đặt và kích hoạt](#cai-dat)

<a id="loi-ich"></a>

## Skill mang lại lợi ích gì khi được kích hoạt?

Kích hoạt nghĩa là agent nạp hướng dẫn và tài nguyên của skill để thực hiện yêu cầu hiện tại. Việc này **không tự chạy quét toàn bộ máy, đọc mọi thư mục, kết nối ERP/ngân hàng hay tải tài liệu lên dịch vụ khác**. Nguồn được đọc, nơi ghi kết quả và công cụ được dùng vẫn phải nằm trong phạm vi được phép.

| Nhu cầu thực tế | Skill hỗ trợ như thế nào? | Giá trị cho người sử dụng |
|---|---|---|
| Có nhiều tệp nhưng chưa biết đã xử lý đủ chưa | Lập inventory, ghi file đã đọc, file lỗi, loại trừ và phạm vi trang/record thực sự xử lý được | Nhìn thấy phần còn thiếu thay vì chỉ nhận kết quả của các tệp đọc thành công |
| Muốn đưa dữ liệu chứng từ vào bảng tính | Chọn schema, tách field/line item, giữ mã định danh dưới dạng text và lưu giá trị nguồn | Giảm việc sửa lại mã mất số 0 đầu, ngày mơ hồ hoặc số liệu bị chuẩn hóa sai |
| Cần kiểm tra một con số đến từ đâu | Gắn document/page/region/snippet, phương pháp trích xuất và trạng thái review khi nguồn cho phép | Lần ngược từ kết quả về bằng chứng để kiểm tra, giải thích hoặc tái thực hiện |
| Cần đối chiếu hồ sơ mua hàng, thanh toán, bán hàng hoặc tồn kho | Match theo vai trò chứng từ, khóa, mức chi tiết và quy tắc được khai báo | Tập trung vào chênh lệch, thiếu hồ sơ và liên kết chưa chắc chắn cần xử lý |
| Muốn dùng lại nội dung cho Word, Excel, PowerPoint hoặc hệ thống tri thức | Tạo nội dung chuẩn hóa trung gian rồi xuất artifact hoặc RAG source package theo mục tiêu | Không phải trích xuất lại từ đầu cho từng đầu ra; biết rõ những gì được giữ lại hoặc chưa hỗ trợ |
| Cần bàn giao cho người khác kiểm tra | Kèm manifest, checksum, config, source references và danh sách vấn đề còn mở | Có căn cứ để kiểm tra đúng phiên bản input/output và logic đã dùng |
| Xử lý tài liệu có nội dung không đáng tin cậy | Giữ original read-only theo workflow; không làm theo lệnh nhúng; các script kiểm soát đường dẫn và mặc định không ghi đè | Hạn chế thao tác ngoài phạm vi và tránh biến nội dung chứng từ thành lệnh thực thi |

Đây là lợi ích về quy trình và khả năng kiểm tra. Repository chưa công bố benchmark về thời gian tiết kiệm, độ chính xác OCR hoặc tỷ lệ phát hiện sai sót; không suy các chỉ số đó từ số lượng tests.

### Điểm mới nổi bật của 1.1.0

- Có ba helper offline cho **conversion artifact**, **RAG source package** và **reconciliation package/workbook**, không chỉ có hướng dẫn hoặc template đầu ra.
- Bổ sung cấu trúc dữ liệu chung cho yêu cầu xử lý, nội dung theo block, artifact manifest, conversion run, RAG package và matching profile; giữ tương thích các contract/tool v1.0 hiện hữu.
- Có **9 matching profiles** đi kèm và cơ chế custom profile cho quy trình khác; không khóa đối soát vào hóa đơn đầu vào–PO–GRN.
- Tách rõ **tệp đã tạo**, **kiểm tra cấu trúc**, **kiểm tra hiển thị/nhập vào hệ thống đích** và **phê duyệt của con người**.
- Phân phối cùng một portable core trong ba gói OpenAI, Claude và Universal; kiểm tra parity và checksum giúp xác định gói đang dùng.

<a id="tinh-nang"></a>

## Ba nhóm tính năng chính

### 1. Chuyển tài liệu thành nội dung và tệp có thể sử dụng tiếp

Task profile: `CONVERT_DOCUMENT`.

Phù hợp khi cần đưa nội dung tài liệu sang định dạng có thể chỉnh sửa, lọc dữ liệu hoặc xử lý tiếp. Agent ưu tiên native text khi đủ dùng; OCR/vision chỉ được dùng khi cần và khi host có công cụ phù hợp.

Nội dung trung gian — **canonical content** — giữ các block heading, paragraph, table, image và caption, cùng ID, thứ tự đọc và liên kết nguồn. Script [render_canonical_artifacts.py](./thien-skill-document-evidence/scripts/render_canonical_artifacts.py) nhận nội dung đã chuẩn hóa này để sinh tệp thật:

| Đầu ra | Mục đích và cách xử lý | Điều cần lưu ý |
|---|---|---|
| JSON | Giữ canonical content để máy đọc, kiểm tra hoặc chuyển sang bước tiếp theo | Không thay thế việc xác minh dữ liệu đã trích từ nguồn |
| Markdown | Tạo bản nội dung có heading, bảng và tham chiếu nguồn để đọc hoặc xử lý tiếp | Là biểu diễn nội dung, không phải bản sao bố cục PDF |
| DOCX — `SEMANTIC_EDITABLE` | Ưu tiên đoạn văn, heading và bảng có thể chỉnh sửa | Không cam kết giữ nguyên phân trang, font hoặc từng pixel của bản gốc |
| XLSX — `STRUCTURED_DATA` | Tạo bảng dữ liệu với kiểu giá trị và mã định danh được kiểm soát | Không phải bản sao hình thức từng trang; workbook đối soát dùng helper riêng |
| PPTX — `EDITABLE_PRESENTATION` | Tạo nội dung slide có thể chỉnh sửa theo mục đích trình bày | Có thể cần chia nội dung/bảng thành nhiều slide; phải ghi rõ thay đổi trình bày |
| PPTX — `PAGE_AS_SLIDE` | Giữ thứ tự trang để xem mỗi trang như một slide | Renderer cần canonical `PAGE_IMAGE` phù hợp; nội dung trang có thể là ảnh, không phải toàn bộ text chỉnh sửa được |
| PPTX — `VISUAL_FIDELITY_BEST_EFFORT` | Dùng vị trí và kích thước block để ưu tiên bố cục nguồn | Cần geometry/page dimensions hợp lệ; không cam kết pixel-perfect |

Nếu chỉ yêu cầu “chuyển sang PowerPoint” mà chưa rõ muốn slide chỉnh sửa hay mỗi trang thành một slide, agent phải hỏi trước khi chọn profile.

Mỗi lần render liên kết **tệp đầu ra + artifact manifest + conversion-run sidecar**, ghi input/output checksum, format, profile và phiên bản runtime. File Office có thể đã tạo thành công nhưng kiểm tra hiển thị trên ứng dụng đích vẫn là `NOT_TESTED`.

**Giới hạn quan trọng:** helper này không tự đọc/OCR PDF thô. Parser/OCR/agent phải tạo canonical content trước. Các cấu trúc phức tạp như nested lists, merged-cell spans, headers/footers và footnotes chưa có biểu diễn first-class đầy đủ trong canonical schema v1.0; nếu quan trọng, phải giữ nguồn liên kết và nêu giới hạn, không tuyên bố chuyển đổi hoàn hảo.

Chi tiết: [conversion output profiles](./thien-skill-document-evidence/references/conversion-output-profiles.md).

### 2. Chuẩn bị gói nguồn RAG có thể truy nguyên

Task profile: `PREPARE_RAG_SOURCE`.

Phù hợp khi muốn chuẩn bị tài liệu cho hệ thống hỏi đáp dựa trên nguồn, kho tri thức hoặc pipeline ingestion. Mục tiêu là **chuẩn bị nguồn có cấu trúc và kiểm tra được**, chưa phải xây chatbot hay vector database.

Script [build_rag_package.py](./thien-skill-document-evidence/scripts/build_rag_package.py) nhận một hoặc nhiều canonical inputs và tạo:

```text
rag-package/
├── rag-package.json          # Control object của gói
├── collection-manifest.json  # Chỉ có khi xử lý collection
└── <document-directory>/
    ├── document.md           # Nội dung theo thứ tự đọc
    ├── metadata.json         # Identity, source, coverage, limitations
    ├── manifest.json         # Danh mục payload và checksum
    ├── assets/               # Khi có asset được tham chiếu và được phép xuất
    └── chunks.jsonl          # Chỉ khi có target và cấu hình chunking
```

Các lợi ích cụ thể:

- Giữ ID tài liệu/block và liên kết trang/nguồn, giúp downstream truy ngược một đoạn nội dung.
- Tách metadata và manifest khỏi nội dung, thuận tiện kiểm tra file thiếu, checksum sai hoặc asset tham chiếu không hợp lệ.
- Xử lý collection nhưng vẫn giữ provenance của từng tài liệu; không tự gộp hai lần xuất hiện của nguồn chỉ vì cùng hash.
- Không tự chọn kích thước chunk chung cho mọi hệ thống. Chỉ tạo chunks khi có target và config; chunk vẫn liên kết về block nguồn.
- Có `--dry-run` để kiểm tra/preview mà không tạo package.

**Không bao gồm:** upload tự động, embeddings, vector index, retrieval evaluation hoặc xác nhận một hệ thống RAG cụ thể đã ingest thành công. OCR và chuyển tài liệu thô thành canonical input vẫn là bước upstream phụ thuộc capability.

Chi tiết: [RAG source package](./thien-skill-document-evidence/references/rag-source-package.md).

### 3. Đối soát chứng từ và tạo workbook phục vụ review

Task profile: `RECONCILE_DOCUMENT_SET`.

Phù hợp khi cần liên kết nhiều chứng từ quanh cùng giao dịch rồi chỉ ra chênh lệch hoặc hồ sơ còn thiếu. Skill tách rõ:

- **Role:** vai trò của từng nguồn, như PO, hóa đơn, phiếu xuất kho hay xác nhận nhận hàng.
- **Grain:** mỗi record đại diện cho một chứng từ, dòng hàng, lô hàng hay phân bổ thanh toán.
- **Key:** trường dùng để liên kết, như số PO, mã hàng, số giao hàng hoặc tham chiếu giao dịch.
- **Rule/policy:** phép so sánh, cách xử lý giao hàng từng phần, tiền tệ, thời điểm và tolerance được phê duyệt.

Script [prepare_reconciliation_workbook.py](./thien-skill-document-evidence/scripts/prepare_reconciliation_workbook.py) nhận **structured document JSON hoặc canonical extraction package**. Nó kiểm kê input trong phạm vi được phép, phân loại theo profile, ghi lỗi từng file, tạo config từ policy được cấp, chạy đối soát deterministic rồi xuất package và workbook theo vai trò.

Đầu ra gồm các thành phần như:

- `matching-profile.json`, `records.json` và `reconciliation-config.json`: profile, dữ liệu và quy tắc thực tế đã dùng;
- `reconciliation-result.json`: liên kết, trạng thái và chênh lệch;
- `workbook-package.json`, validation report và `reconciliation-workbook.xlsx`: dữ liệu chuẩn hóa cùng bản xem để review;
- `workflow-manifest.json`: thông tin run, phạm vi, trạng thái và liên kết output.

Workbook có các sheet role chứa dữ liệu, cùng các view như `MATCH_RESULTS`, `DISCREPANCIES`, `HUMAN_REVIEW`, `SOURCE_INDEX` và `RUN_LOG` khi phù hợp. Không tạo hàng loạt sheet trống chỉ để đủ một mẫu.

Kết quả phân biệt khớp chính xác, trong tolerance đã duyệt, khớp một phần, nhiều ứng viên, mâu thuẫn và chưa khớp. “Trong tolerance” vẫn phải giữ chênh lệch chính xác; “thiếu chứng từ” chỉ có ý nghĩa khi đã xác định bộ hồ sơ được kỳ vọng.

**Không có tolerance/materiality ngầm.** Many-to-many cần bridge/allocation rõ; fuzzy matching không thuộc deterministic core. PDF/ảnh thô phải được trích xuất trước; helper không tự OCR, lấy dữ liệu từ ERP hay kết nối tài khoản ngân hàng. Kết quả là candidate/exception để review, không phải lệnh thanh toán hoặc điều chỉnh sổ.

<a id="matching"></a>

## Chín matching profiles và khả năng mở rộng

Các cấu hình đi kèm nằm trong [assets/reconciliation-profiles](./thien-skill-document-evidence/assets/reconciliation-profiles/). Đây là cấu hình khởi điểm có schema, không phải chính sách nghiệp vụ đã được phê duyệt cho mọi doanh nghiệp.

| Profile | Chuỗi nguồn được đối chiếu | Trường hợp sử dụng |
|---|---|---|
| `PR_PO` | Đề nghị mua hàng ↔ đơn mua hàng | Kiểm tra liên kết nhu cầu mua với đơn hàng |
| `PO_GRN_INVOICE` | Đơn mua hàng ↔ nhận hàng ↔ hóa đơn đầu vào | Three-way matching theo dòng hàng, gồm partial flow khi được cho phép |
| `PR_PO_GRN_INVOICE` | Đề nghị mua ↔ đơn mua ↔ nhận hàng ↔ hóa đơn | Theo dõi chuỗi từ đề nghị đến hóa đơn |
| `CONTRACT_ACCEPTANCE_INVOICE_PAYMENT_REQUEST` | Hợp đồng ↔ nghiệm thu ↔ hóa đơn ↔ đề nghị thanh toán | Liên kết hồ sơ nghiệm thu và thanh toán |
| `INVOICE_PAYMENT_BANK_SETTLEMENT` | Hóa đơn ↔ đề nghị thanh toán ↔ giao dịch ngân hàng đã nhập | Đối chiếu tham chiếu và giá trị thanh toán; đề nghị thanh toán không được coi là đã chi tiền |
| `CONTRACT_PO_GRN_INVOICE_BANK_PAYMENT` | Hợp đồng **hoặc** PO ↔ nhận hàng ↔ hóa đơn ↔ giao dịch ngân hàng | Chuỗi bốn vai trò; profile hiện tại dùng hợp đồng/PO như hai biến thể của cùng vai trò cơ sở |
| `OUTBOUND_INVOICE_GOODS_ISSUE_CUSTOMER_RECEIPT` | Hóa đơn đầu ra ↔ xuất kho ↔ xác nhận khách nhận hàng | Đối chiếu dòng bán hàng, giao hàng và nhận hàng ở khách |
| `INVENTORY_COUNT_BOOK_STOCK` | Kiểm kê thực tế ↔ tồn sổ/hệ thống | Đối chiếu theo kho, mã hàng, lô và đơn vị tính đã xác định |
| `CUSTOM_N_WAY` | Các vai trò do người dùng cấu hình | Template khởi đầu hai vai trò để mở rộng, không phải bộ match tùy ý đã hoàn chỉnh |

**Customer receipt trong outbound profile là xác nhận khách đã nhận hàng, không phải phiếu thu tiền.** Nếu cần đối soát tiền thu của khách, phải khai báo vai trò và mapping phù hợp, không dùng lẫn hai nghĩa.

Để thêm một matching khác, cung cấp role definitions, field mappings, grain, keys, cardinality, comparison rules, missing/duplicate policy và người chịu trách nhiệm review. Helper hỗ trợ `--profile-file`; việc thêm role chain dùng các comparator hiện có có thể thực hiện bằng cấu hình. Logic so sánh mới ngoài khả năng engine vẫn cần phát triển/adapter và kiểm thử riêng.

Ví dụ: PO 100, nhận hàng 50 và hóa đơn 50 không tự động đúng hoặc sai. Agent phải biết policy giao hàng từng phần, cơ sở lũy kế/phân bổ và số lượng còn lại trước khi đưa ra trạng thái.

Chi tiết: [reconciliation và package linking](./thien-skill-document-evidence/references/reconciliation-and-package-linking.md).

## Các năng lực hỗ trợ xuyên suốt

### Kiểm kê, phân loại và trích xuất có nguồn

Skill định tuyến theo chuỗi native text → layout/table → OCR → vision → human review, tùy dữ liệu và công cụ hiện có. Các loại tài liệu mục tiêu gồm PDF native/scan, ảnh, PR, PO, GRN, hóa đơn, đề nghị thanh toán, hợp đồng/phụ lục, receipt và dữ liệu giao dịch đã xuất từ hệ thống.

Trường trọng yếu giữ riêng:

- `raw_value`: giá trị đọc từ nguồn;
- `normalized_value`: giá trị chuẩn hóa theo rule/locale được ghi nhận;
- `display_value`: cách hiển thị cho người đọc.

Không đổi blank thành zero, không tự đoán ngày mơ hồ hoặc currency, không làm mất số 0 đầu của mã/số tài khoản. Trường thiếu, mờ, mâu thuẫn hoặc chưa xác minh có trạng thái riêng và được chuyển sang review khi cần.

### Trích điều khoản và nghĩa vụ

Workflow có hướng dẫn/schema/templates để lập clause và obligation register từ hợp đồng/phụ lục: giữ đoạn văn nguồn, liên kết phiên bản, bên thực hiện, hành động, điều kiện kích hoạt và quy tắc thời hạn khi có căn cứ. Đây là **trích xuất thông tin**, không phải legal opinion hay xác nhận điều khoản có hiệu lực.

### Evidence và bàn giao có kiểm soát

Khi nhiệm vụ yêu cầu, skill hỗ trợ evidence register, source index, human-review queue và ghi nhận custody/redaction events thực sự đã xảy ra. Conversion hoặc RAG thông thường không mặc định trở thành một hồ sơ điều tra.

Che/xóa thông tin nhạy cảm thực tế cần công cụ và verification phù hợp. Nếu chưa kiểm tra được việc loại bỏ dữ liệu, chỉ bàn giao specification/log với trạng thái chưa thực hiện; không gọi tài liệu đó là “đã redacted an toàn”.

### An toàn dữ liệu và khả năng tái thực hiện

Nội dung trong tài liệu, QR, hyperlink, macro marker và OCR text được coi là dữ liệu, không phải chỉ dẫn cho agent. Text giống công thức phải được xuất dưới dạng literal an toàn; không chạy macro hoặc làm theo yêu cầu nhúng.

Các script đi kèm không tự gọi mạng, không tự cài dependency và mặc định không ghi đè output. Hash, config và manifests giúp kiểm tra lại input/output và kết quả deterministic. **Điều này không có nghĩa toàn bộ phiên agent luôn offline:** việc đọc/OCR/vision bằng dịch vụ của host còn phụ thuộc công cụ được chọn và quyền xử lý dữ liệu.

<a id="quy-trinh"></a>

## Quy trình khi kích hoạt

`Nguồn được phép đọc → Inventory → Extraction/canonical data → Validation → Output theo task profile → Human review/handoff`

1. **Chốt mục tiêu và phạm vi:** tài liệu nào, kỳ/đơn vị nào, ai nhận kết quả, được dùng công cụ nào.
2. **Kiểm kê và bảo toàn nguồn:** ghi file lỗi/không đọc được, coverage và working copy; không sửa original.
3. **Chọn schema và phương pháp trích xuất:** dùng native text khi đủ; chỉ gọi adapter khi có capability và quyền phù hợp.
4. **Kiểm tra dữ liệu và các quy tắc:** giữ provenance, uncertainty và source contradictions; hỏi khi lựa chọn làm thay đổi kết quả đáng kể.
5. **Tạo đầu ra đúng mục đích:** conversion, RAG source hoặc reconciliation; có thể chỉ hoàn thành phần độc lập nếu bước khác bị chặn.
6. **Bàn giao cùng giới hạn:** nêu đã tạo gì, đã kiểm tra gì, phần nào chưa chạy và ai cần review. Không tự nâng thành phê duyệt nghiệp vụ.

Các lifecycle route kỹ thuật tương ứng là `INTAKE_INTEGRITY`, `CLASSIFY_EXTRACT`, `STRUCTURE_VALIDATE`, `LINK_RECONCILE`, `EVIDENCE_DISCLOSURE` và `REVIEW_REPERFORM`; không phải mọi task đều phải chạy đủ sáu route.

### Nên cung cấp gì trong yêu cầu đầu tiên?

- Nguồn/tệp hoặc thư mục được phép đọc; thông tin mật cần bảo vệ và nơi được phép ghi output.
- Mục tiêu và định dạng đầu ra, ví dụ Word chỉnh sửa được, workbook đối soát hoặc RAG package chưa chunk.
- Với conversion: ưu tiên chỉnh sửa hay giữ bố cục; yêu cầu riêng cho hình, bảng hoặc từng trang.
- Với RAG: xử lý một tài liệu hay collection; target/config chỉ khi muốn tạo chunks.
- Với matching: các role, grain/keys, kỳ/cut-off, đơn vị tính/tiền tệ, partial policy và tolerance đã duyệt.

Không cần biết tên schema để bắt đầu. Agent có thể giúp xác định phần thiếu, nhưng không tự đặt các quyết định nghiệp vụ quan trọng.

<a id="vi-du"></a>

## Ví dụ yêu cầu có thể dùng ngay

Các prompt dưới đây dùng tên skill; cú pháp gọi cụ thể phụ thuộc nền tảng và cách cài. Đây là ví dụ sử dụng, không phải bằng chứng đã chạy với tài liệu thật của người dùng.

### Hóa đơn thành workbook

```text
Dùng thien-skill-document-evidence để xử lý các hóa đơn tôi cung cấp.
Lập inventory và kiểm tra khả năng đọc trước; trích dữ liệu đầu hóa đơn và dòng hàng.
Tạo workbook phục vụ review, giữ mã hóa đơn/số tài khoản dưới dạng text,
tách raw/normalized values, ghi nguồn trang và các trường còn mơ hồ.
Không tự đoán dữ liệu thiếu hoặc dùng dịch vụ ngoài khi chưa được phép.
```

### Chuyển tài liệu sang Word hoặc PowerPoint

```text
Chuyển tài liệu này thành DOCX có thể chỉnh sửa theo SEMANTIC_EDITABLE.
Giữ heading, bảng, hình và caption khi nguồn/công cụ cho phép.
Kèm nguồn liên kết, manifest và danh sách cấu trúc chưa giữ được.
Không cần giống từng pixel; ghi riêng trạng thái tạo file và kiểm tra hiển thị.
```

Nếu cần PowerPoint, nêu rõ “slide để chỉnh sửa/trình bày” hay “mỗi trang nguồn thành một slide để xem”.

### Chuẩn bị nguồn RAG từ một thư mục

```text
Chuẩn bị RAG source package cho các tài liệu trong thư mục được phép này.
Giữ riêng từng document, stable block IDs, page provenance, metadata và manifests.
Tạo collection manifest; ghi file lỗi, phần thiếu và asset được phép xuất.
Tôi chưa chỉ định target/chunking config: chưa tạo chunks, không upload hoặc tạo embeddings.
```

### Mua hàng và nhận hàng từng phần

```text
Đối soát PO–GRN–hóa đơn bằng profile PO_GRN_INVOICE.
Đề xuất grain và keys từ dữ liệu rồi xác nhận các điểm chưa rõ.
Dùng partial/tolerance policy tôi đính kèm; nếu thiếu phê duyệt thì hỏi.
Xuất workbook chênh lệch, source record IDs và human-review queue.
Không coi tổng tiền khớp là đủ nếu dòng hàng hoặc số lượng còn lệch.
```

### Hóa đơn đầu ra, xuất kho và khách nhận hàng

```text
Dùng profile OUTBOUND_INVOICE_GOODS_ISSUE_CUSTOMER_RECEIPT để đối soát
hóa đơn bán hàng, phiếu xuất kho và xác nhận khách nhận hàng.
Kiểm tra mapping số đơn/số giao hàng, mã hàng, số lượng và ngày theo policy được cấp.
Customer receipt ở đây là nhận hàng, không phải thu tiền.
Ghi thiếu xác nhận nhận hàng, partial delivery và các liên kết nhiều ứng viên để review.
```

### Kiểm kê và tồn sổ

```text
Đối soát biên bản kiểm kê với tồn sổ bằng profile INVENTORY_COUNT_BOOK_STOCK.
Xác nhận cut-off, kho, mã hàng, lô và đơn vị tính trước khi so sánh.
Chỉ dùng tolerance hoặc quy đổi đơn vị đã được phê duyệt.
Tạo danh sách chênh lệch có nguồn; không tự kết luận thất thoát hoặc ghi điều chỉnh sổ.
```

### Trích nghĩa vụ và review lại kết quả

```text
Trích clause và obligation từ hợp đồng cùng phụ lục tôi cung cấp.
Giữ nguyên đoạn nguồn, liên kết phiên bản, party/action/trigger/due rule khi xác định được.
Đưa mâu thuẫn và nội dung cần diễn giải vào human-review queue.
Không kết luận hiệu lực pháp lý. Khi bàn giao, kèm source coverage và giới hạn trích xuất.
```

Để kiểm tra một kết quả đã có, có thể yêu cầu: “Review extraction package và workbook này; kiểm tra provenance, leading zeros, ngày mơ hồ, formula-like text, matching rules và các trạng thái QA chưa có bằng chứng.”

<a id="kiem-thu"></a>

## Phạm vi đã kiểm thử của bản 1.1.0

Các kết quả dưới đây là bằng chứng kỹ thuật tại thời điểm nghiệm thu; không phải cam kết độ chính xác cho mọi tài liệu hoặc môi trường.

| Hạng mục | Kết quả/phạm vi |
|---|---|
| Regression suite | 145 tests: **144 PASS, 1 optional SKIP** do môi trường thiếu PyYAML |
| Kiểm thử workflow từ ZIP 1.1.0 | **24/24 PASS**, gồm kiểm tra identity/parity và các workflow chạy từ gói đã giải nén |
| Matching packaged E2E | 7/9 profiles có kịch bản đại diện; không phải mọi biến thể của từng profile |
| Hai profile còn lại | `CONTRACT_PO_GRN_INVOICE_BANK_PAYMENT` và `CUSTOM_N_WAY` có source-level checks, chưa có packaged E2E tương ứng trong bộ nghiệm thu này |
| Gói phát hành | Exact-build, portable-core parity và checksum đã kiểm tra; giữ nguyên các gói RC lịch sử |
| DOCX/XLSX/PPTX | Có kiểm tra cấu trúc/package; không có lượt visual render mới trong promotion 1.1.0 |
| Live install và dữ liệu thô | Chưa live-install; OCR receipt/scan và full bank-statement extraction vẫn `NOT_TESTED` |
| RAG system đích | Ingestion, embedding và retrieval quality vẫn `NOT_TESTED` |

Các tests dùng fixture/synthetic inputs và kiểm tra kỹ thuật. Behavioral catalog vẫn tách khỏi kết quả thực thi; không gọi toàn bộ kịch bản mô tả là đã được chạy.

Xem [báo cáo nghiệm thu 1.1.0](./ACCEPTANCE-REPORT-v1.1.0.md), [verification record](./qa/release-1.1.0/verification.json) và [packaged release tests](./tests/test_release_110.py). Số phiên bản chính thức `1.1.0` không thay đổi product status `Testing` hoặc trần readiness `READY_FOR_HUMAN_REVIEW`.

## Skill không làm gì?

Skill không:

- xác thực chữ ký, con dấu, danh tính người viết hoặc tài liệu thật/giả;
- đưa legal opinion, audit opinion, fraud/misconduct conclusion;
- tự đặt tolerance, business rule, materiality hoặc payment decision;
- tự tải model, cài dependency, mở URL/QR hoặc upload dữ liệu ra ngoài;
- thay thế ETL/ELT hoặc population analytics quy mô lớn;
- gọi checksum là chữ ký số hoặc forensic certification;
- biến extraction/schema PASS thành xác nhận dữ liệu đúng về mặt nghiệp vụ.

<a id="cai-dat"></a>

## Cài đặt nhanh từ GitHub

### 1. Clone repository

Repository riêng tư yêu cầu tài khoản GitHub có quyền truy cập và Git/SSH hoặc GitHub CLI đã xác thực.

```bash
git clone https://github.com/thiendeptrainhat/Thien-Skill-Document-Evidence.git
cd Thien-Skill-Document-Evidence
```

### 2. Xác minh gói phát hành

Trên macOS:

```bash
(cd dist && shasum -a 256 -c SHA256SUMS-v1.1.0.txt)
```

Trên Linux:

```bash
(cd dist && sha256sum -c SHA256SUMS-v1.1.0.txt)
```

Tất cả artifact phải trả về `OK`. Kiểm tra thêm:

- [release-manifest-v1.1.0.json](./dist/release-manifest-v1.1.0.json);
- [PARITY-v1.1.0.json](./dist/PARITY-v1.1.0.json) phải có `status: PASS`;
- [ACCEPTANCE-REPORT-v1.1.0.md](./ACCEPTANCE-REPORT-v1.1.0.md);
- [LICENSE-APPLICATION.md](./LICENSE-APPLICATION.md) và [LICENSE](./LICENSE).

### 3. Chọn đúng phương án cài đặt

| Bề mặt sử dụng | Gói/phương án nên dùng |
|---|---|
| Codex local — cài nhanh từ GitHub | `$skill-installer` với đường dẫn canonical skill |
| Codex local — personal/project skill | Sao chép canonical folder vào `.agents/skills/` |
| ChatGPT/ChatGPT Work có quyền import plugin | [OpenAI ZIP](./dist/openai/Thien-Skill-Document-Evidence-OpenAI-v1.1.0.zip) |
| Claude Code plugin | [Claude ZIP](./dist/claude/Thien-Skill-Document-Evidence-Claude-v1.1.0.zip) |
| Claude Code standalone | Sao chép canonical folder vào `.claude/skills/` |
| Nền tảng hỗ trợ Agent Skills chuẩn mở | [Universal ZIP](./dist/universal/Thien-Skill-Document-Evidence-Universal-v1.1.0.zip) |

Không trộn file giữa các gói. Canonical source duy nhất là [thien-skill-document-evidence/](./thien-skill-document-evidence/).

## Cài cho OpenAI ChatGPT và Codex

OpenAI hỗ trợ skill được đóng gói từ `SKILL.md` cùng references/scripts/assets tùy chọn; invocation và discovery phụ thuộc bề mặt/host đang dùng. Xem [OpenAI — Build skills](https://developers.openai.com/plugins/build/skills) và [OpenAI — Build plugins](https://developers.openai.com/plugins/build/plugins).

### Cách A — dùng `$skill-installer` trong Codex

Gọi:

```text
$skill-installer
```

Sau đó yêu cầu:

```text
Install the skill from:
https://github.com/thiendeptrainhat/Thien-Skill-Document-Evidence/tree/main/thien-skill-document-evidence
```

Với repository riêng tư, môi trường chạy installer phải có Git credential hoặc `GITHUB_TOKEN`/`GH_TOKEN` phù hợp. Nếu skill chưa xuất hiện ở lượt tiếp theo, khởi động lại Codex.

### Cách B — cài personal skill thủ công

Từ thư mục repository đã clone:

```bash
mkdir -p ~/.agents/skills
cp -R ./thien-skill-document-evidence ~/.agents/skills/
```

Skill sẽ khả dụng cho các project của người dùng đó.

### Cách C — cài project-scoped skill

Tại repository đích nơi Codex sẽ làm việc:

```bash
mkdir -p .agents/skills
cp -R /absolute/path/to/Thien-Skill-Document-Evidence/thien-skill-document-evidence .agents/skills/
```

Commit thư mục `.agents/skills/thien-skill-document-evidence/` nếu muốn các thành viên được phép truy cập cùng dùng skill trong project đó.

### Cách D — OpenAI plugin/ChatGPT

Sử dụng nguyên file:

[Thien-Skill-Document-Evidence-OpenAI-v1.1.0.zip](./dist/openai/Thien-Skill-Document-Evidence-OpenAI-v1.1.0.zip)

Gói chứa:

- `.codex-plugin/plugin.json`;
- UI metadata và logo;
- canonical skill tại `skills/thien-skill-document-evidence/`.

Nếu tài khoản hoặc workspace có giao diện import/private plugin, tải nguyên ZIP lên và kiểm tra đúng tên/version trước khi bật. Quyền import, phân phối và hiển thị plugin phụ thuộc plan, workspace policy và quyền admin; nếu giao diện không có tính năng đó, dùng cách local standalone ở trên.

### Xác minh kích hoạt trên ChatGPT/Codex

1. Mở Skills hoặc chạy `/skills`.
2. Tìm `Thien Skill — Document Intelligence, Evidence & Reconciliation`.
3. Kích hoạt trực tiếp bằng `$thien-skill-document-evidence` trong Codex; trong ChatGPT, gõ `@` và chọn skill.
4. Chạy smoke test:

```text
Dùng thien-skill-document-evidence để lập inventory cho bộ tài liệu mẫu này.
Không OCR nếu native text đủ dùng. Trả về coverage, security flags và page-level provenance.
```

## Cài cho Claude

Claude Code đọc personal skills từ `~/.claude/skills/<skill-name>/SKILL.md`, project skills từ `.claude/skills/<skill-name>/SKILL.md`, và plugin skills từ `<plugin>/skills/<skill-name>/SKILL.md`. Xem [Anthropic — Extend Claude with skills](https://code.claude.com/docs/en/skills).

### Cách A — nạp Claude plugin ZIP

```bash
claude --plugin-dir ./dist/claude/Thien-Skill-Document-Evidence-Claude-v1.1.0.zip
```

Claude Code hỗ trợ `--plugin-dir` với cả thư mục và ZIP. Sau khi mở phiên:

- dùng `/skills` để kiểm tra;
- để Claude tự kích hoạt theo ngữ cảnh; hoặc
- gọi plugin skill theo namespace:

```text
/thien-skill-document-evidence:thien-skill-document-evidence
```

Đây là cách nạp theo phiên để kiểm thử. Cài đặt qua marketplace nội bộ cần private marketplace riêng. Xem [Anthropic — Create plugins](https://code.claude.com/docs/en/plugins).

### Cách B — Claude standalone personal skill

```bash
mkdir -p ~/.claude/skills
cp -R ./thien-skill-document-evidence ~/.claude/skills/
```

Kích hoạt trực tiếp:

```text
/thien-skill-document-evidence
```

### Cách C — Claude project skill

```bash
mkdir -p .claude/skills
cp -R /absolute/path/to/Thien-Skill-Document-Evidence/thien-skill-document-evidence .claude/skills/
```

Nếu tạo mới thư mục skill cấp cao trong khi Claude Code đang chạy mà skill chưa xuất hiện, hãy mở phiên mới. Thay đổi nội dung `SKILL.md` trong thư mục đã được theo dõi thường được phát hiện trực tiếp.

## Cài Universal Agent Skill

Sử dụng:

[Thien-Skill-Document-Evidence-Universal-v1.1.0.zip](./dist/universal/Thien-Skill-Document-Evidence-Universal-v1.1.0.zip)

Gói Universal dành cho bề mặt hỗ trợ Agent Skills hoặc custom skill upload. ZIP có đúng một thư mục cấp cao; sau khi giải nén, `SKILL.md` nằm ngay tại:

```text
thien-skill-document-evidence/SKILL.md
```

Khả năng upload, đồng bộ, tool access và chạy script phụ thuộc nền tảng đích. Việc nền tảng nhận ZIP không chứng minh mọi runtime adapter đều có sẵn.

## Lợi ích khi quản lý và kích hoạt từ GitHub

Khi repository được dùng làm nguồn phân phối có kiểm soát, GitHub hỗ trợ:

- một canonical source rõ ràng thay vì nhiều bản hướng dẫn rời rạc;
- lịch sử commit để biết chính xác instruction, schema hoặc script nào đã thay đổi;
- review và phê duyệt thay đổi trước khi cập nhật bản cài của nhóm;
- pin theo commit/tag/version để tái hiện đúng hành vi đã dùng;
- kiểm tra checksum và package manifest trước khi cài;
- phân phối private theo quyền repository thay vì gửi ZIP không kiểm soát;
- giữ OpenAI, Claude và Universal packages cùng một portable core.

GitHub không chạy skill và repository này không phải GitHub Action. Agent chỉ áp dụng skill sau khi local/project discovery, plugin loader hoặc custom-skill interface của nền tảng đã nạp `SKILL.md`. Vì vậy, mỗi nhóm nên ghi nhận commit/version đã cài và chạy smoke test sau khi cập nhật.

## Cấu trúc repository

```text
.
├── thien-skill-document-evidence/   # Canonical skill
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   ├── schemas/
│   ├── scripts/
│   └── assets/
├── platform/                        # OpenAI và Claude manifests
├── build/                           # Deterministic package builder
├── tests/                           # Automated và behavioral specifications
├── dist/                            # Ba ZIP + checksums/manifests
├── INSTALLATION.md                  # Hướng dẫn vận hành chi tiết
├── ACCEPTANCE-REPORT-v*.md          # Evidence và release gates theo version
└── LEGAL-REVIEW-v*.md               # Versioned legal/license release note
```

Không sửa trực tiếp nội dung trong `dist/`. Mọi thay đổi portable phải thực hiện tại canonical source rồi chạy lại builder.

## Build và kiểm tra

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B build/build_skill_packages.py
PYTHONDONTWRITEBYTECODE=1 python3 -B build/build_skill_packages.py --check
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_*.py'
```

Bản phát hành `1.1.0` có contract/regression tests, kiểm thử implementation Phase 2, package parity, checksum và package-native structural validation. Xem [ACCEPTANCE-REPORT-v1.1.0.md](./ACCEPTANCE-REPORT-v1.1.0.md) để phân biệt gate đã chạy, `NOT_TESTED` và giới hạn còn lại. Release `1.0.0`, `1.1.0-rc.1`, `1.1.0-rc.2` cùng hồ sơ lịch sử của chúng được giữ nguyên trong repository.

### Các CLI trong bản 1.1.0

- `scripts/render_canonical_artifacts.py`: sinh deterministic JSON/Markdown/DOCX/XLSX/PPTX từ canonical content; PPTX bắt buộc intent/profile rõ; mỗi lần chạy liên kết artifact, artifact manifest và closed `conversion-run.json` sidecar.
- `scripts/build_rag_package.py`: sinh DOCUMENT/COLLECTION RAG package, root control, payload manifests, asset media validation và optional configured chunks.
- `scripts/prepare_reconciliation_workbook.py`: inventory structured JSON/canonical package theo phạm vi, áp dụng bundled/custom matching profile rồi sinh deterministic reconciliation package và role-aware review workbook.
- Mọi đường dẫn đều bị giới hạn trong authorized root, no-overwrite mặc định và không gọi mạng hoặc tự cài dependency. Directory package được stage rồi rename; conversion dùng atomic replacement cho từng file và rollback khi lỗi được bắt, nhưng không tuyên bố power-loss transaction trên nhiều rename.

Xem [INSTALLATION.md](./INSTALLATION.md) để có command đầy đủ. Structural ZIP/XML/schema PASS không tự chuyển thành visual, live-ingestion hoặc platform-install PASS.

## Cập nhật skill

1. Chạy `git pull` trong repository nguồn.
2. Đọc release manifest, checksum và acceptance report mới.
3. Sao lưu bản cài có thay đổi cục bộ.
4. Cài lại đúng canonical folder hoặc ZIP của version mới.
5. Mở phiên agent mới hoặc reload plugin theo cơ chế của nền tảng.
6. Chạy lại smoke test trước khi dùng với tài liệu thật.

Không ghi đè bản cài đã sửa cục bộ nếu chưa so sánh hoặc sao lưu.

## Troubleshooting

- **Skill không xuất hiện:** kiểm tra đúng path và `SKILL.md`; chạy `/skills`; mở phiên mới nếu thư mục discovery vừa được tạo.
- **Skill kích hoạt sai:** gọi explicit bằng `$`/ `@`/ `/skill-name` và mô tả rõ loại tài liệu, mục tiêu, output.
- **Claude plugin không load:** chạy `claude plugin validate --strict /path/to/plugin`, kiểm tra `.claude-plugin/plugin.json`, rồi dùng `/reload-plugins`.
- **Generic evidence workbook builder thiếu dependency:** `build_workbook.mjs` cần Node.js và `@oai/artifact-tool`; skill không tự cài. Đây là pipeline riêng với các helper Python offline cho conversion, RAG và reconciliation.
- **OCR/vision không chạy:** cung cấp adapter được phê duyệt hoặc chuyển trạng thái sang `NOT_EXECUTED`/`BLOCKED`/human review.
- **Repository private không clone được:** xác thực đúng GitHub account hoặc token có quyền đọc repository.

Hướng dẫn nâng cao về reconciliation CLI, schema gate, workbook pipeline và gỡ cài đặt nằm tại [INSTALLATION.md](./INSTALLATION.md).

## License và sử dụng có kiểm soát

Áp dụng [Tran Ngoc Thien's Skills Commercial Source-Available License 2.0](./LICENSE). Bản tiếng Việt được ưu tiên khi có mâu thuẫn; pháp luật và tòa án Việt Nam áp dụng theo master license.

Việc xem, clone hoặc nhận package không tự tạo quyền sử dụng thương mại. Đọc [LICENSE-APPLICATION.md](./LICENSE-APPLICATION.md), [NOTICE](./NOTICE), [THIRD-PARTY-NOTICES.md](./THIRD-PARTY-NOTICES.md) và [LEGAL-REVIEW-v1.1.0.md](./LEGAL-REVIEW-v1.1.0.md) trước khi sao chép, sửa đổi, phân phối hoặc dùng ngoài môi trường kiểm thử.

---

**English summary:** This private repository provides one canonical document-intelligence skill and deterministic OpenAI, Claude, and Universal packages. Version `1.1.0` implements offline RAG-package, artifact-conversion, and extensible role-configured reconciliation helpers while retaining v1.0 data contracts. The packages are structurally validated but are not live-installed. The skill does not claim legal validity, fraud, audit opinion, document authenticity, or platform certification.
