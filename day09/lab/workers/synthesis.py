"""
workers/synthesis.py — Synthesis Worker
Sprint 2: Tổng hợp câu trả lời từ retrieved_chunks và policy_result.

Input (từ AgentState):
    - task: câu hỏi
    - retrieved_chunks: evidence từ retrieval_worker
    - policy_result: kết quả từ policy_tool_worker

Output (vào AgentState):
    - final_answer: câu trả lời cuối với citation
    - sources: danh sách nguồn tài liệu được cite
    - confidence: mức độ tin cậy (0.0 - 1.0)

Gọi độc lập để test:
    python workers/synthesis.py
"""

import os

WORKER_NAME = "synthesis_worker"

SYSTEM_PROMPT = """Bạn là trợ lý IT Helpdesk nội bộ.

Quy tắc nghiêm ngặt:
1. CHỈ trả lời dựa vào context được cung cấp. KHÔNG dùng kiến thức ngoài.
2. CHỈ nói 'Không đủ thông tin' khi context HOÀN TOÀN không liên quan. 
   Nếu context có thông tin MỘT PHẦN → trả lời phần có được và nêu rõ 
   phần nào thiếu."
3. Trích dẫn nguồn cuối mỗi câu quan trọng: [tên_file].
4. Trả lời súc tích, có cấu trúc. Không dài dòng.
5. Nếu có exceptions/ngoại lệ → nêu rõ ràng trước khi kết luận.
6. Nếu câu hỏi yêu cầu NHIỀU quy trình hoặc nhiều phần → trả lời TỪNG phần riêng biệt, đánh số rõ ràng.
7. Với câu hỏi về thời gian cụ thể (VD: ticket lúc 22:47) → tính toán thời gian chính xác dựa trên SLA.
8. KHI CÂU HỎI ĐỀ CẬP NGÀY CỤ THỂ: Kiểm tra ngày đó có nằm TRƯỚC 
   effective_date/ngày hiệu lực của tài liệu không. Nếu sự kiện xảy ra 
   TRƯỚC ngày hiệu lực → nêu rõ: "Tài liệu hiện tại có hiệu lực từ 
   [ngày]. Sự kiện trước ngày này có thể áp dụng version cũ hơn mà 
   tài liệu hiện có không bao gồm." KHÔNG bịa nội dung version cũ.
9. Nếu context có dữ liệu từ MCP tool (get_ticket_info, check_access_permission), 
   ƯU TIÊN sử dụng dữ liệu MCP vì đó là dữ liệu chính xác nhất. 
   Liệt kê ĐẦY ĐỦ tất cả các kênh notification, approvers, conditions từ MCP.
"""


def _call_llm(messages: list) -> str:
    """
    Gọi LLM để tổng hợp câu trả lời.
    Thử OpenAI -> google-genai (mới) -> google-generativeai (cũ) -> template fallback.
    """
    # Option A: OpenAI
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY", "")
        if api_key and not api_key.startswith("sk-..."):
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.1,
                max_tokens=500,
            )
            return response.choices[0].message.content
    except Exception:
        pass

    # Option B: Google GenAI (new SDK — google-genai)
    try:
        from google import genai
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if api_key and not api_key.startswith("AI..."):
            client = genai.Client(api_key=api_key)
            combined = "\n".join([m["content"] for m in messages])
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=combined,
            )
            return response.text
    except Exception:
        pass

    # Option C: Google GenerativeAI (old SDK — google-generativeai)
    try:
        import google.generativeai as genai_old
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if api_key and not api_key.startswith("AI..."):
            genai_old.configure(api_key=api_key)
            model = genai_old.GenerativeModel("gemini-1.5-flash")
            combined = "\n".join([m["content"] for m in messages])
            response = model.generate_content(combined)
            return response.text
    except Exception:
        pass

    # Fallback: template-based answer từ context (không cần LLM)
    return _template_fallback(messages)


