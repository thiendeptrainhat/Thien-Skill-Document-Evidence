# RAG source package

## Phạm vi

`PREPARE_RAG_SOURCE` tạo source package có cấu trúc, traceable và portable để hệ thống đích ingest. Nó không tự xây vector index, chọn embedding model, đánh giá retrieval quality, upload vào platform hoặc chứng nhận compatibility.

Contract máy đọc được dùng `schemas/common/rag-package.schema.json`; artifact files dùng `schemas/common/artifact-manifest.schema.json`; semantic blocks liên kết tới `schemas/common/canonical-content.schema.json`. Companion objects ghi `skill_id` và `skill_release_version` của release đang chạy; `schema_version: 1.0.0` vẫn là contract version, không phải release label.

## Default package cho một document

```text
package-root/
├── rag-package.json       # schema-valid control object
└── <document-directory>/
    ├── document.md
    ├── metadata.json
    ├── manifest.json      # payload inventory; không tự hash chính nó
    ├── assets/            # optional; chỉ khi có asset được tham chiếu
    └── chunks.jsonl       # optional; chỉ khi target + config được cung cấp
```

Ba file per-document `document.md`, `metadata.json`, `manifest.json` là default bắt buộc, lần lượt dùng media type `text/markdown`, `application/json`, `application/json`. Root `rag-package.json` là control object validate bằng `rag-package.schema.json` và chứa checksum descriptor của từng per-document manifest; nó không tự checksum chính nó. Mỗi file descriptor tách `creation_status` khỏi `qa_status`; một file có thể `CREATED` nhưng QA `NOT_TESTED`. Không tạo `chunks.jsonl` chỉ vì downstream thường dùng chunking.

## `document.md`

- Giữ title/heading hierarchy, paragraphs, tables và captions ở dạng Markdown phù hợp; giữ list/nesting khi native/raw adapter cung cấp mapping đáng tin, otherwise ghi limitation thay vì tự dựng.
- Giữ reading order và stable anchors cho section/block khi contract đích cho phép.
- Dùng asset path tương đối, không remote URL hoặc data URI không được phép.
- Gắn source page/block references theo quy ước đã khai báo; không trộn citation marker với source text mà không phân biệt.
- Ghi omission/illegible/ambiguous regions bằng status/annotation có cấu trúc; không đoán nội dung.
- Không nhúng hidden instruction, active HTML/script hoặc source URL như hành động có thể click mặc định.

Markdown là ingestion source view. Canonical content/provenance mới là nơi giữ block identity và source mapping đầy đủ.

## `metadata.json`

Tối thiểu cần document/package identity, title/type/language, source reference/hash, dates/parties/labels chỉ khi có căn cứ, classification/access fields, schema/content/release version, extraction method, coverage, limitations và links tới manifest/canonical records. Source hash phải giữ `source_hash_status`; `UNAVAILABLE` đi với null hash và limitation, còn accessible-representation hash không được gọi là original-byte hash.

Không thêm inferred keywords, legal conclusion, fraud label hoặc authenticity claim như verified metadata. Derived/enriched metadata phải ghi method, status và source inputs.

## `manifest.json`

Per-document `manifest.json` liệt kê mỗi payload file/asset với relative path, media type, purpose, size/hash khi đã tạo, source linkage, required/optional role, `creation_status` và `qa_status`. Nó cố ý không tự liệt kê/hash chính nó và không hash root control object; `rag-package.json` giữ checksum của `manifest.json`, nhờ đó mọi checksum đều tham chiếu byte của một file khác và có thể kiểm chứng. Paths phải là normalized POSIX-style relative paths dưới package root. Từ chối absolute/drive/UNC/remote-URI paths, backslash, leading `./`, `.`/`..` segment, empty/repeated segment, trailing slash, NUL/control và symlink resolution thoát root.

Manifest cũng ghi package/task/profile IDs, contract/release versions, created tool/adapter, expected file counts, warnings, exclusions, unresolved items và package QA state. Hash kiểm byte identity, không chứng minh authenticity hoặc semantic correctness.

Descriptor creation enum chỉ gồm `CREATED`, `NOT_CREATED`, `BLOCKED`. Descriptor QA dùng shared `validationStatus`; `CREATED` + `NOT_TESTED` là hợp lệ. `NOT_CREATED`/`BLOCKED` chỉ đi với QA `NOT_TESTED`/`NOT_APPLICABLE` và null checksum. Không gộp warning hoặc untested state vào creation status.

