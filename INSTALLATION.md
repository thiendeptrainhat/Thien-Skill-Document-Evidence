# Cài đặt / Installation

Ba gói phát hành được sinh từ cùng một canonical skill và có cùng portable core. Chọn đúng gói cho bề mặt sử dụng; không trộn file giữa các gói.

`dist/` dùng cấu trúc theo phiên bản. Mỗi `dist/<version>/` là một release độc lập gồm ba ZIP và metadata/checksum tương ứng; không lấy checksum hoặc manifest từ thư mục phiên bản khác.

## Xác minh trước khi cài

1. Giữ nguyên file ZIP đã phát hành.
2. Mở thư mục `dist/1.2.1/` và đối chiếu SHA-256 của ZIP với `SHA256SUMS` trong chính thư mục đó.
3. Kiểm tra `release-manifest.json` và `PARITY.json` trong `dist/1.2.1/` có `status` phù hợp, trong đó parity phải là `PASS`.
4. Đọc `LICENSE.md`, `LICENSE-APPLICATION.md`, `NOTICE`, `LEGAL-REVIEW-v1.2.1.md` và `ACCEPTANCE-REPORT-v1.2.1.md` trước khi sử dụng. Các file version cũ là hồ sơ lịch sử, không phải tài liệu điều khiển bản phát hành hiện tại.

## OpenAI / ChatGPT / Codex

Dùng `dist/1.2.1/Thien-Skill-Document-Evidence-OpenAI-v1.2.1.zip`. Đây là skills-only native plugin có `.codex-plugin/plugin.json`, tài sản giao diện và canonical skill tại `skills/thien-skill-document-evidence/`.

- Khi bề mặt hiện tại có chức năng import/upload plugin, upload nguyên ZIP và kiểm tra tên/version trước khi bật.
- Với Codex local, có thể chỉ sao chép thư mục lồng `skills/thien-skill-document-evidence/` vào `$HOME/.agents/skills/` cho phạm vi cá nhân hoặc `.agents/skills/` tại repository cho phạm vi dự án.
- Nếu UI hoặc policy của workspace không cung cấp import plugin riêng tư, dùng cách standalone skill nêu trên; gói này không tự công bố lên universal plugin directory.
- Không cài `.codex-plugin` vào thư mục standalone skills.

## Claude

Dùng `dist/1.2.1/Thien-Skill-Document-Evidence-Claude-v1.2.1.zip`. Đây là native Claude plugin có `.claude-plugin/plugin.json` và skill tại `skills/thien-skill-document-evidence/`.

- Với Claude Code, giải nén an toàn rồi kiểm tra local bằng `claude --plugin-dir /absolute/path/to/thien-skill-document-evidence`; cài thường xuyên qua marketplace cần một private marketplace/repository riêng và không được cấu hình trong release này vì chưa có repository URL được phê duyệt.
- Với Claude Code standalone, sao chép thư mục lồng `skills/thien-skill-document-evidence/` vào `$HOME/.claude/skills/` cho phạm vi cá nhân hoặc `.claude/skills/` tại repository cho phạm vi dự án.
- Với claude.ai hoặc Claude API custom Skills, dùng gói Universal làm Skill ZIP; native Claude plugin ở trên dành cho Claude Code.
- Gói Claude chủ đích không chứa `agents/openai.yaml`.

## Universal Agent Skill

Dùng `dist/1.2.1/Thien-Skill-Document-Evidence-Universal-v1.2.1.zip` cho bề mặt hỗ trợ Agent Skills hoặc cài đặt thủ công. ZIP có đúng một thư mục cấp cao; sau khi giải nén an toàn, thư mục `thien-skill-document-evidence/` phải chứa `SKILL.md` ở ngay cấp gốc. Gói này không chứa adapter riêng của OpenAI hoặc Claude.

## Kiểm tra sau cài đặt

