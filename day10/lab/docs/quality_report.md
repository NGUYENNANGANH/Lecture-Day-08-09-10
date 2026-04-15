# Quality report — Lab Day 10 (nhóm)

**run_id:** `inject-bad` (inject), `after-fix` (fix)  
**Ngày:** 2026-04-15

---

## 1. Tóm tắt số liệu

| Chỉ số | Trước (inject-bad) | Sau (after-fix) | Ghi chú |
|--------|----------------------|-------------------|---------|
| raw_records | 10 | 10 | Cùng input CSV |
| cleaned_records | 6 | 6 | Số dòng qua quality gate |
| quarantine_records | 4 | 4 | unknown_doc_id(1), missing_effective_date(1), stale_hr(1), duplicate(1) |
| Expectation halt? | **YES** (`refund_no_stale_14d_window` FAIL, `chunk_text_no_stale_markers` FAIL warn) | **NO** (all OK) | Inject bỏ fix → chunk "14 ngày" + marker "sync cũ"/"lỗi migration" còn |
| embed_prune_removed | 1 (khi chuyển từ clean → inject) | 1 (khi chuyển từ inject → clean) | Prune vector cũ hoạt động đúng |

### Expectations mới — metric_impact

| Expectation | Severity | Kịch bản test | Kết quả inject-bad | Kết quả after-fix | metric_impact |
|-------------|----------|---------------|----------------------|---------------------|---------------|
| E7: `exported_at_valid_iso_datetime` | halt | Inject dòng thiếu exported_at | OK (Rule 8 cleaning đã quarantine trước) | OK | Lớp bảo vệ cuối cùng: nếu cleaning rule 8 bỏ sót dòng thiếu exported_at → E7 halt pipeline, ngăn embed dữ liệu thiếu timestamp → freshness check có ý nghĩa |
| E8: `chunk_text_no_stale_markers` | warn | `--no-refund-fix`: chunk chứa "bản sync cũ policy-v3 — lỗi migration" | **FAIL (warn)** — `stale_marker_chunks=1` | **PASS** — `stale_marker_chunks=0` | Phát hiện chunk chưa được clean triệt để: marker "sync cũ", "lỗi migration", "bản cũ", "deprecated" còn sót → data chưa production-ready |

---

## 2. Before / after retrieval (bắt buộc)

> Dữ liệu từ `artifacts/eval/after_inject_bad.csv` (inject) và `artifacts/eval/before_after_eval.csv` (fix).

### Câu hỏi then chốt: refund window (`q_refund_window`)

**Trước (inject-bad — `--no-refund-fix --skip-validate`):**
| Field | Value |
|-------|-------|
| top1_doc_id | policy_refund_v4 |
| contains_expected | yes (có "7 ngày" trong top-k) |
| **hits_forbidden** | **yes** (chunk "14 ngày làm việc" còn trong top-k) |

→ Agent có thể trả lời sai vì context chứa cả thông tin cũ "14 ngày" lẫn mới "7 ngày".

**Sau (after-fix — pipeline chuẩn):**
| Field | Value |
|-------|-------|
| top1_doc_id | policy_refund_v4 |
| contains_expected | yes |
| **hits_forbidden** | **no** |

→ Chunk "14 ngày" đã bị fix thành "7 ngày" + tag `[cleaned: stale_refund_window]`. Agent trả lời đúng.

**Kết luận `q_refund_window`:** Retrieval **tệ hơn khi inject** (`hits_forbidden=yes`), **tốt hơn sau fix** (`hits_forbidden=no`). ✅

### Merit: versioning HR — `q_leave_version`

**Trước (inject-bad):**
| Field | Value |
|-------|-------|
| top1_doc_id | hr_leave_policy |
| contains_expected | yes ("12 ngày") |
| hits_forbidden | no ("10 ngày phép năm" không còn) |
| top1_doc_expected | yes |

**Sau (after-fix):**
| Field | Value |
|-------|-------|
| top1_doc_id | hr_leave_policy |
| contains_expected | yes |
| hits_forbidden | no |
| top1_doc_expected | yes |

→ HR versioning đã đúng cả trước và sau vì cleaning rule quarantine bản HR cũ (`effective_date < 2026-01-01`) hoạt động ngay cả khi `--no-refund-fix`. Tuy nhiên, expectation `hr_leave_no_stale_10d_annual` sẽ FAIL nếu bản cũ lọt qua.

---

## 3. Freshness & monitor

- **Kết quả:** `freshness_check=FAIL` — `age_hours=121.7`, `sla_hours=24.0`
- **Giải thích:** CSV mẫu có `exported_at = 2026-04-10T08:00:00` — export cũ ~5 ngày. FAIL là **hợp lý và mong đợi** trên data mẫu.
- **SLA chọn:** 24 giờ (cấu hình qua `FRESHNESS_SLA_HOURS` trong `.env`). Phù hợp cho batch policy update hàng ngày.
- **Trong production:** Cron job export mới + rerun pipeline giữ SLA.

---

## 4. Corruption inject (Sprint 3)

**Kịch bản inject:**
1. Chạy `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`
2. Flag `--no-refund-fix` giữ nguyên chunk "14 ngày làm việc" (không fix thành 7 ngày)
3. Flag `--skip-validate` bỏ qua halt khi expectation FAIL → vẫn embed data xấu vào Chroma

**Phát hiện (từ log `run_inject-bad.log`):**
- Expectation `refund_no_stale_14d_window` → **FAIL (halt)** — violations=1
- Expectation `chunk_text_no_stale_markers` → **FAIL (warn)** — chunk chứa "bản sync cũ", "lỗi migration"
- Eval retrieval: `hits_forbidden=yes` cho `q_refund_window`

**Fix:** Rerun pipeline chuẩn (`python etl_pipeline.py run --run-id after-fix`) → tất cả expectation PASS, `hits_forbidden=no`, prune loại chunk cũ.

---

## 5. Hạn chế & việc chưa làm

- **Freshness SLA:** Không tự động re-export CSV mới — cần cron job hoặc event-driven trigger.
- **HR cutoff hard-code:** `2026-01-01` trong `cleaning_rules.py` — nên đọc từ `data_contract.yaml` (`policy_versioning.hr_leave_min_effective_date`).
- **Chưa tích hợp LLM-judge:** Eval chỉ dùng keyword matching, chưa đánh giá chất lượng câu trả lời end-to-end.
- **Single collection:** Chưa có blue/green index swap cho zero-downtime update.
- **Alert channel:** Chưa cấu hình (`__TODO__` trong contract) — cần tích hợp Slack/email.
- **E8 stale markers:** Danh sách markers hiện hard-code trong code — nên đọc từ config/contract để dễ mở rộng.
