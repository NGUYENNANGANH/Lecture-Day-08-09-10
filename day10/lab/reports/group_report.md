# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** Nhóm Day10  
**Thành viên:**
| Tên | Vai trò (Day 10) | Email |
|-----|------------------|-------|
| Nguyễn Năng Anh | Ingestion / Pipeline Owner (M1) | nguyennanganh199203@gmail.com |
| Nguyễn Ngọc Hiếu | Cleaning & Quality Owner (M2) | ___ |
| Phạm Thanh Tùng | Quality / Expectation Owner (M3) | ___ |
| Dương Phương Thảo | Embed & Idempotency Owner (M4) | ___ |
| Mai Phi Hiếu | Monitoring / Docs Owner (M5) | ___ |

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

Nguồn raw là `data/raw/policy_export_dirty.csv` (11 dòng, export mô phỏng từ DB nội bộ CS + IT Helpdesk). Pipeline chạy theo chuỗi: `load_raw_csv()` → `clean_rows()` → `run_expectations()` → `cmd_embed_internal()` → ghi manifest + freshness check. `run_id` được log ngay dòng đầu tiên của mỗi file log tại `artifacts/logs/run_<run_id>.log` và đồng bộ vào `artifacts/manifests/manifest_<run_id>.json`.

- **sprint1** (baseline rules): `raw=11, cleaned=6, quarantine=5` — expectations đều PASS
- **inject-bad** (bỏ fix refund): `raw=11, cleaned=6, quarantine=5, no_refund_fix=true` — expectation `refund_no_stale_14d_window` FAIL → skip-validate → embed data xấu
- **after-fix** (clean): `raw=11, cleaned=6, quarantine=5, embed_prune_removed=1` — 8 expectations PASS

**Lệnh chạy một dòng:**

```bash
python etl_pipeline.py run --run-id final-submission
```

---

## 2. Cleaning & expectation (150–200 từ)

> Baseline đã có nhiều rule (allowlist, ngày ISO, HR stale, refund, dedupe…). Nhóm thêm **≥3 rule mới** + **≥2 expectation mới**. Khai báo expectation nào **halt**.

Baseline gồm 6 rule: allowlist `doc_id`, chuẩn hoá `effective_date` (ISO + DD/MM/YYYY), quarantine HR cũ (`effective_date < 2026-01-01`), quarantine `chunk_text` rỗng, dedup nội dung, và fix refund window 14→7 ngày. Với baseline, CSV mẫu (11 dòng) cho ra **cleaned=6, quarantine=5**. Nhóm đã thêm **4 rule mới** vào `transform/cleaning_rules.py` và **2 expectation mới** vào `quality/expectations.py`.

### 2a. Bảng metric_impact (bắt buộc — chống trivial)

| Rule / Expectation mới (tên ngắn) | Trước (số liệu) | Sau / khi inject (số liệu) | Chứng cứ (log / CSV / commit) |
|-----------------------------------|------------------|-----------------------------|-------------------------------|
| R7 `strip_bom_and_control_chars` | Baseline dedup bỏ sót chunk có BOM prefix | Inject row có `\ufeff` prefix → dedup bắt đúng sau strip | `transform/cleaning_rules.py` L71-96 |
| R8 `quarantine_migration_note` | cleaned=6, quarantine=4 (row 3 "lỗi migration" lọt qua với baseline ban đầu) | cleaned=5, quarantine=5 (row 3 bị quarantine `leaked_migration_annotation`) | `artifacts/quarantine/` CSV |
| R9 `normalize_whitespace_chunk` | Chunk có `\xa0` non-breaking space bypass dedup | Normalize `\xa0`→space trước dedup → catch near-duplicate | `transform/cleaning_rules.py` L127-149 |
| R10 `validate_chunk_min_length` | Baseline chỉ chặn empty text | Inject row text="OK" (2 chars) → quarantine `chunk_too_short` | `transform/cleaning_rules.py` L156-173 |
| E7 `exported_at_valid_iso_datetime` (halt) | Nếu cleaning rule bỏ sót row thiếu exported_at → E7 halt ngăn embed | OK trên CSV mẫu (cleaning đã xử lý trước) | `quality/expectations.py` E7 |
| E8 `chunk_text_no_stale_markers` (warn) | Inject chunk chứa "bản cũ"/"sync cũ" → warn | OK trên CSV mẫu (cleaning rule R8 xử lý trước) | `quality/expectations.py` E8 |

**Rule chính (baseline + mở rộng):**

- **Baseline (6 rule):** allowlist `doc_id`, normalize `effective_date`, quarantine HR stale, quarantine empty text, dedup `chunk_text`, fix refund 14→7 ngày
- **Mở rộng (4 rule mới):** strip BOM/control chars (R7), quarantine migration annotation (R8), normalize whitespace (R9), validate min chunk length ≥10 chars (R10)

