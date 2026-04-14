# 🔍 Day 09 Lab — Senior AI Engineer Full Audit

## TL;DR — Lab này build cái gì?

**Mục tiêu:** Refactor RAG pipeline (Day 08 monolith) thành hệ thống **Supervisor-Worker Multi-Agent** với:
- **Supervisor** (`graph.py`) điều phối routing
- **3 Workers**: Retrieval, Policy/Tool, Synthesis  
- **MCP Server** (`mcp_server.py`) — external tool interface
- **Trace & Eval** (`eval_trace.py`) — observability + so sánh Day 08 vs 09
- **Documentation** — 3 docs + group report + individual reports

**Input:** Câu hỏi từ user (test_questions.json / grading_questions.json)  
**Output:** Câu trả lời có citation + full trace (routing, workers, MCP, confidence)

---

## 1. Luồng Chạy Hệ Thống

```
User Question
     │
     ▼
┌──────────────────┐
│  run_graph(task)  │  ← graph.py: entry point
│  make_initial_state()
└────────┬─────────┘
         ▼
┌──────────────────┐
│  supervisor_node  │  ← Phân tích keyword → quyết định route
│  route_reason     │  ← Ghi lý do vào state
└────────┬─────────┘
         │ route_decision()
    ┌────┴────────────────────────┐
    │              │              │
    ▼              ▼              ▼
 retrieval    policy_tool    human_review
  _worker      _worker        _node
    │              │              │
    └──────────────┴──────┬───────┘
                          ▼
                  synthesis_worker
                     (LLM call)
                          │
                          ▼
                   AgentState (output)
                   + save_trace()
```

---

## 2. Trạng Thái Hiện Tại — Code vs Yêu Cầu

### ✅ Đã làm đúng

| Thành phần | Trạng thái | Chi tiết |
|-----------|-----------|---------|
| `AgentState` (TypedDict) | ✅ Đầy đủ | Có tất cả fields cần thiết |
| `supervisor_node()` routing logic | ⚠️ Cơ bản | Keyword matching hoạt động, nhưng **thiếu nhiều keywords quan trọng** |
| `route_decision()` | ✅ Hoàn chỉnh | Conditional edge hoạt động |
| `human_review_node()` | ✅ Placeholder | Hoạt động cho HITL flow |
| `make_initial_state()` | ✅ Hoàn chỉnh | Khởi tạo đúng tất cả fields |
| `build_graph()` - orchestrator | ✅ Hoạt động | Python thuần, if/else routing |
| `save_trace()` | ✅ Hoạt động | Lưu JSON trace files |
| `workers/retrieval.py` — `run()` + `retrieve_dense()` | ✅ Implement full | ChromaDB dense retrieval |
| `workers/policy_tool.py` — `run()` + `analyze_policy()` | ✅ Implement full | Rule-based policy + 3 exceptions |
| `workers/synthesis.py` — `run()` + `synthesize()` | ✅ Implement full | LLM call + abstain logic |
| `mcp_server.py` — 4 tools | ✅ Implement full | search_kb, get_ticket_info, check_access, create_ticket |
| `contracts/worker_contracts.yaml` | ✅ Đầy đủ | I/O contracts cho tất cả workers |
| `eval_trace.py` | ✅ Implement full | Run test, grading, analyze, compare |
| `data/docs/` | ✅ Đủ 5 tài liệu | Đúng yêu cầu |
| `data/test_questions.json` | ✅ 15 câu | Đầy đủ |

### ❌ Vấn đề NGHIÊM TRỌNG — Phải sửa ngay

> [!CAUTION]
> **graph.py vẫn dùng PLACEHOLDER workers!** Workers đã được implement đầy đủ trong `workers/` nhưng **KHÔNG được import và sử dụng** trong graph.py. Hệ thống sẽ chạy nhưng **chỉ trả về kết quả giả** (mock data).

