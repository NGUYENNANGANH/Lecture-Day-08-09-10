# System Architecture — Lab Day 09

**Nhóm:** NGUYENNANGANH  
**Ngày:** 2026-04-14  
**Version:** 2.0 (Sprint 4 — Final)

---

## 1. Tổng quan kiến trúc

**Pattern đã chọn:** Supervisor-Worker (LangGraph StateGraph)  
**Lý do chọn pattern này (thay vì single agent):**

Single agent (Day 08) xử lý mọi thứ trong 1 pipeline monolithic: retrieve → generate → answer. Khi câu hỏi phức tạp (multi-hop, cần policy check), single agent không tách biệt được logic → khó debug và extend. Supervisor-Worker cho phép: (1) routing thông minh theo loại câu hỏi, (2) test từng worker độc lập, (3) thêm MCP tools mà không sửa core pipeline.

---

## 2. Sơ đồ Pipeline

```
User Question (task)
      │
      ▼
┌──────────────────────┐
│     SUPERVISOR        │  ← keyword routing (policy/retrieval/risk)
│  supervisor_node()    │  → supervisor_route, route_reason, risk_high
└──────┬───────────────┘
       │
   [route_decision]
       │
  ┌────┼──────────────────────────┐
  │    │                          │
  ▼    ▼                          ▼
┌─────────────────┐  ┌──────────────────────┐  ┌────────────────┐
│ retrieval_worker │  │ policy_tool_worker   │  │ human_review   │
│  ChromaDB query  │  │  policy analysis     │  │  HITL trigger  │
│  dense retrieval │  │  + MCP tool calls    │  │  auto-approve  │
│  → chunks, srcs  │  │  → policy_result     │  │  → retrieval   │
└────────┬────────┘  └──────────┬───────────┘  └───────┬────────┘
         │                      │                      │
         └──────────┬───────────┘                      │
                    │         ┌─────────────────────────┘
                    ▼         ▼
         ┌─────────────────────────┐
         │   SYNTHESIS WORKER      │
         │  build context + LLM    │
         │  → final_answer + cite  │
         │  → confidence score     │
         └───────────┬─────────────┘
                     │
                     ▼
               AgentState Output
      (answer, sources, confidence, trace)
```

**Key flow:**
- `policy_tool_worker` tự gọi `retrieval_run()` trước nếu chưa có chunks
- `human_review` approve xong → route lại về `retrieval_worker`
- Tất cả workers ghi log vào `worker_io_logs` trong AgentState

---

## 3. Vai trò từng thành phần

### Supervisor (`graph.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Phân loại task và route tới worker phù hợp |
| **Input** | `task` (câu hỏi user) |
| **Output** | `supervisor_route`, `route_reason`, `risk_high`, `needs_tool` |
| **Routing logic** | Keyword-based: policy_keywords → policy_tool, retrieval_keywords → retrieval, risk_keywords + err- → HITL |
| **HITL condition** | `"err-" in task AND risk_high == True` |

### Retrieval Worker (`workers/retrieval.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Dense retrieval từ ChromaDB collection `day09_docs` |
| **Embedding model** | SentenceTransformer `all-MiniLM-L6-v2` (fallback: OpenAI `text-embedding-3-small`) |
| **Top-k** | 3 (default, configurable via `retrieval_top_k`) |
| **Stateless?** | Yes — chỉ đọc ChromaDB, không sửa state ngoài `retrieved_chunks` |

### Policy Tool Worker (`workers/policy_tool.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Phân tích policy rules + gọi MCP tools bổ sung |
| **MCP tools gọi** | `search_kb`, `get_ticket_info`, `check_access_permission` |
| **Exception cases xử lý** | flash_sale_exception, digital_product_exception, activated_product_exception, temporal_scoping |

### Synthesis Worker (`workers/synthesis.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **LLM model** | gpt-4o-mini (fallback: Gemini 2.0 Flash → Gemini 1.5 Flash → template fallback) |
| **Temperature** | 0.1 |
| **Grounding strategy** | System prompt: "CHỈ trả lời dựa vào context. KHÔNG dùng kiến thức ngoài." |
| **Abstain condition** | Context không đủ → "Không đủ thông tin trong tài liệu nội bộ" |

