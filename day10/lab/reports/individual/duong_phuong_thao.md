# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Dương Phương Thảo  
**Vai trò:** Embed & Idempotency Owner  
**Ngày nộp:** 2026-04-15  
**Độ dài yêu cầu:** **400–650 từ**

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

**File / module:**

- `etl_pipeline.py` — hàm `cmd_embed_internal()` (dòng 131–177): tôi chịu trách nhiệm kiểm tra và đảm bảo logic embed idempotent hoạt động đúng — upsert theo `chunk_id`, prune vector lạc hậu, đảm bảo index = snapshot publish.
- `etl_pipeline.py` dòng 162 — tôi sửa logic logging `embed_prune_removed` để luôn ghi vào log kể cả khi không có vector nào bị prune (giá trị = 0), phục vụ verification tự động.
- Toàn bộ artifact pipeline: tôi chạy pipeline với các `run_id` thực tế (`final`, `inject-bad`, `after-fix`) và commit 27 file artifact (logs, manifests, eval CSV, cleaned/quarantine CSV).

**Kết nối với thành viên khác:**

Tôi nhận cleaned CSV từ Cleaning Owner (output `clean_rows()`) rồi kiểm tra embed vào Chroma collection `day10_kb`. Pipeline Owner (Nguyễn Năng Anh) viết hàm điều phối `cmd_run()` gọi `cmd_embed_internal()` ở bước cuối. Tôi cũng chạy `grading_run.py` và tạo file `artifacts/eval/grading_run.jsonl`.

**Bằng chứng (commit / comment trong code):**

- Commit `abde2f4`: *"update artifact logs, manifests, and evaluation files while cleaning up obsolete run records"* — chạy lại pipeline, tổ chức lại 27 file artifact với run_id chính thức (`final`, `inject-bad`, `after-fix`), tạo `grading_run.jsonl`, xóa artifact cũ thừa (`sprint1`, `sprint2`, `ci-smoke`, `before-fix`).
- Thay đổi chưa commit: `etl_pipeline.py` dòng 162 — đưa `log(f"embed_prune_removed={len(drop)}")` ra khỏi `if drop:` để log luôn xuất hiện khi rerun (giá trị 0 khi idempotent).

---

## 2. Một quyết định kỹ thuật (100–150 từ)

**Quyết định: Dùng `upsert` + prune thay vì `delete_collection` + `add` để đảm bảo idempotency.**

Khi embed lại dữ liệu, có hai lựa chọn: (1) xóa toàn bộ collection rồi thêm lại, hoặc (2) upsert theo `chunk_id` rồi prune các id lạc hậu. Tôi kiểm tra và xác nhận cách (2) hoạt động đúng vì:

- **Không downtime:** Collection luôn có data phục vụ retrieval, không gián đoạn giữa delete và add.
- **Idempotent thật sự:** Tôi chạy 2 lần liên tiếp với `run_id=idem-1` và `run_id=idem-2`. Kết quả ghi tại `artifacts/logs/run_idem-1.log` (dòng 14–15) và `artifacts/logs/run_idem-2.log` (dòng 14–15) đều cho cùng kết quả: `embed_prune_removed=0`, `embed_upsert count=6 collection=day10_kb`. Collection không phình từ 6 lên 12 vector sau 2 lần chạy.
- **Snapshot publish:** So sánh `artifacts/manifests/manifest_idem-1.json` và `manifest_idem-2.json`: cả hai đều ghi `cleaned_records=6`, `chroma_collection=day10_kb`. Index chỉ chứa đúng 6 `chunk_id` khớp với `artifacts/cleaned/cleaned_idem-1.csv`, không có vector lạc hậu từ run trước.

Tôi cũng sửa logic logging: ban đầu `embed_prune_removed` chỉ xuất hiện trong log khi có vector bị xóa (`if drop:`). Tôi đưa câu log ra ngoài `if` để khi chạy idempotency test, log luôn hiển thị `embed_prune_removed=0` — giúp giám khảo xác nhận prune logic đã chạy.

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

**Triệu chứng:** Khi chạy `python3 etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`, chunk chứa "14 ngày làm việc" bị embed vào Chroma. Kết quả eval retrieval (file `artifacts/eval/after_inject_bad.csv`, dòng 2) cho `q_refund_window` trả về `hits_forbidden=yes` — agent lấy context sai chứa cả thông tin cũ "14 ngày" lẫn mới "7 ngày".

**Phát hiện:** Tôi so sánh 2 file eval CSV (`after_inject_bad.csv` vs `after_fix.csv`). Cột `hits_forbidden` thay đổi từ `yes` → `no` cho câu hỏi `q_refund_window`, xác nhận chunk bẩn ảnh hưởng trực tiếp retrieval quality.

**Fix:** Rerun pipeline chuẩn:
```bash
python3 etl_pipeline.py run --run-id after-fix
```
Log `run_after-fix.log`: tất cả expectations PASS, `embed_prune_removed=1` (xóa đúng chunk bẩn từ inject), và eval cho `hits_forbidden=no`.

---

## 4. Bằng chứng trước / sau (80–120 từ)

**Run inject-bad** (file `artifacts/eval/after_inject_bad.csv`):
```
q_refund_window, …, contains_expected=yes, hits_forbidden=yes
```

**Run after-fix** (`run_id=after-fix`, file `artifacts/eval/after_fix.csv`):
```
q_refund_window, …, contains_expected=yes, hits_forbidden=no
```

**Idempotency test** (`artifacts/logs/run_idem-1.log` dòng 14–15 vs `run_idem-2.log` dòng 14–15):
```
# run_idem-1.log:
embed_prune_removed=0
embed_upsert count=6 collection=day10_kb

# run_idem-2.log:
embed_prune_removed=0
embed_upsert count=6 collection=day10_kb
```
→ Collection giữ nguyên 6 vectors sau 2 lần chạy — không phình, không mất.

---

## 5. Cải tiến tiếp theo (40–80 từ)

Nếu có thêm 2 giờ, tôi sẽ triển khai **blue/green collection swap**: tạo collection tạm `day10_kb_staging`, embed + validate xong mới rename thành `day10_kb_active`. Nếu run mới FAIL ở bước expectation, collection cũ vẫn phục vụ retrieval mà không bị prune mất data tốt. Cần thêm logic alias/swap trong `cmd_embed_internal()` và rollback trong manifest.
