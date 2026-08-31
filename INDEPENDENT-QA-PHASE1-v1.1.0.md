# Independent QA — Phase 1 — Thien Skill Document Evidence 1.1.0

Ngày đánh giá: `2026-08-31`

Release được đánh giá: `1.1.0 Final`

Baseline commit: `f4dd3446bc3b77511013958ee14aa0e7c402224d`

Kết luận Phase 1: **COMPLETE — REMEDIATION_REQUIRED**

Readiness của kết luận QA: `READY_FOR_HUMAN_REVIEW`

## 1. Kết luận điều hành

Release `1.1.0 Final` và ba phase lịch sử vẫn được giữ nguyên như một trạng thái phát hành đã hoàn tất. Tuy nhiên, đợt QA độc lập này **không xác nhận rằng mọi mục tiêu chất lượng đã đạt**.

Kết quả độc lập ghi nhận:

- `4` finding mức **HIGH**;
- `3` finding mức **MEDIUM**;
- `1` finding mức **LOW**;
- nhiều lớp QA đúng trạng thái `NOT_TESTED`, đặc biệt là 64 behavioral scenarios, live platform, tài liệu thật, OCR thật và RAG retrieval thật.

Full regression và package gates đều PASS, nhưng không phủ các adversarial/concurrency cases vừa phát hiện. Phase 2 cần xử lý finding và nguyên tắc tinh gọn; Phase 3 mới tái kiểm độc lập và quyết định closure.

## 2. Phạm vi và nguyên tắc thực hiện

Phase 1 chỉ thực hiện inventory, static review, black-box forward review, package-native workflow execution, negative/adversarial checks và visual inspection mẫu. Không sửa source, không dọn repository, không rebuild release, không cài dependency, không gọi mạng, không cài skill, không commit/tag/push/publish.

Các sản phẩm chạy thử được tạo trong `/private/tmp`, không đưa vào repository. Hai file bằng chứng Phase 1 là thay đổi duy nhất do đợt QA này tạo trong repository. Thay đổi có sẵn của người dùng đối với `HANDOFF.md` được bảo toàn.

## 3. Baseline repository và hygiene

| Chỉ số | Kết quả |
|---|---:|
| Branch | `main`, đồng bộ `origin/main` tại baseline |
| HEAD / origin/main | `f4dd3446bc3b77511013958ee14aa0e7c402224d` |
| VERSION | `1.1.0` |
| Tracked files | `180` |
| Tổng dung lượng tracked | `40,714,289` bytes |
| `dist/` | `24` tracked files, `36,206,018` bytes — khoảng `88.9%` toàn bộ tracked bytes |
| Release ZIPs | `12` files, `36,194,348` bytes |
| Ba ZIP Final | `9,213,420` bytes |
| Chín ZIP lịch sử | `26,980,928` bytes |
| File tracked lớn nhất | `3,821,458` bytes |
| Git object store | `37.50 MiB`, `garbage: 0` |

Kết luận hygiene:

- Không phát hiện cache, bytecode, log, symlink hỏng, file tạm hoặc file untracked thông thường do QA sinh ra.
- Hai `.DS_Store` local được ignore, không tracked; thư mục `registry/` ở root đang rỗng và không tracked.
- Không xác nhận được tracked orphan. Các reference đều được route từ `SKILL.md`; templates được route theo nhóm; report và ZIP lịch sử có preservation intent rõ trong `HANDOFF.md` và `build/config.json`.
- Các bản ZIP lịch sử **không phải file rác theo policy hiện hành**, nhưng là nguồn phình repository lớn nhất. Chỉ nên chuyển sang cơ chế lưu trữ khác khi Phase 2 có quyết định retention rõ.
- Có bảy nhóm duplicate byte-identical. Sáu nhóm là bản root/canonical cần cho packaging; một nhóm là `logo-large.png` và `logo-original.png`, có provenance intent. Tổng duplicate excess khoảng `1.03 MiB`, chưa đủ căn cứ để xóa.
- Hotspot bảo trì: `render_canonical_artifacts.py` 2,264 dòng, `build_rag_package.py` 2,246 dòng, `reconcile_records.py` 2,112 dòng, `prepare_reconciliation_workbook.py` 1,949 dòng và `build_workbook.mjs` 1,089 dòng. Đây không phải orphan, nhưng làm tăng chi phí review và nguy cơ drift của logic path/JSON/atomic-write lặp lại.

