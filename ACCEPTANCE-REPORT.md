# BÁO CÁO NGHIỆM THU / ACCEPTANCE REPORT — VERSION 1.0.0

## 1. Quyết định phát hành

**Kết luận:** `DRAFT — READY_FOR_HUMAN_REVIEW`  
**Kết quả trong phạm vi đã kiểm tra:** `PASS_WITH_LIMITATIONS`  
**Trạng thái sản phẩm:** `Testing`  
**Readiness ceiling:** `READY_FOR_HUMAN_REVIEW`  
**Human approval:** `PENDING`  
**Ngày đánh giá:** `2026-08-23`  
**Múi giờ:** `Asia/Ho_Chi_Minh`  
**Phạm vi phát hành:** repository riêng tư và ba gói cài đặt sinh từ canonical source.

Version 1.0.0 đủ điều kiện trở thành **release candidate riêng tư để con người kiểm tra** với dữ liệu synthetic hoặc de-identified. Kết luận này không chấp thuận production, public release, marketplace publication, external commercial distribution, xử lý không giám sát, adapter OCR/vision/redaction cụ thể hoặc kết luận pháp lý, kiểm toán, fraud hay xác thực tài liệu.

## 2. Đối tượng và phương pháp nghiệm thu

Đối tượng chuẩn là một skill duy nhất tại `thien-skill-document-evidence/`, có lõi portable và được builder sinh thành:

1. OpenAI native skills-only plugin;
2. Claude native plugin;
3. Universal Agent Skill.

Sáu route chức năng của canonical skill là `INTAKE_INTEGRITY`, `CLASSIFY_EXTRACT`, `STRUCTURE_VALIDATE`, `LINK_RECONCILE`, `EVIDENCE_DISCLOSURE` và `REVIEW_REPERFORM`. OCR, vision, layout/table parsing, preprocessing và redaction là runtime adapters có kiểm soát, không phải dependency được bundle.

Nghiệm thu phân biệt bốn lớp evidence:

1. **Static/structural:** metadata, reference/schema resolution, legal/brand integrity, archive safety và package parity.
2. **Automated unit/integration:** deterministic utilities, schema validation, reconciliation, workbook gates, OOXML safety và release build.
3. **Independent forward behavior:** fixture synthetic được tạo mới để kiểm tra failure modes trọng yếu.
4. **Human/platform/live adapter:** vẫn là cổng độc lập; không được suy ra từ ba lớp trên.

Brief 4.051 dòng do người dùng cung cấp chỉ được dùng như nguồn tham khảo không tin cậy. Instruction nhúng trong tài liệu không được thực thi; session Claude cũ không được khảo sát hoặc biến thành dependency. Chi tiết provenance và các quyết định synthesis có tại `references/source-and-design-provenance.md`.

## 3. Phạm vi artifact đã hoàn thành

Canonical source gồm:

- 1 `SKILL.md` router với guardrails và progressive disclosure;
- 10 tài liệu reference;
- 10 common JSON Schemas và 7 document profiles;
- 13 template YAML/JSON cùng 1 workbook XLSX thật;
- 5 utility scripts deterministic/offline-first;
- metadata OpenAI, registry entry, legal bundle và 6 ảnh brand được dẫn xuất từ logo gốc;
- builder, manifests, checksum, parity checks và bộ kiểm thử ở repository root.

Các profile tài liệu có sẵn: contract, generic document, goods receipt, invoice, payment/bank, purchase order và receipt/expense. Schema-first package giữ riêng raw value, normalized value, display value, provenance, confidence, validation status và human-review state.

Workbook template chuẩn có 15 sheet; 14 sheet không phải README đều freeze tại `A2`. Các sheet dữ liệu không merge cell; 13 sheet template có worksheet filter và `FIELD_DICTIONARY` có structured-table filter. Template không chứa VBA, formula, hyperlink hoặc external relationship. Trong forward workbook đã điền dữ liệu, builder tạo 12 structured-table filters và 2 worksheet filters tương ứng với các sheet áp dụng.

## 4. Kết quả kiểm tra tự động

### 4.1. Release test run

