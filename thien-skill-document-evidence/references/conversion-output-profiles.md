# Conversion output profiles

## Mục đích

Conversion bảo toàn thông tin theo intended use; không phải mặc định sao chép từng pixel. Trước khi tạo artifact, ghi target format, conversion profile, required content, fidelity priority, editability requirement, accessibility requirement và acceptance checks.

Canonical semantic content dùng `schemas/common/canonical-content.schema.json`. Output và source linkage dùng `schemas/common/artifact-manifest.schema.json`; format/profile/intent, exact canonical checksum và artifact/manifest linkage nằm trong closed `schemas/common/conversion-run.schema.json`. Các companion objects ghi `skill_id` và `skill_release_version` của release đang chạy, còn `schema_version: 1.0.0` là contract version. Extraction package/tool v1.0 vẫn là compatibility contract riêng cho fields/tables/evidence và không bị thay thế hoặc relabel thành RC.

## Các profile mặc định

| Target | Profile mặc định | Khi đổi profile |
|---|---|---|
| DOCX | `SEMANTIC_EDITABLE` | Chỉ chọn page-fidelity derivative khi người dùng yêu cầu rõ và runtime có geometry/renderer phù hợp |
| XLSX | `STRUCTURED_DATA` | Nếu task là reconciliation, dùng `RECONCILIATION_WORKBOOK` view theo roles/grain/config |
| PPTX | Intent-aware | `EDITABLE_PRESENTATION` cho presentation intent; `PAGE_AS_SLIDE` cho page-faithful viewing |

Với PPTX, nếu intended use không phân biệt được presentation-editing với page-as-slide, phải hỏi người dùng trước khi tạo và ghi `output_profile: null`, `presentation_intent: AMBIGUOUS`, `ambiguity_status: CLARIFICATION_REQUIRED`. Chỉ điền output profile sau khi người dùng giải quyết ambiguity; không tự chọn chỉ từ đuôi `.pptx`.

## Canonical content trước rendering

Phase 1 canonical contract bảo toàn document/source-content identity, fidelity mode, reading-order status và ordered blocks. Block allowlist là `HEADING`, `PARAGRAPH`, `TABLE`, `IMAGE`, `CAPTION`; mỗi block có stable ID, order, optional parent và page/region/snippet/geometry provenance. Type-specific fields giữ heading level, table columns/rows, image asset/media/checksum/alt text và caption target.

List semantics/nesting, cell spans/header relationships, section/page-break, header/footer và footnote/endnote chưa có first-class field trong companion schema v1.0. Nếu material, giữ chúng trong native/raw extraction hoặc linked field/table object và ghi limitation/extension proposal; không flatten/giả support âm thầm. Không tạo alt text như source fact. Layout inference phải có method/confidence/limitation trong linked extraction/QA evidence.

### Source hash provenance

`source_hash_status` phân biệt:

- `COMPUTED_ORIGINAL_BYTES`: `source_content_id` là `sha256:...` của exact original bytes;
- `COMPUTED_ACCESSIBLE_REPRESENTATION`: hash tính trên representation runtime thực sự truy cập được; limitation phải mô tả representation/transformation và không gọi đó là original-byte hash;
- `UNAVAILABLE`: `source_content_id: null` và limitation giải thích vì sao không tính được.

Hash chỉ chứng minh byte identity của input đã nêu, không authenticity, completeness hoặc semantic fidelity.

### Structural và semantic validation

`structural_validation_status` dùng shared `validationStatus` và chỉ được `PASS` khi structural/schema validation **và** các structural-semantic invariants bắt buộc dưới đây thực sự chạy và đạt. Semantic validator kiểm tối thiểu:

- `block_id` unique; `reading_order` unique, monotonic theo array order;
- mọi `parent_block_id` và caption `target_block_id` tồn tại; không self-reference, dangling reference hoặc parent cycle;
- mỗi table row có đúng số cells như `columns`;
- image asset path là strict safe-relative path và checksum/source linkage đầy đủ;
- geometry thỏa coordinate/page bounds;
- unsupported material semantics có linked raw evidence và limitation.

Vì vậy schema acceptance đơn thuần chưa đủ để đặt `structural_validation_status: PASS`; invariant checks chưa chạy phải để `NOT_TESTED`. PASS này vẫn không chứng minh factual accuracy, completeness, source authenticity, render fidelity hoặc broader semantic correctness.

### Geometry invariants

Khi `geometry_status: CAPTURED`, source page phải là số trang hợp lệ; bounding box phải có `page_width` và `page_height`, `x/y >= 0`, `width/height > 0`. Semantic check bắt `x + width <= page_width` và `y + height <= page_height`. Với `NORMALIZED_0_1`, `page_width`/`page_height` đều bằng `1`, coordinate/size nằm trong `[0,1]` và extents không vượt `1`. `GEOMETRY_AWARE` yêu cầu geometry captured cho mọi block material. Thiếu dimension/bounds check làm geometry/visual QA không thể PASS.

## DOCX — `SEMANTIC_EDITABLE`

Ưu tiên styles, heading hierarchy, editable paragraphs/lists/tables, captions, section breaks và accessible reading order. Hình ảnh được chèn dưới dạng asset có source link; không rasterize toàn bộ trang chỉ để giống PDF.

QA tối thiểu:

- headings/paragraphs/tables/images/captions map đúng semantics và thứ tự trong contract; list/footnote semantics ngoài allowlist có limitation rõ;
- content counts và source references tie;
- identifiers, amounts và ambiguous dates không bị đổi nghĩa;
- images/captions/footnotes material không thất lạc;
- file mở được và render inspection không có clipping/overlap nghiêm trọng khi capability có;
- không macro, active content hoặc external link không được phép.

## XLSX — `STRUCTURED_DATA`

Mỗi sheet/table có grain rõ, typed values an toàn, identifier text, raw/normalized/status/provenance fields và dictionary khi cần. Đây là dữ liệu có cấu trúc, không phải page-layout replica.

Với `RECONCILE_DOCUMENT_SET`, `RECONCILIATION_WORKBOOK` là tên view role-aware của canonical extraction/reconciliation results, không phải một conversion-profile enum bổ sung. Tên sheet hoặc column có thể theo matching profile, nhưng phải giữ role ID, source record ID, grain, match/discrepancy status, differences, tolerances và review links. View này không thay 20-sheet generic workbook contract khi generic evidence workbook được yêu cầu.

Áp dụng formula-injection, row-limit, no-truncation và workbook QA trong `output-redaction-and-handoff.md`.

## PPTX — intent-aware

### `EDITABLE_PRESENTATION`

Dùng khi mục tiêu là trình bày. Tạo slide hierarchy, title/body/table/chart/image objects có thể chỉnh sửa; có thể tái bố cục để readable trên slide. Ghi rõ mọi condensation, omission, split/merge hoặc presenter-note placement. Không gọi nội dung tóm tắt là faithful transcription.

### `PAGE_AS_SLIDE`

Dùng khi mục tiêu là xem từng trang gần với source. Mỗi source page map tới một slide và giữ page order/source page ID. Text editability/accessibility có thể thấp hơn vì page có thể được render thành image hoặc nhóm objects.

Page fidelity chỉ là **best effort** và phụ thuộc source geometry, fonts, renderer, image resolution, page/slide aspect ratio và target writer. Không tuyên bố `pixel-perfect`. Thiếu geometry hoặc render comparison capability phải tạo limitation và `qa_status: NOT_TESTED`/failure phù hợp; creation state của file vẫn ghi riêng.

## `VISUAL_FIDELITY_BEST_EFFORT`

Đây là explicit profile cho yêu cầu fidelity cao, không phải cam kết equivalence. Ghi các dimensions cần so sánh: page/slide count, dimensions, text presence, region position, font substitution, table/image bounds, line/page breaks và visual diff threshold được phê duyệt. Chỉ kết luận trên dimensions đã test; không suy từ một screenshot hoặc file mở được.

Nếu editable output và page fidelity xung đột, trình bày trade-off và yêu cầu chọn profile. Không tạo hybrid khó chỉnh sửa mà không ghi rõ.

## Artifact manifest và QA state

Artifact manifest ghi `skill_id`/`skill_release_version`, package/task profile, `generated_at`, top-level quality `status`, human-review status và từng artifact gồm role, format/media type, relative location, checksum, record count, source document IDs, limitations, `creation_status` và `qa_status`. `conversion-run.json` liên kết canonical input, artifact và manifest bằng safe relative path + SHA-256, đồng thời ghi tool/runtime/source release, format, profile và presentation intent; không nhét field ngoài schema vào artifact manifest.

Renderer stage cả ba file trước publication. Từng file replacement là atomic; lỗi publication được bắt sẽ rollback create/overwrite về trạng thái trước. Không gọi cơ chế nhiều rename này là power-loss transaction. Với XLSX, text trên 32.767 code points/cell phải fail-closed, không truncate. Với editable PPTX, split/pagination phải giữ toàn bộ text/table rows và không đặt shape ngoài canvas; `VISUAL_FIDELITY_BEST_EFFORT` phải dùng captured geometry/page dimensions hoặc dừng, không được alias sang editable layout.

- `creation_status: CREATED | NOT_CREATED | BLOCKED` mô tả creation state; `CREATED` yêu cầu safe relative location, checksum và source linkage theo contract.
- `qa_status` dùng `validationStatus`: `PASS`, `PASS_WITH_WARNING`, `FAIL`, `NOT_TESTED`, `NOT_APPLICABLE`, `HUMAN_REVIEW_REQUIRED`.
- `CREATED` + `NOT_TESTED` là hợp lệ khi file đã sinh nhưng render/import/semantic QA chưa chạy.
- `NOT_CREATED`/`BLOCKED` không được QA PASS; dùng `NOT_TESTED` hoặc `NOT_APPLICABLE` và checksum null theo contract.
- Warning nằm ở `qa_status: PASS_WITH_WARNING`, limitations và top-level roll-up; không tạo enum creation kiểu `CREATED_WITH_WARNINGS`.
- Top-level `status: PASS` chỉ khi mọi artifact entry đã khai báo/bắt buộc cho task/profile là `CREATED` và `qa_status: PASS`; không thêm placeholder optional artifact vào manifest PASS.

Manifest-level quality status, descriptor creation/QA và `human_review_status` phải được giữ tách biệt; workflow readiness nằm trong linked run/handoff object. Không nâng thành approved, certified hoặc production-ready. Human acceptance phải có reviewer/decision/reference thực tế.

## Conditional evidence và redaction

Conversion thông thường không tự kích hoạt chain of custody, investigation packaging hoặc redaction. Khi task request yêu cầu các control này, giữ original/derivative distinction, custody/redaction logs và verification gates trong `output-redaction-and-handoff.md`. Không gọi một file đã che bề mặt là redacted verified.
