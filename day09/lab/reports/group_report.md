# Báo Cáo Nhóm — Lab Day 09: Multi-Agent Orchestration

**Tên nhóm:** 66  
**Thành viên:**
| Tên | Vai trò | Phụ trách |
|-----|---------|-----------|
| Nguyễn Ngọc Hiếu | M1 — Lead Supervisor | graph.py, Shared State, orchestration |
| Phạm Thanh Tùng | M2 — Worker Specialist A | retrieval.py, synthesis.py |
| Nguyễn Năng Anh | M3 — Worker Specialist B | policy_tool.py, worker_contracts.yaml |
| Dương Phương Thảo | M4 — MCP Architect | mcp_server.py, external tools |
| Mai Phi Hiếu | M5 — Quality & Trace Analyst | eval_trace.py, testing, documentation |

**Ngày nộp:** 2026-04-14  
**Repo:** https://github.com/NGUYENNANGANH/Lecture-Day-08-09-10

---

## 1. Kiến trúc nhóm đã xây dựng (~180 từ)

**Hệ thống tổng quan:**

Nhóm xây dựng hệ thống Multi-Agent theo pattern **Supervisor-Worker** sử dụng LangGraph StateGraph. Hệ thống gồm 1 supervisor node điều phối luồng, 3 worker nodes (retrieval, policy_tool, synthesis), 1 human_review node (HITL), và 1 MCP server mock cung cấp 4 external tools. Tổng cộng 5 Python modules chính với 16 fields trong Shared State (AgentState).

**Routing logic cốt lõi:**

Supervisor dùng **keyword-based routing** — 3 nhóm keywords:
- `policy_keywords`: "hoàn tiền", "refund", "flash sale", "cấp quyền", "access level" → `policy_tool_worker`
- `retrieval_keywords`: "P1", "SLA", "ticket", "escalation" → `retrieval_worker`
- `risk_keywords` + "err-": → `human_review` (HITL trigger)

Policy keywords được **check TRƯỚC** retrieval keywords — quyết định thiết kế quan trọng vì câu multi-domain (VD: "P1 + cấp quyền Level 2") cần policy analysis.

**MCP tools đã tích hợp:**

- `search_kb`: Tìm kiếm KB nội bộ (ChromaDB real → fallback mock). Được gọi khi policy worker chưa có chunks.
- `get_ticket_info`: Tra cứu ticket P1-LATEST — dùng cho câu gq01 (SLA notification).
- `check_access_permission`: Kiểm tra quyền Level 1-3 + emergency bypass — dùng cho gq03, gq09.
- `create_ticket`: Tạo ticket mock (demo extensibility).

Trace gq01: `mcp_tools_used: [{mcp_tool_called: "get_ticket_info", mcp_result: {ticket_id: "IT-9847", priority: "P1"}}]`

---

## 2. Quyết định kỹ thuật quan trọng nhất (~220 từ)

**Quyết định:** Keyword-based routing trong supervisor thay vì LLM-based classification.

**Bối cảnh vấn đề:**

Supervisor cần phân loại mỗi câu hỏi để route đúng worker. Có 2 cách: (1) gọi LLM classify intent, (2) keyword matching rule-based. Đây là quyết định ảnh hưởng latency, chi phí, và reproducibility.

**Các phương án đã cân nhắc:**

| Phương án | Ưu điểm | Nhược điểm |
|-----------|---------|-----------|
| LLM classifier | Linh hoạt, xử lý paraphrasing | +800ms latency/câu, tốn API, non-deterministic |
| Keyword routing | Nhanh (~5ms), deterministic, testable | Miss paraphrasing, cần maintain keyword list |

**Phương án đã chọn và lý do:**

Keyword routing — vì lab có 5 tài liệu với domain rõ ràng (refund, SLA, access control), keyword matching đủ chính xác (93% routing accuracy trên 15 câu test). Chi phí: 0 API call ở supervisor. Latency supervisor: ~5ms thay vì ~800ms.

**Bằng chứng từ trace:**

```json
{
  "supervisor_route": "policy_tool_worker",
  "route_reason": "Task contains policy/access keywords -> policy_tool_worker.",
  "latency_supervisor_ms": 3
}
```

Route reason rõ ràng, trace đủ để debug. 14/15 câu route đúng. Câu route sai (q15) được fix bằng đổi keyword priority order — mất 4 phút debug nhờ trace.

---

## 3. Kết quả grading questions (~180 từ)

> Chờ `grading_questions.json` public lúc 17:00 để chạy `python eval_trace.py --grading`.

**Tổng điểm raw ước tính:** Chưa chạy / 96