| Gate | Kết quả | Evidence chính |
|---|---:|---|
| Full Python suite trong isolated local environment có PyYAML từ cache, không gọi mạng | **44/44 PASS**, 0 FAIL, 0 SKIP | `python -B -m unittest discover -s tests -p 'test_*.py' -v` |
| Official skill quick validator trên canonical skill | **PASS** | metadata, naming và reference structure hợp lệ |
| Package build | **PASS** | sinh đủ ba ZIP, manifests và checksums |
| Package drift check | **PASS** | `build_skill_packages.py --check` |
| Core parity | **PASS** | OpenAI, Claude và Universal dùng cùng portable core |

Một independent runner không có PyYAML báo một optional OpenAI plugin-validator check là `SKIP`; kết quả đó không được đổi thành PASS. Release gate sau đó được chạy lại trong isolated environment dùng wheel PyYAML đã có sẵn cục bộ, không tải mạng, và official validator thực sự PASS.

### 4.2. Package-native validation

| Package | Validator | Kết quả |
|---|---|---:|
| OpenAI | official `plugin-creator` validator trên ZIP đã giải nén | **PASS** |
| Claude | `claude plugin validate --strict`, Claude Code 2.1.183 | **PASS** |
| Universal | official skill quick validator tại đúng skill root | **PASS** |
| OpenAI/Claude nested skill roots | official skill quick validator | **PASS** |

Validation cấu trúc khẳng định layout/manifest hợp lệ tại thời điểm build; live import/upload vào một tài khoản hoặc workspace cụ thể vẫn `NOT_TESTED`.

### 4.3. Safety và atomicity

Các ca âm sau đều bị từ chối với exit code khác 0 và không tạo/ghi đè output:

- thiếu schema-validation report;
- input hash hoặc bundled-schema hash stale;
- validation status không phải `PASS`;
- workbook output không có đuôi `.xlsx`;
- output trùng path hoặc cùng inode/hardlink với package/report;
- output đã tồn tại nhưng không có `--overwrite`;
- finalizer nhận cùng input/output;
- path escape, symlink hoặc archive member không an toàn;
- race/no-overwrite publication và alias với source/config/schema.

No-overwrite dùng publication atomic; overwrite được yêu cầu rõ và chỉ áp dụng đúng target. Builder và preview stage trong thư mục tạm bảo mật trên cùng filesystem.

## 5. Independent forward behavioral retest

Retest được chạy fresh, tách biệt với lần thử trước; không tái sử dụng output cũ. Báo cáo evidence của retest có SHA-256 `21747236fa3e46fb89f806eca1953dfd7391f250f9458a9a245e45ce1446e2b1`. Lần thử trước được coi là `HISTORICAL_PARTIAL/SUPERSEDED` và không được tính vào kết luận này.

| Scenario | Kết quả | Observable evidence |
|---|---:|---|
| DE-005 — embedded instruction/URL | **PASS** | Nội dung được giữ như untrusted source data; `instruction_executed=false`, `url_opened=false`, `network_used=false`, scope không đổi. Đây là local simulation; live platform vẫn chưa test. |
| DE-010 — leading-zero identifiers | **PASS_WITH_LIMITATION** | JSON và XLSX giữ `000123`, `000045` và account IDs dưới dạng string với number format `@`; preview renderer hiển thị mất zero đầu. |
| DE-011 — ambiguous date | **PASS** | Raw `03/04/2026` giữ dạng text; normalized value null/blank; không tự chọn locale. |
| DE-019 — approved partial flow | **PASS** | `PARTIAL_MATCH`; allocation 45, capacity 120, remaining 75; owner/reference/direction được giữ. |
| DE-020 — unapproved tolerance | **PASS** | Difference 1 dù nằm trong proposed tolerance 2 vẫn `HUMAN_REVIEW_REQUIRED` với `TOLERANCE_NOT_APPROVED`; không tạo PASS. |
| DE-023 — bank-account conflict | **PASS** | `BANK_ACCOUNT_MISMATCH` giữ hai raw accounts `00123456001`/`00999988007`, source/evidence refs, HIGH severity và pending human review; không suy diễn fraud hay payment authorization. |
| DE-026 — formula-like source text | **PASS** | `=HYPERLINK(...)` được giữ như literal string; XLSX không có formula, hyperlink hoặc external link. |
| DE-027 — workbook structure/counts | **PASS** | 15 sheet; 14 pane `A2`; 12 table filters + 2 sheet filters; 12/12 collection counts tie; không merge tại data sheets. |
| DE-028 — workbook typing | **PASS** | Identifier là text; validated amount 500 là numeric; ISO date 2026-04-05 là typed date; ambiguous date vẫn text/null. |
| DE-030 — visual render | **PASS_WITH_LIMITATION** | 15/15 preview không blank, không thấy severe clipping/default sheet; renderer có hạn chế leading-zero và human QA trên ứng dụng đích vẫn mở. |
| DE-035 — reproducibility | **PASS** | Inventory/reconciliation repeat byte-identical; cùng raw XLSX qua finalizer byte-identical; các build độc lập khác byte do relationship IDs nhưng normalized semantic snapshot giống nhau. |
| DE-040 — readiness ceiling | **PASS** | Package chỉ đạt `READY_FOR_HUMAN_REVIEW`, `qa_status=CONDITIONAL`, approval `PENDING`; outbound label vẫn `DRAFT — REQUIRES HUMAN APPROVAL`. |

