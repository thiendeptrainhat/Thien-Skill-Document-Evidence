# Task profile và capability-aware routing

## Mục đích

Tài liệu này chọn workflow theo **mục đích đầu ra** và capability thực tế của runtime. Tên nền tảng, package đã đóng gói hoặc extension file không tự chứng minh một parser, renderer, OCR engine, spreadsheet writer hay presentation writer đang khả dụng.

Ba task profile được hỗ trợ ở lớp contract:

- `CONVERT_DOCUMENT`: chuyển tài liệu sang artifact có mục đích sử dụng rõ;
- `PREPARE_RAG_SOURCE`: tạo source package có cấu trúc để một hệ thống RAG đích ingest sau đó;
- `RECONCILE_DOCUMENT_SET`: classify, extract, link và đối soát một tập tài liệu/record theo matching profile được cấu hình.

Task request dùng `schemas/common/task-request.schema.json`. Contract này bổ sung cho extraction package v1.0; không thay thế hoặc âm thầm migrate package cũ.

## Discovery trước khi chọn route

Xác nhận tối thiểu:

1. source format, encryption/readability, native text, semantic styles, tables, images, notes và geometry thực sự lấy được;
2. task profile, intended use, target format/system và ưu tiên giữa editability, structure và page fidelity;
3. adapter/tool khả dụng, version, skill release provenance, execution mode, limits và data-handling policy;
4. output root, overwrite policy, naming, size/volume limits và authorized recipients;
5. validation/render/inspection capability cần để chứng minh artifact đạt acceptance criteria;
6. investigation, custody hoặc redaction requirement **chỉ khi engagement yêu cầu**.

Không tự cài dependency, tải model, dùng external service hoặc upload source khi chưa được phép. Capability không phát hiện được phải là `UNKNOWN`/`NOT_TESTED`, không được suy ra `AVAILABLE`.

## Bảng định tuyến

| Task profile | Canonical intermediary | Output mặc định | Reference điều khiển |
|---|---|---|---|
| `CONVERT_DOCUMENT` | `canonical-content.schema.json`; field/table package khi cần dữ liệu | Theo target và conversion intent | `conversion-output-profiles.md` |
| `PREPARE_RAG_SOURCE` | Canonical content + source metadata/provenance | Root `rag-package.json` + per-document `document.md`, `metadata.json`, `manifest.json` | `rag-source-package.md` |
| `RECONCILE_DOCUMENT_SET` | Extraction package + approved reconciliation config | Canonical results; workbook/sidecar view khi được yêu cầu | `reconciliation-and-package-linking.md` |

`schemas/common/artifact-manifest.schema.json` mô tả artifact được tạo. `schemas/common/rag-package.schema.json` mô tả RAG source package. Schema validation chỉ kiểm contract máy đọc được, không chứng minh semantic correctness hoặc platform acceptance.

## Precedence khi route

1. Áp dụng security/integrity blocker trước mọi conversion hoặc extraction.
2. Chọn task profile từ intended use, không từ extension đích đơn lẻ.
3. Dùng native/structured source route trước OCR/vision khi source đủ đáng tin.
4. Chọn output profile theo semantics ở `conversion-output-profiles.md`; PPTX mơ hồ phải hỏi, giữ `output_profile: null` và ghi `ambiguity_status: CLARIFICATION_REQUIRED` cho tới khi được giải quyết.
5. Chỉ dùng reconciliation khi roles, grain, rules, tolerances và decision owner đủ rõ.
6. Chạy validation phù hợp với output; không dùng file existence như bằng chứng duy nhất.

Một task có thể tạo nhiều artifact, nhưng mỗi artifact phải có purpose/profile, source references và QA status riêng. Không gọi một workbook view là canonical source và không gọi RAG source package là một vector index đã ingest.

Creation và validation là orthogonal: descriptor dùng `creation_status: CREATED | NOT_CREATED | BLOCKED` và `qa_status` theo shared `validationStatus`. File có thể đã `CREATED`, có location/checksum, trong khi visual/semantic/target QA vẫn `NOT_TESTED`. Top-level `status: PASS` chỉ hợp lệ khi mọi descriptor bắt buộc cho profile đã `CREATED` và có `qa_status: PASS`.

## Capability result

Mỗi capability material nên ghi:

```yaml
capability_id: string
adapter_name: string | null
adapter_version: string | UNKNOWN | null
status: AVAILABLE | UNAVAILABLE | UNKNOWN | NOT_TESTED
execution_mode: LOCAL | APPROVED_CLOUD | PLATFORM_NATIVE | MANUAL | null
constraints: [string]
evidence: [object-reference]
checked_at: datetime | null
```

`AVAILABLE` cần bằng chứng từ runtime hiện tại. Package build/check hoặc schema validation không tự là live-install test trên ChatGPT, Codex hay Claude.

## Validation layers

- **Structural/schema:** object đáp ứng type/required/enum/conditional contract.
- **Structural-semantic invariants:** IDs/order/parent/target/table-width/geometry relationships và package roll-up logic được kiểm bằng semantic validator phù hợp; canonical `structural_validation_status: PASS` cần cả hai layer đầu đã đạt.
- **Artifact QA:** file mở/render/import được và format-specific checks thực sự chạy.
- **Target/live platform:** install, ingest hoặc smoke test đã chạy trên platform đích.

PASS ở một layer không lan sang render/target layers hoặc broader factual/semantic correctness. Nếu không có evidence thực thi, layer đó là `NOT_TESTED`; không suy luận canonical structural PASS từ schema validation đơn thuần hoặc live-install PASS từ package build/check.

## Safe relative path gate

Artifact, asset và RAG-package paths phải là normalized POSIX-style paths tương đối dưới authorized package root. Từ chối absolute POSIX path, Windows drive/UNC path, remote URI form như `scheme://...`, backslash, leading `./`, segment `.`/`..`, empty segment hoặc repeated `/`, trailing `/`, NUL/control character và symlink resolution thoát root. Validation regex không thay resolved-path containment check trước read/write.

## Stop và fallback

- Không có parser nhưng source có thể review: tạo manual transcription/review contract; không giả automated extraction.
- Có parser nhưng không có target writer: bàn giao canonical content + artifact specification; ghi `creation_status: NOT_CREATED` và workflow step `NOT_EXECUTED`; QA không được ghi PASS.
- Có writer nhưng không có renderer/inspection: có thể tạo artifact với `creation_status: CREATED`, nhưng visual `qa_status: NOT_TESTED` và limitation phải rõ.
- Source geometry không có: không chọn hoặc hứa page-fidelity conversion.
- Target RAG/chunking contract không được cấp: tạo default unchunked source package; không tự chọn chunk size/overlap.
- Matching roles/rules chưa rõ: tạo clarification item và giữ reconciliation `BLOCKED`; vẫn có thể hoàn tất intake/extraction phần độc lập.

Fallback không được trình bày như platform certification, pixel-perfect conversion, production deployment hoặc human approval.

## Handoff

Khi capability thiếu, handoff phải nêu task profile, source/output contracts, completed artifacts, non-executed steps, blockers, data classification và acceptance evidence còn cần. Status tự động tối đa `READY_FOR_HUMAN_REVIEW`.
