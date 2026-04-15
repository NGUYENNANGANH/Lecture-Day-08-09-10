# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Mai Phi Hiếu  
**Vai trò:** Monitoring / Docs Owner (M5)  
**Ngày nộp:** 2026-04-15  
**Độ dài yêu cầu:** **400–650 từ**

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

**File / module:**

- `monitoring/freshness_check.py` — viết lại: dual-boundary freshness (ingest + publish), WARN threshold 75% SLA, logging chi tiết.
- `docs/pipeline_architecture.md` — viết từ đầu: 2 sơ đồ Mermaid, bảng I/O 5 tầng, giải thích idempotency, bảng rủi ro.
- `docs/runbook.md` — 4 incident cases đủ format Symptom → Prevention.
- `reports/group_report.md` — điền mục 4 (Freshness), mục 5 (Day 09), mục 6 (Rủi ro), mục 7 (3 câu peer review).

**Kết nối với thành viên khác:**

Tôi nhận manifest JSON từ M1 (Nguyễn Năng Anh), tổng hợp metric từ M2 (cleaning rules), M3 (expectations), M4 (embed/eval). Module `freshness_check.py` được `etl_pipeline.py` gọi ở cuối pipeline và từ CLI `freshness`.

**Bằng chứng:** `freshness_check.py` header ghi `"Mở rộng bởi Mai Phi Hiếu (M5)"`, docs ghi `"Tác giả: Mai Phi Hiếu (M5)"`.

---

## 2. Một quyết định kỹ thuật (100–150 từ)

> Quyết định: Đo freshness tại **2 boundary** (ingest + publish) thay vì chỉ 1.

Baseline chỉ đo `latest_exported_at` (ingest boundary). Tôi thêm **publish boundary** = `run_timestamp` để phân biệt: data cũ (ingest FAIL) vs pipeline chưa chạy (publish FAIL).

Kết quả trên `run_id=after-fix`:
- **Ingest FAIL** (age=122.7h > SLA 24h) → data export cũ 5 ngày
- **Publish PASS** (age=0.2h) → pipeline vừa chạy
- **Processing delay** = 122.5h → cần re-export, không cần debug pipeline

Tôi cũng thêm WARN tại 75% SLA (18h) — buffer sớm trước FAIL. Overall status = worst-case 2 boundary.

Quyết định đáp ứng Distinction criterion (b) và Bonus +1 trong SCORING.md.

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

> Sự cố: Git merge conflicts trong manifest JSON khiến freshness check crash.

**Triệu chứng:** `python etl_pipeline.py freshness --manifest manifest_after-fix.json` raise `JSONDecodeError` — file chứa markers `<<<<<<<`, `=======`, `>>>>>>>`.

**Phát hiện:** Mở manifest — 2 phiên bản `run_timestamp` và `raw_path` xen kẽ (Windows `\\` vs Unix `/`). Tương tự `manifest_inject-bad.json`.

**Fix:** Resolve thủ công — giữ phiên bản Windows, loại markers. Sau fix, freshness check chạy thành công:
```
freshness_check run_id=after-fix | overall=FAIL | ingest=FAIL (age=122.7h) | publish=PASS (age=0.2h)
```

**Bài học:** Artifact JSON phải clean trước khi commit — merge conflict làm hỏng parse chain từ manifest → freshness → pipeline log.

---

## 4. Bằng chứng trước / sau (80–120 từ)

**Trước (baseline, `run_id=final`):**
```
freshness_check=FAIL {"latest_exported_at": "2026-04-10T08:00:00", "age_hours": 122.239, "sla_hours": 24.0, "reason": "freshness_sla_exceeded"}
```
→ Chỉ biết FAIL, không phân biệt pipeline mới/cũ.

**Sau (dual-boundary, `run_id=after-fix`):**
```
overall=FAIL | ingest=FAIL (age=122.7h) | publish=PASS (age=0.2h) | processing_delay=122.5h
```
→ **Ingest FAIL** (data cũ) nhưng **publish PASS** (pipeline hoạt động) — actionable: cần re-export CSV, không debug pipeline.

---

## 5. Cải tiến tiếp theo (40–80 từ)

Nếu có thêm 2 giờ, tôi sẽ **đọc `hr_leave_min_effective_date` từ `data_contract.yaml`** thay vì hard-code `2026-01-01`. Viết `load_contract_config()` truyền cutoff vào `clean_rows()`. Inject test: đổi cutoff thành `2025-06-01` → row HR 2025 lọt qua → expectation FAIL → chứng minh config-driven versioning. Đây đáp ứng Distinction criterion (d).
