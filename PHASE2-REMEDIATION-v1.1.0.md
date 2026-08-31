# QA Remediation — Phase 2 — Thien Skill Document Evidence

Ngày hoàn tất: `2026-08-31`

Baseline được xử lý: `1.1.0 Final` tại commit `f4dd3446bc3b77511013958ee14aa0e7c402224d`

Kết luận Phase 2: **COMPLETE — SOURCE REMEDIATED — READY FOR PHASE 3 INDEPENDENT RETEST**

Readiness của kết luận: `READY_FOR_HUMAN_REVIEW`

## 1. Kết luận điều hành

Tám finding `IQA-001` đến `IQA-008` của Phase 1 đã được xử lý trong canonical source, có regression tương ứng và đã chạy lại từ package Universal dựng tạm. Không còn source blocker High/Critical hoặc hygiene bypass đã biết trong phạm vi retest Phase 2.

Phase 2 không sửa `VERSION`, không ghi đè `dist/`, không commit/tag/push/publish và không biến các thay đổi này thành một bản `1.1.0 Final` khác. Ba ZIP Final và các release lịch sử vẫn là release đã đóng băng. Phase 3 phải tái kiểm độc lập và quyết định phiên bản/promote; current source và frozen `dist/` được kỳ vọng khác nhau cho đến lúc đó.

## 2. Disposition của findings

| Finding | Disposition Phase 2 | Bằng chứng chính |
|---|---|---|
| `IQA-001` — RAG overwrite race | REMEDIATED | Nếu publish gặp destination race, output cũ được khôi phục hoặc backup được giữ với recovery path; regression mô phỏng race đạt. |
| `IQA-002` — OOXML external relationship bypass | REMEDIATED | `.rels` được parse XML có giới hạn, không phụ thuộc whitespace/case; malformed, oversize, DTD/entity đều fail-closed. |
| `IQA-003` — readiness overclaim | REMEDIATED | Helper không tự ghi `READY_FOR_LIMITED_USE`; clean/conditional tối đa `READY_FOR_HUMAN_REVIEW`, còn `FAIL`, `BLOCKED`, unknown hoặc thiếu required role roll up thành `BLOCKED`; workflow manifest và workbook package đồng nhất. |
| `IQA-004` — forged validation report | REMEDIATED | Workbook builder chạy lại bundled validator trên exact package/schema và exact-compare fresh evidence; forged PASS bị từ chối. Package mode cần Python 3; template mode vẫn Node-only. |
| `IQA-005` — mixed source snapshot | REMEDIATED | Checksum, signature và active-content inspection dùng cùng immutable snapshot; thay đổi source trong lúc capture bị chặn. |
| `IQA-006` — thiếu release provenance | REMEDIATED | Đọc release fail-closed từ bundled `VERSION`; workflow manifest ghi `skill_release_version`, còn closed extraction package ghi release trong map mở sẵn `run_manifest.tool_versions` để giữ wire contract `1.0.0` byte-compatible với validator cũ. |
| `IQA-007` — XLSX khó đọc | REMEDIATED | Width theo cột, wrapped cells, header rõ và row height thích ứng tới giới hạn Excel. Visual retest với provenance `659` ký tự hiển thị không overlap; formula-error scan `0`. Dữ liệu cực dài vẫn chịu trần row height của Excel nhưng không bị xóa khỏi cell. |
| `IQA-008` — README dist inventory | REMEDIATED | README phân biệt ba ZIP hiện hành với các release lịch sử được giữ lại. |

## 3. Tinh gọn và chống file rác

Đã xóa hai `.DS_Store` local, cache bytecode do QA sinh và thư mục `registry/` rỗng. Không xóa release lịch sử hoặc duplicate có provenance/packaging intent.

Cổng `build/check_repository_hygiene.py` kiểm actual working tree trước cả build và `--check`:

- cấm cache, log, temp, editor metadata, generated Office ngoài allowlist, symlink, empty directory và special file;
- chặn `.env*`, coverage output, nested `.git`, directory có suffix tạm và lỗi không đọc được subtree;
- hỗ trợ root `.git` dạng file của linked worktree nhưng vẫn từ chối nested `.git`;
- áp budget repository `50 MiB`, `dist` `40 MiB`, regular file `1 MiB`, dist file `5 MiB`, brand asset `2 MiB`;
- áp source soft/hard limit `1500/2500` dòng, retention cap ba version và exact duplicate allowlist;
- build mặc định lẫn `--check` đều từ chối unmanaged artifact trong `dist/`.

Gate hiện `PASS_WITH_WARNINGS`: không có lỗi, bảy duplicate groups đều allowlisted, ba historical versions đúng retention cap. Bốn helper còn vượt soft line limit nhưng dưới hard limit: `build_rag_package.py` `2264`, `prepare_reconciliation_workbook.py` `1961`, `reconcile_records.py` `2145`, `render_canonical_artifacts.py` `2308` dòng. Không tách cơ học trong Phase 2 vì sẽ mở rộng blast radius; hard gate ngăn chúng tiếp tục phình không kiểm soát.

Nguyên tắc runtime/output cũng đã được ghi rõ: intermediate, preview, retry và staging ở ngoài repository/package; chỉ persist artifact cuối được yêu cầu cùng sidecar bắt buộc; không sinh bản `final-final`; output lớn phải ước lượng số file/bytes và dùng control workbook/sidecar hoặc trạng thái `BLOCKED` khi chưa đủ cấu hình. Yêu cầu chunking thiếu target/config phải pause trước publish thay vì tự thay bằng unchunked package.

## 4. Bằng chứng xác minh

| Gate | Kết quả |
|---|---|
| Full regression trên working tree, frozen release được giữ nguyên | `162` tests: `161 PASS`, `1 optional SKIP` |
| Focused remediation chạy từ Universal ZIP dựng tạm | `44/44 PASS` |
| Candidate build và exact `--check` trong `/private/tmp` | PASS, `6/6` generated artifacts reproducible |
| Candidate SHA-256 | `5/5 OK` |
| ZIP structure | Universal, OpenAI, Claude đều `unzip -t` PASS |
| Repository hygiene standalone | PASS, bốn soft LOC warnings |
| XLSX import/style/data/formula scan | PASS |
| XLSX visual retest đại diện | PASS |
| `git diff --check` | PASS |

Optional `quick_validate.py` tiếp tục không khả dụng vì môi trường thiếu PyYAML; dependency không được cài. Đây là `SKIP`, không phải `PASS`.

## 5. Ranh giới release và Phase 3

- `VERSION` vẫn là `1.1.0`.
- `dist/` không có diff và chưa chứa remediation Phase 2.
- Các package dựng trong `/private/tmp` chỉ là probe để chứng minh packaging/parity/checksum/package-native behavior; không phải release được promote.
- Không được rebuild đè `1.1.0 Final`. Phase 3 cần reperform độc lập tám finding, xác nhận release/version strategy, rồi mới quyết định promotion.
- Các khoảng trống live platform, tài liệu/OCR thật, live RAG retrieval, fidelity diện rộng, volume/performance và 64 behavioral scenarios vẫn không được Phase 2 nâng thành PASS.

Machine-readable record: `qa/phase2-1.1.0/verification.json`.
