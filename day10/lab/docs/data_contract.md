# Data Contract — Lab Day 10

**Nhóm:** Nhóm Day10  
**Cập nhật:** 2026-04-15  
**Tham chiếu:** `contracts/data_contract.yaml`

---

## 1. Nguồn dữ liệu (Source Map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|-------------------|----------------|
| `data/raw/policy_export_dirty.csv` | `load_raw_csv()` đọc UTF-8 CSV | Thiếu cột bắt buộc, `doc_id` không nằm trong allowlist, `effective_date` sai định dạng, `chunk_text` rỗng, dòng trùng lặp | `raw_records`, `quarantine_records` ghi trong log + manifest |
| `data/docs/*.txt` (5 file policy) | Đọc trực tiếp bởi agent RAG Day 09 | File bị xóa / đổi tên / encoding sai | Kiểm tra file tồn tại trước mỗi lần embed; cảnh báo nếu thiếu |

---

## 2. Schema Cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| `chunk_id` | string | Có | Hash ổn định: `SHA256(doc_id + chunk_text + seq)[:16]` — idempotent khi rerun |
| `doc_id` | string | Có | Phải nằm trong `allowed_doc_ids` của contract (`policy_refund_v4`, `sla_p1_2026`, `it_helpdesk_faq`, `hr_leave_policy`) |
| `chunk_text` | string | Có | Độ dài tối thiểu 8 ký tự sau clean |
| `effective_date` | date (YYYY-MM-DD) | Có | Normalize từ `DD/MM/YYYY` nếu cần; quarantine nếu không parse được |
| `exported_at` | datetime (ISO 8601) | Có | Dùng để tính freshness SLA trong manifest |

---

## 3. Quy tắc Quarantine vs Drop

| Reason code | Điều kiện | Hành động |
|-------------|-----------|-----------|
| `unknown_doc_id` | `doc_id` không thuộc allowlist | Quarantine CSV — chờ catalog owner duyệt |
| `missing_effective_date` | `effective_date` rỗng sau parse | Quarantine — không đủ metadata versioning |
| `invalid_effective_date_format` | Không parse được (không phải ISO, không phải DD/MM/YYYY) | Quarantine — cần fix ở nguồn |
| `stale_hr_policy_effective_date` | `hr_leave_policy` có `effective_date < 2026-01-01` | Quarantine — conflict version (10 ngày vs 12 ngày phép) |
| `missing_chunk_text` | `chunk_text` rỗng | Quarantine — không có nội dung để embed |
| `duplicate_chunk_text` | Trùng nội dung với chunk đã xử lý trong cùng run | Quarantine — giữ bản đầu tiên |

> **Merge lại:** Record trong quarantine cần Cleaning Owner xác nhận fix ở nguồn trước khi re-ingest. Không tự động merge.

---

## 4. Phiên bản & Canonical

| Policy | File canonical | Version hiện hành | Ghi chú |
|--------|---------------|-------------------|---------|
| Refund | `data/docs/policy_refund_v4.txt` | v4 — cửa sổ **7 ngày** làm việc | Bản v3 có "14 ngày" là lỗi migration — rule fix tự động trong pipeline |
| HR Leave | `data/docs/hr_leave_policy.txt` | 2026 — **12 ngày** phép năm | Bản 2025 (10 ngày) bị quarantine theo `effective_date < 2026-01-01` |
| SLA P1 | `data/docs/sla_p1_2026.txt` | 2026 | Phản hồi 15 phút, resolution 4 giờ |
| IT Helpdesk | `data/docs/it_helpdesk_faq.txt` | Hiện hành | Khóa tài khoản sau 5 lần sai |
