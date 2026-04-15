# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** Nhóm Day10  
**Thành viên:**
| Tên | Vai trò (Day 10) | Email |
|-----|------------------|-------|
| Nguyễn Năng Anh | Ingestion / Pipeline Owner | nguyennanganh199203@gmail.com |
| ___ | Cleaning & Quality Owner | ___ |
| ___ | Embed & Idempotency Owner | ___ |
| ___ | Monitoring / Docs Owner | ___ |

**Ngày nộp:** 2026-04-15  
**Repo:** https://github.com/NGUYENNANGANH/Lecture-Day-08-09-10  
**Độ dài khuyến nghị:** 600–1000 từ

---

> **Nộp tại:** `reports/group_report.md`  
> **Deadline commit:** xem `SCORING.md` (code/trace sớm; report có thể muộn hơn nếu được phép).  
> Phải có **run_id**, **đường dẫn artifact**, và **bằng chứng before/after** (CSV eval hoặc screenshot).

---

## 1. Pipeline tổng quan (150–200 từ)

> Nguồn raw là gì (CSV mẫu / export thật)? Chuỗi lệnh chạy end-to-end? `run_id` lấy ở đâu trong log?

**Tóm tắt luồng:**

Nguồn raw là `data/raw/policy_export_dirty.csv` (10 dòng, export mô phỏng từ DB). Pipeline chạy theo chuỗi: `load_raw_csv()` → `clean_rows()` → `run_expectations()` → `cmd_embed_internal()` → ghi manifest. `run_id` được log ngay dòng đầu tiên của mỗi file log tại `artifacts/logs/run_<run_id>.log` và đồng bộ vào `artifacts/manifests/manifest_<run_id>.json`.

- **sprint1** (baseline rules): `raw=10, cleaned=6, quarantine=4` — 6 expectations đều PASS
- **sprint2** (rules mới R7–R10 + E7–E8): `raw=10, cleaned=5, quarantine=5, embed_prune_removed=5` — 8 expectations đều PASS

**Lệnh chạy một dòng:**

```bash
python etl_pipeline.py run --run-id final-submission
```

---

## 2. Cleaning & expectation (150–200 từ)

> Baseline đã có nhiều rule (allowlist, ngày ISO, HR stale, refund, dedupe…). Nhóm thêm **≥3 rule mới** + **≥2 expectation mới**. Khai báo expectation nào **halt**.

Baseline gồm 6 rule: allowlist `doc_id`, chuẩn hoá `effective_date` (ISO + DD/MM/YYYY), quarantine HR cũ (`effective_date < 2026-01-01`), quarantine `chunk_text` rỗng, dedup nội dung, và fix refund window 14→7 ngày. Với baseline, CSV mẫu (10 dòng) cho ra **cleaned=6, quarantine=4**. Nhóm đã thêm **4 rule mới** vào `transform/cleaning_rules.py`, kết quả **cleaned=5, quarantine=5** — tăng 1 quarantine nhờ Rule 8 bắt row 3 chứa annotation migration bị leak.

### 2a. Bảng metric_impact (bắt buộc — chống trivial)

| Rule / Expectation mới (tên ngắn) | Trước (số liệu) | Sau / khi inject (số liệu) | Chứng cứ (log / CSV / commit) |
|-----------------------------------|------------------|-----------------------------|-------------------------------|
| R7 `strip_bom_and_control_chars` | Baseline dedup bỏ sót chunk có BOM prefix | Inject row có `\ufeff` prefix → dedup bắt đúng sau strip | `transform/cleaning_rules.py` L71-96 |
| R8 `quarantine_migration_note` | cleaned=6, quarantine=4 (row 3 "lỗi migration" lọt qua) | cleaned=5, quarantine=5 (row 3 bị quarantine `leaked_migration_annotation`) | `artifacts/quarantine/` CSV, commit `feature/cleaning` |
| R9 `normalize_whitespace_chunk` | Chunk có `\xa0` non-breaking space bypass dedup | Normalize `\xa0`→space trước dedup → catch near-duplicate | `transform/cleaning_rules.py` L127-149 |
| R10 `validate_chunk_min_length` | Baseline chỉ chặn empty text | Inject row text="OK" (2 chars) → quarantine `chunk_too_short` | `transform/cleaning_rules.py` L156-173 |

