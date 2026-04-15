# Runbook — Lab Day 10: Data Pipeline & Data Observability

**Tác giả:** Mai Phi Hiếu (M5 — Monitoring / Docs Owner)  
**Cập nhật:** 2026-04-15  
**Tham chiếu:** `docs/pipeline_architecture.md`, `contracts/data_contract.yaml`

> **Mục đích:** Hướng dẫn xử lý sự cố data pipeline theo format chuẩn 5 bước:
> **Symptom → Detection → Diagnosis → Mitigation → Fix → Prevention**

---

## Case 1: Stale Data — Agent trả lời "14 ngày" thay vì "7 ngày"

### Symptom

User hỏi chính sách hoàn tiền, agent trả lời "Khách có **14 ngày làm việc** để gửi yêu cầu hoàn tiền" — sai so với policy hiện hành (v4 = **7 ngày**).

### Detection

| Metric / Signal | Giá trị phát hiện | Nguồn |
|-----------------|-------------------|-------|
| `freshness_check` | **FAIL** — `age_hours=122.5`, `sla_hours=24.0` | `artifacts/logs/run_inject-bad.log` |
| Expectation `refund_no_stale_14d_window` | **FAIL (halt)** — `violations=1` | `artifacts/logs/run_inject-bad.log` |
| Eval retrieval `q_refund_window` | `hits_forbidden=yes` — chunk "14 ngày" còn trong top-k | `artifacts/eval/after_inject_bad.csv` |

### Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|-------------------|
| 1 | Kiểm tra `artifacts/manifests/manifest_inject-bad.json` | `no_refund_fix=true`, `skipped_validate=true` → pipeline inject không fix refund |
| 2 | Kiểm tra log freshness | `freshness_check=FAIL` — ingest boundary: `age_hours > 120h` → data export cũ 5 ngày |
| 3 | Mở `artifacts/quarantine/quarantine_inject-bad.csv` | Xác nhận row migration bị quarantine nhưng row refund "14 ngày" lọt qua (vì `--no-refund-fix`) |
| 4 | Chạy `python eval_retrieval.py` | `hits_forbidden=yes` cho `q_refund_window` → context chứa thông tin stale |
| 5 | Kiểm tra Chroma collection | Chunk với text "14 ngày làm việc" tồn tại trong index |

**Root cause:** Pipeline chạy với `--no-refund-fix` → Rule 6 bị bypass → chunk stale "14 ngày" embed vào Chroma → agent trích sai.

### Mitigation

1. **Ngay lập tức:** Rerun pipeline chuẩn (không flag inject):
   ```bash
   python etl_pipeline.py run --run-id hotfix-refund
   ```
2. Pipeline sẽ:
   - Rule 6 fix "14 ngày" → "7 ngày"
   - Prune vector cũ (`embed_prune_removed` > 0)
   - Upsert cleaned vectors
3. Xác nhận: Chạy eval retrieval và kiểm tra `hits_forbidden=no`

### Fix

```bash
# 1. Rerun pipeline chuẩn
python etl_pipeline.py run --run-id after-fix

# 2. Kiểm tra expectation pass
# Log: expectation[refund_no_stale_14d_window] OK (halt) :: violations=0

# 3. Eval retrieval
python eval_retrieval.py --out artifacts/eval/after_fix.csv
# Kết quả: q_refund_window → contains_expected=yes, hits_forbidden=no ✅
```

### Prevention

1. **Expectation halt:** `refund_no_stale_14d_window` (severity=halt) ngăn embed khi chunk stale còn trong cleaned data
2. **Never bypass in production:** Flag `--no-refund-fix` và `--skip-validate` chỉ dùng cho demo Sprint 3 — không dùng trên production run
3. **Freshness alert:** Cấu hình `FRESHNESS_SLA_HOURS=24` trong `.env` — pipeline log FAIL nếu data export quá cũ
4. **CI/CD check:** Script `instructor_quick_check.py` sanity check manifest trước deploy
5. **Đọc thêm policy versioning từ contract:** `data_contract.yaml` → `policy_versioning` thay vì hard-code

---

## Case 2: Refund sai — Xung đột version policy (Clean vs Stale)

### Symptom

Agent trả lời khách hàng với 2 thông tin mâu thuẫn: "7 ngày" và "14 ngày" xuất hiện cùng lúc trong context, gây nhầm lẫn. Hoặc: sau khi re-export CSV mới, prune không hoạt động và chunk cũ vẫn tồn tại trong index.

### Detection

| Metric / Signal | Giá trị phát hiện | Nguồn |
|-----------------|-------------------|-------|
| Eval retrieval | `hits_forbidden=yes` — cả "7 ngày" VÀ "14 ngày" trong top-k | `eval_retrieval.py` output |
| Manifest diff | 2 manifest liên tiếp có `no_refund_fix` khác nhau | `artifacts/manifests/` diff |
| Expectation | `refund_no_stale_14d_window` FAIL khi inject, OK khi fix | Log comparison |

### Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|-------------------|
| 1 | So sánh manifest `inject-bad` vs `after-fix` | `no_refund_fix: true` vs `false`; `skipped_validate: true` vs `false` |
| 2 | Check `embed_prune_removed` trong log | Nếu `prune_removed > 0` → pipeline đã xóa chunk cũ; nếu 0 → chunk content giống nhau (chỉ text đổi, id đổi theo) |
| 3 | Đếm `collection.count()` qua 2 runs | Nếu count tăng → prune không đúng hoặc chunk_id đổi |
| 4 | Kiểm tra `chunk_id` có ổn định không | `SHA256(doc_id|chunk_text|seq)` — nếu text đổi, id sẽ đổi → upsert tạo mới, prune xóa cũ |

**Root cause:** Pipeline chạy 2 lần với flag khác nhau mà không prune đúng, HOẶC chunk_id thay đổi giữa các run do text content thay đổi (fix 14→7 đổi hash).

### Mitigation

1. **Rerun pipeline chuẩn** để sync index:
   ```bash
   python etl_pipeline.py run --run-id fix-version-conflict
   ```
2. Prune sẽ xóa chunk có id cũ (text "14 ngày") và upsert chunk mới (text "7 ngày")
3. Verify: `embed_prune_removed` trong log > 0

### Fix

```bash
# Rerun + verify
python etl_pipeline.py run --run-id after-fix
# Log output:
#   embed_prune_removed=1  ← chunk "14 ngày" bị xóa
#   embed_upsert count=6   ← 6 cleaned chunks upsert

python eval_retrieval.py --out artifacts/eval/after_fix.csv
# q_refund_window: hits_forbidden=no ✅
```

### Prevention

1. **Idempotent pipeline:** Mỗi run là snapshot — prune xóa vector không còn trong cleaned, upsert cập nhật vector có cùng id
2. **Single source of truth:** Duy trì 1 canonical run (không dùng `--no-refund-fix` trên production)
3. **Manifest lineage:** Ghi `no_refund_fix`, `skipped_validate` vào manifest → có thể audit ngược
4. **Expectation chain:** E3 (halt) ngăn embed khi stale refund; E8 (warn) cảnh báo marker stale trong text
5. **Scheduled rerun:** Cron rerun pipeline hàng ngày → đảm bảo index luôn reflect cleaned mới nhất

---

## Case 3: Embed Duplicate — Vector trùng trong ChromaDB

### Symptom

Agent retrieval trả về nhiều kết quả giống nhau (duplicate chunks) trong top-k, khiến context bị chiếm bởi cùng 1 nội dung — giảm chất lượng coverage của retrieval, có thể bỏ lỡ chunk quan trọng khác.

### Detection

| Metric / Signal | Giá trị phát hiện | Nguồn |
|-----------------|-------------------|-------|
| `collection.count()` | Tăng sau mỗi lần rerun (expected: không đổi) | Chroma API / pipeline log |
| `embed_prune_removed` | **0** mặc dù data đã thay đổi | `artifacts/logs/run_*.log` |
| Eval retrieval | Top-k chứa chunks giống nhau từ cùng `doc_id` | `eval_retrieval.py` output |

### Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|-------------------|
| 1 | Kiểm tra `embed_prune_removed` trong log gần nhất | Nếu = 0 khi data đã đổi → prune chưa chạy đúng |
| 2 | So sánh `collection.count()` qua 2 run liên tiếp | Nếu tăng bất thường (> `cleaned_records`) → duplicate |
| 3 | Kiểm tra `chunk_id` generation | `_stable_chunk_id(doc_id, text, seq)` — nếu seq thay đổi dù text giống → id mới, tạo bản trùng |
| 4 | Kiểm tra BOM/whitespace | Text giống nhau nhưng BOM (\ufeff) hoặc NBSP (\xa0) khiến hash khác → 2 vector cho cùng nội dung |
| 5 | Kiểm tra cleaning rules R7, R9 | Rules strip BOM + normalize whitespace TRƯỚC khi hash → đảm bảo consistency |

**Root cause tiềm năng:**
- `chunk_id` tính từ `SHA256(doc_id|chunk_text|seq)` — nếu BOM/whitespace không clean trước, 2 chunk "giống" sẽ có hash khác
- Prune logic bị lỗi (exception catched nhưng không re-raise)
- Multiple concurrent pipeline runs ghi vào cùng collection

### Mitigation

1. **Immediate:** Xóa collection và rebuild:
   ```bash
   # Xóa chroma_db folder (hoặc delete collection)
   rm -rf chroma_db/
   python etl_pipeline.py run --run-id rebuild
   ```
2. Verify: `collection.count() == len(cleaned_rows)` (= 6 trên CSV mẫu)

### Fix