| # | Vấn đề | Impact | File |
|---|--------|--------|------|
| 1 | **Workers KHÔNG được kết nối vào graph** — Lines 178-181 vẫn comment `# from workers.retrieval import run` | 💀 CRITICAL — mọi output đều fake | `graph.py` |
| 2 | **Worker wrapper nodes vẫn dùng placeholder** — Lines 184-229 trả về mock data thay vì gọi real workers | 💀 CRITICAL — 0 điểm grading | `graph.py` |
| 3 | **Chưa có `.env` file** — LLM calls (synthesis) sẽ fail | 🔴 HIGH — synthesis trả "ERROR" | `.env` |
| 4 | **Chưa build ChromaDB index** — Retrieval sẽ fail/empty | 🔴 HIGH — retrieval trả [] | `chroma_db/` |
| 5 | **Chưa có `artifacts/` directory** — trace files không lưu được | 🟡 MEDIUM — eval_trace crash | `artifacts/` |
| 6 | **Chưa có `grading_questions.json`** — chạy grading sẽ fail | 🟡 Chờ 17:00 | `data/` |
| 7 | **`worker_contracts.yaml` status vẫn "TODO Sprint 2/3"** | 🟡 Mất điểm tracing | `contracts/` |
| 8 | **Routing thiếu keywords cho grading questions** | 🟠 Sẽ route sai 1 số câu | `graph.py` |
| 9 | **gq09 multi-hop: graph KHÔNG gọi cả 2 workers** cho 1 câu | 🔴 HIGH — mất 16 điểm | `graph.py` |
| 10 | **Tất cả docs/ đều BLANK** (template chưa điền) | 🔴 Mất 10 điểm documentation | `docs/` |
| 11 | **group_report.md BLANK** | 🔴 Mất điểm | `reports/` |
| 12 | **Không có individual report** (chỉ có template.md) | 🔴 Mất 30 điểm cá nhân | `reports/individual/` |

---

## 3. Phân Tích Scoring — Mapping Code Hiện Tại

### Phần Nhóm — 60 điểm

#### 3.1 Sprint Deliverables (20 điểm)

| Tiêu chí | Điểm max | Hiện tại | % | Vấn đề |
|----------|---------|---------|---|--------|
| Sprint 1: `python graph.py` chạy không lỗi | 3 | ⚠️ 1 | 33% | Chạy được nhưng output fake |
| Sprint 1: route_reason rõ ràng | 2 | ✅ 2 | 100% | Routing logic có ghi reason |
| Sprint 2: Workers test độc lập, khớp contracts | 3 | ⚠️ 1 | 33% | Workers OK, nhưng **không kết nối vào graph** |
| Sprint 2: Policy exception ≥1 case | 2 | ✅ 2 | 100% | Flash Sale + digital product + activated |
| Sprint 3: MCP 2 tools + gọi từ worker | 3 | ⚠️ 1 | 33% | MCP OK, policy_tool gọi MCP, nhưng graph dùng placeholder |
| Sprint 3: Trace ghi mcp_tool_called | 2 | ⚠️ 0 | 0% | Graph placeholder không gọi MCP |
| Sprint 4: eval_trace.py chạy end-to-end | 3 | ❌ 0 | 0% | Chưa chạy, chưa có traces |
| Sprint 4: single_vs_multi_comparison.md | 2 | ❌ 0 | 0% | Template trống |
| **Subtotal** | **20** | **~7** | **35%** | |

#### 3.2 Group Documentation (10 điểm)

| Tiêu chí | Điểm max | Hiện tại | % |
|----------|---------|---------|---|
| system_architecture.md — vai trò workers | 2 | ❌ 0 | 0% |
| system_architecture.md — sơ đồ pipeline | 1 | ❌ 0 | 0% |
| system_architecture.md — lý do chọn pattern | 1 | ❌ 0 | 0% |
| routing_decisions.md — 3 quyết định thực tế | 2 | ❌ 0 | 0% |
| routing_decisions.md — format đầy đủ | 1 | ❌ 0 | 0% |
| single_vs_multi_comparison.md — 2 metrics | 2 | ❌ 0 | 0% |
| single_vs_multi_comparison.md — kết luận | 1 | ❌ 0 | 0% |
| **Subtotal** | **10** | **0** | **0%** |