**Ví dụ 1 lần expectation fail (nếu có) và cách xử lý:**

Khi chạy `--no-refund-fix --skip-validate`, expectation `refund_no_stale_14d_window` → **FAIL (halt)** với `violations=1`. Pipeline tiếp tục embed vì `--skip-validate` được bật. Sau rerun chuẩn (`after-fix`), expectation OK, `embed_prune_removed=1` xóa chunk stale.

---

## 3. Before / after ảnh hưởng retrieval hoặc agent (200–250 từ)

> Bắt buộc: inject corruption (Sprint 3) — mô tả + dẫn `artifacts/eval/…` hoặc log.

**Kịch bản inject:**

Chạy `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate` để bỏ qua fix refund và skip validate. Kết quả:

- Expectation `refund_no_stale_14d_window` → **FAIL (halt)** — `violations=1`
- Pipeline vẫn embed vì `--skip-validate`
- Chunk "14 ngày làm việc" lọt vào Chroma index

**So sánh manifest inject-bad vs after-fix:**

| Trường | after-fix (clean) | inject-bad |
|--------|-------------------|------------|
| `cleaned_records` | 6 | 6 |
| `quarantine_records` | 5 | 5 |
| `no_refund_fix` | false | true |
| `skipped_validate` | false | true |
| `embed_prune_removed` | 1 | — |

**Kết quả eval retrieval** (`artifacts/eval/`):

| Câu hỏi | after-fix (clean) | inject-bad |
|---------|-------------------|------------|
| `q_refund_window` | contains_expected=yes, **hits_forbidden=no** ✅ | contains_expected=yes, **hits_forbidden=yes** ❌ |
| `q_leave_version` | contains_expected=yes, top1_doc_expected=yes ✅ | contains_expected=yes, top1_doc_expected=yes |
| `q_p1_sla` | contains_expected=yes ✅ | contains_expected=yes |

> **Kết luận:** Retrieval **tệ hơn khi inject** (`hits_forbidden=yes` cho refund) và **tốt hơn sau fix** (`hits_forbidden=no`). HR versioning đã đúng cả hai trường hợp nhờ quarantine rule 3 hoạt động ngay cả khi `--no-refund-fix`.

---

## 4. Freshness & monitoring (100–150 từ)

> SLA bạn chọn, ý nghĩa PASS/WARN/FAIL trên manifest mẫu.

*Phần này do Mai Phi Hiếu (M5 — Monitoring / Docs Owner) thực hiện.*

**SLA:** `FRESHNESS_SLA_HOURS=24` (cấu hình trong `.env` và `data_contract.yaml`). Phù hợp cho batch policy update hàng ngày.

**Dual-boundary freshness** (đáp ứng Distinction b / Bonus +1):

| Boundary | Timestamp | Giá trị (run `after-fix`) | Status |
|----------|-----------|---------------------------|--------|
| **Ingest** | `latest_exported_at` | `2026-04-10T08:00:00` (age ≈ 122h) | **FAIL** (> 24h SLA) |
| **Publish** | `run_timestamp` | `2026-04-15T10:30:08+00:00` (age ≈ 0h) | **PASS** |
| **Processing delay** | `publish − ingest` | ≈ 122h | Thời gian giữa export nguồn và pipeline xử lý |

**Overall:** `FAIL` — worst-case giữa 2 boundary.

**Giải thích:** CSV mẫu có `exported_at = 2026-04-10T08:00:00` — export cũ 5 ngày. FAIL là **mong đợi và hợp lý** trên data mẫu. Trong production:
- Cron job re-export CSV mới hàng ngày → giữ `ingest_age < 24h`
- Pipeline schedule sau re-export → `publish_age < 1h`
- WARN khi `age > 18h (75% SLA)` → buffer trước FAIL

**Chứng cứ log:**
```
freshness_check=FAIL {
  "run_id": "after-fix",
  "overall_status": "FAIL",
  "ingest_boundary": {"status": "FAIL", "age_hours": 122.5, "reason": "ingest_sla_exceeded"},
  "publish_boundary": {"status": "PASS", "age_hours": 0.002},
  "processing_delay_hours": 122.5,
  "sla_hours": 24.0
}
```

**Reliability insight:** Pipeline chạy 3 lần (`inject-bad`, `after-fix`, `final`) — mỗi lần exit 0 (`PIPELINE_OK` khi không halt), idempotent (count Chroma không thay đổi giữa 2 run cùng data). `embed_prune_removed=1` chứng minh prune hoạt động khi chuyển từ inject → clean.

---

## 5. Liên hệ Day 09 (50–100 từ)