```bash
# 1. Kiểm tra rules R7 + R9 đang active
# cleaning_rules.py: strip_bom_and_control_chars() + normalize_whitespace_chunk()
# → text normalized TRƯỚC khi tính chunk_id

# 2. Rerun pipeline
python etl_pipeline.py run --run-id fix-dup

# 3. Verify idempotency — run lần 2
python etl_pipeline.py run --run-id fix-dup-verify
# Log: embed_upsert count=6, collection count không đổi → idempotent ✅
```

### Prevention

1. **Cleaning rules R7 + R9:** Strip BOM + normalize whitespace TRƯỚC dedupe và hash → cùng nội dung = cùng chunk_id
2. **Rule R10:** Chunk quá ngắn (< 10 chars) bị quarantine → giảm noise
3. **Prune mechanism:** Pipeline xóa IDs không còn trong cleaned trước khi upsert → index = exact snapshot
4. **Idempotency test:** Rerun 2 lần cùng data, kiểm tra `collection.count()` không đổi
5. **Expectation E4:** `chunk_min_length_8` (warn) phát hiện chunk ngắn — thường là noise/dup fragments
6. **Monitoring:** Thêm log `collection_count_before` và `collection_count_after` để detect phình bất thường

---

## Case 4: Freshness SLA Exceeded (FAIL) — Data snapshot cũ

### Symptom

Pipeline chạy thành công (`PIPELINE_OK`) nhưng `freshness_check=FAIL` — agent vẫn phục vụ data đúng nhưng cũ so với SLA.

### Detection

| Metric / Signal | Giá trị phát hiện | Nguồn |
|-----------------|-------------------|-------|
| `freshness_check` | **FAIL** — `age_hours=122.5 > sla_hours=24.0` | Pipeline log + manifest |
| Dual-boundary | Ingest: FAIL (`exported_at` cũ), Publish: PASS (vừa chạy) | `monitoring/freshness_check.py` |

### Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|-------------------|
| 1 | Kiểm tra `latest_exported_at` trong manifest | `2026-04-10T08:00:00` — export cũ 5 ngày |
| 2 | Kiểm tra `run_timestamp` | Gần `now` → pipeline chạy gần đây nhưng data cũ |
| 3 | Tính `processing_delay` | `run_timestamp - latest_exported_at` = ~122h → data cũ được xử lý muộn |
| 4 | Kiểm tra nguồn export | Source DB/API chưa re-export CSV mới |

**Root cause:** CSV mẫu (`policy_export_dirty.csv`) có `exported_at = 2026-04-10T08:00:00` — đây là snapshot cố định cho lab, SLA 24h → FAIL là **mong đợi và hợp lý**.

### Mitigation

- **Trong lab:** FAIL là hành vi đúng — ghi nhận trong report
- **Trong production:**
  1. Trigger re-export từ nguồn (API call hoặc cron)
  2. Rerun pipeline với CSV mới
  3. Nếu không thể re-export ngay: banner "Dữ liệu đang bảo trì" trên UI

### Fix

```bash
# Option 1: Chấp nhận FAIL (lab scenario — data mẫu cố định)
# Giải thích: SLA 24h áp cho production batch, FAIL trên snapshot cũ là chính xác

# Option 2: Giảm yêu cầu SLA (nếu phù hợp)
# .env: FRESHNESS_SLA_HOURS=168  (weekly batch)

# Option 3: Production — cập nhật exported_at
# Re-export CSV mới từ source DB → rerun pipeline
```

### Prevention

1. **Cron job re-export:** Tự động export CSV mới hàng ngày từ source DB
2. **Dual-boundary monitoring:** Tách biệt ingest freshness vs publish freshness — ingest FAIL + publish PASS = data cũ, pipeline mới
3. **Alert escalation:** WARN khi `age > 75% SLA` → team có buffer trước FAIL
4. **SLA documentation:** Ghi rõ trong `data_contract.yaml` → `freshness.sla_hours: 24` và `freshness.measured_at: publish`
5. **`FRESHNESS_SLA_HOURS` configurable:** Không hard-code — đọc từ `.env` hoặc contract

---

## Tổng hợp — Debug Order (từ slide Day 10)

```
Freshness / version → Volume & errors → Schema & contract → Lineage / run_id → Model / prompt
```

> **Nguyên tắc:** Luôn kiểm tra data trước model. 60-80% effort trong AI production thường là data work.

---

## Quick Reference — Lệnh chẩn đoán

```bash
# 1. Kiểm tra freshness
python etl_pipeline.py freshness --manifest artifacts/manifests/manifest_<run-id>.json

# 2. Đọc log pipeline
cat artifacts/logs/run_<run-id>.log

# 3. Kiểm tra quarantine
cat artifacts/quarantine/quarantine_<run-id>.csv

# 4. Eval retrieval
python eval_retrieval.py --out artifacts/eval/check.csv

# 5. Sanity check grading
python instructor_quick_check.py --grading artifacts/eval/grading_run.jsonl
python instructor_quick_check.py --manifest artifacts/manifests/manifest_<run-id>.json
```