def _template_fallback(messages: list) -> str:
    """
    Tổng hợp câu trả lời từ context mà không cần LLM.
    Dùng khi không có API key — trích xuất thông tin trực tiếp từ chunks.
    """
    # Lấy user message (chứa context)
    user_msg = ""
    for m in messages:
        if m.get("role") == "user":
            user_msg = m.get("content", "")

    if not user_msg:
        return "Khong du thong tin trong tai lieu noi bo de tra loi cau hoi nay."

    # Tách phần context và câu hỏi
    lines = user_msg.split("\n")
    question = ""
    context_lines = []
    in_context = False

    for line in lines:
        if line.strip().startswith("Cau hoi:") or line.strip().startswith("C\u00e2u h\u1ecfi:"):
            question = line.split(":", 1)[-1].strip()
        elif "TAI LIEU THAM KHAO" in line or "T\u00c0I LI\u1ec6U THAM KH\u1ea2O" in line:
            in_context = True
        elif "POLICY EXCEPTIONS" in line:
            in_context = True
        elif in_context and line.strip():
            context_lines.append(line.strip())

    if not context_lines:
        return "Khong du thong tin trong tai lieu noi bo de tra loi cau hoi nay."

    # Trích xuất keywords từ câu hỏi để matching thông minh hơn
    stop_words = {
        "là", "gì", "bao", "lâu", "nào", "có", "không", "được", "của",
        "cho", "và", "hay", "hoặc", "thì", "mà", "khi", "nếu", "với",
        "trong", "từ", "đến", "theo", "về", "như", "bị", "đã", "sẽ",
        "đang", "cần", "phải", "để", "ai", "bao nhiêu", "thế nào",
        "nhưng", "vì", "do", "tại", "ra", "lên", "xuống", "vào",
    }
    keywords = []
    if question:
        for word in question.lower().split():
            # Bỏ dấu câu
            clean_word = word.strip("?!.,;:()\"'")
            if clean_word and clean_word not in stop_words and len(clean_word) > 1:
                keywords.append(clean_word)

    # Xây dựng answer từ context trực tiếp
    # Lấy phần evidence quan trọng nhất — ưu tiên dòng chứa keyword
    evidence_parts = []
    sources = set()
    for line in context_lines:
        if line.startswith("[") and "]" in line:
            # Đây là evidence line, e.g. "[1] Nguồn: sla_p1_2026.txt..."
            evidence_parts.append(line)
            # Trích xuất source
            if "Ngu\u1ed3n:" in line or "Nguon:" in line:
                src = line.split("Ngu")[1].split("(")[0].strip()
                src = src.replace("\u1ed3n:", "").replace("on:", "").strip()
                sources.add(src)
        elif line.startswith("-") or line.startswith("*"):
            evidence_parts.append(line)
        elif keywords and any(kw in line.lower() for kw in keywords):
            # Chỉ lấy dòng context chứa ít nhất 1 keyword từ câu hỏi
            evidence_parts.append(line)
        elif not keywords and len(line) > 20:
            # Fallback: nếu không extract được keyword nào, giữ logic cũ
            evidence_parts.append(line)

    # Ghép answer
    answer_parts = ["Dua tren tai lieu noi bo:"]
    # Lấy tối đa 8 dòng evidence quan trọng nhất
    for part in evidence_parts[:8]:
        # Bỏ prefix [1] Nguồn:
        clean = part
        if clean.startswith("[") and "]" in clean:
            idx = clean.index("]")
            rest = clean[idx+1:].strip()
            if "relevance:" in rest:
                rest = rest.split("\n", 1)[-1] if "\n" in rest else rest.split(")", 1)[-1]
            clean = rest.strip()
        if clean:
            answer_parts.append(f"- {clean}")

    if sources:
        answer_parts.append(f"\n[Nguon: {', '.join(sources)}]")

    return "\n".join(answer_parts)


def _build_context(chunks: list, policy_result: dict) -> str:
    """Xây dựng context string từ chunks và policy result."""
    parts = []

    if chunks:
        parts.append("=== TÀI LIỆU THAM KHẢO ===")
        for i, chunk in enumerate(chunks, 1):
            source = chunk.get("source", "unknown")
            text = chunk.get("text", "")
            score = chunk.get("score", 0)
            parts.append(f"[{i}] Nguồn: {source} (relevance: {score:.2f})\n{text}")

    if policy_result and policy_result.get("exceptions_found"):
        parts.append("\n=== POLICY EXCEPTIONS ===")
        for ex in policy_result["exceptions_found"]:
            parts.append(f"- {ex.get('rule', '')}")

    if not parts:
        return "(Không có context)"

    return "\n\n".join(parts)


