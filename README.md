<p align="center">
  <img src="./thien-skill-document-evidence/assets/brand/logo-large.png" alt="TDTN logo" width="180">
</p>

# Thien Skill — Document Intelligence, Evidence & Reconciliation

Skill chuyên xử lý tài liệu thành dữ liệu và gói bằng chứng có thể truy nguyên: kiểm kê, phân loại, trích xuất, kiểm tra, đối soát, lập evidence register, tạo workbook/JSON và chuyển các điểm chưa chắc chắn sang human review.

> GitHub là nơi lưu trữ source và các gói phát hành. Việc clone repository **không tự kích hoạt skill**. Skill chỉ hoạt động sau khi được cài vào đúng vị trí discovery hoặc được nạp như plugin trên ChatGPT/Codex/Claude.

## Trạng thái

| Thuộc tính | Giá trị |
|---|---|
| Skill ID | `thien-skill-document-evidence` |
| Version | `1.0.0` |
| Product status | `Testing` |
| Readiness ceiling | `READY_FOR_HUMAN_REVIEW` |
| Repository | Private |
| Owner | Tran Ngoc Thien |
| License | Tran Ngoc Thien's Skills Commercial Source-Available License 2.0 |

Phiên bản này dành cho kiểm thử và human review. Không được hiểu là production-ready, forensic-certified, legal approval hoặc fraud/audit conclusion.

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
(cd dist && shasum -a 256 -c SHA256SUMS-v1.0.0.txt)
```

Trên Linux:

```bash
(cd dist && sha256sum -c SHA256SUMS-v1.0.0.txt)
```

Tất cả artifact phải trả về `OK`. Kiểm tra thêm:

- [release-manifest-v1.0.0.json](./dist/release-manifest-v1.0.0.json);
- [PARITY-v1.0.0.json](./dist/PARITY-v1.0.0.json) phải có `status: PASS`;
- [ACCEPTANCE-REPORT.md](./ACCEPTANCE-REPORT.md);
- [LICENSE-APPLICATION.md](./LICENSE-APPLICATION.md) và [LICENSE](./LICENSE).

### 3. Chọn đúng phương án cài đặt

| Bề mặt sử dụng | Gói/phương án nên dùng |
|---|---|
| Codex local — cài nhanh từ GitHub | `$skill-installer` với đường dẫn canonical skill |
| Codex local — personal/project skill | Sao chép canonical folder vào `.agents/skills/` |
| ChatGPT/ChatGPT Work có quyền import plugin | [OpenAI ZIP](./dist/openai/Thien-Skill-Document-Evidence-OpenAI-v1.0.0.zip) |
| Claude Code plugin | [Claude ZIP](./dist/claude/Thien-Skill-Document-Evidence-Claude-v1.0.0.zip) |
| Claude Code standalone | Sao chép canonical folder vào `.claude/skills/` |
| Nền tảng hỗ trợ Agent Skills chuẩn mở | [Universal ZIP](./dist/universal/Thien-Skill-Document-Evidence-Universal-v1.0.0.zip) |

Không trộn file giữa các gói. Canonical source duy nhất là [thien-skill-document-evidence/](./thien-skill-document-evidence/).

## Cài cho OpenAI ChatGPT và Codex

OpenAI hiện hỗ trợ explicit invocation và implicit invocation: trong ChatGPT, gõ `@` rồi chọn skill; trong Codex CLI/IDE có thể dùng `/skills` hoặc gõ `$` để chọn skill. Codex đọc local skills từ các thư mục `.agents/skills/` ở phạm vi project và `~/.agents/skills/` ở phạm vi người dùng. Xem [OpenAI — Build skills](https://learn.chatgpt.com/docs/build-skills).

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

[Thien-Skill-Document-Evidence-OpenAI-v1.0.0.zip](./dist/openai/Thien-Skill-Document-Evidence-OpenAI-v1.0.0.zip)

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
claude --plugin-dir ./dist/claude/Thien-Skill-Document-Evidence-Claude-v1.0.0.zip
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

[Thien-Skill-Document-Evidence-Universal-v1.0.0.zip](./dist/universal/Thien-Skill-Document-Evidence-Universal-v1.0.0.zip)

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

## Skill mang lại lợi ích gì khi được kích hoạt?

### 1. Tăng khả năng truy nguyên

Mỗi giá trị trọng yếu được thiết kế để liên kết với document, page/region, snippet, extraction method, schema/version, validation và review status. Người kiểm tra có thể lần ngược từ workbook/JSON về nguồn thay vì chỉ nhận một bảng kết quả không có bằng chứng.

### 2. Giảm sai lệch khi trích xuất

Skill buộc tách riêng:

- `raw_value`: dữ liệu đọc được từ nguồn;
- `normalized_value`: giá trị đã chuẩn hóa theo rule/locale;
- `display_value`: giá trị trình bày.

Cách tách này giúp tránh mất leading zero, tự đoán ngày mơ hồ, đổi blank thành zero hoặc ghi đè dữ liệu nguồn.

### 3. Đối soát có kiểm soát

Invoice, PO, GRN, payment/bank hoặc ERP records được liên kết bằng grain, keys, direction, partial rules và tolerance đã khai báo. Kết quả phân biệt exact match, within tolerance, partial, ambiguous, conflicting và unmatched thay vì biến mọi chênh lệch thành một kết luận chung.

### 4. Tạo output phục vụ review

Skill có contracts và templates cho:

- document inventory;
- extraction package JSON;
- field dictionary;
- line-item và clause/obligation registers;
- reconciliation results và discrepancy log;
- evidence register;
- chain-of-custody log;
- human-review queue;
- workbook XLSX có filter, freeze pane và kiểu dữ liệu được kiểm soát.

### 5. Giảm rủi ro từ tài liệu không tin cậy

Instruction, QR, URL, formula-like text, macro marker hoặc OCR text bên trong tài liệu được coi là dữ liệu, không phải lệnh. Skill không tự mở URL, chạy macro, phá password, upload ra ngoài hoặc thay đổi phạm vi vì nội dung nhúng.

### 6. Tái thực hiện và kiểm tra độc lập

Các script deterministic hỗ trợ inventory, schema validation, reconciliation, workbook build/finalization và từ chối overwrite mặc định. Run/config/hash giúp người khác kiểm tra lại cùng input và quy tắc.

### 7. Dùng cùng một logic trên nhiều nền tảng

OpenAI, Claude và Universal packages được sinh từ một canonical source. Portable core parity giúp hạn chế việc cùng một yêu cầu nhưng mỗi nền tảng dùng một bộ quy tắc nghiệp vụ khác nhau.

## Sáu nhóm tính năng chính

| Route | Tính năng | Output điển hình |
|---|---|---|
| `INTAKE_INTEGRITY` | Inventory, SHA-256, MIME/signature, duplicate-content link, encryption/active-content flags, page/completeness status | Document inventory, integrity issues, processing eligibility |
| `CLASSIFY_EXTRACT` | Phân loại tài liệu; ưu tiên native text rồi mới layout/OCR/vision; ghi adapter metadata | Classification result, raw candidates, coverage |
| `STRUCTURE_VALIDATE` | Schema-first extraction cho field, table, line item, party, date, amount, clause và obligation | Validated JSON, field/table registers, review items |
| `LINK_RECONCILE` | Two/three/four-way matching, partial flow, tolerance gate, conflict/duplicate candidate handling | Reconciliation register, discrepancies, unresolved links |
| `EVIDENCE_DISCLOSURE` | Provenance, reliability, chain of custody, redaction working-copy/log, controlled handoff | Evidence package, custody/redaction logs, disclosure limitations |
| `REVIEW_REPERFORM` | Review extraction, schema, workbook, reconciliation, security và unsupported conclusions | QA results, rerun evidence, limitations, human-review queue |

## Tài liệu và tình huống phù hợp

Skill được thiết kế cho:

- PDF có native text, PDF scan và ảnh tài liệu;
- hóa đơn, PO, GRN/biên bản nhận hàng;
- chứng từ thanh toán và bank/ERP records;
- hợp đồng, phụ lục, clause và obligation register;
- receipt/expense và generic business documents;
- document-to-Excel, document-to-JSON và package reconciliation;
- evidence indexing, controlled review và reperformance.

OCR, vision, handwriting, layout/table parsing và redaction thực tế cần runtime adapter do host cung cấp hoặc người dùng phê duyệt. Skill điều phối, đặt contract và guardrail; nó không bundle model OCR/cloud service.

## Điều gì thay đổi trong cách agent làm việc?

Khi skill được kích hoạt, agent được hướng dẫn phải:

1. xác định mục tiêu, authorization, nguồn, data classification và output recipient;
2. giữ original read-only và tách working copy;
3. ghi coverage, exclusions, failure và unresolved items;
4. chọn schema trước khi gọi kết quả là structured extraction;
5. giữ raw/normalized/display values và provenance riêng;
6. hỏi khi grain, key, tolerance, currency/date basis hoặc quyền xử lý thay đổi đáng kể kết quả;
7. đưa ambiguity, conflict và critical uncertainty vào human-review queue;
8. tạo output nhỏ nhất nhưng đủ cho quyết định và tái thực hiện;
9. giới hạn readiness tối đa ở `READY_FOR_HUMAN_REVIEW`;
10. từ chối tự kết luận fraud, legal validity, audit opinion hoặc authenticity.

## Ví dụ prompt

### Document-to-Excel

```text
Dùng $thien-skill-document-evidence để chuyển các hóa đơn này thành workbook.
Giữ invoice number và bank account dưới dạng text, tách raw/normalized values,
trích page-level provenance và đưa ngày mơ hồ vào human review.
```

### Three-way matching

```text
Đối soát invoice–PO–GRN theo PO number, line number và material code.
Không tự đặt tolerance. Ghi exact difference, partial-flow status,
source record IDs và tạo discrepancy register.
```

### Contract extraction

```text
Trích clause và obligation từ hợp đồng cùng phụ lục.
Giữ nguyên base text, tạo supersession links, trích party/action/trigger/due rule/evidence requirement.
Không đưa ra kết luận hiệu lực hoặc compliance.
```

### Evidence review

```text
Review lại extraction package và workbook này.
Kiểm tra source coverage, provenance, leading zeros, ambiguous dates,
formula-like source text, reconciliation rules và readiness status.
```

## Skill không làm gì?

Skill không:

- xác thực chữ ký, con dấu, danh tính người viết hoặc tài liệu thật/giả;
- đưa legal opinion, audit opinion, fraud/misconduct conclusion;
- tự đặt tolerance, business rule, materiality hoặc payment decision;
- tự tải model, cài dependency, mở URL/QR hoặc upload dữ liệu ra ngoài;
- thay thế ETL/ELT hoặc population analytics quy mô lớn;
- gọi checksum là chữ ký số hoặc forensic certification;
- biến extraction/schema PASS thành xác nhận dữ liệu đúng về mặt nghiệp vụ.

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
├── ACCEPTANCE-REPORT.md             # Evidence và release gates
└── LEGAL-REVIEW.md                  # Legal issue-spotting
```