#### 3.3 Grading Questions — Trace (30 điểm)

| Trạng thái | Chi tiết |
|-----------|---------|
| ❌ 0/30 | Chưa có grading_questions.json, pipeline trả fake data, không có artifacts/grading_run.jsonl |

**Ước tính tổng nhóm hiện tại: ~7/60 (12%)**

### Phần Cá Nhân — 40 điểm

| Tiêu chí | Điểm max | Hiện tại |
|----------|---------|---------|
| Individual Report | 30 | ❌ 0 — chưa có file |
| Code Contribution Evidence | 10 | ⚠️ ~4 — code có nhưng chưa có comment/initials |
| **Subtotal** | **40** | **~4** |

> [!IMPORTANT]
> **Tổng ước tính hiện tại: ~11/100 (11%). Cần hành động ngay!**

---

## 4. Checklist Chi Tiết — Từ Ưu Tiên Cao → Thấp

### 🔴 Critical Path (PHẢI xong trước 17:00)

- [ ] **Task 1: Kết nối real workers vào graph.py** — Uncomment imports + thay placeholder nodes
- [ ] **Task 2: Tạo file .env** — Điền API key (OpenAI hoặc Gemini)
- [ ] **Task 3: Build ChromaDB index** — Index 5 docs vào collection `day09_docs`
- [ ] **Task 4: Sửa routing logic** — Thêm keywords cho grading questions (SLA, mật khẩu, remote, store credit, v.v.)
- [ ] **Task 5: Thêm multi-hop support** — Cho graph gọi BOTH retrieval + policy workers cho câu phức tạp (gq09)
- [ ] **Task 6: Chạy `python graph.py`** — Verify pipeline hoạt động end-to-end
- [ ] **Task 7: Chạy `python eval_trace.py`** — Verify 15 test questions
- [ ] **Task 8: Tạo thư mục `artifacts/traces/`**

### 🟠 Trước 17:00 (Documentation)

- [ ] **Task 9: Điền `docs/system_architecture.md`**
- [ ] **Task 10: Cập nhật `contracts/worker_contracts.yaml`** — status → "done"
- [ ] **Task 11: Điền `docs/routing_decisions.md`** — 3 routing decisions thực tế từ traces

### 🟡 17:00–18:00 (Grading)

- [ ] **Task 12: Chạy `python eval_trace.py --grading`** — khi grading_questions.json public
- [ ] **Task 13: Verify `artifacts/grading_run.jsonl`** — đúng format JSONL
- [ ] **Task 14: Điền `docs/single_vs_multi_comparison.md`** — ≥2 metrics thực tế

### 🟢 Sau 18:00 (Reports)

- [ ] **Task 15: Viết `reports/group_report.md`**
- [ ] **Task 16: Viết individual reports** — mỗi người 1 file `reports/individual/[ten].md`

---

## 5. Hướng Dẫn Sửa Cụ Thể Từng Task

### Task 1: Kết nối workers vào graph.py

**Vấn đề:** Lines 178-181 vẫn comment. Lines 184-229 là placeholder.

**Sửa `graph.py`:**