**Rule chính (baseline + mở rộng):**

- **Baseline (6 rule):** allowlist `doc_id`, normalize `effective_date`, quarantine HR stale, quarantine empty text, dedup `chunk_text`, fix refund 14→7 ngày
- **Mở rộng (4 rule mới):** strip BOM/control chars (R7), quarantine migration annotation (R8), normalize whitespace (R9), validate min chunk length ≥10 chars (R10)

**Ví dụ 1 lần expectation fail (nếu có) và cách xử lý:**

Khi chạy `--no-refund-fix`, Rule 8 vẫn quarantine row 3 (migration note) trước khi refund fix áp dụng — chứng minh rule hoạt động độc lập. Nếu bỏ Rule 8, row 3 chứa "14 ngày làm việc" sẽ lọt vào cleaned và trigger expectation `refund_no_stale_14d_window` → **halt**.

---

## 3. Before / after ảnh hưởng retrieval hoặc agent (200–250 từ)

> Bắt buộc: inject corruption (Sprint 3) — mô tả + dẫn `artifacts/eval/…` hoặc log.

**Kịch bản inject:**

Chạy `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate` để bỏ qua fix refund và skip validate. Tuy nhiên, Rule 8 (`quarantine_migration_note`) đã quarantine row 3 (chứa annotation "ghi chú: bản sync cũ policy-v3 — lỗi migration") trước khi bước refund fix được áp dụng, khiến stale refund text không lọt vào index dù dùng `--no-refund-fix`.

**So sánh manifest inject-bad vs sprint2 (clean):**

| Trường | sprint2 (clean) | inject-bad |
|--------|----------------|------------|
| `cleaned_records` | 5 | 5 |
| `quarantine_records` | 5 | 5 |
| `no_refund_fix` | false | true |
| `skipped_validate` | false | false |

**Kết quả eval retrieval** (`artifacts/eval/`):

| Câu hỏi | before_after_eval (clean) | after_inject_bad |
|---------|--------------------------|-----------------|
| `q_refund_window` | contains_expected=yes, hits_forbidden=no | contains_expected=yes, hits_forbidden=no |
| `q_leave_version` | contains_expected=yes, top1_doc_expected=yes | contains_expected=yes, top1_doc_expected=yes |
| `q_p1_sla` | contains_expected=yes | contains_expected=yes |

> **Nhận xét:** Rule 8 đã quarantine row migration trước bước refund fix → stale text không vào index → retrieval không thay đổi giữa inject và clean. Đây là bằng chứng Rule 8 hoạt động như "lớp bảo vệ sớm" ngay cả khi fix bị bypass.

---

## 4. Freshness & monitoring (100–150 từ)

> SLA bạn chọn, ý nghĩa PASS/WARN/FAIL trên manifest mẫu.

SLA freshness được đặt là **24 giờ** (`FRESHNESS_SLA_HOURS=24` trong `.env`). Pipeline đo freshness bằng trường `latest_exported_at` trong manifest — là giá trị `exported_at` lớn nhất của các cleaned rows.

Trên data mẫu, `latest_exported_at = 2026-04-10T08:00:00` (cũ hơn thời điểm chạy pipeline ~121 giờ) → kết quả là **FAIL** (`age_hours=121.21, reason=freshness_sla_exceeded`).

| Trạng thái | Ý nghĩa | Hành động |
|-----------|---------|-----------|
| PASS | Data mới hơn SLA 24h | Tiếp tục bình thường |
| WARN | Không có timestamp trong manifest | Kiểm tra pipeline có ghi `exported_at` không |
| FAIL | Data cũ hơn SLA | Cảnh báo team data — cần re-export từ nguồn |

> **Lưu ý:** FAIL trên data mẫu là **hợp lý và có chủ đích** — CSV mẫu dùng ngày cố định để minh hoạ cơ chế freshness, không phải data production thật.

---

## 5. Liên hệ Day 09 (50–100 từ)

> Dữ liệu sau embed có phục vụ lại multi-agent Day 09 không? Nếu có, mô tả tích hợp; nếu không, giải thích vì sao tách collection.

_________________

---

## 6. Rủi ro còn lại & việc chưa làm

- …
