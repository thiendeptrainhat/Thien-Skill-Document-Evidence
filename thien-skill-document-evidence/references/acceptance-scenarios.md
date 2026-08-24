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

## Acceptance evidence

Mỗi test record nên có scenario ID, fixture/synthetic source, command/method, expected/actual, pass/fail/not-tested, output hashes/paths, warnings, reviewer và date. Checklist wording hoặc file existence đơn lẻ không chứng minh behavior.
