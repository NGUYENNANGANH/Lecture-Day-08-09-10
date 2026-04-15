# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Nguyễn Ngọc Hiếu
**Vai trò:** Cleaning Owner
**Ngày nộp:** 2026-04-15

---

> Viết **"tôi"**, đính kèm **run_id**, **tên file**, **đoạn log** hoặc **dòng CSV** thật.  
> Nếu làm phần clean/expectation: nêu **một số liệu thay đổi** (vd `quarantine_records`, `hits_forbidden`, `top1_doc_expected`) khớp bảng `metric_impact` của nhóm.  
> Lưu: `reports/individual/[ten_ban].md`

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

**File / module:**

- `cleaning_rules.py`

**Kết nối với thành viên khác:**

Tôi nhận dữ liệu thô từ Ingestion Owner, tiến hành dọn dẹp và áp dụng baseline cùng 4 rule mới (loại BOM, chuẩn hóa whitespace, chặn chunk ngắn, và bắt migration notes). Output sạch sẽ giúp Quality Owner (M3) chạy đúng expectation và Embed Owner (M4) đưa nội dung vào Chroma mà không bị rác. Tôi cũng phối hợp điều chỉnh thứ tự rule để M3 có thể test logic cấy lỗi (`--no-refund-fix`).

**Bằng chứng (commit / comment trong code):**

Thêm 4 logic hàm (R7-R10) vào `transform/cleaning_rules.py` (L71-L173): `strip_bom_and_control_chars`, `quarantine_migration_note`, `normalize_whitespace_chunk`, `validate_chunk_min_length`.
Số liệu `quarantine_records` được filter chặt hơn từ 4 (baseline) lên 5.

---

## 2. Một quyết định kỹ thuật (100–150 từ)

> VD: chọn halt vs warn, chiến lược idempotency, cách đo freshness, format quarantine.

Tôi đã đưa ra quyết định thay đổi **thứ tự chạy các cleaning rules** trong hàm `clean_rows()`. Cụ thể, tôi chuyển rule bắt migration/sync note (R8) xuống sau rule sửa "14 ngày làm việc" (R6). 
Lý do: Khi chạy cấy dữ liệu lỗi để Quality Owner chứng minh expectation (`--no-refund-fix`), nếu dòng "14 ngày làm việc" bị quarantine bởi R8 trước đó (do dòng này có note migration trong text), expectation cấy lỗi sẽ không bao giờ nhìn thấy nó để báo HALT. Thay đổi này đảm bảo tính độc lập của việc đánh giá logic.

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

> Mô tả triệu chứng → metric/check nào phát hiện → fix.

Triệu chứng: Dữ liệu export từ production đôi khi bị dính các ký tự vô hình (như Zero-width space, BOM `\ufeff`) và Non-breaking space `\xa0`.
Hệ quả: Logic dedup bằng text comparison của baseline sẽ không bắt được do 2 câu nhìn bằng mắt thường giống nhau nhưng hash ra kết quả khác biệt, gây false-negative dedup vào vector index.
Fix: Tôi phát triển rule R7 (`strip_bom_and_control_chars`) và R9 (`normalize_whitespace_chunk`) để loại các byte thừa Unicode (control chars, zero-width) và thay tất cả biến thể khoảng trắng về một space tiêu chuẩn trước khi chạy lệnh dedup. Deduplication sau đó đã detect chính xác các bản ghi near-duplicate.

---

## 4. Bằng chứng trước / sau (80–120 từ)

> Dán ngắn 2 dòng từ `before_after_eval.csv` hoặc tương đương; ghi rõ `run_id`.

**Trích xuất từ `before_after_eval.csv`:**
- Khi inject lỗi (`run_id: inject-bad`): Cờ `--no-refund-fix` làm `q_refund_window, ... hits_forbidden=yes`.
- Sau khi fix (`run_id: after-fix`): `q_refund_window, Khách hàng có bao nhiêu ngày để yêu cầu hoàn tiền... ,policy_refund_v4, ... ,yes,no,,3`
➔ Cho thấy `hits_forbidden=no` chứng minh logic clean hoạt động, loại bỏ được chính sách quá hạn "14 ngày" sau khi apply lại rule R6. Cùng với `quarantine_records=5` hiển thị tại `manifest_after-fix.json`.

---

## 5. Cải tiến tiếp theo (40–80 từ)

> Nếu có thêm 2 giờ — một việc cụ thể (không chung chung).

Tôi sẽ tích hợp thư viện `presidio-analyzer` kết hợp RegExp để phát hiện và mask các PII (Personal Identifiable Information) như SĐT hoặc Email có thể bị nhân sự gõ nhầm vào doc nội bộ trước khi đẩy vào Chroma. Lọc data rác là chưa đủ, mà lọc rủi ro bảo mật còn tốt hơn.