**Câu pipeline xử lý tốt nhất (dự kiến từ test questions):**
- ID: q01 ("SLA P1") — Lý do: retrieval đúng doc SLA, synthesis trả lời đầy đủ, confidence 0.92. Single-source, routing đơn giản.

**Câu pipeline fail hoặc partial (dự kiến):**
- ID: q15 ("P1 + Level 2 emergency + contractor") — Fail lần đầu ở routing (route retrieval thay vì policy). Root cause: "P1" match retrieval_keywords trước policy_keywords. Fix: đổi check order.

**Câu gq07 (abstain):** Dự kiến: synthesis phát hiện context không đủ → trả lời "Không đủ thông tin trong tài liệu nội bộ" → valid abstain. Confidence thấp (~0.30).

**Câu gq09 (multi-hop khó nhất):** Dự kiến: supervisor route → policy_tool_worker → retrieval + check_access_permission MCP → synthesis. Trace cần ghi 2 workers: `["retrieval_worker", "policy_tool_worker", "synthesis_worker"]`. Challenge: kết hợp SLA timeline + access control rules → multi-hop reasoning.

---

## 4. So sánh Day 08 vs Day 09 — Điều nhóm quan sát được (~170 từ)

**Metric thay đổi rõ nhất (có số liệu):**

| Metric | Day 08 | Day 09 | Delta |
|--------|--------|--------|-------|
| Multi-hop accuracy | 40% (2/5) | 60% (3/5) | **+20%** |
| False abstain rate | 20% (2/10) | 7% (1/15) | **−13%** |
| Debug time/bug | ~15 phút | ~5 phút | **−10 phút** |
| Latency | ~2000ms | ~2500ms | +500ms |

**Điều nhóm bất ngờ nhất khi chuyển từ single sang multi-agent:**

Debug time giảm mạnh nhất. Khi q15 trả lời sai, nhờ trace có `route_reason` và `worker_io_logs`, chỉ mất 4 phút xác định vấn đề nằm ở supervisor routing (keyword priority). Day 08 cùng vấn đề tương tự mất ~15 phút vì phải đọc hàng trăm dòng rag_answer.py monolithic.

**Trường hợp multi-agent KHÔNG giúp ích hoặc làm chậm hệ thống:**

Câu đơn giản 1-source (VD: "SLA P1 bao lâu?") — accuracy không cải thiện (cả 2 đều đúng), nhưng latency tăng ~500ms do supervisor overhead. Với simple FAQ bot, single agent nhanh hơn và đủ tốt.

---

## 5. Phân công và đánh giá nhóm (~130 từ)

**Phân công thực tế:**

| Thành viên | Phần đã làm | Sprint |
|------------|-------------|--------|
| Nguyễn Ngọc Hiếu (M1) | graph.py: supervisor routing, LangGraph StateGraph, run_graph() | Sprint 1 |
| Phạm Thanh Tùng (M2) | retrieval.py + synthesis.py: ChromaDB retrieval, multi-LLM synthesis | Sprint 2 |
| Nguyễn Năng Anh (M3) | policy_tool.py + worker_contracts.yaml: exception rules, access control | Sprint 2 |
| Dương Phương Thảo (M4) | mcp_server.py: 4 tools, dispatch_tool, _CALL_LOG system | Sprint 3 |
| Mai Phi Hiếu (M5) | eval_trace.py v2 + 3 docs + group report + deadline giám sát | Sprint 4 |

**Điều nhóm làm tốt:**

Worker contracts YAML (M3) — mọi thành viên tham chiếu format I/O chuẩn → integration không conflict. Mỗi worker test độc lập bằng `python workers/[name].py`.

**Điều nhóm làm chưa tốt:**

Documentation viết muộn (Sprint 4 cuối giờ). Nên song song code + docs từ Sprint 1.

**Nếu làm lại, nhóm sẽ thay đổi gì:**

Viết worker_contracts.yaml TẤT Sprint 1 (trước code) thay vì Sprint 2. Contracts-first approach giúp team code song song mà không đợi nhau.

---

## 6. Nếu có thêm 1 ngày, nhóm sẽ làm gì? (~80 từ)

1. **LLM-based routing** (thay keyword matching): Trace q15 cho thấy keyword routing miss câu multi-domain. LLM classifier (~800ms thêm) sẽ xử lý paraphrasing tốt hơn — đáng đổi cho câu phức tạp.

2. **Cross-encoder reranker** trong retrieval_worker: Hiện tại chỉ dùng bi-encoder (all-MiniLM-L6-v2). Thêm cross-encoder rerank top-10 → top-3 sẽ cải thiện retrieval precision cho multi-hop queries (gq09: +20% accuracy dự kiến).

---

*File này lưu tại: `reports/group_report.md`*  
*Commit sau 18:00 được phép theo SCORING.md*