```diff
# --- Lines 178-181: Uncomment imports ---
-# from workers.retrieval import run as retrieval_run
-# from workers.policy_tool import run as policy_tool_run
-# from workers.synthesis import run as synthesis_run
+from workers.retrieval import run as retrieval_run
+from workers.policy_tool import run as policy_tool_run
+from workers.synthesis import run as synthesis_run


# --- Lines 184-196: Replace retrieval_worker_node ---
 def retrieval_worker_node(state: AgentState) -> AgentState:
     """Wrapper gọi retrieval worker."""
-    # TODO Sprint 2: Thay bằng retrieval_run(state)
-    state["workers_called"].append("retrieval_worker")
-    state["history"].append("[retrieval_worker] called")
-    # Placeholder output ...
-    state["retrieved_chunks"] = [...]
-    state["retrieved_sources"] = [...]
-    state["history"].append(...)
-    return state
+    return retrieval_run(state)


# --- Lines 199-213: Replace policy_tool_worker_node ---
 def policy_tool_worker_node(state: AgentState) -> AgentState:
     """Wrapper gọi policy/tool worker."""
-    # TODO Sprint 2: Thay bằng policy_tool_run(state)
-    ...placeholder...
+    return policy_tool_run(state)


# --- Lines 216-229: Replace synthesis_worker_node ---
 def synthesis_worker_node(state: AgentState) -> AgentState:
     """Wrapper gọi synthesis worker."""
-    # TODO Sprint 2: Thay bằng synthesis_run(state)
-    ...placeholder...
+    return synthesis_run(state)
```

### Task 2: Tạo .env

```bash
cp .env.example .env
# Mở .env, điền 1 trong 2:
# OPENAI_API_KEY=sk-proj-... (khuyến nghị)
# GOOGLE_API_KEY=AI...
```

### Task 3: Build ChromaDB index

```python
# Chạy script này từ thư mục day09/lab/
import chromadb
import os
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')
client = chromadb.PersistentClient(path='./chroma_db')
col = client.get_or_create_collection('day09_docs', metadata={"hnsw:space": "cosine"})

docs_dir = './data/docs'
chunk_id = 0
for fname in os.listdir(docs_dir):
    filepath = os.path.join(docs_dir, fname)
    with open(filepath, encoding='utf-8') as f:
        content = f.read()
    
    # Simple chunking: split by double newlines or paragraphs
    chunks = [c.strip() for c in content.split('\n\n') if c.strip() and len(c.strip()) > 50]
    
    for chunk_text in chunks:
        embedding = model.encode([chunk_text])[0].tolist()
        col.add(
            ids=[f"chunk_{chunk_id}"],
            embeddings=[embedding],
            documents=[chunk_text],
            metadatas=[{"source": fname, "chunk_index": chunk_id}]
        )
        chunk_id += 1

print(f"Indexed {chunk_id} chunks from {len(os.listdir(docs_dir))} files.")
print(f"Collection count: {col.count()}")
```

### Task 4: Sửa routing logic trong `supervisor_node()`

**Vấn đề:** Thiếu nhiều keywords cho grading questions.

```python
# Thay thế phần routing logic (lines 100-121 trong graph.py)

# --- Keyword groups ---
policy_keywords = [
    "hoàn tiền", "refund", "flash sale", "license", "store credit",
    "cấp quyền", "access", "level 2", "level 3", "permission",
    "ngoại lệ", "exception", "policy", "chính sách",
]
retrieval_keywords = [
    "p1", "sla", "ticket", "escalation", "sự cố", "incident",
    "mật khẩu", "password", "đăng nhập", "login",
    "remote", "làm việc từ xa", "thử việc", "probation",
    "phê duyệt", "approve",
]
risk_keywords = ["emergency", "khẩn cấp", "2am", "không rõ", "err-"]

# Multi-hop detection: cần CẢ 2 workers
multi_hop_signals = [
    ("p1", "cấp quyền"), ("p1", "access"), ("p1", "level"),
    ("sla", "access"), ("sla", "cấp quyền"),
    ("ticket", "quyền"), ("contractor", "p1"),
]

# Check multi-hop first (highest priority)
is_multi_hop = any(
    s1 in task and s2 in task for s1, s2 in multi_hop_signals
)

if is_multi_hop:
    route = "policy_tool_worker"
    route_reason = f"Multi-hop detected: task contains cross-domain signals -> route to policy_tool (will also call retrieval via MCP)"
    needs_tool = True
    risk_high = True
elif any(kw in task for kw in policy_keywords):
    route = "policy_tool_worker"
    matched = [kw for kw in policy_keywords if kw in task]
    route_reason = f"Task contains policy keyword(s): {matched} -> route to policy_tool_worker"
    needs_tool = True
elif any(kw in task for kw in retrieval_keywords):
    route = "retrieval_worker"
    matched = [kw for kw in retrieval_keywords if kw in task]
    route_reason = f"Task contains retrieval keyword(s): {matched} -> route to retrieval_worker"
else:
    route = "retrieval_worker"
    route_reason = "No specific keyword match -> default route to retrieval_worker"

if any(kw in task for kw in risk_keywords):
    risk_high = True
    route_reason += " | risk_high flagged"

# Human review override
if risk_high and "err-" in task:
    route = "human_review"
    route_reason = f"Unknown error code + risk_high -> human_review required"
```

