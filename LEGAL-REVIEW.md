# RÀ SOÁT PHÁP LÝ VỀ GIẤY PHÉP VÀ TUYÊN BỐ ÁP DỤNG

> **DỰ THẢO — BẮT BUỘC LUẬT SƯ VIỆT NAM ĐỦ NĂNG LỰC RÀ SOÁT TRƯỚC PHÁT HÀNH**
>
> Tài liệu này là hồ sơ nghiên cứu và issue-spotting, không phải ý kiến pháp lý chính thức, không bảo đảm hiệu lực hoặc khả năng thi hành trong một giao dịch cụ thể.

**Skill:** `Thien Skill — Document Intelligence, Evidence & Reconciliation`  
**Mã định danh:** `thien-skill-document-evidence`  
**Phiên bản:** `1.0.0`  
**Pháp luật được kiểm tra đến ngày:** `2026-08-23`  
**Ngày sự kiện được đánh giá:** `2026-08-23`  
**Phạm vi tài phán chính:** Việt Nam  
**Mức độ bảo mật:** Nội bộ; repository `PRIVATE`  
**Cấp nguồn:** P1 — nguồn chính thức của Chính phủ/Công báo và nguồn lưu chiểu điều ước chính thức

## 1. Kết luận điều hành

**[PHÂN TÍCH] Master license phải tiếp tục được giữ byte-identical.** Không có thay đổi pháp luật được tìm thấy sau ngày `2026-08-04` đến ngày chốt `2026-08-23` buộc phải sửa nội dung `Tran Ngoc Thien's Skills Commercial Source-Available License 2.0` để áp dụng cho Skill này.

**[SỰ KIỆN]** Root `LICENSE`, canonical `thien-skill-document-evidence/LICENSE.md` và template chính thức `Tran-Ngoc-Thiens-Skills-Commercial-Source-Available-License-2.0.md` đã được đối chiếu byte-for-byte tại ngày rà soát. Cả ba có SHA-256:

`ced33214d371fabe382d3ca303042af7219ad96fb98acdd1b858d0d89478d4b5`

**[PHÂN TÍCH]** Các thông tin riêng của Skill, cảnh báo chuyên môn, loại trừ tài liệu bên thứ ba, provenance brand và trạng thái repository nên tiếp tục nằm trong `LICENSE-APPLICATION.md`, `NOTICE`, `THIRD-PARTY-NOTICES.md` và `assets/brand/PROVENANCE.md`; không chèn chúng vào hoặc sửa master license.

**Mức rủi ro:** Trung bình trước legal sign-off; có thể giảm nếu Granting Instrument, assent evidence, consumer classification, chain of title và data/platform controls được kiểm tra.  
**Độ tin cậy:** Cao về khung pháp luật và kết luận giữ master byte-identical; Trung bình về khả năng thi hành trong từng giao dịch vì còn phụ thuộc sự kiện, chủ thể, cách giao kết, luật bắt buộc và diễn giải của cơ quan tài phán.

## 2. Dữ kiện, pháp luật và caveat không được trộn lẫn

### 2.1. Sự kiện đã xác nhận