### MCP Server (`mcp_server.py`)

| Tool | Input | Output |
|------|-------|--------|
| search_kb | query, top_k | chunks, sources, total_found |
| get_ticket_info | ticket_id | ticket details (priority, SLA, notifications) |
| check_access_permission | access_level, requester_role, is_emergency | can_grant, required_approvers, emergency_override |
| create_ticket | priority, title, description | ticket_id, url, created_at |

**MCP trace:** Mỗi tool call tự ghi vào `_CALL_LOG` với format `{mcp_tool_called, mcp_input, mcp_result, timestamp}`. `graph.py` inject log vào `AgentState["mcp_tools_used"]` sau mỗi run.

---

## 4. Shared State Schema

| Field | Type | Mô tả | Ai đọc/ghi |
|-------|------|-------|-----------| 
| task | str | Câu hỏi đầu vào | supervisor đọc |
| supervisor_route | str | Worker được chọn | supervisor ghi |
| route_reason | str | Lý do route | supervisor ghi |
| risk_high | bool | Câu hỏi có risk cao không | supervisor ghi |
| needs_tool | bool | Cần gọi MCP tool không | supervisor ghi |
| hitl_triggered | bool | HITL đã trigger chưa | human_review ghi |
| retrieved_chunks | list | Evidence từ ChromaDB | retrieval ghi, synthesis đọc |
| retrieved_sources | list | Source filenames | retrieval ghi |
| policy_result | dict | Kết quả kiểm tra policy | policy_tool ghi, synthesis đọc |
| mcp_tools_used | list | Tool calls đã thực hiện | policy_tool ghi, graph inject |
| final_answer | str | Câu trả lời cuối | synthesis ghi |
| confidence | float | Mức tin cậy (0.1–0.95) | synthesis ghi |
| history | list | Log decisions theo thứ tự | mọi node append |
| workers_called | list | Danh sách workers đã gọi | mọi worker append |
| worker_io_logs | list | IO log từng worker (input/output/error) | mọi worker append |
| run_id | str | Unique ID cho run này | graph tạo |
| latency_ms | int | Tổng thời gian chạy | graph ghi |

---

## 5. Lý do chọn Supervisor-Worker so với Single Agent (Day 08)

| Tiêu chí | Single Agent (Day 08) | Supervisor-Worker (Day 09) |
|----------|----------------------|--------------------------|
| Debug khi sai | Khó — phải đọc 560 dòng rag_answer.py | Dễ — xem trace → test worker độc lập |
| Thêm capability mới | Sửa prompt + pipeline gốc | Thêm MCP tool + route rule |
| Routing visibility | Không có | route_reason trong mỗi trace |
| Multi-hop queries | 40% accuracy (single pipeline) | 60% accuracy (policy + retrieval workers) |
| Latency | ~2000ms (1 pipeline) | ~2500ms (multi-step, +25%) |

**Quan sát thực tế:** Multi-agent overhead ~500ms là chấp nhận được vì: (1) câu phức tạp cải thiện accuracy +20%, (2) debug time giảm 10 phút/bug, (3) thêm MCP tool không cần sửa core code.

---

## 6. Giới hạn và điểm cần cải tiến

1. **Keyword routing thiếu linh hoạt:** Supervisor dùng keyword matching → miss câu hỏi paraphrased hoặc ambiguous. Cải tiến: dùng LLM classifier hoặc intent detection.
2. **Single LLM call:** Chỉ có 1 LLM call ở synthesis. Câu multi-hop phức tạp có thể cần 2 LLM calls (1 cho reasoning, 1 cho synthesis).
3. **MCP mock:** 3/4 tools là mock data. Production cần real API integration (Jira, LDAP, Knowledge Base search).
4. **Confidence chưa calibrated:** Confidence score dựa trên chunk score average — chưa phản ánh chính xác mức tin cậy thực sự của answer.