## 4. Bằng chứng thực thi

| Gate / workflow | Kết quả |
|---|---|
| Full unittest suite | `145` tests: `144 PASS`, `1 optional SKIP` |
| Exact package build check | PASS |
| Final checksums | `5/5 OK` |
| Package manifest hash verification | Universal `90/90`, Claude `96/96`, OpenAI `99/99` |
| JSON Schema references | `26` schema files, không có `$ref`/fragment thiếu |
| Conversion package-native | JSON, Markdown, DOCX, XLSX và ba PPTX profiles chạy thành công; `14/14` companion objects validate PASS |
| Conversion negative boundaries | ambiguous PPTX, traversal và no-overwrite đều bị chặn; formula payload không tạo formula/external/VBA |
| RAG package-native | single, configured chunks và collection PASS về structure/checksum; rebuild byte-identical |
| Reconciliation package-native | `9/9` profiles chạy kỹ thuật thành công, `36` contract checks PASS, XLSX unzip/formula/external/VBA checks PASS, rebuild byte-identical |
| Intake sampled | MIME mismatch được flag; symlink ra ngoài root bị từ chối |
| Fresh DOCX/PPTX render | PASS về clipping/overflow trên fixture mẫu |
| Fresh XLSX render | import/render PASS nhưng phát hiện vấn đề đọc dữ liệu dài tại IQA-007 |
| Blind forward review | 6/6 tình huống có hành vi fail-closed đúng; hai ambiguity nhỏ được ghi ở Mục 7 |

`quick_validate.py` không chạy được vì môi trường thiếu PyYAML; dependency không được tự cài. Đây là optional SKIP, không được nâng thành PASS.

## 5. Findings đã xác nhận

### IQA-001 — HIGH — RAG overwrite có thể làm mất output cũ khi có race

- Vị trí: `thien-skill-document-evidence/scripts/build_rag_package.py:2087-2105`.
- Khi `--overwrite` chuyển output cũ sang backup, một target cạnh tranh có thể xuất hiện trước lúc publish staging. Rename staging thất bại; do target đã tồn tại, cleanup xóa backup thay vì khôi phục output cũ.
- Repro kiểm soát thu được `original_survives=false`, `racer_survives=true`, `new_exists=false`, `backup_count=0` cùng exception `atomic directory publication failed`.
- Tác động: mất dữ liệu output đã tồn tại trong một đường chạy được ủy quyền overwrite.

### IQA-002 — HIGH — External OOXML relationship có thể lọt qua intake gate

- Vị trí: `thien-skill-document-evidence/scripts/document_inventory.py:378-391` và `:474-491`.
- Detector tìm exact substring `targetmode="external"`; XML hợp lệ `TargetMode = "External"` có whitespace quanh `=` bị bỏ sót.
- Fixture DOCX 479 bytes, SHA-256 `a49c0737e1610a74dd65433482f130b0e19c2d0fd99d22774d678f45cee728a5` cho kết quả sai: `external_links=NOT_DETECTED`, `processing_eligibility=ELIGIBLE`, `review_status=NOT_REQUIRED`, `security_flags=[]`.
- Tác động: tài liệu có external relationship không được cô lập/review theo chính intake policy.

### IQA-003 — HIGH — Readiness ceiling mâu thuẫn và reconciliation overclaim

