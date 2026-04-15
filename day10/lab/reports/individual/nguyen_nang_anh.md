# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Nguyễn Năng Anh  
**Vai trò:** Ingestion Owner (M1)  
**Ngày nộp:** 2026-04-15  
**Độ dài yêu cầu:** **400–650 từ**
**run_id tham chiếu:** `sprint1`, `sprint2`

---

## 1. Tôi phụ trách phần nào?

**File / module chính:**

| File | Nội dung phụ trách |
|------|--------------------|
| `etl_pipeline.py` (phần ingest) | Gọi `load_raw_csv()`, ghi log `run_id / raw_records / cleaned_records / quarantine_records`, đảm bảo pipeline chạy đúng end-to-end |
| `contracts/data_contract.yaml` | Điền `owner_team`, `sla_hours`, allowlist `doc_id`, `hr_leave_min_effective_date` cho từng policy |
| `docs/data_contract.md` | Viết source map ≥2 nguồn, schema cleaned (5 cột), bảng quarantine vs drop, bảng phiên bản policy 4 docs |

**Commit evidence:**

- `ad15ec3` — *"[Day10 S1] Dien data_contract.yaml - owner_team va alert_channel"*
- `6832df9` — *"[Day10 S1] Viet docs/data_contract.md - source map, schema, quarantine rules"*
- `b791f3d` — *"[Day10 S1] Bo ignore *.log de commit artifact log cho grading"* (sửa `day10/lab/.gitignore`)
- `4493742` — *"[Day10 S1] Chay pipeline sprint1 - raw=10 cleaned=6 quarantine=4 PIPELINE_OK"*
- `7f838c9` — *"[Day10 S2] Chay pipeline sprint2 - rules moi active, embed_prune=5"*

**Kết nối với thành viên khác:**

Output của tôi — cleaned CSV + quarantine CSV + manifest — là input cho M3 (Tùng kiểm tra expectations) và M4 (Thảo embed vào Chroma). M2 (Ngọc Hiếu) viết cleaning rules; tôi chạy pipeline để xác nhận rules hoạt động đúng trên dữ liệu thực.

---

## 2. Một quyết định kỹ thuật: Dùng `contracts/data_contract.yaml` làm khai báo allowlist `doc_id` thay vì comment trong code

**Quyết định:** Khi điền `data_contract.yaml`, tôi tổ chức `allowed_doc_ids` và `hr_leave_min_effective_date` (cutoff ngày để quarantine HR cũ) thành các field riêng trong contract — thay vì để M2 chỉ hard-code trực tiếp trong `cleaning_rules.py`.

**Lý do:** Nếu allowlist chỉ nằm trong code, khi thêm doc mới vào corpus (ví dụ `access_control_v2`), cả nhóm phải tìm đúng chỗ trong code để sửa, dễ bỏ sót. Contract YAML giúp:

1. **Tăng visibility**: Mọi người đọc contract biết ngay corpus gồm những gì, không cần đọc code.
2. **Tách ownership**: Ingestion Owner cập nhật contract, Cleaning Owner đọc vào — rõ ranh giới trách nhiệm.
3. **Audit trail**: Git history của `data_contract.yaml` cho thấy corpus thay đổi khi nào, bởi ai — không cần đọc diff code.

**Trade-off:** Hiện tại `cleaning_rules.py` vẫn hard-code `ALLOWED_DOC_IDS` thay vì đọc từ YAML (vì thời gian không đủ để viết `load_data_contract()`). Contract và code tạm thời tồn tại song song — technical debt này được ghi nhận trong `docs/pipeline_architecture.md` mục "Rủi ro đã biết — Hard-code HR cutoff."

**Evidence:** `contracts/data_contract.yaml` (commit `ad15ec3`) và `docs/data_contract.md` bảng "Phiên bản & Canonical" listing 4 policy docs với owner, version hiện hành, ghi chú quarantine.

---

## 3. Một anomaly đã xử lý: `freshness_check=FAIL` xuất hiện cùng `PIPELINE_OK` gây nhầm lẫn ban đầu