- Xác nhận `SKILL.md` và các file được tham chiếu có thể đọc được.
- Chạy một tình huống smoke test không nhạy cảm, ví dụ: lập inventory cho một bộ tài liệu mẫu và yêu cầu evidence locator ở mức trang.
- Không coi kiểm tra ZIP hoặc cài đặt cục bộ là xác nhận production. Phiên bản `1.2.1` có trạng thái `Testing` và cần human review theo acceptance report phiên bản tương ứng.
- Bản phát hành 1.2.1 này đã được tạo để cài đặt nhưng không được live-install trên ChatGPT, Codex hay Claude; các gate đó giữ `NOT_TESTED` theo quyết định phạm vi của người dùng.

## Output của trình đối soát deterministic

`scripts/reconcile_records.py` mặc định ghi full result ra stdout để giữ tương thích. Tùy chọn `--output-view package` tạo canonical extraction-package view; `--output-view discrepancies` chỉ tạo discrepancy register. Ví dụ:

```text
python3 scripts/reconcile_records.py records.json config.json --root /authorized/work --output-view package
python3 scripts/reconcile_records.py records.json config.json --root /authorized/work --output-view discrepancies --output discrepancies.json
```

Đường dẫn `--output` phải nằm dưới `--root`. Script ghi atomic, không ghi đè nếu thiếu `--overwrite`, và luôn từ chối thay thế input/config. Discrepancy là chênh lệch kỹ thuật theo rule, giữ raw values/source IDs và trạng thái human review; nó không tự tạo kết luận nghiệp vụ.

## Chuẩn bị reconciliation package và review workbook

Phase 2 bổ sung workflow helper dùng named profile hoặc custom profile, inventory từng input và cô lập lỗi theo file:

```text
python3 /path/to/thien-skill-document-evidence/scripts/prepare_reconciliation_workbook.py \
  --root /authorized/work \
  --profile-id PR_PO \
  --input pr.json \
  --input po.json \
  --output-dir pr-po-review
```

Input là structured document JSON, object có `documents`, hoặc canonical extraction package đã được tạo bởi bước upstream. PDF/ảnh/attachment thô phải được inventory, classify và extract thành contract này trước; helper không tự OCR hoặc gọi model. Bundled registry có các chuỗi `PR_PO`, `PO_GRN_INVOICE`, `PR_PO_GRN_INVOICE`, `CONTRACT_ACCEPTANCE_INVOICE_PAYMENT_REQUEST`, `INVOICE_PAYMENT_BANK_SETTLEMENT`, `CONTRACT_PO_GRN_INVOICE_BANK_PAYMENT`, `CUSTOM_N_WAY` và hai profile mở rộng outbound/inventory. Dùng `--profile-file` cho role chain khác; schema giữ `profile_kind` mở.

Tolerance, partial matching hoặc allocation chỉ được materialize từ `--policy-overrides` đã phê duyệt; không có giá trị mặc định ngầm. Output directory gồm matching profile/config, records, reconciliation result, validated workbook package, role-aware XLSX và workflow manifest. Sheet chỉ xuất hiện khi role/data tương ứng tồn tại. Directory được stage cạnh đích rồi publish no-overwrite bằng rename; output vẫn là technical reconciliation cần human business review, không phải quyết định thanh toán, ghi nhận kho, fraud hoặc audit conclusion.

## Chuyển canonical content thành artifact

Phase 2 cung cấp renderer offline, không tự tải dependency. Input phải validate bằng `canonical-content.schema.json`; artifact, artifact manifest và closed `conversion-run.json` sidecar đều nằm dưới authorized root, không ghi đè mặc định.

```text
python3 /path/to/thien-skill-document-evidence/scripts/render_canonical_artifacts.py canonical.json \
  --root /authorized/work \
  --output out/document.docx \
  --format DOCX \
  --output-profile SEMANTIC_EDITABLE \
  --assets-root assets
```

Đối với XLSX dùng `--format XLSX --output-profile STRUCTURED_DATA`. Đối với PPTX phải ghép đúng `--presentation-intent PRESENTATION --output-profile EDITABLE_PRESENTATION`, `FAITHFUL_PAGE_CONVERSION`/`PAGE_AS_SLIDE` khi canonical content thực sự là `PAGE_IMAGE`, hoặc `VISUAL_FIDELITY`/`VISUAL_FIDELITY_BEST_EFFORT` khi mọi block có geometry/page dimensions hợp lệ. JSON/Markdown không nhận conversion profile. Manifest mặc định là `<output>.manifest.json`; run sidecar mặc định là `<output>.conversion-run.json` và ghi exact input/output checksums, runtime/source release, format, profile và intent.