Không sửa trực tiếp nội dung trong `dist/`. Mọi thay đổi portable phải thực hiện tại canonical source rồi chạy lại builder.

## Build và kiểm tra

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B build/build_skill_packages.py
PYTHONDONTWRITEBYTECODE=1 python3 -B build/build_skill_packages.py --check
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_*.py'
```

Release 1.0.0 đã có package parity, checksum, schema/workbook safety và package-native validation. Xem [ACCEPTANCE-REPORT.md](./ACCEPTANCE-REPORT.md) để phân biệt các scenario đã thực thi với catalog `SPECIFICATION_ONLY`.

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
- **Workbook builder thiếu dependency:** host phải có Node.js và `@oai/artifact-tool`; skill không tự cài.
- **OCR/vision không chạy:** cung cấp adapter được phê duyệt hoặc chuyển trạng thái sang `NOT_EXECUTED`/`BLOCKED`/human review.
- **Repository private không clone được:** xác thực đúng GitHub account hoặc token có quyền đọc repository.

Hướng dẫn nâng cao về reconciliation CLI, schema gate, workbook pipeline và gỡ cài đặt nằm tại [INSTALLATION.md](./INSTALLATION.md).

## License và sử dụng có kiểm soát

Áp dụng [Tran Ngoc Thien's Skills Commercial Source-Available License 2.0](./LICENSE). Bản tiếng Việt được ưu tiên khi có mâu thuẫn; pháp luật và tòa án Việt Nam áp dụng theo master license.

Việc xem, clone hoặc nhận package không tự tạo quyền sử dụng thương mại. Đọc [LICENSE-APPLICATION.md](./LICENSE-APPLICATION.md), [NOTICE](./NOTICE), [THIRD-PARTY-NOTICES.md](./THIRD-PARTY-NOTICES.md) và [LEGAL-REVIEW.md](./LEGAL-REVIEW.md) trước khi sao chép, sửa đổi, phân phối hoặc dùng ngoài môi trường kiểm thử.

---

**English summary:** This private repository provides one canonical document-intelligence skill and deterministic OpenAI, Claude, and Universal packages. Install the skill into the discovery location for your platform or load the matching plugin ZIP; hosting it on GitHub alone does not activate it. Once enabled, it guides document inventory, extraction, schema validation, reconciliation, evidence provenance, controlled workbook export, and human review without claiming legal validity, fraud, audit opinion, or document authenticity.