**Triệu chứng:** Sau khi chạy `python etl_pipeline.py run --run-id sprint1`, log dòng cuối hiển thị:

```
freshness_check=FAIL {"age_hours": 122.701, "sla_hours": 24.0, "reason": "freshness_sla_exceeded"}
PIPELINE_OK
```

Ban đầu tôi nhầm: pipeline báo `FAIL` nhưng lại kết thúc bằng `PIPELINE_OK` và exit 0 — trông mâu thuẫn. Tôi lo ngại data stale có thể được embed vào Chroma mà không có warning.

**Phân tích:** Đọc lại `etl_pipeline.py` dòng 124–127: `check_manifest_freshness()` được gọi và kết quả được **log**, nhưng không ảnh hưởng exit code. `PIPELINE_OK` là trạng thái riêng của pipeline gate (ingest → clean → validate → embed). `freshness_check` là **observability metric** của M5, không phải gate.

**Root cause:** CSV mẫu có `exported_at = 2026-04-10T08:00:00` — export cũ ~122 giờ, vượt SLA 24h. FAIL là **hành vi đúng** trên data mẫu. Pipeline vẫn OK vì data đã qua quality gate đầy đủ — freshness FAIL chỉ là cảnh báo cho monitoring, không block pipeline.

**Fix:** Không cần sửa code pipeline — thiết kế đã đúng. Tôi thực hiện 3 bước:

1. **Xác nhận behavior**: Đọc lại `etl_pipeline.py` L124-127, confirm `check_manifest_freshness()` chỉ log, không return exit code khác 0.
2. **Document rõ trong report cá nhân**: Ghi phân tích gate vs metric để cả nhóm tham chiếu.
3. **Đề xuất production remediation cụ thể**:
   - Cron job chạy lúc 06:00 hàng ngày: re-export CSV từ DB → `exported_at` luôn < 6h < SLA 24h
   - Alert riêng cho freshness: nếu `freshness_check=FAIL` xuất hiện ≥2 run liên tiếp → Slack/email alert (tách biệt với pipeline exit code)
   - Ngưỡng WARN tại 75% SLA (18h) để buffer trước FAIL

**Bài học:** Phân biệt **pipeline gate** (halt nếu fail) và **observability metric** (log/alert, không halt). Hai loại này phải tách rõ trong thiết kế — gate failure và metric failure có response khác nhau.

---

## 4. Bằng chứng trước / sau

**`artifacts/logs/run_sprint1.log` — pipeline chuẩn sprint1:**

```
run_id=sprint1
raw_records=11
cleaned_records=6
quarantine_records=5
expectation[refund_no_stale_14d_window] OK (halt) :: violations=0
expectation[hr_leave_no_stale_10d_annual] OK (halt) :: violations=0
embed_upsert count=6 collection=day10_kb
freshness_check=FAIL {"age_hours": 122.701, "sla_hours": 24.0}
PIPELINE_OK
```

**`artifacts/manifests/manifest_sprint1.json` — audit trail:**

```json
{
  "run_id": "sprint1",
  "raw_records": 11,
  "cleaned_records": 6,
  "quarantine_records": 5,
  "no_refund_fix": false,
  "skipped_validate": false
}
```

→ Log xác nhận pipeline chạy đúng: 11 raw rows, 6 cleaned, 5 quarantined, tất cả expectations PASS, embed 6 vectors, `no_refund_fix=false` và `skipped_validate=false` ghi rõ đây là clean run, không có flag inject nào.

---

## 5. Cải tiến tiếp theo

Nếu có thêm 2 giờ, tôi sẽ viết hàm `load_data_contract(path)` trong `etl_pipeline.py` để đọc `allowed_doc_ids` và `hr_leave_min_effective_date` từ `contracts/data_contract.yaml`, sau đó truyền vào `clean_rows()` qua parameter. Inject test: đổi cutoff thành `2025-06-01` trong YAML → row HR 2025 lọt qua rule 3 → expectation `hr_leave_no_stale_10d_annual` FAIL → chứng minh contract là single source of truth thực sự hoạt động, không chỉ là documentation. Đáp ứng Distinction criterion (d) của SCORING.md.