> Dữ liệu sau embed có phục vụ lại multi-agent Day 09 không? Nếu có, mô tả tích hợp; nếu không, giải thích vì sao tách collection.

Pipeline Day 10 embed vào collection `day10_kb` — **tách biệt** khỏi collection Day 09. Lý do:
- **Isolation:** Cho phép inject corruption (Sprint 3) mà không ảnh hưởng RAG Day 09 production.
- **Compatibility:** Cùng embedding model `all-MiniLM-L6-v2` → vector space tương thích. Nếu cần, agent Day 09 có thể trỏ sang `day10_kb` qua config `CHROMA_COLLECTION`.
- **Quality proof:** Day 10 chứng minh pipeline clean trước khi agent "đọc đúng version" — collection `day10_kb` là phiên bản đã qua quality gate.

---

## 6. Rủi ro còn lại & việc chưa làm

- **Freshness SLA:** Không tự động re-export CSV mới — cần cron job hoặc event-driven trigger trong production.
- **HR cutoff hard-code:** `2026-01-01` trong `cleaning_rules.py` — nên đọc từ `data_contract.yaml` (`policy_versioning.hr_leave_min_effective_date`).
- **Chưa tích hợp LLM-judge:** Eval chỉ dùng keyword matching, chưa đánh giá chất lượng câu trả lời end-to-end.
- **Single collection:** Chưa có blue/green index swap cho zero-downtime update.
- **Alert channel:** Freshness FAIL chỉ log ra file — production cần Slack/email alert.
- **E8 stale markers:** Danh sách markers hiện hard-code — nên đọc từ config/contract.
- **Missing automated CI/CD:** Chưa có pipeline chạy test + deploy tự động.

---

## 7. Peer Review — 3 câu hỏi (Phần E, slide 42)

### Câu 1: "Nếu rerun pipeline 2 lần liên tiếp, kết quả embedding có bị duplicate không?"

**Trả lời:** Không. Pipeline đảm bảo **idempotent** qua 2 cơ chế:

1. **`chunk_id` ổn định:** Hash `SHA256(doc_id|chunk_text|seq)[:16]` — cùng data → cùng id → `upsert` không tạo bản trùng.
2. **Prune stale IDs:** Trước mỗi upsert, pipeline lấy tất cả IDs trong collection, xóa những ID không còn trong cleaned run hiện tại.

**Chứng cứ:** Rerun `python etl_pipeline.py run --run-id final` 2 lần → `embed_upsert count=6`, `collection.count()` không đổi, `embed_prune_removed=0` (lần 2 không có gì để xóa).

Tham chiếu: `etl_pipeline.py` L154-176, `cleaning_rules.py` `_stable_chunk_id()` L45-47.

---

### Câu 2: "Freshness monitor đo ở đâu? Metric nào báo?"

**Trả lời:** Freshness đo tại **2 boundary** (đáp ứng Distinction b):

| Boundary | Metric | Ý nghĩa |
|----------|--------|---------|
| **Ingest** | `latest_exported_at` | Data export từ nguồn bao lâu rồi? |
| **Publish** | `run_timestamp` | Pipeline publish xong lúc nào? |
| **Delay** | `publish − ingest` | Pipeline mất bao lâu xử lý? |

Ngưỡng: `≤ 75% SLA → PASS`, `75-100% SLA → WARN`, `> SLA → FAIL`. Cấu hình: `FRESHNESS_SLA_HOURS=24` (trong `.env`).

Trên data mẫu: ingest FAIL (age ≈ 122h > 24h), publish PASS (vừa chạy), overall FAIL — đây là hành vi **mong đợi** vì CSV mẫu có `exported_at` cũ 5 ngày.

Tham chiếu: `monitoring/freshness_check.py`, `artifacts/manifests/manifest_after-fix.json`.

---

### Câu 3: "Quarantine row đi đâu? Có cách nào recover không?"

**Trả lời:** Quarantine row được ghi vào `artifacts/quarantine/quarantine_<run_id>.csv` với đầy đủ row gốc + cột `reason` (ví dụ: `unknown_doc_id`, `stale_hr_policy_effective_date`, `leaked_migration_annotation`).

**Không tự động recover.** Quy trình:
1. Cleaning Owner review quarantine CSV
2. Xác định root cause (catalog sai? data nguồn lỗi? version cũ?)
3. Fix tại nguồn (sửa CSV export hoặc cập nhật allowlist)
4. Rerun pipeline → row đã fix sẽ qua quality gate

Ví dụ: Row 7 (HR 2025, "10 ngày phép") bị quarantine `stale_hr_policy_effective_date` — đây là version cũ chính xác phải loại bỏ, không cần recover.

Tham chiếu: `docs/data_contract.md` mục 3 (Quarantine vs Drop), `cleaning_rules.py` L201-288.
