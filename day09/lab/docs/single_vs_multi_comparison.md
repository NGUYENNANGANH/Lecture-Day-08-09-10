# Single Agent vs Multi-Agent Comparison — Lab Day 09

**Nhóm:** NGUYENNANGANH  
**Ngày:** 2026-04-14

---

## 1. Metrics Comparison

> Số liệu Day 08 lấy từ eval_trace.py v2 (batch dense, 10 câu).
> Số liệu Day 09 lấy từ eval_trace.py v2 (15 câu test).

| Metric | Day 08 (Single Agent) | Day 09 (Multi-Agent) | Delta | Ghi chú |
|--------|----------------------|---------------------|-------|---------|
| Avg confidence | 0.78 (est.) | 0.82 (est.) | +0.04 | Day 09 có confidence thực từ chunk score |
| Avg latency (ms) | ~2000ms | ~2500ms | +500ms | Multi-step overhead: supervisor + routing |
| Abstain rate (%) | 20% (2/10) | 7% (1/15) | −13% | Day 09 giảm false abstain nhờ MCP fallback |
| Multi-hop accuracy | 40% (2/5 hard) | 60% (3/5 hard) | +20% | Policy worker + cross-doc reasoning |
| Routing visibility | ✗ Không có | ✓ Có route_reason | N/A | Day 09 trace ghi rõ tại sao chọn worker |
| Debug time (estimate) | ~15 phút | ~5 phút | −10 phút | Trace route_reason + worker_io isolate issue nhanh |
| MCP tool calls | N/A | 1.2 calls/câu policy | N/A | Thêm context từ MCP tools |

---

## 2. Phân tích theo loại câu hỏi

### 2.1 Câu hỏi đơn giản (single-document)

| Nhận xét | Day 08 | Day 09 |
|---------|--------|--------|
| Accuracy | 80% (4/5 easy) | 83% (5/6 easy) |
| Latency | ~1800ms | ~2200ms |
| Observation | Retrieval + LLM đơn giản, nhanh | Thêm supervisor overhead nhưng kết quả tương tự |

**Kết luận:** Câu đơn giản, multi-agent **không cải thiện accuracy** — chỉ thêm latency. Single agent đủ tốt cho câu 1-source.

### 2.2 Câu hỏi multi-hop (cross-document)

| Nhận xét | Day 08 | Day 09 |
|---------|--------|--------|
| Accuracy | 40% (2/5) | 60% (3/5) |
| Routing visible? | ✗ | ✓ route_reason cho biết cần 2 workers |
| Observation | Single pipeline không biết cần cross-doc | Supervisor route policy_tool → retrieval trước synthesis |

**Kết luận:** Multi-agent **cải thiện rõ rệt** ở câu multi-hop. Policy worker gọi MCP `check_access_permission` bổ sung context mà single agent không có.

### 2.3 Câu hỏi cần abstain

| Nhận xét | Day 08 | Day 09 |
|---------|--------|--------|
| Abstain rate | 20% (2/10) — 2 false abstain | 7% (1/15) — 1 correct abstain |
| Hallucination cases | 0 | 0 |
| Observation | LLM quá conservative vì strict grounding | MCP fallback cung cấp thêm context → giảm false abstain |

**Kết luận:** Day 09 có lợi thế nhờ MCP `search_kb` fallback. Khi ChromaDB thiếu data, mock KB vẫn cung cấp context → giảm false abstain.

---

## 3. Debuggability Analysis

### Day 08 — Debug workflow
```
Khi answer sai → phải đọc toàn bộ rag_answer.py (560 dòng)
  → Tìm lỗi ở embedding? retrieval? prompt? LLM?
  → Không có trace → phải thêm print() debug
  → Không biết chunk nào được chọn, prompt gì gửi LLM
Thời gian ước tính: 15 phút/bug
```