def _estimate_confidence(chunks: list, answer: str, policy_result: dict) -> float:
    """
    Ước tính confidence dựa vào:
    - Số lượng và quality của chunks
    - Có exceptions không
    - Answer có abstain không

    TODO Sprint 2: Có thể dùng LLM-as-Judge để tính confidence chính xác hơn.
    """
    if not chunks:
        return 0.1  # Không có evidence → low confidence

    if "Không đủ thông tin" in answer or "không có trong tài liệu" in answer.lower():
        return 0.3  # Abstain → moderate-low

    # Weighted average của chunk scores
    if chunks:
        avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks)
    else:
        avg_score = 0

    # Penalty nếu có exceptions (phức tạp hơn)
    exception_penalty = 0.05 * len(policy_result.get("exceptions_found", []))

    confidence = min(0.95, avg_score - exception_penalty)
    return round(max(0.1, confidence), 2)


def synthesize(task: str, chunks: list, policy_result: dict) -> dict:
    """
    Tổng hợp câu trả lời từ chunks và policy context.

    Returns:
        {"answer": str, "sources": list, "confidence": float}
    """
    context = _build_context(chunks, policy_result)

    # Build messages
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""Câu hỏi: {task}

{context}

Hãy trả lời câu hỏi dựa vào tài liệu trên."""
        }
    ]

    answer = _call_llm(messages)
    sources = list({c.get("source", "unknown") for c in chunks})
    confidence = _estimate_confidence(chunks, answer, policy_result)

    return {
        "answer": answer,
        "sources": sources,
        "confidence": confidence,
    }


def run(state: dict) -> dict:
    """
    Worker entry point — gọi từ graph.py.
    """
    task = state.get("task", "")
    chunks = state.get("retrieved_chunks", [])
    policy_result = state.get("policy_result", {})

    state.setdefault("workers_called", [])
    state.setdefault("history", [])
    state["workers_called"].append(WORKER_NAME)

    worker_io = {
        "worker": WORKER_NAME,
        "input": {
            "task": task,
            "chunks_count": len(chunks),
            "has_policy": bool(policy_result),
        },
        "output": None,
        "error": None,
    }

    try:
        result = synthesize(task, chunks, policy_result)
        state["final_answer"] = result["answer"]
        state["sources"] = result["sources"]
        state["confidence"] = result["confidence"]

        worker_io["output"] = {
            "answer_length": len(result["answer"]),
            "sources": result["sources"],
            "confidence": result["confidence"],
        }
        state["history"].append(
            f"[{WORKER_NAME}] answer generated, confidence={result['confidence']}, "
            f"sources={result['sources']}"
        )

    except Exception as e:
        worker_io["error"] = {"code": "SYNTHESIS_FAILED", "reason": str(e)}
        state["final_answer"] = f"SYNTHESIS_ERROR: {e}"
        state["confidence"] = 0.0
        state["history"].append(f"[{WORKER_NAME}] ERROR: {e}")

    state.setdefault("worker_io_logs", []).append(worker_io)
    return state


# ─────────────────────────────────────────────
# Test độc lập
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("Synthesis Worker — Standalone Test")
    print("=" * 50)

    test_state = {
        "task": "SLA ticket P1 là bao lâu?",
        "retrieved_chunks": [
            {
                "text": "Ticket P1: Phản hồi ban đầu 15 phút kể từ khi ticket được tạo. Xử lý và khắc phục 4 giờ. Escalation: tự động escalate lên Senior Engineer nếu không có phản hồi trong 10 phút.",
                "source": "sla_p1_2026.txt",
                "score": 0.92,
            }
        ],
        "policy_result": {},
    }

    result = run(test_state.copy())
    print(f"\nAnswer:\n{result['final_answer']}")
    print(f"\nSources: {result['sources']}")
    print(f"Confidence: {result['confidence']}")

    print("\n--- Test 2: Exception case ---")
    test_state2 = {
        "task": "Khách hàng Flash Sale yêu cầu hoàn tiền vì lỗi nhà sản xuất.",
        "retrieved_chunks": [
            {
                "text": "Ngoại lệ: Đơn hàng Flash Sale không được hoàn tiền theo Điều 3 chính sách v4.",
                "source": "policy_refund_v4.txt",
                "score": 0.88,
            }
        ],
        "policy_result": {
            "policy_applies": False,
            "exceptions_found": [{"type": "flash_sale_exception", "rule": "Flash Sale không được hoàn tiền."}],
        },
    }
    result2 = run(test_state2.copy())
    print(f"\nAnswer:\n{result2['final_answer']}")
    print(f"Confidence: {result2['confidence']}")

    print("\n✅ synthesis_worker test done.")
