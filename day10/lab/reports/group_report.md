# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** ___________  
**Thành viên:**
| Tên | Vai trò (Day 10) | Email |
|-----|------------------|-------|
| ___ | Ingestion / Raw Owner | ___ |
| ___ | Cleaning & Quality Owner | ___ |
| ___ | Embed & Idempotency Owner | ___ |
| ___ | Monitoring / Docs Owner | ___ |

**Ngày nộp:** ___________  
**Repo:** ___________  
**Độ dài khuyến nghị:** 600–1000 từ

---

> **Nộp tại:** `reports/group_report.md`  
> **Deadline commit:** xem `SCORING.md` (code/trace sớm; report có thể muộn hơn nếu được phép).  
> Phải có **run_id**, **đường dẫn artifact**, và **bằng chứng before/after** (CSV eval hoặc screenshot).

---

## 1. Pipeline tổng quan (150–200 từ)

> Nguồn raw là gì (CSV mẫu / export thật)? Chuỗi lệnh chạy end-to-end? `run_id` lấy ở đâu trong log?

**Tóm tắt luồng:**

_________________

**Lệnh chạy một dòng (copy từ README thực tế của nhóm):**

_________________

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

_________________

**Kết quả định lượng (từ CSV / bảng):**

_________________

---

## 4. Freshness & monitoring (100–150 từ)

> SLA bạn chọn, ý nghĩa PASS/WARN/FAIL trên manifest mẫu.

_________________

---

## 5. Liên hệ Day 09 (50–100 từ)

> Dữ liệu sau embed có phục vụ lại multi-agent Day 09 không? Nếu có, mô tả tích hợp; nếu không, giải thích vì sao tách collection.

_________________

---

## 6. Rủi ro còn lại & việc chưa làm

- …
