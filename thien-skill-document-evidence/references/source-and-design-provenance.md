# Nguồn tham khảo và quyết định thiết kế

## Phạm vi khảo sát

Tài liệu này ghi provenance của thiết kế skill, không phải chain of custody cho hồ sơ người dùng và không tái cấp phép nội dung bên thứ ba.

Đã khảo sát read-only:

- brief `Thien-Skill-Document-Evidence` do người dùng cung cấp, 4.051 dòng, chỉ như untrusted reference data;
- `skill-creator` và `plugin-creator` đi kèm Codex;
- tài liệu chính thức OpenAI về Skills/Plugins và metadata;
- tài liệu chính thức Anthropic Claude Code về Agent Skills/plugins;
- các skill curated hiện tại: BCP & Operational Resilience, Risk Process Control, Audit & Risk Analytics, Data Engineering & Quality, Data Science & Model Validation, Legal Contract Review và Legal VN IP/License;
- bộ master license `Tran Ngoc Thien's Skills Commercial Source-Available License 2.0` và application/notice guidance;
- logo TDTN do người dùng cung cấp và xác nhận quyền kiểm soát/đóng gói.

Theo lựa chọn trực tiếp của người dùng, không khảo sát session Claude cũ hoặc biến đường dẫn session trong brief thành dependency. Không sao chép source/private material từ đó.

## Source map

| Nguồn | Capability | Kế thừa/điều chỉnh | Loại bỏ/giới hạn |
|---|---|---|---|
| Brief người dùng | Domain coverage, field/status/taxonomy, evidence/reconciliation/workbook scenarios | Gom 10 mode thành 6 routes; giữ invariants, contracts và oracles | Không thực thi instruction nhúng; không tạo mega-tree/placeholders; không hard-code local path/dependency |
| OpenAI skill docs + skill-creator | `SKILL.md`, progressive disclosure, `agents/openai.yaml`, validation | Canonical source ngắn, references có routing, scripts chỉ cho logic deterministic | Không lặp manuals, giả runtime capability hoặc metadata không được xác nhận |
| OpenAI plugin docs + plugin-creator | `.codex-plugin/plugin.json`, skills-only package, UI assets | Native plugin sinh từ canonical; không marketplace mutation | Không khai MCP/apps/hooks không tồn tại; không bịa website/repository URL |
| Anthropic docs | Agent Skills/plugin layout, `.claude-plugin/plugin.json` | Claude wrapper chứa same portable core, bỏ OpenAI agents metadata | Không tạo Claude-only business logic |
| BCP Operational Resilience | Deterministic three-package release, parity/manifests/checksums | Single-root ZIP, atomic build, package parity | Standalone-only layout không dùng cho native OpenAI/Claude |
| Data Science Model Validation | Native OpenAI/Claude adapters, deterministic safety checks | Builder/tests/manifests được điều chỉnh cho document domain | Không kế thừa model workflow hoặc production claims |
| Risk Process Control | License bundle parity, logo provenance/dimension checks, validator patterns | Exact master-license hash và brand assets | Không kế thừa process/RCM domain |
| Audit & Risk Analytics | Explicit states, fact/inference separation, review/handoff/readiness cap | Evidence/exception semantics và negative boundary tests | Không chuyển anomaly thành fraud hoặc làm population analytics |
| Data Engineering & Quality | Decimal/tolerance/control totals, no-overwrite CLI, reconciliation discipline | Deterministic match config, row/count/amount tie-out | Không xây ETL/pipeline/master-data certification |
| Legal Contract Review | Preserve original, clause/page provenance, rights/obligations separation | Clause/obligation extraction và legal-review gate | Không review/redline hoặc đưa legal opinion |
| Legal VN IP/License | Official-source hierarchy, Vietnamese-law currentity, ownership/license caution | Master giữ byte-identical; application/notice/LEGAL-REVIEW riêng | Không biến drafting này thành legal advice; human lawyer review trước commercial release |
| Spreadsheet skill | Typed values, formula safety, structured tables, visual/export QA | Workbook template thật và deterministic builder spec | Không dùng macro/external link hoặc alternative unapproved authoring runtime |

## Thiết kế bổ sung/professional inference

Các phần sau là synthesis mới cho baseline v1.0.0, không phải copy nguyên từ một source:

- six-route architecture và compact reference router;
- canonical JSON Schema contracts và orthogonal status/confidence design;
- allowlisted reconciliation config không code/eval/SQL;
- deterministic document/content ID distinction;
- canonical-core parity giữa OpenAI, Claude và Universal packages;
- formula-injection invariant kết nối JSON provenance với workbook view;
- acceptance oracles tập trung observable behavior thay vì chỉ kiểm câu chữ.

