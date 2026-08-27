# Nghiệm thu bản phát hành 1.1.0

Ngày: 2026-08-27  
Phiên bản phát hành: `1.1.0` — không có hậu tố prerelease  
Product status / QA: `Testing`  
Readiness ceiling: `READY_FOR_HUMAN_REVIEW`

## Phạm vi và ủy quyền

Người dùng đã xác nhận gói cài đặt và yêu cầu chuyển số phiên bản thành 1.1.0 hoàn chỉnh, không dùng rc.1/rc.2. Đây là phát hành gói theo yêu cầu đó, không phải triển khai live hoặc phê duyệt nghiệp vụ/production.

Thay đổi release gồm VERSION, metadata hai plugin và registry, tên ZIP/report, hướng dẫn cài đặt, nhận diện phiên bản trong notices và acceptance tests. Checker thư mục dist được bổ sung rule bỏ qua regular `.DS_Store` của Finder; vẫn từ chối symlink (kể cả dangling) và artifact lạ, không xóa metadata của người dùng. Không đổi instruction nghiệp vụ, script xử lý, schema/config compatibility 1.0.0, matching profiles, templates, logo hoặc fixture provenance.

Ba gói hiện tại:

- `Thien-Skill-Document-Evidence-OpenAI-v1.1.0.zip`
- `Thien-Skill-Document-Evidence-Claude-v1.1.0.zip`
- `Thien-Skill-Document-Evidence-Universal-v1.1.0.zip`

## Bằng chứng

| Kiểm tra | Kết quả |
|---|---|
| Baseline Phase 3 trước promotion | 119 tests: 118 PASS, 1 optional SKIP |
| Regression sau promotion | 145 tests: 144 PASS, 1 optional SKIP |
| Workflow từ ba ZIP 1.1.0 | 24/24 tests PASS: tái dùng 22 packaged checks và thêm 2 kiểm tra promotion |
| Exact build, parity và checksums | PASS; 6 outputs hiện tại, 20 checksum targets của 4 releases |
| Mã nghiệp vụ so với RC2 | PASS; 81/87 portable-core files giữ nguyên, chỉ 6 release-metadata files thay đổi |
| Bảo toàn các release/report/QA RC lịch sử | PASS; RC ZIPs, reports và toàn bộ hồ sơ QA Phase 3 giữ nguyên byte |
| quick_validate.py | UNAVAILABLE — thiếu PyYAML; không tự cài dependency |

Kết quả hiện hành và command tái thực hiện được ghi tại `qa/release-1.1.0/verification.json` trong repository; file đó không nằm trong ZIP. Regression hiện hành giữ các tests RC2 hash-pinned và tái dùng cùng các assertions conversion/RAG/matching cho gói 1.1.0. Tests không tự nâng execution status của behavioral catalog.

## Giới hạn không thay đổi

- Không cài thử hoặc đồng bộ vào thư mục discovery, không commit/tag/push/publication.
- Live Codex/ChatGPT/Claude, OCR receipt/scan, full bank-statement extraction, target RAG ingestion/embedding/retrieval vẫn `NOT_TESTED`.
- Output Office được kiểm cấu trúc; không có lượt visual render mới trong promotion.
- Matching registry có 9 profiles; packaged E2E đại diện bao phủ 7 profiles, không phải mọi biến thể/N-way.
- Tên phiên bản 1.1.0 không tự tạo human independent approval, quyền sử dụng thương mại hoặc chứng nhận pháp lý/production.

## Lịch sử và tái thực hiện

Các gói 1.0.0, rc.1, rc.2, HANDOFF và hồ sơ Phase 3 RC2 giữ nguyên byte. Hồ sơ RC2 là snapshot tại thời điểm nghiệm thu; checker so toàn working tree với baseline RC2 sẽ phát hiện những thay đổi version có chủ đích của bản 1.1.0, không phải bằng chứng gói RC2 bị sửa.

Từ repository:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B build/build_skill_packages.py --check
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -v
```

Từ thư mục dist:

```bash
shasum -a 256 -c SHA256SUMS-v1.1.0.txt
```

Đọc `INSTALLATION.md`, `LICENSE.md`, `LICENSE-APPLICATION.md`, `NOTICE` và `LEGAL-REVIEW-v1.1.0.md` trước sử dụng. Người dùng đã yêu cầu số phiên bản chính thức; đánh giá kỹ thuật lần này là self-check, không có peer/human review mới độc lập.