- Vị trí: `thien-skill-document-evidence/SKILL.md:163`, `references/acceptance-scenarios.md:61`, `scripts/prepare_reconciliation_workbook.py:1689-1720`, `references/reconciliation-and-package-linking.md:188`.
- Top-level skill và acceptance scenario quy định trạng thái tự động tối đa `READY_FOR_HUMAN_REVIEW`, nhưng workflow manifest của cả `9/9` clean reconciliation runs tự ghi `READY_FOR_LIMITED_USE`.
- Workbook package bên trong vẫn ghi `READY_FOR_HUMAN_REVIEW`, tạo bất nhất cross-artifact. Existing tests đang encode `READY_FOR_LIMITED_USE`, nên regression PASS không phát hiện xung đột contract này.
- Tác động: người dùng/downstream system có thể hiểu quá mức mức sẵn sàng của kết quả tự động.

### IQA-004 — HIGH — Workbook builder tin PASS report tự khai và xuất package sai schema

- Vị trí: `thien-skill-document-evidence/scripts/build_workbook.mjs:251-278` và `:324-355`.
- Builder chỉ kiểm shape nông của package và các claim/hash trong validation report; không tái validate schema hoặc xác lập provenance/authenticity của report.
- Package có `document_inventory: [{}]`, vi phạm schema, vẫn được xuất với exit `0` và status `PASS` khi đi kèm report giả có hash khớp.
- Invalid package SHA-256: `7e0aea1ec2b91c356daa9856b638462dea4cc04c31ca8c2a6ae56f9ea2e42bde`.
- Tác động: schema gate có thể bị bypass bởi report cạnh package bị sửa/giả, sinh artifact trông hợp lệ từ dữ liệu không hợp lệ.

### IQA-005 — MEDIUM — Inventory có thể ghép checksum cũ với security metadata mới

- Vị trí: `thien-skill-document-evidence/scripts/document_inventory.py:580-595` và `:431-455`.
- File được hash trước rồi mở lại để đọc signature/active content mà không xác nhận identity/size/mtime hoặc snapshot consistency.
- Repro mutation giữa hai lần đọc tạo report chứa hash của PDF sạch cũ nhưng `javascript=DETECTED` từ bytes mới.
- Tác động: provenance record có thể mô tả hai phiên bản khác nhau của cùng đường dẫn.

### IQA-006 — MEDIUM — Reconciliation output thiếu release provenance 1.1.0

- Vị trí: `thien-skill-document-evidence/scripts/prepare_reconciliation_workbook.py:1787-1794` và `scripts/reconcile_records.py:1905-1911`.
- Giữ tool/schema compatibility ở `1.0.0` là hợp lệ. Vấn đề là workflow manifest không có trường riêng liên kết runtime release `1.1.0`; workbook package chỉ ghi `skill_version` theo `TOOL_VERSION=1.0.0`.
- Tác động: artifact không đủ dữ kiện để phân biệt release skill đã sinh ra nó với phiên bản contract/tool tương thích.

### IQA-007 — MEDIUM — XLSX canonical output làm dữ liệu provenance dài khó đọc

- Vị trí: `thien-skill-document-evidence/scripts/render_canonical_artifacts.py:1035-1111`.
- Tất cả 16 cột dùng width `22`, không có wrap style. Fresh render cho thấy các cell dài như `source_snippet`, JSON và text bị cắt/đè thị giác khi cột kế tiếp có dữ liệu.
- Dữ liệu vẫn còn trong workbook; đây là lỗi usability/visual QA, không phải mất dữ liệu.

### IQA-008 — LOW — README mô tả inventory `dist/` không chính xác

- Vị trí: `README.md:581` ghi “Ba ZIP + checksums/manifests”, trong khi repository giữ `12` ZIP; `README.md:597` mới giải thích các release lịch sử.
- Tác động: người bảo trì dễ hiểu nhầm số artifact thực tế.

## 6. Mức đạt mục tiêu

