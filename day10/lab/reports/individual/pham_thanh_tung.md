# Báo cáo cá nhân — Lab Day 10

**Họ tên:** Phạm Thanh Tùng  
**Vai trò Day 10:** Người 3 — Quality / Expectation Owner  
**run_id tham chiếu:** `inject-bad` (inject corruption), `after-fix` (pipeline chuẩn)

---

## 1. Phần phụ trách cụ thể

Tôi phụ trách file `quality/expectations.py` — thêm 2 expectation mới vào bộ baseline 6 expectations:

- **E7 `exported_at_valid_iso_datetime`** (severity: **halt**): Kiểm tra tất cả cleaned rows có `exported_at` đúng format ISO datetime (regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}`). Nếu fail → halt pipeline vì `freshness_check.py` sẽ không parse được timestamp → mất khả năng đo SLA.

- **E8 `chunk_text_no_stale_markers`** (severity: **warn**): Quét chunk_text tìm marker stale: `"bản cũ"`, `"sync cũ"`, `"lỗi migration"`, `"deprecated"`. Nếu tìm thấy → warn, nghĩa là data chưa clean triệt để.

Ngoài ra tôi chạy inject Sprint 3 (`--no-refund-fix --skip-validate`), lưu 2 file eval (`after_inject_bad.csv` vs `before_after_eval.csv`), và hoàn thiện `docs/quality_report.md` từ template.

---

## 2. Một quyết định kỹ thuật: Chọn severity halt cho E7, warn cho E8

**Quyết định:** E7 (`exported_at_valid_iso_datetime`) dùng **halt**, E8 (`chunk_text_no_stale_markers`) dùng **warn**.

**Lý do:** Nếu `exported_at` không parse được, toàn bộ freshness monitoring mất tác dụng — pipeline báo "green" nhưng data có thể stale mà không ai biết. Đây là lỗi nghiêm trọng xứng đáng halt. Ngược lại, stale markers trong chunk_text là cảnh báo data chất lượng thấp nhưng không ngăn pipeline hoạt động — warn đủ để nhóm review mà không block embed.

**Trade-off:** E7 halt có thể block pipeline khi `exported_at` thiếu do lỗi export nhỏ. Tuy nhiên, cleaning Rule 8 trong `cleaning_rules.py` đã quarantine dòng thiếu `exported_at` trước khi tới E7 → tạo defense in depth: Rule 8 chặn ở tầng clean, E7 chặn ở tầng validate.

---

## 3. Một sự cố: Expectation refund FAIL khi inject

**Phát hiện:** Chạy `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`, log báo:
```
expectation[refund_no_stale_14d_window] FAIL (halt) :: violations=1
```

**Nguyên nhân:** Flag `--no-refund-fix` giữ chunk dòng 3 CSV chứa "14 ngày làm việc" (bản sync cũ policy-v3). Expectation E3 phát hiện đúng 1 violation. Pipeline vẫn chạy tiếp nhờ `--skip-validate`.

**Fix:** Rerun `python etl_pipeline.py run --run-id after-fix` (không flag) → cleaning rule fix "14→7" ngày, E3 pass, `embed_prune_removed` xóa vector stale.

**Evidence:** `artifacts/eval/after_inject_bad.csv` dòng `q_refund_window`: `hits_forbidden=yes`. `artifacts/eval/before_after_eval.csv` cùng câu: `hits_forbidden=no`.

---

## 4. Before/after

**Trước (run_id=inject-bad):**
```
q_refund_window: contains_expected=yes, hits_forbidden=yes
```
→ Top-k chứa chunk "14 ngày làm việc" stale → agent có thể trả sai.

**Sau (run_id=after-fix):**
```
q_refund_window: contains_expected=yes, hits_forbidden=no
```
→ Chỉ còn chunk "7 ngày làm việc" → agent trả đúng.

---

## 5. Cải tiến 2h

Tích hợp **Great Expectations** thay bộ expectation thủ công: tạo `ExpectationSuite` với `expect_column_values_to_not_be_null("exported_at")` + `expect_column_values_to_match_regex("effective_date", ...)`. Lợi ích: report HTML tự động, data docs, version control suite — đạt Distinction (a) + Bonus +2.