- **[SỰ KIỆN]** Nhãn bộ sưu tập/thương hiệu được yêu cầu là `Tran Ngoc Thien's Skill`.
- **[SỰ KIỆN]** Tên hiển thị chính xác là `Thien Skill — Document Intelligence, Evidence & Reconciliation`; mã `thien-skill-document-evidence`; phiên bản `1.0.0`; ngày áp dụng `23 August 2026`.
- **[SỰ KIỆN]** Owner là Tran Ngoc Thien, cá nhân; email cấp quyền `thien.8888@gmail.com`; địa chỉ `Ho Chi Minh, Vietnam`.
- **[SỰ KIỆN]** Repository và bản phân phối được chỉ định `PRIVATE`; nền tảng dự kiến là OpenAI, Anthropic Claude và Universal.
- **[SỰ KIỆN]** `LICENSE-APPLICATION.md` chỉ nhận diện Tài liệu được cấp phép và không phải Công cụ cấp quyền. Cơ chế cấp quyền nghiêm ngặt vẫn yêu cầu Đơn hàng trả phí, Văn bản chấp thuận hoặc Thỏa thuận thương mại hợp lệ.
- **[SỰ KIỆN]** Ảnh nguồn TDTN có SHA-256 `020a47a3c831664c700c9e4491c7ae00cf5a8f330e6c3c57422ee246df56d69e`; người dùng xác nhận quyền hoặc quyền kiểm soát cần thiết để cung cấp/đóng gói ảnh. Đây là representation của người dùng, chưa phải chain-of-title opinion.
- **[SỰ KIỆN]** Canonical inventory tại ngày rà soát không vendor thư viện thực thi, binary, model, dataset, font hoặc bản sao tài liệu chính thức của bên thứ ba.

### 2.2. Căn cứ pháp luật và nguồn chính thức