| Mục tiêu | Kết luận Phase 1 |
|---|---|
| Một skill, ba task profiles và routing | PASS về contract và blind-forward behavior |
| Portable packages / parity / checksums | PASS |
| Conversion | PARTIAL — structural/security PASS; sample visual có lỗi XLSX; native Office/fidelity rộng chưa kiểm |
| RAG source preparation | PARTIAL — package/determinism PASS; overwrite race HIGH; live ingestion/retrieval NOT_TESTED |
| Reconciliation | FAIL tại readiness boundary; core technical `9/9` profiles PASS |
| Intake/security/provenance | PARTIAL — sampled boundaries PASS nhưng có external-link bypass và mixed-snapshot defects |
| Schema-gated workbook export | FAIL tại trust boundary của validation report |
| No-overclaim / human review ceiling | FAIL do IQA-003 |
| Repo hygiene / maintainability | PARTIAL — không có tracked junk/orphan xác nhận; dist retention và các helper lớn là maintenance debt |
| Behavioral acceptance catalog | NOT_TESTED — `64/64` cases vẫn là `SPECIFICATION_ONLY` / `NOT_TESTED` |

## 7. Khoảng trống và ambiguity chưa nâng thành defect

- Live install/smoke trên OpenAI, Claude hoặc host thực: `NOT_TESTED`.
- OCR scan/receipt/handwriting, locale mơ hồ và full bank statement trên dữ liệu thật: `NOT_TESTED`.
- Live RAG ingestion, embedding, indexing và retrieval quality: `NOT_TESTED`.
- Native Office/LibreOffice import và pixel/fidelity comparison diện rộng: `NOT_TESTED`.
- Clause/obligation extraction, custody flow và redaction-removal verification end-to-end: `NOT_TESTED`.
- Performance, volume, Excel row/column overflow và resource exhaustion: `NOT_TESTED`.
- Blind review thấy chưa có quy tắc dứt khoát về việc tự tạo unchunked base package hay pause toàn bộ khi người dùng yêu cầu chunks nhưng thiếu config.
- Blind review thấy top-level roll-up giữa thiếu trang và critical-field failure còn phụ thuộc judgment, chưa deterministic.
- Package-native E2E hiện đã chạy đủ 9 profile trong Phase 1, nhưng suite regression tracked trước đó chỉ đại diện 7/9 profile.

## 8. Candidate controls cho Phase 2 — chưa triển khai

Phase 2 nên xử lý theo thứ tự: bốn finding HIGH, ba finding MEDIUM, rồi hygiene/maintenance. Các nguyên tắc hạn chế file rác/file quá lớn nên được đưa thành rule có thể kiểm tự động:

1. Chỉ tạo intermediate/runtime artifacts ngoài repository; repo chỉ nhận artifact cuối có owner, purpose và retention rõ.
2. Từ chối tracked cache/log/temp/editor metadata; kiểm cả root và `dist/`, không chỉ archive contents.
3. Đặt soft limit cho source file/LOC và yêu cầu lý do/waiver cho helper vượt ngưỡng; tách module theo trust boundary thay vì tách cơ học.
4. Đặt size budget theo nhóm: source, fixtures, brand assets, current release và historical release; mọi ngoại lệ phải allowlist có lý do.
5. Không giữ duplicate binary lớn nếu không có provenance/packaging need được kiểm tự động.
6. Tách current release artifacts khỏi historical retention policy; không xóa ZIP lịch sử trước khi có quyết định lưu trữ và khả năng phục hồi.
7. Thêm regression cho race/rollback, OOXML XML parsing, immutable source snapshot, forged validation report, readiness ceiling và visual XLSX readability.

Không control hoặc remediation nào trong mục này đã được áp dụng ở Phase 1.

## 9. Closure của Phase 1

Phase 1 hoàn tất vì baseline, independent reviews, package/workflow checks, hygiene inventory, findings và phạm vi `NOT_TESTED` đã được ghi lại. Không có kết luận production-ready, forensic-certified, legal-approved hoặc all-goals-pass.

Machine-readable record: `qa/independent-1.1.0/verification.json`.
