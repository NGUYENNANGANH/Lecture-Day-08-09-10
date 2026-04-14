# Báo Cáo Cá Nhân — Lab Day 09: Multi-Agent Orchestration

**Họ và tên:** Nguyễn Năng Anh  
**Vai trò trong nhóm:** M3 — Worker Specialist B (policy_tool.py + worker_contracts.yaml)  
**Ngày nộp:** 2026-04-14

---

## 1. Tôi phụ trách phần nào?

**Module/file tôi chịu trách nhiệm:**
- File chính: `workers/policy_tool.py` (597 dòng) — xử lý phân tích chính sách hoàn tiền và kiểm soát truy cập.
- File phụ: `contracts/worker_contracts.yaml` (295 dòng, v1.1) — hợp đồng I/O cho mọi component.

**Functions tôi implement:** `analyze_policy()` (dòng 261), `_detect_refund_exceptions()` (dòng 144), `_check_refund_eligibility()` (dòng 165), `_detect_temporal_scoping()` (dòng 199), `_detect_access_control()` (dòng 217), `_call_mcp_tool()` (dòng 31), `run()` (dòng 376).

**Kết nối với thành viên khác:** `worker_contracts.yaml` là tham chiếu chung — M1 dựa vào để routing, M2 biết format `policy_result` để synthesis, M4 biết output `dispatch_tool` để ghi log. Policy worker nhận `retrieved_chunks` từ M2 và gọi MCP tools của M4 qua `dispatch_tool_http()`.

**Bằng chứng:** `worker_contracts.yaml` dòng 175–183: `status: "done"`, notes "Sprint 2 (M3)".

---

## 2. Tôi đã ra một quyết định kỹ thuật gì?

**Quyết định:** Thiết kế `REFUND_EXCEPTION_RULES` dưới dạng **danh sách rule có cấu trúc** (`policy_tool.py` dòng 69–98) thay vì dùng LLM phân tích chính sách.

**Bối cảnh:** Khi nhận câu hoàn tiền (gq02, gq04, gq10), pipeline cần xác định đơn hàng có thuộc ngoại lệ không (Flash Sale, kỹ thuật số, đã kích hoạt).

| Phương án | Ưu điểm | Nhược điểm |
|-----------|---------|------------|
| LLM policy analysis | Linh hoạt, xử lý paraphrasing | +1s latency, hallucination risk, non-deterministic |
| Rule-based matching | Deterministic, ~2ms, không hallucinate, dễ test | Cần maintain keyword list, miss paraphrasing |

**Lý do chọn rule-based:** Chính sách v4 có đúng 3 ngoại lệ binary. Dùng LLM rủi ro bịa thêm ngoại lệ — theo SCORING.md hallucination bị trừ 50% điểm. Rule-based đảm bảo chỉ trigger khi keyword khớp chính xác với tài liệu.

**Trade-off:** Miss paraphrasing. Tôi giảm thiểu bằng cách match cả `keywords_task` (câu hỏi) VÀ `keywords_context` (chunks), tăng coverage.

**Bằng chứng từ trace gq10 (grading_run.jsonl):**
```json
{
  "id": "gq10",
  "supervisor_route": "policy_tool_worker",
  "policy_result": {"policy_applies": false, "exceptions_found": [{"type": "flash_sale_exception"}]},
  "confidence": 0.56,
  "latency_ms": 9039
}
```
Kết quả: phát hiện đúng Flash Sale exception, trả lời "không được hoàn tiền" — đúng Điều 3 policy v4. Latency policy analysis: ~2ms (rule-based). Nếu dùng LLM classifier ước tính thêm ~1000ms + rủi ro hallucinate ngoại lệ không tồn tại. **0 hallucination trên 5/10 câu grading chạy qua policy worker.**

---

## 3. Tôi đã sửa một lỗi gì?

**Lỗi:** Câu gq02 ("đơn ngày 31/01/2026, hoàn tiền 07/02/2026") bị trả lời sai — policy worker không phát hiện đơn đặt **trước ngày hiệu lực** của policy v4.

**Symptom:** Pipeline áp dụng v4 cho đơn 31/01 → kết luận sai. Trace ghi `policy_name: "refund_policy_v4"` nhưng không cảnh báo temporal scope.

**Root cause:** `analyze_policy()` ban đầu không kiểm tra ngày đặt hàng so với ngày hiệu lực 01/02/2026. Mọi câu hoàn tiền đều mặc định áp dụng v4.

**Cách sửa:** Thêm `_detect_temporal_scoping()` (dòng 199–214) kiểm tra temporal markers ("31/01", "30/01", "tháng 1/2026"...). Nếu phát hiện → inject cảnh báo vào `policy_version_note`: *"Đơn đặt trước 01/02/2026 áp dụng chính sách phiên bản 3. Cần escalate."*

**Bằng chứng trước/sau (trace gq02 trong grading_run.jsonl):**

Trước khi sửa:
```
policy_name: "refund_policy_v4"   ← áp dụng sai
policy_version_note: ""            ← trống, không cảnh báo
answer: "Đủ điều kiện hoàn tiền"   ← SAI
```

Sau khi sửa (dòng 199–214 thêm `_detect_temporal_scoping()`):
```
policy_name: "refund_policy_v4"
policy_version_note: "⚠️ Đơn hàng đặt trước 01/02/2026 áp dụng chính sách phiên bản 3"
answer: "...cần xác nhận thêm thông tin từ chính sách phiên bản cũ"  ← ĐÚNG
confidence: 0.30   ← thấp, phản ánh đúng mức không chắc chắn
```

---

## 4. Tôi tự đánh giá đóng góp của mình

**Tôi làm tốt nhất:** Thiết kế `worker_contracts.yaml` chặt chẽ — Sprint 2 không xảy ra conflict I/O. Code cover 5/10 câu grading với 0 hallucination.

**Tôi làm chưa tốt:** Contracts nên viết xong Sprint 1 (contracts-first). Thực tế viết song song Sprint 2, khiến M2 phải đoán format `policy_result`.

**Nhóm phụ thuộc vào tôi:** Policy worker xử lý 5/10 câu grading. Câu gq09 (16 điểm — khó nhất) cần policy worker gọi `check_access_permission` + `get_ticket_info`.

**Tôi phụ thuộc:** `retrieved_chunks` từ M2, `dispatch_tool_http()` từ M4.

---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì?

Tôi sẽ thêm **LLM-based temporal reasoning** cho `_detect_temporal_scoping()`. Trace gq02 cho thấy detect "31/01" bằng keyword — nhưng "cuối tháng 1" sẽ miss. Một LLM call ngắn (~150 tokens) hỏi "đơn này trước hay sau 01/02/2026?" sẽ tăng accuracy mà cost thấp (câu yes/no, không hallucinate policy).

---

*File: `reports/individual/nguyen_nang_anh.md` · Commit sau 18:00 được phép (SCORING.md)*
