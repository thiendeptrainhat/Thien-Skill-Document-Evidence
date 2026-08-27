# THÔNG BÁO BÊN THỨ BA VÀ NGUỒN THAM KHẢO / THIRD-PARTY NOTICES AND REFERENCE SOURCES

**Bản tiếng Việt ưu tiên áp dụng khi có mâu thuẫn. / The Vietnamese version prevails in case of conflict.**

## I. Bản tiếng Việt — ưu tiên áp dụng

### 1. Phạm vi kiểm kê của phiên bản 1.1.0

Theo kiểm kê canonical skill tại ngày `27 August 2026`, phiên bản `1.1.0` không vendor hoặc đóng gói thư viện/mã nguồn thực thi của bên thứ ba, binary, OCR model, AI model, dataset, font, credential, cloud connector hoặc bản sao tài liệu chính thức. JSON Schema, tài liệu phương pháp và metadata được phát hành trong canonical skill là thành phần của Skill chỉ trong phạm vi quyền thực tế của Chủ sở hữu.

Runtime, thư viện, model, API, ứng dụng, hệ điều hành, dịch vụ cloud hoặc plugin host có thể có sẵn trong môi trường người sử dụng không được gộp vào Skill chỉ vì Skill có thể tương tác với chúng. Mỗi thành phần đó tiếp tục chịu điều khoản và giấy phép riêng của nhà cung cấp. Skill không tự tải, tự cài hoặc tái cấp phép chúng.

Các script Python đi kèm chỉ dùng Python standard library. `scripts/build_workbook.mjs` là runtime adapter có thể dynamic-import package bên ngoài `@oai/artifact-tool` khi package đó đã có sẵn trong host được phép. `@oai/artifact-tool` không được bundle, tải xuống hoặc tự cài bởi Skill và tiếp tục chịu license/điều khoản riêng của môi trường cung cấp. Việc công cụ này được dùng để tạo hoặc kiểm tra workbook không nhúng quyền đối với công cụ vào workbook hoặc tái cấp phép chính công cụ.

### 2. Brief và tài liệu do người dùng cung cấp

Brief xây dựng `Thien-Skill-Document-Evidence`, yêu cầu, ảnh đính kèm và các tài liệu nguồn do người dùng cung cấp được xử lý như dữ liệu tham khảo/đầu vào chưa tin cậy để xác định yêu cầu và kiểm tra thiết kế.

Tran Ngoc Thien và package **không tuyên bố quyền sở hữu hoặc tái cấp phép đối với brief do người dùng cung cấp với tư cách tài liệu nguồn**, cũng không đưa brief đó vào canonical skill/package. Tài liệu mà người sử dụng hoặc Khách hàng xử lý bằng Skill tiếp tục thuộc quyền và trách nhiệm của chủ thể tương ứng; quyền truy cập kỹ thuật không chứng minh quyền sở hữu, quyền xử lý hoặc quyền công bố.

### 3. Tài liệu chính thức, điều ước và tiêu chuẩn

Các luật, bộ luật, nghị định, thông tư, văn bản hợp nhất, Công báo, quyết định, điều ước, tài liệu WIPO/WTO, tài liệu cơ quan nhà nước, tiêu chuẩn và tài liệu nền tảng có thể được dẫn tên, liên kết hoặc tóm tắt ngắn để ghi provenance, giải thích boundary hoặc định tuyến nghiên cứu.

Tran Ngoc Thien và package **không tuyên bố sở hữu, không sao chép toàn bộ và không tái cấp phép các tài liệu chính thức hoặc tài liệu của tổ chức/cơ quan đó**. Link hoặc citation không biến nội dung nguồn thành Tài liệu được cấp phép và không thay thế việc kiểm tra bản chính, phiên bản, hiệu lực, phạm vi áp dụng, quyền truy cập và điều khoản của nguồn tại thời điểm sử dụng.

Các URL tài liệu OpenAI và Anthropic trong `references/source-and-design-provenance.md` chỉ là nguồn documentation/provenance, không phải runtime dependency và không hàm ý tài trợ, liên kết hay chứng thực.

### 4. Skill và tài liệu tham khảo cục bộ

Các skill cục bộ được phép đọc, cùng `skill-creator`, `plugin-creator` và tài liệu chuyên môn liên quan, chỉ được khảo sát để học pattern kiến trúc, security boundary, packaging, legal-license discipline, schema và QA. Quyết định kế thừa, điều chỉnh hoặc loại bỏ ở cấp thiết kế được ghi trong `references/source-and-design-provenance.md`.

Việc khảo sát không thay đổi giấy phép của source, không biến source thành dependency được phân phối và không tuyên bố quyền sở hữu hoặc tái cấp phép nội dung mà Chủ sở hữu không có quyền cấp. Canonical skill không chứa bản sao nguyên văn của các skill tham khảo.

### 5. Tài sản thương hiệu

Ảnh nguồn `Logo TDTN.png` do người dùng trực tiếp cung cấp. Người dùng xác nhận quyền hoặc quyền kiểm soát cần thiết để cung cấp và đóng gói ảnh cho Skill; đây là xác nhận của người dùng, không phải kết luận độc lập về đăng ký, title hoặc không xâm phạm.

