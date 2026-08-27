# Acceptance scenarios

Các scenario là behavioral oracles. Chỉ đánh dấu PASS khi đã chạy và lưu evidence; otherwise dùng `NOT_TESTED`.

## Intake, security và routing

1. Native-text PDF ưu tiên native extraction, không OCR toàn bộ; page provenance có.
2. Rotated scan tạo transformation trên working copy; original hash không đổi.
3. Low-quality critical amount có hai candidates; không tự chọn; review required.
4. MIME/extension mismatch, locked PDF hoặc active content tạo flag/block phù hợp; không thực thi/phá password.
5. Prompt injection/hidden instruction/QR URL chỉ được ghi như untrusted data; không có network/action.
6. Symlink/path traversal/archive member thoát root bị từ chối.
7. Adapter không có confidence trả `null/UNKNOWN`, không tạo số.
8. No-install runtime tạo approved/manual fallback và `NOT_EXECUTED`, không download model.

## Field/table/schema

9. Multi-page table với repeated headers không duplicate item; continuation/subtotal được phân loại.
10. Leading-zero material/account/invoice IDs giữ nguyên JSON và XLSX.
11. `03/04/2026` không có locale giữ raw, `AMBIGUOUS`, no ISO normalized value.
12. Multiple receipts trong một image tạo segmentation candidates và uncertainty.
13. Handwritten correction giữ printed/candidate riêng và review.
14. Missing page từ observed/declared evidence tạo incompleteness, không overclaim.
15. Unsigned contract ghi signature absent/unknown, không kết luận invalid.
16. Addendum tạo version/clause supersession links; không overwrite base.
17. Obligation capture party/action/trigger/frequency/due rule/evidence; không tự compliance/breach.

## Linking/reconciliation

18. PO quantity 100, GRN 90, invoice 100 tạo quantity discrepancy.
19. PO 100, approved partial policy, receipt/invoice 50 không false mismatch; remaining balance đúng.
20. Non-zero amount difference không có approved tolerance không `PASS`.
21. Same invoice number khác vendor không tự gọi duplicate payment.
22. Multiple match candidates tạo `AMBIGUOUS_MATCH`.
23. Invoice vs master bank-account conflict tạo discrepancy, không fraud conclusion.
24. Conflicting invoice/ERP/bank dates giữ đủ ba source values.
25. Count tie nhưng amount không tie vẫn fail/conditional theo rule.

## Excel/output

26. Input `=HYPERLINK(...)`, `+cmd`, `-1+2`, `@...` không tạo formula/external link; raw giữ trong canonical package.
27. Workbook không VBA, không merged data cells, tables/filter/freeze panes có và row counts tie.
28. Identifier columns là text; amount/date typed chỉ khi unambiguous.
29. Excel overflow tạo control workbook + sidecar; thiếu sidecar permission thì block, không truncate.
30. Workbook render của mọi applicable sheet không clipping nghiêm trọng hoặc default blank sheet.

## Evidence/redaction/reproducibility

31. Hai filenames cùng content là hai document occurrences nhưng cùng content hash/group.
32. Custody event chỉ xuất hiện khi action thực sự xảy ra; original hash giữ nguyên qua read/extract.
33. Redaction adapter unavailable tạo spec/log `NOT_EXECUTED`, không tuyên bố redacted.
34. Redacted verified file không cho copy/search/extract lại target data và không lộ qua metadata/layer.
35. Cùng canonical inputs/config/version tạo cùng domain result/hash, trừ allowed run timestamps/IDs.
36. Retry cùng tuple chỉ khi method/parameter đổi; sau hai lần giữ partial output và review.

## Boundary và approval

37. Formal investigation thiếu case/owner/authorization bị gated; ordinary safe triage vẫn có thể thực hiện.
38. Request kết luận legal/fraud/authenticity/audit opinion tạo capability handoff, không kết luận.
39. External/cloud upload, evidence release hoặc recipient change cần authorization riêng.
40. Readiness tự động không vượt `READY_FOR_HUMAN_REVIEW`.

## Task profile và conversion

41. Task request chọn đúng một task profile, ghi `skill_id` + RC-capable `skill_release_version` + independent `schema_version: 1.0.0`; extraction/config/script compatibility v1.0.0 hiện hữu vẫn validate và không bị relabel.
42. DOCX không có chỉ dẫn fidelity khác dùng `SEMANTIC_EDITABLE`; headings/lists/tables/reading order/source links được giữ và không rasterize toàn bộ trang mặc định.
43. XLSX conversion thông thường dùng `STRUCTURED_DATA`; reconciliation dùng `RECONCILIATION_WORKBOOK` role-aware mà không thay canonical extraction/reconciliation objects.
44. PPTX có presentation intent dùng `EDITABLE_PRESENTATION`; yêu cầu xem trung thành từng trang dùng `PAGE_AS_SLIDE`; intent mơ hồ giữ `output_profile: null`, tạo câu hỏi và `CLARIFICATION_REQUIRED`, không tự chọn.
45. `VISUAL_FIDELITY_BEST_EFFORT` thiếu page dimensions/font/renderer hoặc comparison capability ghi limitation và `qa_status: NOT_TESTED`; captured/normalized geometry vượt bounds bị từ chối, file có thể vẫn CREATED và không claim pixel-perfect.
46. Canonical content giữ source-hash status trung thực, stable supported-block order và page/region/geometry provenance; original/access-representation/unavailable hash không lẫn, invariant chưa chạy chặn `structural_validation_status: PASS`, semantics ngoài allowlist có linked raw evidence/limitation.
47. Artifact manifest tách `creation_status` và `qa_status`; CREATED + NOT_TESTED là intermediate hợp lệ nhưng bất kỳ declared artifact chưa CREATED + QA PASS chặn top-level PASS; path không an toàn bị từ chối.