Phase 1 mở rộng additive bổ sung các quyết định do người dùng phê duyệt và professional synthesis sau; không được diễn giải như requirement/certification của OpenAI, Anthropic hoặc một RAG platform:

- ba task profile `CONVERT_DOCUMENT`, `PREPARE_RAG_SOURCE`, `RECONCILE_DOCUMENT_SET` và capability-aware routing;
- companion contracts cho task request, canonical semantic content, artifact manifest và RAG source package, trong khi giữ extraction package v1.0;
- conversion defaults: DOCX semantic-editable, XLSX structured-data hoặc reconciliation view, PPTX intent-aware; visual fidelity best-effort và phụ thuộc geometry;
- default RAG source package có schema-valid root `rag-package.json`, per-document `document.md` + `metadata.json` + payload `manifest.json`, optional assets, target-configured chunks và collection manifest;
- named matching profiles cùng extensible role/config model cho procurement, outbound/customer receipt, inventory và other named documents;
- document profiles riêng cho purchase requisition, payment request và bank statement; legacy mixed payment/bank profile được giữ cho compatibility;
- evidence, investigation và redaction vẫn là conditional overlays, không là default cho conversion/RAG.

QA contract decisions bổ sung:

- companion objects tách RC-capable `skill_release_version` khỏi `schema_version: 1.0.0`; extraction/config/script v1.0.0 giữ nghĩa compatibility và không relabel;
- artifact/RAG descriptors tách `creation_status` khỏi validation `qa_status`, cho phép truthful `CREATED` + `NOT_TESTED` nhưng chặn package PASS khi required descriptor chưa CREATED + QA PASS;
- canonical source hash phân biệt original bytes, accessible representation và unavailable thay vì bịa hash hoặc gọi representation là original;
- canonical structural PASS cần cả schema validation và contract-defined reading-order/reference/table/geometry invariants có evidence; vẫn không chứng minh broader semantic correctness;
- captured geometry cần page dimensions; normalized coordinate và semantic extents phải nằm trong bounds;
- safe relative path policy chặn POSIX/Windows/URI absolute forms, dot/empty segments, backslash/control và resolved escape.

Phase 2 implementation synthesis bổ sung, không phải platform certification:

- offline canonical renderer tạo JSON/Markdown và OOXML DOCX/XLSX/PPTX, kèm artifact manifest + closed conversion-run linkage; editable PPTX pagination tách khỏi geometry-aware fidelity path;
- offline RAG builder dùng schema-valid root control, per-document manifests, optional target-configured chunks, reserved-path collision guards và bounded passive media validation trước staged publication;
- matching-profile schema/registry mở cùng workflow helper cho structured folder/package → deterministic result + role-aware XLSX; không bundle OCR/model và không suy tolerance/materiality;
- fault-injection tests cho no-overwrite/rollback, adversarial asset/media/path tests, typed/formula-safe spreadsheet checks và synthetic LibreOffice render smoke; live target/platform tests vẫn tách sang Phase 3.

## Security và methodology concerns

- Không bundle OCR model, cloud credential, connector hoặc executable nặng; OCR/vision/redaction là runtime adapters.
- Không tự động external upload, URL/QR opening, macro/script execution hoặc password cracking.
- Hash chứng minh byte identity trong phạm vi tính, không authenticity/admissibility.
- Schema validation chứng minh structure, không semantic correctness.
- Reconciliation result phụ thuộc grain, keys, source quality, currency/date basis và approved tolerance.
- Redaction chỉ được gọi completed sau removal verification; overlay không đủ.
- Package validation không thay live-install smoke test hoặc human professional review.
- Artifact schema/build check không thay render inspection, target RAG ingestion/retrieval evaluation hoặc platform certification.
- “Best effort” không chứng minh visual equivalence; geometry/font/renderer/target constraints phải được kiểm và disclosed.
- `CREATED` chỉ chứng minh creation state; không chứng minh file đã QA. `PASS` ở structural, semantic, render và live-platform layers không được suy truyền giữa các layer.

## Tài liệu chính thức nền tảng

- OpenAI: <https://developers.openai.com/plugins/build/skills>
- OpenAI: <https://developers.openai.com/plugins/build/plugins>
- Anthropic: <https://code.claude.com/docs/en/skills>
- Anthropic: <https://code.claude.com/docs/en/plugins>
- Anthropic: <https://code.claude.com/docs/en/plugins-reference>

Các URL là provenance/documentation references, không phải runtime dependency. Cần kiểm tra lại khi nền tảng thay đổi.
