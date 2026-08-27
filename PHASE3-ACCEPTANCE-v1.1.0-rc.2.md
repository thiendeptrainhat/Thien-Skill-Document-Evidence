# Nghiệm thu Phase 3 — RC2 package-only

**Kết luận kỹ thuật:** `PASS_WITH_LIMITATIONS` trong phạm vi `PACKAGE_ONLY`.  
**Trạng thái hồ sơ:** `COMPLETE_PACKAGE_ONLY` — peer review đã hoàn tất.  
**Phiên bản:** `1.1.0-rc.2` · **Sản phẩm:** `Testing` · **Readiness:** `READY_FOR_HUMAN_REVIEW`.  
**QA disposition:** `ready_with_conditions` · **Human approval:** `pending_human_approval`.  
**Ngày:** 2026-08-27 · **Engagement:** `DE-PHASE3-RC2-20260827` · hồ sơ lưu bền trong repository.

Phase 3 được thực hiện theo yêu cầu chỉ bàn giao gói, không cài thử. Kết luận này chốt nghiệm thu kỹ thuật của ba ZIP RC2, **không chứng nhận toàn bộ cross-platform acceptance của HANDOFF gốc**. Các gate live/OCR/RAG vẫn chưa kiểm. Không nâng stable, commit, tag, push hoặc đồng bộ bản cài local.

## Bàn giao

| Gói | Artifact | Kích thước | Số file |
|---|---|---:|---:|
| OpenAI | [OpenAI RC2 ZIP](dist/openai/Thien-Skill-Document-Evidence-OpenAI-v1.1.0-rc.2.zip) | 3.821.458 bytes | 100 |
| Claude | [Claude RC2 ZIP](dist/claude/Thien-Skill-Document-Evidence-Claude-v1.1.0-rc.2.zip) | 2.719.185 bytes | 97 |
| Universal | [Universal RC2 ZIP](dist/universal/Thien-Skill-Document-Evidence-Universal-v1.1.0-rc.2.zip) | 2.681.864 bytes | 91 |

Các gói giữ nguyên byte từ Phase 2, không rebuild. Hash đầy đủ nằm trong [SHA256SUMS RC2](dist/SHA256SUMS-v1.1.0-rc.2.txt); [release manifest](dist/release-manifest-v1.1.0-rc.2.json) và [parity record](dist/PARITY-v1.1.0-rc.2.json) xác định cùng portable core 87 files.

SHA-256:

- OpenAI: `bc4e26afeace3633fd8f8ab7def510d532cc700dd63ed3dbbf4f8bdcb7a1a514`
- Claude: `ff2e3d17ebb24ca193d35fa49c10b655dd26335eabcf7f1c9414f914d0bfb748`
- Universal: `6d13e21fe7fd177da0da96a06cfb9afedbf2fb848eebf546015c3da0e9b3bc7d`

