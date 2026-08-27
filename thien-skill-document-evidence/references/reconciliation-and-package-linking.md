# Document package linking và reconciliation

## Mục tiêu

Liên kết document/system records theo business grain và tạo kết quả có thể tái thực hiện. Reconciliation là control độc lập: count match không che amount mismatch; aggregate tie không che line/key exception.

## Chuỗi package tham chiếu (một ví dụ)

`Contract → Requisition → PO → Delivery/GRN/Acceptance → Invoice → Payment Request/Approval → Bank Payment → ERP Record`

Đây là chuỗi procurement/payables minh họa, không phải ontology đóng. Không yêu cầu mọi package có đủ mọi loại. Expected-document set do process/owner xác định; absence chỉ là discrepancy khi expectation có căn cứ.

Reconciliation dùng `matching_profile_id` và danh sách roles có cấu hình. `role_id` là identifier mở rộng (ví dụ `PURCHASE_ORDER`, `SALES_INVOICE`, `INVENTORY_COUNT`), không phải enum procurement. Document type, business role và physical filename là ba khái niệm riêng.

## Chuẩn bị trước match

Xác định:

- sides/roles và required/optional role;
- grain: document, invoice, PO line, item/lot, payment allocation hoặc other;
- unique/candidate keys và cardinality expected;
- normalization/version;
- date/currency/exchange-rate basis;
- partial delivery/invoice/payment, credit note, reversal và cancellation policy;
- absolute/relative tolerance, unit, basis, owner và approval reference;
- duplicate/multi-candidate/missing-value behavior;
- control totals và coverage period/entities.

Không có tolerance được phê duyệt thì non-zero numeric difference không được `PASS`.

## Match keys

Exact candidates có thể dùng contract/PO/PO line/invoice/GRN/payment refs, vendor/customer code, tax ID, material/item, amount/currency, date, project/cost center, bank account và source-system ID.

Mỗi derived key phải giữ raw components và normalizer version. Chỉ dùng allowlist như `TRIM`, `UNICODE_NFKC`, `CASEFOLD`, `COLLAPSE_WHITESPACE`; separator removal hoặc zero padding cần domain basis.

Fuzzy/weighted similarity nằm ngoài deterministic core. Adapter có thể tạo `STRONG_CANDIDATE`; human/business review phải xác nhận material link.

## Comparator allowlist

- `IDENTIFIER_EXACT`: exact string sau approved normalization; không numeric coercion.
- `EXACT_TEXT`: exact text theo configured case/space policy.
- `NORMALIZED_TEXT`: deterministic normalizer list.
- `DECIMAL_ABSOLUTE`: `abs(left-right) <= tolerance` bằng Decimal.
- `DECIMAL_RELATIVE`: định nghĩa denominator/zero behavior rõ.
- `DATE_WINDOW`: ISO dates và day window đã phê duyệt.

Không cho config chứa code, `eval`, SQL, shell, regex tùy ý hoặc URL action.

## Named matching profiles

Không mô tả workflow chỉ bằng “two-way/three-way/four-way”, vì cùng số sides có thể có roles, grain và control objective khác nhau. Mỗi run phải ghi `matching_profile_id`, profile version, role mapping và config hash.

### `PR_PO_GRN_INVOICE`

Roles tham chiếu: `PURCHASE_REQUISITION` ↔ `PURCHASE_ORDER` ↔ `GOODS_RECEIPT` ↔ `PURCHASE_INVOICE`.

So sánh requester/entity/vendor, requested/ordered/received/invoiced item và quantity, UOM, unit price, tax, amount, currency, dates, approvals và tolerance. Profile phải định nghĩa partial requisition/order/receipt/invoice và amendment/cancellation behavior.

### `CONTRACT_ACCEPTANCE_INVOICE_PAYMENT_REQUEST`

Roles tham chiếu: `CONTRACT` ↔ `ACCEPTANCE_RECORD` ↔ `PURCHASE_INVOICE` ↔ `PAYMENT_REQUEST`.

So sánh contract/version/schedule/ceiling, deliverable/acceptance state, invoice references/amounts và payment-request approvals/allocations. Payment request không được coi là bank settlement.

### `INVOICE_PAYMENT_BANK_SETTLEMENT`

Roles tham chiếu: `PURCHASE_INVOICE` hoặc `SALES_INVOICE` ↔ `PAYMENT_REQUEST`/`PAYMENT_RECORD` ↔ `BANK_TRANSACTION` theo process được cấu hình.

So sánh invoice/party/account/reference/currency, requested/paid/settled amount, value/posting dates, fee/withholding, allocation, reversal và credit-note effects. Bank statement row là source riêng; không mặc định ưu tiên hơn ERP hoặc source document.