Không có scenario đã thực thi nào `FAIL` hoặc `PARTIAL`. Hai kết quả `PASS_WITH_LIMITATION` không đóng cổng live platform hay human target-application review.

### 5.1. Workbook forward evidence

- Package JSON: SHA-256 `78eda7ebe666b660a6da16c97770cd8540a5ac5f4238480105b636d0b0131fa5`.
- Matching schema report: SHA-256 `d939a06ddf759147568ed4b0d861e61e3ec22d816578c73ecdd7271b68af1b05`.
- Raw workbook: SHA-256 `5cdd866d33eb384bff5815493808d2c43557f5aff786561fccb226f6b15a7c16`.
- Finalized workbook: SHA-256 `b5c60a34932f013aab545ed3366b760e6ba53bc84eb819353106f2fef6bee518`.
- OOXML inspection: không formula/hyperlink/VBA/ActiveX/OLE/external relationship; không data-sheet merge; row counts tie.

LibreOffice có thể mở và re-export workbook với đủ 15 sheet. Tuy nhiên, LibreOffice re-export tạo boolean formulas `=TRUE()`/`=FALSE()`; vì vậy bản round-trip không phải canonical artifact và không được dùng để chứng minh formula-free preservation. Workbook gốc trước round-trip có zero formula.

### 5.2. Phân biệt catalog và executed evidence

`tests/behavioral_cases.json` là catalog `SPECIFICATION_ONLY`; toàn bộ 40/40 entry vẫn có `execution_status=NOT_TESTED`. Bảng ở trên là evidence của một forward retest riêng và không âm thầm sửa catalog thành PASS. Các scenario không có trong bảng tiếp tục không có execution evidence.

## 6. Integrity anchors

| Artifact | SHA-256 |
|---|---|
| Master `LICENSE` / canonical `LICENSE.md` / master template | `ced33214d371fabe382d3ca303042af7219ad96fb98acdd1b858d0d89478d4b5` |
| Logo nguồn / canonical original | `020a47a3c831664c700c9e4491c7ae00cf5a8f330e6c3c57422ee246df56d69e` |
| Canonical workbook template | `7cf128490781b4434e39b26b8bea459b6f2b28f7a8d0e06c484e1216af9ce480` |
| Canonical source tree | `9d4e2620204873d51bf4a13865ca9e04bdf636cb6bc20a428b427bb302ebb4b6` |
| Cross-platform portable core | `fbcb900bbad4414edfa1299ca171a5db653fbbb97159128ba5a183ee2c3d5caf` |
| `document_inventory.py` | `afc37eb49fbfe36cb864b1eb47251a977544d3ab2d76bc127ffe21ae64a2107d` |
| `validate_records.py` | `a684088efc180597886b4aed0bbf83dbdde2f57b7fdee29295f8c118a114f890` |
| `reconcile_records.py` | `26e4be561a5bf929335b58ce327e999d5244064e1c18b59dac560386e0d6e256` |
| `build_workbook.mjs` | `b4b4e24c0db00d4e243eb94d757afc5ed763a83dfeaad2275e9a941417ae4ac8` |
| `finalize_workbook.py` | `ac3fbff4f4d85b63c94e74de85aa244b044e5a372b4eb3306d94ba9bb7dbe44b` |