### Task 5: Multi-hop support in `build_graph()`

**Vấn đề:** Câu gq09 cần gọi CẢ retrieval + policy workers. Graph hiện tại chỉ gọi 1.

```python
# Sửa flow trong build_graph() -> run() function

def run(state: AgentState) -> AgentState:
    import time
    start = time.time()

    # Step 1: Supervisor decides route
    state = supervisor_node(state)
    route = route_decision(state)

    if route == "human_review":
        state = human_review_node(state)
        state = retrieval_worker_node(state)
    elif route == "policy_tool_worker":
        # Policy worker: ALWAYS do retrieval first for context
        state = retrieval_worker_node(state)
        state = policy_tool_worker_node(state)
    else:
        state = retrieval_worker_node(state)

    # Step 3: Always synthesize
    state = synthesis_worker_node(state)

    state["latency_ms"] = int((time.time() - start) * 1000)
    state["history"].append(f"[graph] completed in {state['latency_ms']}ms")
    return state
```

> [!IMPORTANT]
> Thay đổi quan trọng: khi route = `policy_tool_worker`, **luôn gọi retrieval trước** để lấy context. 
> Điều này đảm bảo câu multi-hop (gq09) trace ghi được `workers_called: ["retrieval_worker", "policy_tool_worker", "synthesis_worker"]`.

### Task 8: Tạo artifacts directory

```bash
mkdir -p artifacts/traces
```

### Task 10: Cập nhật contracts status

Trong `worker_contracts.yaml`, thay tất cả `status: "TODO Sprint X"` → `status: "done"`.

---

## 6. Phân Tích Grading Questions — Dự Đoán Kết Quả

| ID | Câu hỏi | Điểm | Route đúng | Workers cần | Rủi ro |
|----|---------|------|-----------|------------|--------|
| gq01 | P1 lúc 22:47 — thông báo, kênh, deadline | 10 | retrieval | retrieval → synthesis | ✅ OK nếu SLA doc indexed tốt |
| gq02 | Đơn 31/01 hoàn tiền 07/02 | 10 | policy_tool | retrieval → policy → synthesis | ⚠️ Temporal scoping phức tạp |
| gq03 | Level 3 access — mấy người phê duyệt | 10 | policy_tool | retrieval → policy → synthesis | ✅ Access doc có info |
| gq04 | Store credit = bao nhiêu % | 6 | policy_tool | retrieval → policy → synthesis | ✅ Numeric fact in doc |
| gq05 | P1 không phản hồi 10 phút | 8 | retrieval | retrieval → synthesis | ✅ OK |
| gq06 | NV thử việc remote | 8 | retrieval | retrieval → synthesis | ✅ HR doc có info |
| gq07 | Mức phạt SLA P1 | 10 | retrieval | retrieval → synthesis | 🔴 **PHẢI ABSTAIN** — info KHÔNG có trong docs |
| gq08 | Mật khẩu đổi mấy ngày | 8 | retrieval | retrieval → synthesis | ✅ FAQ doc có info |
| gq09 | P1 2am + Level 2 access | 16 | policy_tool | retrieval → policy → synthesis | ⚠️ **Multi-hop hardest** — cần cả 2 docs |
| gq10 | Flash Sale + lỗi NSD + 7 ngày | 10 | policy_tool | retrieval → policy → synthesis | ✅ Exception detection OK |