### Day 09 — Debug workflow
```
Khi answer sai → đọc trace JSON (artifacts/traces/run_*.json)
  → Xem supervisor_route + route_reason → route đúng chưa?
  → Xem worker_io_logs → retrieval_worker trả chunks đúng không?
  → Nếu route sai → sửa keywords trong supervisor_node()
  → Nếu retrieval sai → test retrieval_worker độc lập: python workers/retrieval.py
  → Nếu synthesis sai → test synthesis_worker độc lập: python workers/synthesis.py
Thời gian ước tính: 5 phút/bug
```

**Câu cụ thể nhóm đã debug:**

Câu q15 ("P1 lúc 2am + cần cấp Level 2") ban đầu chỉ route về `retrieval_worker` vì "P1" match retrieval_keywords trước. Khi đọc trace, thấy `route_reason = "task contains P1 SLA keyword"` — supervisor không nhận ra cần policy worker. Fix: thêm check kết hợp "P1 + cấp quyền" → route `policy_tool_worker` (policy worker tự gọi retrieval trước). Debug mất 4 phút nhờ trace rõ ràng.

---

## 4. Extensibility Analysis

| Scenario | Day 08 | Day 09 |
|---------|--------|--------|
| Thêm 1 tool/API mới | Phải sửa toàn prompt trong rag_answer.py | Thêm MCP tool + dispatch entry |
| Thêm 1 domain mới | Phải retrain/re-prompt toàn bộ | Thêm 1 worker mới + routing keyword |
| Thay đổi retrieval strategy | Sửa trực tiếp trong pipeline monolithic | Sửa retrieval_worker độc lập |
| A/B test một phần | Khó — phải clone toàn pipeline | Dễ — swap worker implementation |

**Nhận xét:** Day 09 vượt trội về extensibility. Ví dụ: thêm `create_ticket` MCP tool chỉ cần thêm function + đăng ký vào `TOOL_REGISTRY`. Day 08 phải sửa rag_answer.py gốc.

---

## 5. Cost & Latency Trade-off

| Scenario | Day 08 calls | Day 09 calls |
|---------|-------------|-------------|
| Simple query (q01: SLA P1) | 1 LLM call | 1 LLM call (synthesis) |
| Complex query (q15: P1 + access) | 1 LLM call | 1 LLM call + 2 MCP calls |
| MCP tool call | N/A | 0-3 MCP calls/câu (in-process mock, <5ms mỗi call) |

**Nhận xét về cost-benefit:**

Multi-agent thêm overhead ~500ms do supervisor routing + worker orchestration, nhưng MCP calls gần như miễn phí (in-process mock <5ms). LLM calls vẫn chỉ 1 lần ở synthesis — không tăng cost. Trade-off: latency tăng nhẹ, nhưng accuracy + debuggability cải thiện đáng kể cho câu phức tạp.

---

## 6. Kết luận

> **Multi-agent tốt hơn single agent ở điểm nào?**

1. **Multi-hop accuracy +20%** — policy worker + MCP tools bổ sung context từ nhiều nguồn
2. **Debuggability −10 phút/bug** — trace với route_reason + worker_io cho phép isolate issue nhanh
3. **False abstain giảm 13%** — MCP search_kb fallback cung cấp context khi ChromaDB thiếu

> **Multi-agent kém hơn hoặc không khác biệt ở điểm nào?**

1. **Latency tăng ~500ms** do overhead supervisor routing + multi-step pipeline
2. **Câu đơn giản không cải thiện** — single agent đã đủ tốt cho 1-source queries

> **Khi nào KHÔNG nên dùng multi-agent?**

Khi hệ thống chỉ có 1 domain, câu hỏi đơn giản, và không cần MCP tools. Multi-agent thêm complexity không cần thiết cho use case đơn giản. Single agent RAG đủ tốt cho FAQ bot cơ bản.

> **Nếu tiếp tục phát triển hệ thống này, nhóm sẽ thêm gì?**

1. LLM-based routing (thay vì keyword) để xử lý câu hỏi ambiguous tốt hơn
2. Cross-encoder reranker trong retrieval_worker cho multi-hop queries
3. Real MCP HTTP server (bonus +2) thay vì in-process mock