Các profile ID trên là defaults/minh họa, không làm registry đóng. Một tổ chức có thể version profile riêng như outbound flow `SALES_ORDER` ↔ `SALES_INVOICE` ↔ `GOODS_ISSUE` ↔ `DELIVERY_NOTE` ↔ `PROOF_OF_DELIVERY`/`CUSTOMER_RECEIPT`, hoặc inventory flow `INVENTORY_COUNT` ↔ `INVENTORY_LEDGER` ↔ `SYSTEM_RECORD`.

Bundled machine-readable profiles nằm dưới `assets/reconciliation-profiles/` và validate bằng `schemas/common/matching-profile.schema.json`. Registry RC2 gồm bảy chuỗi bắt buộc `PR_PO`, `PO_GRN_INVOICE`, `PR_PO_GRN_INVOICE`, `CONTRACT_ACCEPTANCE_INVOICE_PAYMENT_REQUEST`, `INVOICE_PAYMENT_BANK_SETTLEMENT`, `CONTRACT_PO_GRN_INVOICE_BANK_PAYMENT`, `CUSTOM_N_WAY`, cùng hai ví dụ mở rộng outbound/inventory. `profile_kind` là uppercase identifier mở; thêm profile không cần đổi enum nhưng vẫn phải qua schema + semantic validation về unique role/rule/sheet IDs, role references, mapping variants, mode/role count, aggregation, comparator/tolerance unit và date/currency basis.

`mode` trong reconciliation config (`TWO_WAY`, `THREE_WAY`, `FOUR_WAY`, `ERP_DOCUMENT`, `CUSTOM_DETERMINISTIC`) chỉ là technical engine mode để giữ compatibility. Nó không định nghĩa business profile. Dùng `CUSTOM_DETERMINISTIC` khi roles không khớp mode có sẵn; không cần thêm enum mới để mở rộng role set.

## Role registry mở rộng

Role ID nên là stable uppercase identifier và có definition/version trong matching profile. Ví dụ:

- procurement/payables: `PURCHASE_REQUISITION`, `PURCHASE_ORDER`, `GOODS_RECEIPT`, `ACCEPTANCE_RECORD`, `PURCHASE_INVOICE`, `PAYMENT_REQUEST`, `PAYMENT_RECORD`, `BANK_TRANSACTION`;
- sales/fulfilment: `SALES_ORDER`, `SALES_INVOICE`, `GOODS_ISSUE`, `DELIVERY_NOTE`, `PROOF_OF_DELIVERY`, `CUSTOMER_RECEIPT`;
- inventory/system: `INVENTORY_COUNT`, `INVENTORY_LEDGER`, `SYSTEM_RECORD`;
- contractual/custom: `CONTRACT` hoặc domain-specific role theo pattern contract.

Trong registry này, `CUSTOMER_RECEIPT` phải được định nghĩa rõ là customer receipt/acceptance of delivered goods; chứng từ thu tiền dùng role khác như `CUSTOMER_PAYMENT_RECEIPT`. Thêm role không tự tạo comparator, key hoặc tolerance. Profile phải định nghĩa required/optional status, document/schema candidates, grain, keys, cardinality, rules, rollups và missing/multi-candidate policy. “Other document” cần named custom role và definition; không dùng một catch-all không semantics.

## Status

Link status:

- `EXACT_MATCH`;
- `WITHIN_TOLERANCE`;
- `STRONG_CANDIDATE`;
- `PARTIAL_MATCH`;
- `AMBIGUOUS_MATCH`;
- `CONFLICTING_MATCH`;
- `UNMATCHED`;
- `NOT_APPLICABLE`;
- `HUMAN_REVIEW_REQUIRED`.

Run/technical status: `PASS`, `PASS_WITH_WARNINGS`, `CONDITIONAL`, `FAIL`, `BLOCKED`, `NOT_TESTED`, `ERROR`.

`WITHIN_TOLERANCE` phải ghi exact difference và tolerance basis; không đổi thành exact.

## Discrepancy taxonomy

Hỗ trợ missing document/page/field/system record, amount/quantity/price/tax/date/party/account/reference/currency mismatch, signature/approval/acceptance missing, duplicate/version conflict, payment before approval, over-invoice/over-payment, partial transaction, credit/reversal not reflected, contract ceiling exceeded, unresolved OCR và ambiguous match.

Discrepancy là observed difference/absence theo rule; không tự là control failure, immaterial item, fraud hoặc legal breach.

## Duplicate logic

