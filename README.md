# Thien Skill — Document Intelligence, Evidence & Reconciliation

Repository nguồn riêng tư của `thien-skill-document-evidence`, một skill duy nhất với lõi portable và ba cách đóng gói: OpenAI native plugin, Claude native plugin và Universal Agent Skill.

## Trạng thái

- Version: `1.0.0`
- Status: `Testing`
- Readiness ceiling: `READY_FOR_HUMAN_REVIEW`
- Owner: Tran Ngoc Thien
- Repository: Private

Skill hỗ trợ intake/integrity, classification/extraction, schema-first structuring, package linking/reconciliation, evidence disclosure và review/reperformance. OCR, vision, preprocessing chuyên dụng và redaction là runtime adapters có kiểm soát; chúng không được bundle hoặc tự gọi mạng.

## Canonical source

`thien-skill-document-evidence/` là nguồn chuẩn duy nhất. Không sửa trực tiếp nội dung trong `dist/`; chạy lại builder để sinh ba gói có cùng portable core.

Các thành phần chính:

- `SKILL.md`: router và guardrails cốt lõi;
- `references/`: quy trình và output contracts;
- `schemas/`: JSON Schema versioned;
- `assets/templates/`: templates trống và workbook XLSX không macro;
- `scripts/`: utilities deterministic, offline-first;
- `agents/openai.yaml`: metadata native OpenAI;
- `platform/`: manifest adapters cho OpenAI và Claude;
- `build/`: builder deterministic và parity checks;
- `tests/`: packaging, script và behavioral fixtures.

## Build và kiểm tra

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B build/build_skill_packages.py
PYTHONDONTWRITEBYTECODE=1 python3 -B build/build_skill_packages.py --check
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_*.py'
```

Đọc `INSTALLATION.md` để chọn gói đúng nền tảng. Đọc `ACCEPTANCE-REPORT.md` trước khi dùng ngoài môi trường kiểm thử.

## License

Áp dụng `Tran Ngoc Thien's Skills Commercial Source-Available License 2.0`. Bản tiếng Việt được ưu tiên khi có mâu thuẫn; pháp luật và tòa án Việt Nam áp dụng theo nội dung master license. Xem `LICENSE`, canonical `LICENSE.md`, `LICENSE-APPLICATION.md` và `NOTICE`.

English summary: this private repository maintains one canonical portable skill and deterministically derives native OpenAI, native Claude, and Universal packages. Version 1.0.0 remains in Testing and is not represented as production-ready.
