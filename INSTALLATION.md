# Cài đặt / Installation

Ba gói phát hành được sinh từ cùng một canonical skill và có cùng portable core. Chọn đúng gói cho bề mặt sử dụng; không trộn file giữa các gói.

## Xác minh trước khi cài

1. Giữ nguyên file ZIP đã phát hành.
2. Đối chiếu SHA-256 của ZIP với `SHA256SUMS-v1.0.0.txt`.
3. Kiểm tra `release-manifest-v1.0.0.json` và `PARITY-v1.0.0.json` có `status` phù hợp, trong đó parity phải là `PASS`.
4. Đọc `LICENSE.md`, `LICENSE-APPLICATION.md`, `NOTICE`, `LEGAL-REVIEW.md` và `ACCEPTANCE-REPORT.md` trước khi sử dụng.

## OpenAI / ChatGPT / Codex

Dùng `Thien-Skill-Document-Evidence-OpenAI-v1.0.0.zip`. Đây là skills-only native plugin có `.codex-plugin/plugin.json`, tài sản giao diện và canonical skill tại `skills/thien-skill-document-evidence/`.

- Khi bề mặt hiện tại có chức năng import/upload plugin, upload nguyên ZIP và kiểm tra tên/version trước khi bật.
- Với Codex local, có thể chỉ sao chép thư mục lồng `skills/thien-skill-document-evidence/` vào `$HOME/.agents/skills/` cho phạm vi cá nhân hoặc `.agents/skills/` tại repository cho phạm vi dự án.
- Nếu UI hoặc policy của workspace không cung cấp import plugin riêng tư, dùng cách standalone skill nêu trên; gói này không tự công bố lên universal plugin directory.
- Không cài `.codex-plugin` vào thư mục standalone skills.

## Claude

Dùng `Thien-Skill-Document-Evidence-Claude-v1.0.0.zip`. Đây là native Claude plugin có `.claude-plugin/plugin.json` và skill tại `skills/thien-skill-document-evidence/`.

- Với Claude Code, giải nén an toàn rồi kiểm tra local bằng `claude --plugin-dir /absolute/path/to/thien-skill-document-evidence`; cài thường xuyên qua marketplace cần một private marketplace/repository riêng và không được cấu hình trong release này vì chưa có repository URL được phê duyệt.
- Với Claude Code standalone, sao chép thư mục lồng `skills/thien-skill-document-evidence/` vào `$HOME/.claude/skills/` cho phạm vi cá nhân hoặc `.claude/skills/` tại repository cho phạm vi dự án.
- Với claude.ai hoặc Claude API custom Skills, dùng gói Universal làm Skill ZIP; native Claude plugin ở trên dành cho Claude Code.
- Gói Claude chủ đích không chứa `agents/openai.yaml`.

## Universal Agent Skill

Dùng `Thien-Skill-Document-Evidence-Universal-v1.0.0.zip` cho claude.ai custom Skill upload, Claude API Skills upload, các bề mặt hỗ trợ Agent Skills hoặc cài đặt thủ công. ZIP có đúng một thư mục cấp cao; sau khi giải nén an toàn, thư mục `thien-skill-document-evidence/` phải chứa `SKILL.md` ở ngay cấp gốc. Gói này không chứa adapter riêng của OpenAI hoặc Claude.

## Kiểm tra sau cài đặt

- Xác nhận `SKILL.md` và các file được tham chiếu có thể đọc được.
- Chạy một tình huống smoke test không nhạy cảm, ví dụ: lập inventory cho một bộ tài liệu mẫu và yêu cầu evidence locator ở mức trang.
- Không coi cài đặt cục bộ là xác nhận production. Phiên bản 1.0.0 có trạng thái `Testing` và cần human review theo acceptance report.

## Output của trình đối soát deterministic

`scripts/reconcile_records.py` mặc định ghi full result ra stdout để giữ tương thích. Tùy chọn `--output-view package` tạo canonical extraction-package view; `--output-view discrepancies` chỉ tạo discrepancy register. Ví dụ:

```text
python3 scripts/reconcile_records.py records.json config.json --root /authorized/work --output-view package
python3 scripts/reconcile_records.py records.json config.json --root /authorized/work --output-view discrepancies --output discrepancies.json
```

Đường dẫn `--output` phải nằm dưới `--root`. Script ghi atomic, không ghi đè nếu thiếu `--overwrite`, và luôn từ chối thay thế input/config. Discrepancy là chênh lệch kỹ thuật theo rule, giữ raw values/source IDs và trạng thái human review; nó không tự tạo kết luận nghiệp vụ.

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

Builder chỉ chạy khi host đã có `@oai/artifact-tool`; skill không tự tải hoặc cài dependency. Finalizer dùng Python standard library, luôn tạo output khác input và kiểm tra lại OOXML trước khi publish. Sau cùng vẫn phải mở/render workbook trên ứng dụng đích để kiểm tra row count, kiểu dữ liệu, freeze pane, filter và readability; structural PASS không phải business hoặc visual approval.

## Gỡ cài đặt

Trước khi xóa hoặc thay thế, sao lưu thư mục skill hiện tại nếu có thay đổi cục bộ. Chỉ xóa đúng thư mục `thien-skill-document-evidence`; không dùng lệnh recursive với đường dẫn rộng hoặc chưa xác định.

---

English summary: verify the published checksums and manifests, use the native OpenAI or Claude ZIP for plugin installation, and use the Universal ZIP for portable Agent Skill installation. Version 1.0.0 remains in Testing and requires human review before production use.