| Source ID | Văn bản/nguồn chính thức | Hiệu lực hoặc trạng thái tại 2026-08-23 | Nội dung liên quan |
|---|---|---|---|
| S-01 | [Bộ luật Dân sự 91/2015/QH13](https://vanban.chinhphu.vn/default.aspx?docid=183188&pageid=27160) | Hiệu lực từ 2017-01-01 | Điều 117: điều kiện có hiệu lực; Điều 119: giao dịch điện tử có thể đáp ứng hình thức văn bản; Điều 404–406: giải thích, hợp đồng mẫu/điều kiện giao dịch chung; Điều 683: lựa chọn luật cho hợp đồng có yếu tố nước ngoài và ngoại lệ bắt buộc. |
| S-02 | [Luật 131/2025/QH15 sửa Luật SHTT](https://vanban.chinhphu.vn/?classid=1&docid=216511&pageid=27160&typegroupid=3) | Hiệu lực từ 2026-04-01 | Sửa đổi trọng yếu mới nhất đã xác minh đối với Luật SHTT. Phải đọc cùng luật nền và chuyển tiếp. |
| S-03 | [67/VBHN-VPQH hợp nhất Luật SHTT](https://congbao.chinhphu.vn/van-ban/van-ban-hop-nhat-so-67-vbhn-vpqh-469197.htm) | Xác thực 2026-03-23; là nền đọc, không tạo hiệu lực độc lập | Điều 14, 22: biểu đạt, chương trình máy tính và tuyển tập đủ điều kiện; Điều 15: loại trừ ý tưởng, quy trình, hệ thống, phương pháp, khái niệm và dữ liệu thuần túy; Điều 47–48: chuyển quyền sử dụng và nội dung/hình thức hợp đồng. |
| S-04 | [Nghị định 134/2026/NĐ-CP](https://vanban.chinhphu.vn/?docid=217833&pageid=27160) | Hiệu lực từ 2026-04-09 | Sửa Nghị định 17/2023/NĐ-CP về quyền tác giả/quyền liên quan; phải kiểm tra đúng điều và chuyển tiếp khi áp dụng vào hành vi cụ thể. |
| S-05 | [Luật Giao dịch điện tử 20/2023/QH15 — bản Công báo](https://congbao.chinhphu.vn/van-ban/luat-so-20-2023-qh15-39848/45939.htm) và [36/VBHN-VPQH](https://vanban.chinhphu.vn/?docid=217207&pageid=27160) | Luật hiệu lực từ 2024-07-01; VBHN xác thực 2026-03-13 và không tạo hiệu lực độc lập | Điều 7–9: thông điệp dữ liệu, email và hợp đồng điện tử không bị phủ nhận giá trị chỉ vì ở dạng điện tử; yêu cầu văn bản có thể được đáp ứng khi nội dung có thể truy cập để tham chiếu. Metadata trên một trang Công báo cũ hiển thị sai ngày hiệu lực; bản ký/VBHN được ưu tiên. |
| S-06 | [Luật Bảo vệ quyền lợi người tiêu dùng 19/2023/QH15](https://vanban.chinhphu.vn/?docid=208363&pageid=27160) và [bản Công báo](https://congbao.chinhphu.vn/van-ban/luat-so-19-2023-qh15-39843/45917.htm) | Hiệu lực từ 2024-07-01 | Điều 24–25: giải thích có lợi cho người tiêu dùng khi mơ hồ; hạn chế điều khoản loại trừ trách nhiệm bắt buộc hoặc hạn chế khiếu nại/khởi kiện. |
| S-07 | [21/VBHN-VPQH hợp nhất Bộ luật Tố tụng dân sự](https://congbao.chinhphu.vn/van-ban/van-ban-hop-nhat-so-21-vbhn-vpqh-468974.htm) | Xác thực 2026-02-12; nền đọc, không tạo hiệu lực độc lập | Thẩm quyền theo vụ việc/cấp/lãnh thổ, ngôn ngữ tố tụng và chứng cứ tiếng nước ngoài. Phải kiểm tra cơ cấu tòa và thẩm quyền tại ngày khởi kiện. |
| S-08 | [Luật Dữ liệu 60/2024/QH15](https://vanban.chinhphu.vn/?classid=1&docid=212488&pageid=27160) | Hiệu lực từ 2025-07-01 | Khung quản trị, chia sẻ và sản phẩm/dịch vụ dữ liệu; không biến license IP thành quyền xử lý mọi dữ liệu. |
| S-09 | [Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15](https://vanban.chinhphu.vn/?classid=1&docid=214590&pageid=27160&typegroupid=3) và [Nghị định 356/2025/NĐ-CP](https://vanban.chinhphu.vn/?classid=1&docid=216387&pageid=27160) | Cùng hiệu lực từ 2026-01-01 | Căn cứ xử lý, trách nhiệm, quyền chủ thể, bảo mật và chuyển dữ liệu phải được đánh giá theo vai trò/dữ kiện; license không tự tạo căn cứ xử lý. |
| S-10 | [Luật Trí tuệ nhân tạo 134/2025/QH15](https://vanban.chinhphu.vn/?classid=1&docid=216334&pageid=27160&typegroupid=3) và [Nghị định 142/2026/NĐ-CP](https://vanban.chinhphu.vn/?docid=218029&orggroupid=2&pageid=27160) | Luật hiệu lực từ 2026-03-01; Nghị định hiệu lực từ 2026-05-01 | Nghĩa vụ đối với phát triển/cung cấp/sử dụng AI phải đọc cùng SHTT, dữ liệu, dữ liệu cá nhân, hợp đồng và điều khoản nền tảng. |
| S-11 | [WIPO — tình trạng điều ước của Việt Nam](https://www.wipo.int/wipolex/en/treaties/ShowResults?code=VN), [thông báo WCT số 102](https://www.wipo.int/wipolex/en/treaties/notifications/details/treaty_wct_102) và [WTO TRIPS](https://www.wto.org/english/docs_e/legal_e/trips_e.htm) | Berne có hiệu lực với Việt Nam từ 2004-10-26; WCT từ 2022-02-17; TRIPS là điều ước chính thức của WTO | TRIPS Điều 9–10 phân biệt biểu đạt với ý tưởng/phương pháp; bảo hộ chương trình máy tính như tác phẩm văn học và tuyển tập dữ liệu đủ điều kiện, không tự bảo hộ dữ liệu thô. Điều ước không biến source visibility thành license. |
| S-12 | [Chỉ mục Công báo điện tử](https://congbao.chinhphu.vn/cong-bao.htm) và [Công báo số 476 ngày 2026-08-21](https://congbao.chinhphu.vn/cong-bao/cong-bao-so-476-ngay-21-08-2026-47413.htm) | Chỉ mục chính thức được kiểm tra đến số 476, truy cập 2026-08-23 | Kiểm tra currentity sau mốc nghiên cứu 2026-08-04; không tìm thấy văn bản làm thay đổi các kết luận license trọng yếu. Đây là kết luận âm có giới hạn, không phải bằng chứng tuyệt đối rằng không có văn bản chưa đăng/chưa lập chỉ mục. |

### 2.3. Caveat pháp lý và dữ kiện

- **[CAVEAT]** Văn bản hợp nhất là công cụ đọc, không phải văn bản tạo quy phạm mới và không có ngày hiệu lực độc lập.
- **[CAVEAT]** Không có nguồn chính thức nào tự chứng minh quyền sở hữu của Tran Ngoc Thien đối với mọi nội dung hoặc logo. Chain of title, người đóng góp, tài sản bên thứ ba và quyền nhân thân phải được kiểm tra bằng chứng riêng.
- **[CAVEAT]** Việc một điều khoản phù hợp với khung luật không bảo đảm tòa án sẽ thi hành trong mọi trường hợp. Năng lực, thẩm quyền đại diện, tự nguyện, disclosure, assent, nội dung, consumer status, foreign elements và chứng cứ có thể thay đổi kết quả.
- **[CAVEAT]** Luật nước ngoài hoặc quy tắc bắt buộc tại nơi có người dùng/Khách hàng vẫn có thể áp dụng dù hợp đồng chọn luật Việt Nam.
- **[CAVEAT]** Điều khoản và chức năng OpenAI/Anthropic có thể thay đổi; compatibility và quyền nền tảng phải được kiểm tra lại tại ngày upload/phát hành.

## 3. Áp dụng vào các điều khoản trọng yếu

### 3.1. Luật áp dụng và khung hợp đồng

**[PHÁP LUẬT]** Bộ luật Dân sự cho phép thỏa thuận và, với hợp đồng có yếu tố nước ngoài, lựa chọn luật áp dụng trong phạm vi Điều 683, nhưng điều kiện có hiệu lực và quy tắc bắt buộc vẫn áp dụng. Hợp đồng mẫu/điều kiện giao dịch chung phải được disclosure rõ; điều khoản mơ hồ có thể bị giải thích bất lợi cho bên soạn, và điều khoản bất cân xứng có thể không có hiệu lực theo Điều 404–406 cùng luật chuyên ngành.

**[PHÂN TÍCH]** Điều khoản chọn luật Việt Nam của master phù hợp về cấu trúc vì đồng thời bảo lưu quy định bắt buộc. Tuy nhiên, không được dùng nó để tuyên bố loại trừ luật bảo vệ người tiêu dùng hoặc luật bắt buộc nước ngoài trong mọi trường hợp.

### 3.2. SHTT, phần mềm và phạm vi license

**[PHÁP LUẬT]** Luật SHTT hiện hành bảo hộ biểu đạt đủ điều kiện, phần mềm và tuyển tập có tính sáng tạo, nhưng không bảo hộ ý tưởng, phương pháp, quy trình, hệ thống, khái niệm hoặc dữ liệu thuần túy chỉ vì được mô tả trong package. Chuyển quyền sử dụng phải có đối tượng, căn cứ, phạm vi và nội dung đủ xác định theo Điều 47–48.

**[PHÂN TÍCH]** Cấu trúc master + Application Declaration + Granting Instrument là phù hợp: Application nhận diện Skill/version, còn quyền thực tế chỉ phát sinh theo Paid Order, Written Permission hoặc Commercial Agreement. `LICENSE-APPLICATION.md` đã giới hạn “Licensed Material” bằng cụm “trong phạm vi Chủ sở hữu thực sự sở hữu hoặc có quyền cấp phép” và loại trừ luật, official documents, brief người dùng và tài sản bên thứ ba; cách viết này tránh suy rộng quyền tác giả hoặc chain of title.

**[CAVEAT]** Hạn chế hợp đồng có thể ràng buộc một bên đã assent ngay cả khi một thành phần không được bảo hộ quyền tác giả, nhưng không được mô tả như quyền độc quyền SHTT tuyệt đối đối với ý tưởng/phương pháp/dữ liệu và vẫn chịu quy tắc bắt buộc.

### 3.3. Giao kết điện tử và chứng cứ chấp thuận

**[PHÁP LUẬT]** Thông điệp dữ liệu không bị phủ nhận giá trị chỉ vì ở dạng điện tử và có thể đáp ứng yêu cầu văn bản khi truy cập được để tham chiếu.

**[PHÂN TÍCH]** Cơ chế email/e-contract của master là phù hợp và thận trọng. Mỗi giao dịch phải lưu ít nhất: định danh và quyền đại diện của bên chấp thuận; license version/hash; Application version; Paid Order/Written Permission/Commercial Agreement; nội dung, thời điểm, tài khoản/kênh, payment status và integrity log. Một email không tự trở thành chữ ký số bảo đảm nếu chưa đáp ứng tiêu chí pháp luật tương ứng.

### 3.4. Tòa án và thương lượng 30 ngày

**[PHÂN TÍCH]** Cách viết “Tòa án có thẩm quyền tại Việt Nam theo pháp luật tố tụng Việt Nam” an toàn hơn việc cố định tên một tòa cụ thể trong bối cảnh cơ cấu/thẩm quyền có thể thay đổi. Các bên không thể tự tạo thẩm quyền trái quy định bắt buộc.

**[PHÂN TÍCH]** Thương lượng thiện chí 30 ngày có thể duy trì như bước hợp đồng trước tranh tụng, nhưng không nên được mô tả như bảo đảm tòa án sẽ bác/đình chỉ đơn kiện nộp sớm, không tự gia hạn thời hiệu và không được ngăn biện pháp khẩn cấp, bảo toàn chứng cứ hoặc bảo vệ SHTT. Master đã bảo lưu các ngoại lệ này; không cần sửa.

### 3.5. Bản tiếng Việt ưu tiên

**[PHÁP LUẬT]** Không tìm thấy quy tắc chung cấm các bên trong license tư chọn bản tiếng Việt kiểm soát; tố tụng tại Việt Nam sử dụng tiếng Việt và tài liệu nước ngoài thường cần bản dịch phù hợp. Quy tắc giải thích hợp đồng và bảo vệ người tiêu dùng vẫn áp dụng.

**[PHÂN TÍCH]** Priority clause tiếng Việt nên giữ nguyên. Nó không chữa được bản dịch lệch nghĩa trọng yếu, điều khoản ẩn, disclosure/assent yếu hoặc consumer unfairness. Application và Notice vì vậy phải giữ parity song ngữ và nói rõ tiếng Việt ưu tiên.

### 3.6. Dữ liệu, AI và tài liệu chứng cứ

**[PHÁP LUẬT]** Luật Dữ liệu, Luật Bảo vệ dữ liệu cá nhân, Nghị định 356/2025/NĐ-CP, Luật AI và Nghị định 142/2026/NĐ-CP đặt nghĩa vụ dựa trên vai trò, dữ liệu, hệ thống và hành vi thực tế. Giấy phép IP không tự tạo căn cứ xử lý hoặc quyền tải dữ liệu lên nền tảng.

**[PHÂN TÍCH]** Master có thể giữ byte-identical vì `LICENSE-APPLICATION.md` và `NOTICE` đã ghi rõ: không có quyền external upload mặc nhiên; người dùng chịu trách nhiệm về lawful basis, confidentiality, minimization, retention/deletion, transfers, platform terms và human verification. Cảnh báo này là boundary vận hành, không phải bảo đảm tuân thủ.

### 3.7. Consumer, standard terms và public distribution

**[PHÂN TÍCH]** Master đã bảo lưu luật bảo vệ người tiêu dùng bắt buộc, nhưng disclaimer, liability cap, termination, refund, choice-of-law, data và complaint clauses vẫn cần review riêng nếu phân phối B2C. Trước B2C release, counsel cũng phải kiểm tra danh mục hợp đồng theo mẫu/điều kiện giao dịch chung phải đăng ký, trong đó có [Quyết định 07/2024/QĐ-TTg](https://congbao.chinhphu.vn/van-ban/quyet-dinh-so-07-2024-qd-ttg-42107.htm), theo đúng sản phẩm và kênh thực tế.

## 4. Kiểm tra thay đổi sau 2026-08-04

**[SỰ KIỆN NGHIÊN CỨU]** Chỉ mục và số Công báo chính thức được kiểm tra đến Công báo số 476 ngày `2026-08-21`; các truy vấn mục tiêu tập trung vào sửa đổi/bãi bỏ liên quan Bộ luật Dân sự, Luật SHTT, giao dịch điện tử tư, tố tụng dân sự, dữ liệu cá nhân và AI.

**[KẾT QUẢ]** Không tìm thấy luật, nghị định hoặc thông tư ban hành/đăng sau `2026-08-04` làm thay đổi nội dung master theo cách buộc phải sửa template cho Application này. Các thay đổi về thủ tục hành chính điện tử được quan sát trong giai đoạn này không thay đổi quy tắc cốt lõi về giá trị hợp đồng điện tử tư.

**[CAVEAT]** Đây là negative-source check dựa trên nguồn đã đăng và được lập chỉ mục tới ngày truy cập. Phải refresh currentity ngay trước ngày ký Granting Instrument quan trọng hoặc ngày phát hành nếu các ngày đó muộn hơn `2026-08-23`.

## 5. Quyết định đối với master và bundle

1. **Giữ master byte-identical:** Không sửa root `LICENSE`, canonical `LICENSE.md` hoặc hai file `LICENSE-VERSION`.
2. **Giữ Application/Notice bên ngoài master:** Dùng các tài liệu này để xác định version, repository, platforms, scope, exclusions, disclaimers và provenance.
3. **Duy trì strict grant:** Không quyền nào phát sinh từ source/package access. Granting Instrument phải xác định Licensee, material/version, user/Team scope, purpose, platform, territory, term, fees và commercial/Client/public rights.
4. **Lưu assent evidence:** Lưu immutable license/application copies hoặc hashes cùng order/agreement, payment và acceptance records.
5. **Kiểm tra chain of title:** Xác minh contributors, source text, schemas, platform adapters, logo và mọi thành phần bổ sung trước external release.
6. **Không nhận quyền đối với nguồn:** `THIRD-PARTY-NOTICES.md` phải tiếp tục nói rõ không tuyên bố sở hữu official documents hoặc user brief.

## 6. Cổng kiểm tra pháp lý bắt buộc

> **Kiểm tra của con người bắt buộc:** Trước lần phát hành thương mại ra bên ngoài đầu tiên **hoặc** trước bất kỳ lần phát hành/công khai repository, package, marketplace listing hay source nào, một luật sư Việt Nam đủ năng lực phải rà soát và chấp thuận bằng văn bản: (i) master license byte-identical; (ii) `LICENSE-APPLICATION.md`; (iii) `NOTICE`; (iv) `THIRD-PARTY-NOTICES.md`; (v) brand provenance/chain of title; (vi) Granting Instrument và quy trình assent/payment; (vii) consumer/data/AI/platform facts; và (viii) luật hiện hành tại chính ngày phát hành.

Cho đến khi có xác nhận đó, repository và distribution phải tiếp tục `PRIVATE`; bộ hồ sơ chỉ có trạng thái `DRAFT — READY FOR QUALIFIED VIETNAMESE COUNSEL REVIEW`, không phải legal approval hoặc production/public-release approval.