- Same SHA-256: exact-content duplicate candidate.
- Same invoice number + same vendor/entity/currency/amount: business duplicate candidate, vẫn kiểm version/status.
- Same invoice number + different vendor: không tự là duplicate; tạo collision/ambiguity review.
- Duplicate payment cần payment/transaction/account/amount/date/reference logic riêng.

Near duplicate phải nêu compared features/method; không xác nhận identity.

## Partial flows

PO 100, receipt 50, invoice 50 có thể hợp lệ chỉ khi partial policy cho phép và cumulative/remaining quantities được tính đúng. Không so một invoice partial với toàn PO rồi tự fail/pass.

Ghi allocation table:

```yaml
allocation_id: string
source_record_id: string
target_record_id: string
quantity_allocated: decimal-string | null
amount_allocated: decimal-string | null
currency: string | null
basis: string
status: string
```

Không allocate vượt source/target available balance; many-to-many ambiguity cần review.

## ERP/system reconciliation

System data là source riêng, không ưu tiên mặc định hơn document. Mỗi result gồm document/system IDs, match type/keys, document/system values, difference/tolerance, status/reason, source refs và review.

Tách:

- rounding difference;
- timing difference;
- currency-conversion difference;
- partial/allocation difference;
- duplicate system record;
- missing document/system record;
- unresolved source/OCR difference.

Contradictory dates/amounts giữ đủ từng source; không hợp nhất thành một fact.

## Reconciliation config contract

Config versioned và approved:

```json
{
  "schema_version": "1.0.0",
  "config_id": "procurement-three-way",
  "config_version": "1.0.0",
  "mode": "THREE_WAY",
  "grain": "LINE",
  "roles": [],
  "link_rules": [],
  "rollup_rules": [],
  "missing_value_policy": "HUMAN_REVIEW_REQUIRED",
  "multi_candidate_policy": "AMBIGUOUS_MATCH",
  "currency_conversion": "DISABLED",
  "human_approval_status": "PENDING"
}
```

`matching_profile_id` có thể nằm trong task request/profile registry, còn config v1.0 vẫn giữ contract hiện hữu. Không thêm field vào config cũ nếu schema không cho phép; liên kết hai object bằng task/run metadata và hashes.

`schema_version`/`config_version` và reconciliation script/tool compatibility `1.0.0` không phải RC release label và không được relabel. Ghi release provenance bằng `skill_id`/`skill_release_version` trong companion task/artifact objects hoặc release manifest liên kết; giữ config/tool version riêng để tái thực hiện logic v1.

Mỗi numeric tolerance là decimal string với unit/basis/owner/approval reference. Currency conversion mặc định disabled; rate/source/date chưa được cấp thì không convert.

## Workflow helper Phase 2

`scripts/prepare_reconciliation_workbook.py` nhận requested structured JSON/canonical extraction packages trong authorized root, inventory/cô lập lỗi từng file, classify theo named/custom profile, materialize config chỉ từ approved policy input, gọi `scripts/reconcile_records.py` và sinh role-aware workbook/package. Raw PDF/ảnh/attachment cần upstream inventory/classification/extraction; helper không tự OCR, gọi model hoặc mạng.

Output directory được stage cạnh đích rồi publish no-overwrite bằng rename. Nó gồm `matching-profile.json`, `records.json`, `reconciliation-config.json`, `reconciliation-result.json`, `workbook-package.json`, validation report, `reconciliation-workbook.xlsx` và `workflow-manifest.json`. Chỉ tạo role sheet có dữ liệu; luôn giữ `MATCH_RESULTS`, `DISCREPANCIES`, `HUMAN_REVIEW`, `SOURCE_INDEX` hoặc `RUN_LOG` khi có ý nghĩa theo package. `READY_FOR_LIMITED_USE` chỉ hợp lệ khi không có preparation issue và deterministic reconciliation đạt pass state; mọi non-pass chuyển human review, không tự phê duyệt nghiệp vụ.

## Output và QA

Mỗi run ghi config/version/hash, input package/version/hash, run ID, counts/totals theo role, matched/unmatched/ambiguous counts, exact differences, exclusions, warnings/errors và output hash khi có.

QA tối thiểu:

- input counts/totals theo role và grain;
- key uniqueness/cardinality;
- no silent null/float coercion;
- allocations không over-allocate;
- line và aggregate tie-out;
- status/tolerance logic nhất quán;
- every discrepancy resolves source IDs;
- repeated run cùng input/config tạo cùng domain results (trừ explicit run metadata).

`scripts/reconcile_records.py` không quyết định materiality, fraud, payment release hoặc control pass/fail.