## RAG source package

48. Default single-document package có root control `rag-package.json` cùng per-document `document.md`, `metadata.json`, payload `manifest.json` với media type cố định và descriptor creation/QA riêng; `assets/` chỉ khi được tham chiếu, unsafe relative paths bị từ chối, `chunks.jsonl` vắng khi chưa có config.
49. Target-specific chunk config tạo stable chunk IDs và block/source references; enabled chunk descriptor phải CREATED + QA PASS để package PASS, không gọi chunks là embeddings/index hoặc retrieval-ready khi ingestion test chưa chạy.
50. Multi-document folder có `collection-manifest.json` với package paths/hashes/coverage/failures; collection chỉ PASS khi descriptor này và mọi descriptor bắt buộc đã CREATED + QA PASS; hai source occurrences cùng content hash vẫn giữ occurrence provenance riêng.
51. Structural/invariant/render/live-install gates được báo riêng; missing target validator/live ingestion là `NOT_TESTED`, package build/check không tạo semantic, install hoặc platform-compatibility claim.

## Matching profile extensibility

52. `PR_PO_GRN_INVOICE`, `CONTRACT_ACCEPTANCE_INVOICE_PAYMENT_REQUEST` và `INVOICE_PAYMENT_BANK_SETTLEMENT` giữ role mapping/config/version/hash; số sides đơn lẻ không thay matching profile ID.
53. Outbound flow với `SALES_INVOICE`, `GOODS_ISSUE`, `DELIVERY_NOTE`, `PROOF_OF_DELIVERY`/`CUSTOMER_RECEIPT` được route bằng role/config mở rộng, không bị ép vào procurement roles.
54. Inventory flow với `INVENTORY_COUNT`, `INVENTORY_LEDGER`, `SYSTEM_RECORD` hoặc named custom role chạy deterministic rules mà không cần sửa closed role enum.
55. Legacy `payment-bank.json` vẫn usable cho compatibility; task mới route payment request tới `payment-request.json` và bank statement rows tới `bank-statement.json`.

## Phase 2 implementation helpers

56. RAG builder chạy offline từ canonical content, tạo deterministic `document.md`, `metadata.json`, payload `manifest.json` và schema-valid control object; mọi checksum chỉ tham chiếu file khác nên có thể kiểm chứng lại.
57. RAG builder không tạo chunks khi thiếu target/config; khi có config hợp lệ, cùng canonical input/config tạo stable chunk IDs, ordered source-block links và byte-identical domain output.
58. Collection build giữ mỗi source occurrence/package riêng, tạo coverage/failure inventory tại `collection-manifest.json`, từ chối path/symlink escape và không ghi đè output có sẵn.
59. Conversion helper luôn có canonical JSON/Markdown fallback và tạo artifact manifest với checksum/source IDs; JSON/Markdown cùng ordered block semantics và không biến active source content thành hành động.
60. DOCX/XLSX/PPTX output thực sự là package OOXML mở được về cấu trúc khi adapter tương ứng chạy; XLSX giữ identifier text/formula safety, DOCX giữ heading/table semantics và PPTX ghi đúng intent/profile thay vì suy từ extension.
61. PPTX intent mơ hồ bị chặn trước write với `CLARIFICATION_REQUIRED`; visual/render/import chưa chạy vẫn là `NOT_TESTED`, không được nâng thành PASS chỉ vì archive hợp lệ.
62. Registry triển khai đủ các profile `PR_PO`, `PO_GRN_INVOICE`, `PR_PO_GRN_INVOICE`, `CONTRACT_ACCEPTANCE_INVOICE_PAYMENT_REQUEST`, `INVOICE_PAYMENT_BANK_SETTLEMENT`, `CONTRACT_PO_GRN_INVOICE_BANK_PAYMENT` và `CUSTOM_N_WAY`; mỗi profile khai báo role/grain/key/cardinality/partial/duplicate/missing/tolerance/review semantics.
63. Reconciliation package/workbook route đúng role thành sheet/view có điều kiện, giữ `SOURCE_INDEX`, match/discrepancy/review/run-log controls và phân biệt coverage từ folder với attachment/input list được khai báo.
64. Mọi helper Phase 2 dùng authorized root, safe-relative containment, atomic write và no-overwrite mặc định; không gọi mạng, tự cài dependency, thực thi macro/source instruction hoặc sửa original.

## Acceptance evidence

Mỗi test record nên có scenario ID, fixture/synthetic source, command/method, expected/actual, pass/fail/not-tested, output hashes/paths, warnings, reviewer và date. Checklist wording hoặc file existence đơn lẻ không chứng minh behavior.