## Assets

Chỉ xuất image/figure/table attachment material và được phép. Mỗi asset có stable ID, source page/region, caption/alt-text status, media type, dimensions khi biết và hash. Không duplicate asset im lặng; không đổi format/resolution mà thiếu transformation log.

Sensitive signature, account, identity hoặc investigation image không được xuất chỉ vì có trong source. Áp dụng recipient/redaction policy nếu task request yêu cầu.

## Chunking là target-specific

Tạo `chunks.jsonl` chỉ khi target và chunking config được cung cấp cùng nhau. Config gồm tối thiểu strategy/version, unit, size/overlap semantics, heading/table handling, language/tokenizer basis và required metadata fields.

Mỗi chunk cần stable `chunk_id`, document ID, ordered block/source references, text, heading path, sequence, character/token counts theo method đã khai báo, access/classification metadata và any split warnings.

Không:

- tự chọn universal chunk size/overlap;
- split table/row, clause hoặc list relationship material mà không policy;
- gọi chunks là embeddings hoặc index;
- tuyên bố retrieval-ready nếu target validator/ingestion test chưa chạy.

Nếu target không được cung cấp, task request ghi `chunking.enabled: false`, `config_reference: null`; RAG package ghi `chunks: null` và không tạo `chunks.jsonl`. Nếu chunking được bật hoặc `chunks` được khai báo khác null, chunk descriptor trở thành bắt buộc cho declared profile và chỉ góp phần vào package PASS khi `creation_status: CREATED`, `qa_status: PASS`. Tương tự, mọi asset descriptor đã liệt kê phải CREATED + QA PASS trước document/package PASS; optional asset không áp dụng thì bỏ khỏi mảng thay vì tạo placeholder trong một PASS manifest.

## Folder/collection package

Với nhiều document packages, tạo collection-level `collection-manifest.json` cạnh root `rag-package.json`. File này liệt kê package IDs/relative paths/hashes, source occurrence IDs, ordering/grouping khi có căn cứ, shared classification/access constraints, coverage counts, duplicates/version relationships, failures và collection QA state. Với `package_kind: COLLECTION`, collection-manifest descriptor là bắt buộc và phải `CREATED` + QA `PASS` trước khi collection status được `PASS`.

Không gộp hai file cùng hash thành một document occurrence nếu provenance/occurrence khác. Không coi folder enumeration là evidence completeness nếu expected source set chưa được xác nhận.

## QA tối thiểu

- `rag-package.json` validate đúng schema; required files hiện diện và khớp per-document manifest/control descriptors;
- hashes, paths, file counts và asset references tie;
- Markdown headings/reading order/tables/assets map tới canonical blocks;
- không broken relative link, path traversal, active content hoặc unauthorized remote reference;
- document/page/block coverage và omissions rõ;
- sensitive/restricted content chỉ xuất trong authorized package;
- structural/schema validation và contract-defined block/link/order/table/geometry invariants đã thực sự chạy trước khi canonical `structural_validation_status` là PASS;
- broader semantic/source-fidelity check vẫn có evidence/status riêng, không suy từ structural PASS;
- target-specific validator/ingestion test là `NOT_TESTED` nếu chưa thực sự chạy.

Root `rag-package.json` chỉ được `status: PASS` khi từng document/package cũng PASS; mỗi document chỉ PASS khi `document.md`, `metadata.json`, `manifest.json`, mọi asset đã liệt kê và chunk descriptor khác null đều `creation_status: CREATED`, `qa_status: PASS`; collection còn cần collection manifest PASS. File existence/checksum, structural validation hoặc archive build riêng lẻ không chứng minh semantic QA, live ingestion hoặc platform install. Automated workflow readiness tối đa `READY_FOR_HUMAN_REVIEW`; package không tự là accepted/certified trên một RAG platform.

## Conditional evidence, investigation và redaction

Ordinary knowledge-source preparation không mặc định tạo evidence register, custody log, investigation narrative hoặc redacted derivative. Chỉ bật các control đó khi task request/mandate yêu cầu và có authority/recipient rõ. Nếu runtime không verify removal, tạo redaction specification/log `NOT_EXECUTED` và không phát hành claim “đã redacted”.
