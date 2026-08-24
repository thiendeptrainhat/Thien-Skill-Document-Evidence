# Document package linking và reconciliation

## Mục tiêu

Liên kết document/system records theo business grain và tạo kết quả có thể tái thực hiện. Reconciliation là control độc lập: count match không che amount mismatch; aggregate tie không che line/key exception.

## Chuỗi package tham chiếu

`Contract → Requisition → PO → Delivery/GRN/Acceptance → Invoice → Payment Request/Approval → Bank Payment → ERP Record`

Không yêu cầu mọi package có đủ mọi loại. Expected-document set do process/owner xác định; absence chỉ là discrepancy khi expectation có căn cứ.

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

## Two-, three- và four-way

### Three-way

`PO ↔ Goods Receipt/Acceptance ↔ Invoice`

So sánh vendor/entity, item/PO line, ordered/received/invoiced quantity, UOM, unit price, tax, amount, currency, dates và tolerance.

### Four-way

`Contract/PO ↔ Receipt/Acceptance ↔ Invoice ↔ Payment`

Thêm ceiling/schedule/terms, approval state, amount paid, allocation, value/payment date, fee/withholding, partial/reversal/credit-note effects.

Four-way definition có thể khác theo process; phải ghi config, không hard-code một mô hình duy nhất.

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

Mỗi numeric tolerance là decimal string với unit/basis/owner/approval reference. Currency conversion mặc định disabled; rate/source/date chưa được cấp thì không convert.

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