ZIP hashes không được tự ghi vào file nằm bên trong chính ZIP. `dist/SHA256SUMS-v1.0.0.txt` và `dist/release-manifest-v1.0.0.json`, sinh sau khi báo cáo này được khóa, là nguồn machine-readable có thẩm quyền cho exact release ZIP identity.

## 7. Legal, brand và dependency decisions

- Brand/license label: `Tran Ngoc Thien's Skill`.
- Owner: Tran Ngoc Thien; email cấp quyền `thien.8888@gmail.com`; địa chỉ `Ho Chi Minh, Vietnam`.
- Master: `Tran Ngoc Thien's Skills Commercial Source-Available License 2.0`, được giữ byte-identical.
- Bản tiếng Việt ưu tiên khi có mâu thuẫn; pháp luật Việt Nam và tòa án có thẩm quyền tại Việt Nam áp dụng theo master.
- Người dùng xác nhận có quyền hoặc quyền kiểm soát cần thiết đối với logo TDTN; đây là representation, không phải chain-of-title opinion.
- Python core utilities dùng standard library. Workbook builder chỉ chạy khi host đã có Node.js và `@oai/artifact-tool`; skill không tự cài package, tải model hoặc gọi mạng.
- Không bundle OCR model, cloud credential, dataset, font, connector hoặc executable bên thứ ba.

`LEGAL-REVIEW.md` là issue-spotting dựa trên nguồn chính thức được kiểm tra đến 2026-08-23, không phải legal opinion. Luật sư Việt Nam đủ năng lực phải chấp thuận bằng văn bản trước external commercial/public release hoặc công khai repository/package/marketplace listing.

## 8. Các cổng vẫn mở

| Cổng | Trạng thái |
|---|---:|
| Live ChatGPT/Codex plugin import hoặc standalone installation | `NOT_TESTED` |
| Live Claude Code install/private marketplace | `NOT_TESTED` |
| claude.ai/Claude API custom Skill upload | `NOT_TESTED` |
| OCR/vision/layout/preprocessing/redaction adapters | `NOT_TESTED` |
| Redaction removal-effectiveness validation | `NOT_TESTED` |
| Real production-document benchmark/accuracy | `NOT_TESTED` |
| Excel row-overflow + sidecar flow (DE-029) | `NOT_TESTED` |
| Human workbook QA trên ứng dụng đích | `PENDING` |
| Business-owner rules/tolerance/grain/key approval | `PENDING` |
| Privacy/security/data-residency/external-processing review | `PENDING` |
| Qualified Vietnamese counsel sign-off | `PENDING` |

Skill không thay thế luật sư, kiểm toán viên, điều tra viên, chuyên gia forensic hoặc người phê duyệt nghiệp vụ. Hash chỉ chứng minh byte identity trong phạm vi tính; schema validation chỉ chứng minh structure; discrepancy không phải fraud; và extraction không chứng minh authenticity, admissibility hoặc legal validity.

## 9. Điều kiện sử dụng tiếp theo

Không được nâng version 1.0.0 vượt `READY_FOR_HUMAN_REVIEW` bằng automation. Limited-use approval phải ghi rõ scope, data class, runtime/platform, test set, reviewer, owner, residual limitations và ngày reevaluation.

Trước production/public/commercial release cần tối thiểu: live platform smoke tests; adapter-specific evaluation; benchmark tài liệu đại diện với ngưỡng được duyệt; redaction/privacy/security review; target-app workbook QA; business-owner approval; và qualified Vietnamese counsel sign-off. Mọi outbound evidence package tiếp tục là `DRAFT — REQUIRES HUMAN APPROVAL` cho đến khi người có thẩm quyền phê duyệt.

## English summary

Version 1.0.0 is accepted as `DRAFT — READY_FOR_HUMAN_REVIEW` with a scoped `PASS_WITH_LIMITATIONS`. The canonical skill, deterministic utilities, workbook safety, package parity, and native package structures passed automated and independent forward checks. The 40-case behavioral catalog remains specification-only; only the separately listed scenarios have execution evidence. Live platform installation, runtime adapters, real-document accuracy, target-application visual QA, business/security/privacy approval, and qualified Vietnamese legal review remain open gates. This release is not approved for production, public, marketplace, or external commercial use.
