# Routing Decisions Log — Lab Day 09

**Nhóm:** NGUYENNANGANH  
**Ngày:** 2026-04-14

---

## Routing Decision #1

**Task đầu vào:**
> "SLA xử lý ticket P1 là bao lâu?"

**Worker được chọn:** `retrieval_worker`  
**Route reason (từ trace):** `Task contains retrieval keywords (P1/SLA/Ticket) -> retrieval_worker.`  
**MCP tools được gọi:** Không (retrieval_worker không gọi MCP)  
**Workers called sequence:** `[retrieval_worker, synthesis_worker]`

**Kết quả thực tế:**
- final_answer (ngắn): "Ticket P1 có SLA phản hồi 15 phút, xử lý trong 4 giờ. [sla_p1_2026.txt]"
- confidence: 0.92
- Correct routing? **Yes** — câu hỏi SLA đơn giản chỉ cần retrieval

**Nhận xét:** Routing chính xác. Keyword "P1" + "SLA" match `retrieval_keywords` trong supervisor_node. Không cần policy worker vì đây là fact lookup, không có exception/policy check.

---

## Routing Decision #2

**Task đầu vào:**
> "Khách hàng Flash Sale yêu cầu hoàn tiền vì sản phẩm lỗi — được không?"

**Worker được chọn:** `policy_tool_worker`  
**Route reason (từ trace):** `Task contains policy/access keywords -> policy_tool_worker.`  
**MCP tools được gọi:** `search_kb(query="Flash Sale hoàn tiền...", top_k=3)`  
**Workers called sequence:** `[retrieval_worker, policy_tool_worker, synthesis_worker]`

**Kết quả thực tế:**
- final_answer (ngắn): "Không được hoàn tiền. Đơn hàng Flash Sale thuộc ngoại lệ theo Điều 3 chính sách v4. [policy_refund_v4.txt]"
- confidence: 0.88
- Correct routing? **Yes** — cần policy check, phát hiện flash_sale_exception

**Nhận xét:** Routing đúng. Keyword "hoàn tiền" + "Flash Sale" match `policy_keywords`. Policy worker phát hiện `flash_sale_exception` từ REFUND_EXCEPTION_RULES. MCP `search_kb` được gọi để bổ sung context. Trace ghi rõ `exceptions_found: [{type: "flash_sale_exception"}]`.

---

## Routing Decision #3

**Task đầu vào:**
> "ERR-403-AUTH là lỗi gì và cách xử lý?"

**Worker được chọn:** `human_review`  
**Route reason (từ trace):** `Unknown error code detected + high risk -> human_review.`  
**MCP tools được gọi:** Không (HITL triggered trước khi gọi MCP)  
**Workers called sequence:** `[human_review, retrieval_worker, synthesis_worker]`

**Kết quả thực tế:**
- final_answer (ngắn): "Không tìm thấy thông tin về ERR-403-AUTH trong tài liệu nội bộ."
- confidence: 0.30
- Correct routing? **Yes** — mã lỗi không rõ + risk_high = đúng HITL flow

**Nhận xét:** Routing đúng. "ERR-" match `risk_keywords` → `risk_high = True`. Kết hợp với "err-" check → route `human_review`. Trong lab mode, auto-approve → pipeline tiếp tục qua retrieval → synthesis abstain đúng. `hitl_triggered: true` trong trace.

---

## Routing Decision #4 (bonus — câu khó nhất)

**Task đầu vào:**
> "Ticket P1 lúc 2am. Cần cấp Level 2 access tạm thời cho contractor. Đồng thời cần notify stakeholders theo SLA. Nêu đủ cả hai quy trình."

**Worker được chọn:** `policy_tool_worker`  
**Route reason:** `Task contains policy/access keywords -> policy_tool_worker.`

**Nhận xét: Đây là trường hợp routing khó nhất trong lab. Tại sao?**

Câu q15 kết hợp **2 domain**: SLA (P1 notification) + Access Control (Level 2 emergency). Supervisor phải chọn 1 worker duy nhất. Ban đầu keyword "P1" match `retrieval_keywords` trước `policy_keywords`, gây route sai → chỉ trả lời phần SLA. 

**Fix:** Trong `supervisor_node`, check `policy_keywords` TRƯỚC `retrieval_keywords` (logic order matters). Khi route sang `policy_tool_worker`, worker tự gọi `retrieval_run()` trước để lấy context SLA, rồi gọi MCP `check_access_permission(level=2, is_emergency=True)`. Trace ghi:
```json
{
  "supervisor_route": "policy_tool_worker",
  "workers_called": ["retrieval_worker", "policy_tool_worker", "synthesis_worker"],
  "mcp_tools_used": [
    {"tool": "check_access_permission", "input": {"access_level": 2, "is_emergency": true}}
  ]
}
```

Kết quả: answer bao gồm cả SLA escalation timeline VÀ Level 2 emergency bypass procedure. Đây là ví dụ tốt nhất cho lợi ích multi-agent: policy worker orchestrate retrieval + MCP → cross-doc answer.

---

## Tổng kết

### Routing Distribution

| Worker | Số câu được route | % tổng |
|--------|------------------|--------|
| retrieval_worker | 9 | 60% |
| policy_tool_worker | 5 | 33% |
| human_review | 1 | 7% |

### Routing Accuracy

- Câu route đúng: **14 / 15** (93%)
- Câu route sai (đã sửa): q15 ban đầu route retrieval thay vì policy → sửa keyword priority order
- Câu trigger HITL: 1 (q09 — ERR-403-AUTH)

### Lesson Learned về Routing

1. **Keyword order matters:** Policy keywords phải được check TRƯỚC retrieval keywords, vì câu policy thường cũng chứa retrieval keywords (VD: "P1 + cấp quyền"). Nếu check retrieval trước, câu multi-domain bị route sai.
2. **HITL threshold nên dựa trên confidence:** Hiện tại HITL chỉ trigger khi có error code + risk. Tốt hơn: trigger khi confidence < 0.4 sau retrieval.

### Route Reason Quality

Nhìn lại các `route_reason` trong trace — phần lớn đủ thông tin để debug: `"Task contains policy/access keywords -> policy_tool_worker"` cho biết rõ lý do. Tuy nhiên, route_reason chưa ghi **cụ thể keyword nào** match. Cải tiến: thêm matched keyword vào reason: `"Task contains 'hoàn tiền' (policy keyword) -> policy_tool_worker"`.
