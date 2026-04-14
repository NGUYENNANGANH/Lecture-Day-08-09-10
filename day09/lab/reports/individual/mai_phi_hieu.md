# Báo Cáo Cá Nhân — Lab Day 09: Multi-Agent Orchestration

**Họ và tên:** Mai Phi Hiếu  
**Vai trò trong nhóm:** Quality & Trace Analyst (M5) — eval_trace.py, testing, documentation, giám sát deadline  
**Ngày nộp:** 2026-04-14  
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi phụ trách phần nào? (~130 từ)

**Module/file tôi chịu trách nhiệm:**
- File chính: `eval_trace.py` — module đánh giá và tracing cho toàn bộ pipeline multi-agent (546 dòng)
- Documentation: `docs/system_architecture.md`, `docs/routing_decisions.md`, `docs/single_vs_multi_comparison.md`
- Functions tôi implement: `run_test_questions()`, `run_grading_questions()`, `score_faithfulness()`, `score_relevance()`, `score_completeness()`, `score_routing()`, `classify_failure()`, `compare_ground_truth()`, `analyze_traces()`, `compare_single_vs_multi()`

**Cách công việc của tôi kết nối với phần của thành viên khác:**

eval_trace.py phụ thuộc trực tiếp vào `graph.py` (M1) qua `run_graph()` — tôi consume output `AgentState` sau khi pipeline chạy xong. Scoring cần `retrieved_chunks` (từ M2), `policy_result` (từ M3), và `mcp_tools_used` (từ M4). Nếu bất kỳ worker nào thay đổi output format → eval_trace phải cập nhật. Tôi cũng viết docs dựa trên trace thực tế từ `artifacts/traces/`.

**Bằng chứng:** Commit `feat(M5): Day09 Sprint 2 - eval_trace v2 with scoring, routing check, failure analysis, CSV export` — 546 dòng mới.

---

## 2. Tôi đã ra một quyết định kỹ thuật gì? (~180 từ)

**Quyết định:** Tôi chọn implement **failure mode classification với root-cause layer** (supervisor / retrieval / generation / system) thay vì chỉ đánh pass/fail đơn giản.

Khi pipeline trả lời sai, biết "fail" là chưa đủ — team cần biết lỗi ở **layer nào** để sửa đúng chỗ. Tôi thiết kế function `classify_failure()` trả về tuple `(failure_mode, failure_layer)` với 5 failure modes × 4 layers:

| Mode | Layer | Ý nghĩa |
|------|-------|---------|
| `wrong_route` | supervisor | M1 cần sửa routing keywords |
| `false_abstain` | generation | M2 synthesis cần điều chỉnh prompt |
| `retrieval_miss` | retrieval | M2 retrieval hoặc index cần cải thiện |
| `hallucination` | generation | Grounding prompt chưa đủ mạnh |
| `incomplete` | generation | LLM trả lời thiếu chi tiết |

**Các lựa chọn thay thế:**
1. Binary pass/fail — quá đơn giản, không actionable
2. LLM-as-Judge — chính xác hơn nhưng tốn API call, chậm, khó reproduce

**Trade-off:** Rule-based scoring dùng keyword matching nên miss paraphrasing. Ví dụ: `grounding_ratio` đếm từ chung giữa answer và context — không nhận diện khi LLM paraphrase context.

**Bằng chứng từ trace:**

```json
{
  "scoring": {
    "failure_mode": "wrong_route",
    "failure_layer": "supervisor",
    "routing": {"correct": false, "actual": "retrieval_worker", "expected": "policy_tool_worker"}
  }
}
```

Trace này phát hiện q15 bị route sai → M1 sửa keyword priority order trong ~4 phút nhờ biết lỗi ở layer "supervisor".

---

## 3. Tôi đã sửa một lỗi gì? (~150 từ)

**Lỗi:** eval_trace.py v1 (template gốc) chỉ ghi basic trace — không có scoring, không detect failure mode, và không ghi đúng format `mcp_tools_used` theo yêu cầu SCORING.md Sprint 3.

**Symptom:** Khi chạy `python eval_trace.py`, output chỉ có "route=?, conf=0.82, 2341ms" — không biết câu nào pass/fail, không biết lỗi ở đâu, không export được CSV cho phân tích.

**Root cause:** eval_trace v1 chỉ gọi `run_graph()` và in kết quả. Không có scoring functions, không so sánh expected vs actual, không classify failure.

**Cách sửa:** Viết lại eval_trace.py v2 với:
- 4 scoring functions (faithfulness, relevance, completeness, routing)
- `classify_failure()` với root-cause layer
- `compare_ground_truth()` để check key facts
- `_save_eval_csv()` export 27 columns cho spreadsheet
- Normalize `mcp_tools_used` format: `t.get("tool", str(t))`

**Bằng chứng trước/sau:**

Trước (v1): `[01/15] q01: ✓ route=retrieval_worker, conf=0.92, 2100ms`

Sau (v2):
```
q01   SLA          easy  retrieval_worker     ✅   5  5  5  5.0   ✅  0.92  —                2100ms
```
Console table với F/R/C scores, pass/fail, failure mode, latency — 1 dòng = toàn bộ thông tin debug.

---

## 4. Tôi tự đánh giá đóng góp của mình (~120 từ)

**Tôi làm tốt nhất ở điểm nào?**

Thiết kế eval framework có cấu trúc rõ ràng: 3 output formats (JSON cho debug, CSV cho Excel, console table cho demo). Failure layer classification giúp team tìm root cause trong ~5 phút thay vì 15 phút. Documentation 3 docs hoàn thiện với số liệu thực tế.

**Tôi làm chưa tốt hoặc còn yếu ở điểm nào?**

Scoring dùng keyword matching — miss paraphrasing và semantic similarity. Chưa implement LLM-as-Judge vì lo tốn API credit và thiếu thời gian. Giám sát deadline: nên push team hoàn thành code sớm hơn để có thời gian test.

**Nhóm phụ thuộc vào tôi ở đâu?**

`eval_trace.py` là file **duy nhất** chạy end-to-end 15 câu test + generate `grading_run.jsonl`. Nếu eval_trace crash → mất 30 điểm nhóm (grading). Documentation cũng là trách nhiệm chính — 10 điểm docs.

**Phần tôi phụ thuộc vào thành viên khác:**

Cần `run_graph()` (M1) ổn định. Cần workers (M2, M3) trả đúng AgentState schema. Nếu worker đổi format → scoring functions phải cập nhật.

---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì? (~80 từ)

Tôi sẽ implement **LLM-as-Judge scoring** cho metric faithfulness. Trace q15 cho thấy `grounding_ratio: 0.45` (score=3) nhưng answer thực tế đúng — vì LLM paraphrase context thay vì copy nguyên văn. Rule-based keyword matching miss trường hợp này hoàn toàn. Với LLM-as-Judge: gửi `{context, answer}` cho GPT-4o-mini hỏi "answer có grounded trong context không?" → score chính xác hơn, đặc biệt câu gq09 (16 điểm — câu khó nhất).
