# Báo Cáo Cá Nhân — Lab Day 09: Multi-Agent Orchestration

**Họ và tên:** Phạm Thanh Tùng  
**Vai trò trong nhóm:** M2 — Worker Specialist A (Retrieval Worker + Synthesis Worker)  
**Ngày nộp:** 2026-04-14  
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi phụ trách phần nào? (100–150 từ)

**Module/file tôi chịu trách nhiệm:**
- File chính: `workers/retrieval.py` (207 dòng) — Dense retrieval từ ChromaDB, trả chunks + sources cho pipeline
- File chính: `workers/synthesis.py` (370 dòng) — Tổng hợp câu trả lời có citation từ evidence + policy context

**Functions tôi implement:**
- Retrieval: `_get_embedding_fn()`, `_get_collection()`, `retrieve_dense()`, `run()` 
- Synthesis: `_call_llm()`, `_template_fallback()`, `_build_context()`, `_estimate_confidence()`, `synthesize()`, `run()`

**Cách công việc của tôi kết nối với phần của thành viên khác:**

Retrieval worker là nguồn evidence duy nhất cho toàn pipeline — `retrieved_chunks` được policy_tool_worker (M3) dùng để phân tích exception, và synthesis worker tổng hợp thành câu trả lời cuối. Supervisor (M1) gọi `retrieval_run(state)` qua `graph.py`. MCP server (M4) fallback sang `retrieve_dense()` khi ChromaDB có data. Eval_trace (M5) đánh giá chất lượng dựa trên chunks tôi trả về.

**Bằng chứng:** Contract `worker_contracts.yaml` ghi rõ `retrieval_worker` và `synthesis_worker` — status: "done", notes ghi M2 implement.

---

## 2. Tôi đã ra một quyết định kỹ thuật gì? (150–200 từ)

**Quyết định:** Tôi chọn implement **multi-LLM fallback chain** trong synthesis worker thay vì hard-code một LLM duy nhất.

Synthesis cần gọi LLM để tổng hợp answer có citation. Vấn đề: nhóm có người dùng OpenAI API key, người dùng Google API key, và có lúc cả hai đều hết credit. Tôi thiết kế `_call_llm()` với fallback chain 4 tầng:

| Ưu tiên | Provider | Model | Khi nào dùng |
|---------|----------|-------|-------------|
| 1 | OpenAI | gpt-4o-mini | Có `OPENAI_API_KEY` hợp lệ |
| 2 | Google (new SDK) | gemini-2.0-flash | Có `GOOGLE_API_KEY`, dùng `google-genai` |
| 3 | Google (old SDK) | gemini-1.5-flash | Có `GOOGLE_API_KEY`, dùng `google-generativeai` |
| 4 | Template fallback | — | Không cần API key, trích xuất trực tiếp từ context |

**Các lựa chọn thay thế:**
1. Chỉ dùng OpenAI → crash khi hết credit, blocking cả nhóm
2. Chỉ dùng template → answer quality thấp, không có reasoning

**Trade-off:** Template fallback (tầng 4) chất lượng kém hơn LLM — chỉ trích keywords từ context, không reasoning. Nhưng đảm bảo pipeline **không bao giờ crash** do thiếu API key.

**Bằng chứng từ trace:**

```python
# workers/synthesis.py — _call_llm() fallback chain (dòng 46-97)
# Option A: OpenAI → Option B: google-genai → Option C: google-generativeai → Fallback: template
def _call_llm(messages: list) -> str:
    try:  # OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(model="gpt-4o-mini", ...)
    except: pass
    try:  # Google GenAI (new)
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.0-flash", ...)
    except: pass
    # ... fallback template
```

Trace câu q01: `confidence: 0.92`, answer có citation `[sla_p1_2026.txt]` — chứng tỏ LLM chain hoạt động đúng. Khi test offline (không API), template fallback vẫn trả về answer có sources.

---

## 3. Tôi đã sửa một lỗi gì? (150–200 từ)

**Lỗi:** Retrieval worker ban đầu dùng `DEFAULT_TOP_K = 3` — với câu multi-hop (gq09: "P1 lúc 2am + cấp quyền Level 2"), chỉ retrieve 3 chunks không đủ cover 2 tài liệu (SLA + Access Control).

**Symptom:** Câu multi-hop chỉ trả lời được 1 phần (SLA hoặc Access Control), thiếu phần còn lại. Confidence thấp (~0.5). Eval trace ghi `failure_mode: "incomplete"`.

**Root cause:** `top_k=3` chỉ lấy 3 chunks — thường cùng 1 tài liệu (SLA). Chunks từ `access_control_sop.txt` bị đẩy xuống rank 4-5, ngoài tầm retrieve.

**Cách sửa:** Tăng `DEFAULT_TOP_K` từ 3 lên 7 (dòng 28, `retrieval.py`). Sau đó điều chỉnh xuống 5 để cân bằng giữa coverage và noise.

**Bằng chứng trước/sau:**

Trước (`top_k=3`):
```
retrieved_sources: ["sla_p1_2026.txt"]    # chỉ 1 doc
scoring.completeness: 2                   # incomplete
```

Sau (`top_k=7`):
```
retrieved_sources: ["sla_p1_2026.txt", "access_control_sop.txt"]  # 2 docs
scoring.completeness: 4                                            # pass
```

Latency tăng ~200ms nhưng multi-hop accuracy cải thiện đáng kể (+20% theo group report).

---

## 4. Tôi tự đánh giá đóng góp của mình (100–150 từ)

**Tôi làm tốt nhất ở điểm nào?**

Thiết kế retrieval + synthesis với error handling mạnh. Pipeline không crash trong bất kỳ trường hợp nào — ChromaDB lỗi → return `[]`, LLM hết credit → template fallback, embedding model thiếu → random embeddings warning. Tất cả worker đều test độc lập được (`python workers/retrieval.py`, `python workers/synthesis.py`).

**Tôi làm chưa tốt hoặc còn yếu ở điểm nào?**

Confidence scoring (`_estimate_confidence`) quá đơn giản — chỉ dùng weighted average chunk scores. Không phản ánh chất lượng reasoning của LLM. Chưa implement reranker để cải thiện retrieval precision.

**Nhóm phụ thuộc vào tôi ở đâu?**

Retrieval worker cung cấp `retrieved_chunks` — input bắt buộc cho M3 (policy analysis) và synthesis. Nếu retrieval trả chunks sai → toàn pipeline trả lời sai. Synthesis worker tạo `final_answer` — output cuối cùng của toàn hệ thống.

**Phần tôi phụ thuộc vào thành viên khác:**

Cần `AgentState` schema từ M1 (graph.py) để biết format input/output. Cần `policy_result` từ M3 để synthesis xây dựng context đầy đủ.

---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì? (50–100 từ)

Tôi sẽ thêm **cross-encoder reranker** vào retrieval worker. Trace câu gq09 cho thấy bi-encoder (all-MiniLM-L6-v2) xếp chunk `access_control_sop.txt` ở rank 5-6, gần bị miss với `top_k=5`. Cross-encoder rerank: retrieve top-15 bằng bi-encoder → rerank bằng cross-encoder → chọn top-5 chính xác nhất. Dự kiến cải thiện retrieval precision cho multi-hop queries +15-20%, đặc biệt gq09 (16 điểm — câu khó nhất) mà không cần tăng top_k gây noise.

---

*Lưu file này tại: `reports/individual/pham_thanh_tung.md`*  
*Commit sau 18:00 được phép theo SCORING.md*