Renderer kiểm package ZIP/XML, checksum, path, cell-size và semantic invariants trước write. Ba file được stage trước; mỗi replacement là atomic và lỗi publication được bắt sẽ rollback cả bộ. Điều này không phải power-loss transaction trên nhiều filesystem rename. Việc tạo file vẫn chưa phải visual/import QA: DOCX/XLSX/PPTX mới tạo giữ `creation_status: CREATED`, `qa_status: NOT_TESTED` cho đến khi artifact được render/inspect trên runtime đích.

## Tạo RAG source package

Default không chunk:

```text
python3 /path/to/thien-skill-document-evidence/scripts/build_rag_package.py canonical.json \
  --root /authorized/work \
  --output rag-output
```

Collection nhận nhiều canonical input. Chỉ thêm chunks khi có target và config rõ:

```text
python3 /path/to/thien-skill-document-evidence/scripts/build_rag_package.py canonical-a.json canonical-b.json \
  --root /authorized/work \
  --output rag-collection \
  --target-id approved-target \
  --chunk-config chunk-config.json
```

Output có root `rag-package.json`, per-document directory với `document.md`, `metadata.json`, payload `manifest.json`, optional assets/chunks và `collection-manifest.json` khi là collection. Canonical asset phải nằm dưới `assets/`; builder kiểm extension/media type, bounded PNG/JPEG/WebP structure, passive SVG allowlist, checksum, duplicate/reserved/prefix collision, path/symlink/hardlink/input-output collision rồi mới publish directory bằng rename. Đây là structural media/package validation, không phải visual decoder hay target ingestion/retrieval QA. Builder không ingest, tạo embedding/index hoặc kiểm retrieval quality. Dùng `--dry-run` để validate/preview mà không ghi.

## Xuất workbook có kiểm soát

Package JSON phải qua bundled schema trước khi tạo workbook. Với một working directory được phép, chạy ba bước và giữ cả validation report lẫn canonical JSON làm evidence:

```text
python3 /path/to/thien-skill-document-evidence/scripts/validate_records.py package.json \
  --root /authorized/work \
  --schema-root /path/to/thien-skill-document-evidence/schemas \
  --schema common/extraction-package.schema.json \
  --output package.validation.json

node /path/to/thien-skill-document-evidence/scripts/build_workbook.mjs \
  --package /authorized/work/package.json \
  --schema-validation-report /authorized/work/package.validation.json \
  --output /authorized/work/workbook.raw.xlsx

python3 /path/to/thien-skill-document-evidence/scripts/finalize_workbook.py \
  --root /authorized/work \
  --input workbook.raw.xlsx \
  --output workbook.xlsx
```

Builder chỉ chạy khi host đã có Node.js, Python 3 và `@oai/artifact-tool`; skill không tự tải hoặc cài dependency. Trước export, builder tự tái chạy bundled `validate_records.py` trên exact package bytes và yêu cầu report được cung cấp khớp fresh validation evidence; `DOCUMENT_EVIDENCE_PYTHON` chỉ nên trỏ tới Python 3 được tin cậy khi `python3` không nằm trên PATH. Finalizer dùng Python standard library, luôn tạo output khác input và kiểm tra lại OOXML trước khi publish. Sau cùng vẫn phải mở/render workbook trên ứng dụng đích để kiểm tra row count, kiểu dữ liệu, freeze pane, filter và readability; structural PASS không phải business hoặc visual approval.

## Gỡ cài đặt

Trước khi xóa hoặc thay thế, sao lưu thư mục skill hiện tại nếu có thay đổi cục bộ. Chỉ xóa đúng thư mục `thien-skill-document-evidence`; không dùng lệnh recursive với đường dẫn rộng hoặc chưa xác định.

---

English summary: verify the published checksums and manifests, use the native OpenAI or Claude ZIP for plugin installation, and use the Universal ZIP for portable Agent Skill installation. Version `1.2.1` remains in Testing, was not live-installed, and requires human review before production use.
