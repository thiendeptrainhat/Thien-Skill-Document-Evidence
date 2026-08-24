# NGUỒN GỐC TÀI SẢN THƯƠNG HIỆU TDTN / TDTN BRAND-ASSET PROVENANCE

**Bản tiếng Việt ưu tiên áp dụng khi có mâu thuẫn. / The Vietnamese version prevails in case of conflict.**

## I. Bản tiếng Việt — ưu tiên áp dụng

### 1. Nguồn và xác nhận quyền kiểm soát

- **Nguồn:** ảnh `Logo TDTN.png` do người dùng trực tiếp cung cấp cho việc xây dựng `thien-skill-document-evidence`.
- **SHA-256 ảnh nguồn:** `020a47a3c831664c700c9e4491c7ae00cf5a8f330e6c3c57422ee246df56d69e`.
- **Định dạng nguồn:** PNG `1100 × 1100`, 8-bit RGBA, non-interlaced, có alpha channel.
- **Xác nhận của người dùng:** người dùng xác nhận có quyền hoặc quyền kiểm soát cần thiết để cung cấp ảnh nguồn và cho phép đóng gói ảnh cùng Skill.
- **Giới hạn xác minh:** xác nhận trên là representation của người dùng. Hồ sơ này ghi provenance và byte integrity; nó không phải kết luận độc lập về tác giả, chủ sở hữu pháp lý, đăng ký nhãn hiệu/bản quyền hoặc không xâm phạm.

### 2. Quy tắc biến đổi

Ảnh nguồn được xử lý theo đúng các quy tắc sau:

- `logo-original.png` và `logo-large.png` là bản sao byte-identical của ảnh nguồn;
- các icon được resize theo toàn bộ canvas vuông `1100 × 1100` xuống đúng kích thước đích;
- **không crop**, không thay đổi tỷ lệ khung, không cắt viền, không tách thành phần;
- **không redesign**, redraw, recolor, retouch, thêm/bớt nội dung hoặc tạo bằng AI;
- alpha channel/transparency được giữ trong mọi file; và
- màu metadata `#001838` chỉ là brand accent của interface, không phải phép đổi màu pixel ảnh.

### 3. Inventory và hash đã xác minh ngày 23 August 2026

| File | Kích thước | Định dạng | Phép biến đổi | SHA-256 |
|---|---:|---|---|---|
| `logo-original.png` | 1100×1100 | PNG RGBA, alpha retained | Bản sao byte-identical | `020a47a3c831664c700c9e4491c7ae00cf5a8f330e6c3c57422ee246df56d69e` |
| `logo-large.png` | 1100×1100 | PNG RGBA, alpha retained | Bản sao byte-identical | `020a47a3c831664c700c9e4491c7ae00cf5a8f330e6c3c57422ee246df56d69e` |
| `icon-512.png` | 512×512 | PNG RGBA, alpha retained | Resize toàn khung; không crop/redesign | `be8ef61706db7ea9d0d8a6911d41a09b8f368e9d27d5ab02fbf44b000799c220` |
| `icon-small.png` | 400×400 | PNG RGBA, alpha retained | Resize toàn khung; không crop/redesign | `25f406f44dcf349a70305529e7c23e388b55a88e79d4de98d0fa5e4ce6d581ac` |
| `icon-128.png` | 128×128 | PNG RGBA, alpha retained | Resize toàn khung; không crop/redesign | `58695db66aa845d5b58631fc97ee0303d100cd1d0b1b81fd0bbf89b933d4ee12` |
| `icon-64.png` | 64×64 | PNG RGBA, alpha retained | Resize toàn khung; không crop/redesign | `1b3acfa3a717f8286bba000a027e133e9a28275b8abee5936a9c947b3a500322` |

### 4. Giới hạn sử dụng thương hiệu

Các file logo/icon là tài sản nhận diện được bảo lưu, không phải public-domain hoặc open-source asset. Việc file xuất hiện trong source, repository, package hoặc giao diện không tự cấp quyền sử dụng.

Chỉ được hiển thị file nguyên vẹn cùng đúng Skill/package trong phạm vi một Công cụ cấp quyền hợp lệ theo `Tran Ngoc Thien's Skills Commercial Source-Available License 2.0`. Không có quyền độc lập để crop, redesign, recolor, tách riêng, tái phân phối, đăng ký, cấp lại, dùng làm nhãn hiệu hoặc dùng để hàm ý tài trợ/chứng thực, trừ khi Tran Ngoc Thien chấp thuận rõ ràng bằng văn bản.

## II. English version — Vietnamese version prevails

### 1. Source and rights/control confirmation

- **Source:** `Logo TDTN.png`, supplied directly by the user for `thien-skill-document-evidence`.
- **Source SHA-256:** `020a47a3c831664c700c9e4491c7ae00cf5a8f330e6c3c57422ee246df56d69e`.
- **Source format:** `1100 × 1100` PNG, 8-bit RGBA, non-interlaced, with an alpha channel.
- **User confirmation:** the user confirmed sufficient rights or control to provide the source image and authorize packaging it with the Skill.
- **Verification limit:** that confirmation is a user representation. This record documents provenance and byte integrity; it is not an independent conclusion on authorship, legal title, trademark/copyright registration, or non-infringement.

### 2. Transformation rules

The source image was processed under these rules:

- `logo-original.png` and `logo-large.png` are byte-identical copies of the source;
- icon variants resize the complete square `1100 × 1100` canvas to the exact target size;
- **no cropping**, aspect-ratio change, edge removal, or element separation;
- **no redesign**, redrawing, recoloring, retouching, content addition/removal, or AI-generated alteration;
- the alpha channel/transparency is retained in every file; and
- interface metadata color `#001838` is a brand accent only and does not recolor image pixels.

### 3. Inventory and hashes verified on 23 August 2026

The single bilingual table above is controlling for filenames, dimensions, formats, transformations, and SHA-256 values. It covers the exact `1100`, `512`, `400`, `128`, and `64` pixel assets distributed with version `1.0.0`.

### 4. Brand-use restrictions

The logo/icon files are reserved identifiers, not public-domain or open-source assets. Their presence in source, a repository, a package, or an interface does not itself grant use rights.

An intact file may be displayed only with the covered Skill/package and within a valid Granting Instrument under the `Tran Ngoc Thien's Skills Commercial Source-Available License 2.0`. No independent right is granted to crop, redesign, recolor, separate, redistribute, register, relicense, use as a mark, or imply sponsorship/endorsement unless Tran Ngoc Thien expressly approves it in writing.