### Rủi ro cao nhất:

1. **gq07 (10 điểm)**: Pipeline **PHẢI abstain** — nói rõ "không có thông tin về mức phạt tài chính trong tài liệu". **Nếu bịa = -5 điểm (penalty)**
2. **gq09 (16 điểm)**: Cần cross-reference SLA P1 + Access Control SOP. Trace phải ghi 2+ workers
3. **gq02 (10 điểm)**: Temporal scoping — đơn trước 01/02/2026 áp dụng policy v3 (không có trong docs)

---

## 7. Format Chuẩn Cần Tuân Thủ

### Trace output format (`artifacts/grading_run.jsonl`)

Mỗi dòng PHẢI là 1 JSON object:

```json
{
  "id": "gq01",
  "question": "Ticket P1 được tạo lúc 22:47...",
  "answer": "Câu trả lời từ pipeline...",
  "sources": ["sla_p1_2026.txt"],
  "supervisor_route": "retrieval_worker",
  "route_reason": "Task contains retrieval keyword(s): ['p1', 'ticket'] -> route to retrieval_worker",
  "workers_called": ["retrieval_worker", "synthesis_worker"],
  "mcp_tools_used": [],
  "confidence": 0.88,
  "hitl_triggered": false,
  "timestamp": "2026-04-14T17:23:45"
}
```

> [!WARNING]
> **Thiếu `route_reason` = mất 20% điểm câu đó!**
> **`route_reason` = "" hoặc "unknown" = coi như thiếu!**

### `mcp_tools_used` trong grading trace

Hiện tại `eval_trace.py` line 128 lấy MCP tools:
```python
"mcp_tools_used": [t.get("tool") for t in result.get("mcp_tools_used", [])],
```

Nhưng `result["mcp_tools_used"]` từ graph là list of dicts `{"tool": "search_kb", "input": ..., "output": ..., "timestamp": ...}`. Code eval đang đúng — nhưng chỉ extract tên tool. Cần verify sau khi kết nối workers.

---

## 8. Tóm Tắt — Cần Làm Gì Để PASS 100%

### Mức tối thiểu (PASS ~60%):
1. ✅ Kết nối workers → graph.py (Task 1)
2. ✅ Tạo .env + Build ChromaDB (Task 2, 3)
3. ✅ Chạy graph.py + eval_trace.py (Task 6, 7)
4. ✅ Chạy grading questions (Task 12)

### Mức tốt (75-85%):
5. ✅ Sửa routing cho tất cả grading questions (Task 4)
6. ✅ Thêm multi-hop support (Task 5)
7. ✅ Điền 3 docs templates (Task 9, 11, 14)

### Mức tối đa (90-100%):
8. ✅ Verify gq07 abstain đúng
9. ✅ Verify gq09 trace ghi 2 workers  
10. ✅ Viết group + individual reports (Task 15, 16)
11. ✅ Cập nhật contracts status (Task 10)

### Bonus (+5 điểm):
- `confidence` score thực tế (KHÔNG hard-code) — ✅ đã implement trong synthesis.py
- gq09 Full marks + 2 workers trong trace — cần Task 5
- MCP server thật (HTTP) — optional (+2)

> [!TIP]
> **Ưu tiên tuyệt đối: Task 1 → 2 → 3 → 4 → 5 → 6 → 7.** Nếu hoàn thành 7 tasks này, pipeline sẽ hoạt động thực sự và có thể chạy grading questions.