Dùng [INSTALLATION.md](INSTALLATION.md) khi tự cài sau này. Claude CLI hiện mô tả `--plugin-dir` nhận cả thư mục và ZIP, nên route ZIP trong README và route giải nén trong INSTALLATION đều có căn cứ tài liệu; Phase 3 không chạy CLI để xác nhận runtime. [Nguồn chính thức, kiểm ngày 2026-08-27](https://code.claude.com/docs/en/cli-reference#cli-flags).

## Kết quả đã thực thi

Bằng chứng trực tiếp và command đầy đủ: [executions.json](qa/phase3-rc2/executions.json). Kết quả do agent chạy riêng được tách trong [test-author-report.json](qa/phase3-rc2/test-author-report.json), không trộn thành một lượt chạy.

| Kiểm tra | Kết quả | Phạm vi chứng minh |
|---|---|---|
| Regression baseline trước bổ sung | 97 run: 96 PASS, 1 optional SKIP | Mã nguồn/fixtures hiện hữu |
| Full regression sau bổ sung | **119 run: 118 PASS, 1 optional SKIP** | Root tái chạy trên Python 3.14.5; 17,254 giây |
| Tests mới từ ba ZIP | **22/22 methods PASS; 69/69 subtests PASS** | Agent dùng Python 3.12.13; 22 methods này đã nằm trong 119, không cộng lần nữa |
| Exact deterministic release check | PASS, 6/6 outputs | `build_skill_packages.py --check`, không ghi build output |
| Checksum RC2 + RC1 + 1.0.0 | PASS, 15/15 targets | Chạy từ thư mục dist; không ghi đè lịch sử |
| Ba ZIP RC2 | PASS | CRC, member paths/types/permissions, hashes, adapter versions và core parity |
| JSON nghiêm ngặt / YAML | PASS | JSON không duplicate key/nonfinite; loại fixture invalid có chủ đích; 12 YAML canonical parse được bằng Ruby |
| Local reference review | PASS | Peer kiểm 48 Markdown targets + 27 canonical code-span paths, không thiếu |
| Behavioral catalog | STRUCTURAL ONLY | 64 IDs DE-001…DE-064; execution vẫn NOT_TESTED |
| `quick_validate.py` / optional plugin validator | UNAVAILABLE / SKIP | Thiếu PyYAML; không báo PASS và không tự cài dependency |
| QA contract/invariant verification | PASS | 5 contracts + 5 negative controls; 18 planned/result checks và 152 original hashes reconcile; không phải full Draft 2020-12 certification |
| Final peer review | PASS_WITH_LIMITATIONS | 17 QA checks PASS, 1 inconclusive (optional dependency); không có Critical/High hoặc package-only blocker |

Tests mới [test_phase3_packaged_workflows.py](tests/test_phase3_packaged_workflows.py) pin exact RC2 hashes, kiểm toàn archive trước khi giải nén vào thư mục tạm. Helpers chạy bằng absolute path với `python -I -B`, cwd/PATH rỗng ngoài repository, không inherited PYTHONPATH hoặc credentials. Extracted files và ZIPs được kiểm lại không đổi sau chạy.

### Ba nhóm workflow

- **Conversion:** JSON, Markdown, DOCX, XLSX và PPTX editable tạo được từ canonical synthetic content. Kiểm nội dung, identifier, OOXML, canonical payload, manifest và conversion-run sidecar; output hashes bằng nhau giữa ba layouts. Trạng thái QA của Office chưa render vẫn `NOT_TESTED`, không nâng thành visual PASS.
- **RAG:** default không chunk; explicit target+config mới tạo chunks; collection, dry-run và missing-config negatives đạt. Kiểm payload/descriptor checksums, IDs, provenance và membership. Không tạo embeddings hoặc gọi target.
- **Reconciliation:** so sánh từng raw source field với role worksheet thực tế; kiểm record counts, leading zero, formula literal, role sheets, output checksum, partial allocation và no-overwrite. Test dùng structured records, không chứng minh OCR.

Phase 2 đã có synthetic render evidence DOCX/PPTX và XLSX có cảnh báo print density; đó là **bằng chứng lịch sử**, không phải lượt render mới của Phase 3. Xem [báo cáo Phase 2](ACCEPTANCE-REPORT-v1.1.0-rc.2.md).

### Coverage matching

| Profile | Registry/schema | E2E từ ba ZIP ở Phase 3 |
|---|---|---|
| PR_PO | PASS | Exact PR → PO |
| PO_GRN_INVOICE | PASS | 1 PO + 2 GRN + 2 invoices: 40/60 partial; 60/50 over-allocation → human review |
| PR_PO_GRN_INVOICE | PASS | Exact PR → PO → GRN → invoice |
| CONTRACT_ACCEPTANCE_INVOICE_PAYMENT_REQUEST | PASS | Default CONTRACT + dedicated ACCEPTANCE + invoice + payment request |
| INVOICE_PAYMENT_BANK_SETTLEMENT | PASS | Invoice + payment request + bank transaction |
| CONTRACT_PO_GRN_INVOICE_BANK_PAYMENT | PASS | NOT_TESTED từ ZIP; có nhánh đại diện trong source suite cũ |
| CUSTOM_N_WAY | PASS | NOT_TESTED từ ZIP; có derived dotted-field profile trong source suite cũ |
| OUTBOUND_INVOICE_GOODS_ISSUE_CUSTOMER_RECEIPT | PASS | Sales invoice + warehouse issue + proof of delivery |
| INVENTORY_COUNT_BOOK_STOCK | PASS | Physical count + inventory ledger balance |

Có **7 profile được chạy E2E từ cả ba ZIP**, không phải 9. Source suite và tests mới kết hợp có nhánh đại diện cho chín families, nhưng không bao phủ mọi mapping variant, cardinality hoặc many-to-many business resolution. [Coverage chi tiết](qa/phase3-rc2/coverage.json).

## Gate giữ nguyên NOT_TESTED

| Scenario trong HANDOFF gốc | Codex | ChatGPT | Claude |
|---|---|---|---|
| Ảnh receipt → JSON/XLSX | NOT_TESTED | NOT_TESTED | NOT_TESTED |
| PDF scan nhiều trang → DOCX | NOT_TESTED | NOT_TESTED | NOT_TESTED |
| PDF → PPTX editable | NOT_TESTED | NOT_TESTED | NOT_TESTED |
| PDF → RAG Markdown | NOT_TESTED | NOT_TESTED | NOT_TESTED |
| Folder nhiều chứng từ / attachment equivalents | NOT_TESTED | NOT_TESTED | NOT_TESTED |
| PO-GRN-Invoice matching trên host | NOT_TESTED | NOT_TESTED | NOT_TESTED |
| Four-way có payment/bank trên host | NOT_TESTED | NOT_TESTED | NOT_TESTED |
| Partial delivery/payment trên host | NOT_TESTED | NOT_TESTED | NOT_TESTED |
| Trang mờ/thiếu → review queue | NOT_TESTED | NOT_TESTED | NOT_TESTED |

27 ô này không bị thay bằng kết quả offline. Target RAG ingestion/retrieval, raw-source fidelity và human independent approval cũng chưa thực hiện.

## Findings, điều kiện và giới hạn

- **P3-SCOPE-F01 — OPEN, medium, non-blocking cho package-only:** minimum raw-source corpus còn thiếu receipt image/OCR, multipage scan và bank statement đầy đủ opening/closing balances. Đã bổ sung bộ *structured* hai GRN/hai invoices, nhưng không đóng raw-source gap. Giữ `PARTIAL_COVERAGE`; chưa có chấp nhận rủi ro của người dùng.
- **P3-SCOPE-F02 — CLOSED_VERIFIED (canonical state: closed):** tests mới đã chạy qua các profile/nhánh trước đây thiếu integration evidence và peer đã xác minh closure. Không mở rộng kết luận thành tất cả profile/variant đều chạy trên host.
- **P3-ENV-F03 — OPEN, low, non-blocking:** validator dựa PyYAML chưa chạy được. Internal/package tests và JSON/YAML checks là bằng chứng bổ sung, không giả danh validator chuẩn.

Lượt authoring đầu của test mới có sai expectation `null` so với `NOT_APPLICABLE` cho DOCX/XLSX intent; đã đối chiếu schema và sửa **test oracle**, không sửa sản phẩm. Một checksum invocation phụ sai cwd đã chạy lại đúng từ dist. Cả hai được lưu trong test-author report.

Điều kiện bàn giao do root chịu trách nhiệm tại ngày 2026-08-27: báo cáo phải đi kèm giới hạn trên và giữ RC2/Testing/human-review ceiling; không phát hành claim stable/platform/production. Đối với sử dụng thực tế, người dùng quyết định scope và chỉ định người phê duyệt. Không tự đặt deadline, tự nhận human approval hoặc tự coi rủi ro được chấp nhận.

## Bảo toàn và khả năng tái thực hiện

Baseline là working tree có thay đổi chưa commit, không phải chỉ HEAD `42489dc35ae7bb249504c283a37d52348d200b0d`. [BASELINE.json](qa/phase3-rc2/BASELINE.json) định danh 152 files có trước Phase 3. HANDOFF gốc, canonical source, reports lịch sử và tất cả dist artifacts được giữ nguyên byte. Hash HANDOFF: `3d1c4c360d1f69d3fc23c3b830a28c6f79286f6460dbaa15ddb05fe19b14dd55`. Điều này chứng minh bảo toàn trong cửa sổ review, không chứng minh lịch sử trước baseline.

Chỉ thêm test, báo cáo và hồ sơ QA. Không cài vào thư mục discovery, không chạy host, không upload tài liệu và không gọi OCR/RAG API.

Từ repository:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -B build/build_skill_packages.py --check
PYTHONDONTWRITEBYTECODE=1 python3 -B qa/phase3-rc2/verify_dossier.py
```

Checksum riêng cho test/báo cáo/hồ sơ Phase 3: [SHA256SUMS.txt](qa/phase3-rc2/SHA256SUMS.txt), tạo cuối cùng và không hash chính nó. Kiểm từ repository bằng `shasum -a 256 -c qa/phase3-rc2/SHA256SUMS.txt`.

Từ thư mục `dist`:

```bash
shasum -a 256 -c SHA256SUMS-v1.1.0-rc.2.txt
```

Tests mới pin RC2 nên intentionally fail nếu archive bị thay. Temporary artifacts được cleanup sau test; script, inputs, hashes và command đủ để tái thực hiện. Kiểm QA contracts có thêm command/limitations trong executions.json; cần local skill templates và Ruby, không phải dependency bắt buộc của sản phẩm.

## Vai trò, phê duyệt và hồ sơ

engagement_mode: `assurance_technical_package_only`  
prior_advisory_involvement: `Root đã triển khai Phase 1/2`  
self_review_risk: `present`  
independence_threat: `same-maker self-review; các agent dùng chung workspace/context`  
safeguards: `frozen baseline; isolated ZIP execution; separate-agent peer review; explicit limits`  
reviewer_independence: `self_check + peer_review; không phải human independent assurance`

QA Methodology điều khiển việc tách lớp bằng chứng và trạng thái findings; Master Orchestrator giữ scope/role/approval gates; skill-creator cung cấp validator đã thử nhưng thiếu dependency. Registry snapshot ngày 2026-08-27, xác minh bằng local SKILL.md; versions/roles và workplan đầy đủ tại [CONTROL.json](qa/phase3-rc2/CONTROL.json).

Hồ sơ: [intake](qa/phase3-rc2/qa-intake.json), [inventory](qa/phase3-rc2/artifact-inventory.json), [review plan](qa/phase3-rc2/review-plan.json), [review record](qa/phase3-rc2/review-record.json), [disposition](qa/phase3-rc2/disposition.json), [peer review](qa/phase3-rc2/peer-review-final.json).

Bước an toàn tiếp theo là người dùng nhận/chọn gói. Nếu sau này muốn stable/production hoặc platform certification, mở scope riêng cho live invocation, corpus thực được phép, target RAG và human sign-off. Không còn implementation bắt buộc nào để bàn giao **package-only**; các gate ngoài phạm vi không được coi là đã hoàn thành.