Logo/icon TDTN vì vậy được ghi nhận là tài sản brand do người dùng/Chủ sở hữu cung cấp, không phải tài sản bên thứ ba được vendor. Nguồn, SHA-256, kích thước và phép resize toàn khung được ghi tại `assets/brand/PROVENANCE.md` trong canonical skill/package hoặc `thien-skill-document-evidence/assets/brand/PROVENANCE.md` tại root repository. Quyền sử dụng brand bị giới hạn bởi Giấy phép chung và `LICENSE-APPLICATION.md`.

### 6. Tên và nhãn hiệu của nền tảng

OpenAI, ChatGPT, Codex, Anthropic, Claude và các tên, logo hoặc nhãn hiệu khác thuộc chủ thể quyền tương ứng. Việc nhắc tên chỉ để mô tả compatibility hoặc nền tảng dự kiến; không tuyên bố sở hữu, tài trợ, liên kết, chứng thực hoặc quyền sử dụng nhãn hiệu.

Nếu một bản phát hành tương lai bổ sung thành phần bên thứ ba, bên phát hành phải kiểm kê đúng phiên bản, giữ attribution/notice bắt buộc và cập nhật tài liệu này trước khi phát hành.

## II. English version — Vietnamese version prevails

### 1. Version 1.1.0 inventory scope

Based on the canonical-Skill inventory as of `27 August 2026`, version `1.1.0` does not vendor or package third-party executable source libraries, binaries, OCR models, AI models, datasets, fonts, credentials, cloud connectors, or copies of official documents. JSON Schemas, methodology documents, and metadata released in the canonical Skill are Skill components only to the extent of the Owner's actual rights.

A runtime, library, model, API, application, operating system, cloud service, or host plugin available in a user's environment is not bundled merely because the Skill can interact with it. Each remains governed by its provider's separate terms and license. The Skill does not automatically download, install, or relicense it.

The included Python scripts use the Python standard library only. `scripts/build_workbook.mjs` is a runtime adapter that may dynamically import the external `@oai/artifact-tool` package when it is already available in an authorized host. `@oai/artifact-tool` is not bundled, downloaded, or automatically installed by the Skill and remains governed by the supplying environment's separate license/terms. Using that tool to create or inspect a workbook neither embeds rights in the tool into the workbook nor relicenses the tool itself.

### 2. User-supplied brief and materials

The `Thien-Skill-Document-Evidence` build brief, requests, attached image, and source materials supplied by the user were treated as untrusted reference/input data for requirements and design verification.

Tran Ngoc Thien and the package **do not claim ownership of or relicense the user-supplied brief as a source document**, and the brief is not included in the canonical Skill/package. Materials processed by a user or Client remain subject to the rights and responsibilities of the relevant parties; technical access does not prove ownership, processing authority, or publication rights.

### 3. Official material, treaties, and standards

Laws, codes, decrees, circulars, consolidations, Official Gazette material, decisions, treaties, WIPO/WTO materials, government-agency materials, standards, and platform documentation may be named, linked, or briefly summarized for provenance, boundary explanation, or research routing.

Tran Ngoc Thien and the package **do not claim ownership of, reproduce in full, or relicense those official or organization/agency materials**. A link or citation does not make source content Licensed Material and does not replace checking the authoritative text, version, effective status, applicability, access rights, and source terms at the time of use.

OpenAI and Anthropic documentation URLs in `references/source-and-design-provenance.md` are documentation/provenance references only, not runtime dependencies, and imply no sponsorship, affiliation, or endorsement.

### 4. Local skills and reference material

Authorized local skills, `skill-creator`, `plugin-creator`, and related professional material were reviewed only for architectural patterns, security boundaries, packaging, legal-license discipline, schemas, and QA. Design-level adoption, adjustment, and rejection decisions are recorded in `references/source-and-design-provenance.md`.

Review does not change a source's license, make it a distributed dependency, or claim ownership of or relicense content outside the Owner's rights. The canonical Skill contains no verbatim copy of the reference skills.

### 5. Brand assets

The source `Logo TDTN.png` image was supplied directly by the user. The user confirmed sufficient rights or control to provide and package it for the Skill; that statement is a user representation, not an independent conclusion on registration, title, or non-infringement.

The TDTN logo/icons are therefore recorded as user/Owner-supplied brand assets rather than vendored third-party assets. Source, SHA-256, dimensions, and full-frame resize provenance are recorded in `assets/brand/PROVENANCE.md` in the canonical Skill/package or `thien-skill-document-evidence/assets/brand/PROVENANCE.md` at repository root. Brand use is restricted by the Master License and `LICENSE-APPLICATION.md`.

### 6. Platform names and marks

OpenAI, ChatGPT, Codex, Anthropic, Claude, and other names, logos, or marks belong to their respective rightsholders. Naming them describes compatibility or intended platforms only and claims no ownership, sponsorship, affiliation, endorsement, or trademark right.

If a future release adds a third-party component, the releaser must inventory the exact version, preserve mandatory attribution/notices, and update this document before release.
