"""
workers/policy_tool.py — Policy & Tool Worker
Sprint 2: Kiểm tra policy dựa vào context, gọi MCP tools khi cần.

Input (từ AgentState):
    - task: câu hỏi
    - retrieved_chunks: context từ retrieval_worker
    - needs_tool: True nếu supervisor quyết định cần tool call

Output (vào AgentState):
    - policy_result: {"policy_applies", "policy_name", "exceptions_found", "source", "rule"}
    - mcp_tools_used: list of tool calls đã thực hiện
    - worker_io_log: log

Gọi độc lập để test:
    python workers/policy_tool.py
"""

import os
import sys
from datetime import datetime
from typing import Optional

WORKER_NAME = "policy_tool_worker"


# ─────────────────────────────────────────────
# MCP Client — gọi tools từ mcp_server.py
# ─────────────────────────────────────────────

def _call_mcp_tool(tool_name: str, tool_input: dict) -> dict:
    """
    Gọi MCP tool qua dispatch_tool (in-process mock).

    Returns:
        dict với keys: tool, input, output, error, timestamp
    """
    try:
        # Import từ mcp_server (cùng thư mục lab/)
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from mcp_server import dispatch_tool
        result = dispatch_tool(tool_name, tool_input)
        return {
            "tool": tool_name,
            "input": tool_input,
            "output": result,
            "error": None,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "tool": tool_name,
            "input": tool_input,
            "output": None,
            "error": {"code": "MCP_CALL_FAILED", "reason": str(e)},
            "timestamp": datetime.now().isoformat(),
        }


# ─────────────────────────────────────────────
# Policy Analysis Logic — Rule-based + Context-aware
# ─────────────────────────────────────────────

# Refund policy exceptions theo policy_refund_v4.txt Điều 3
REFUND_EXCEPTION_RULES = [
    {
        "type": "flash_sale_exception",
        "keywords_task": ["flash sale"],
        "keywords_context": ["flash sale", "chương trình khuyến mãi flash sale",
                             "mã giảm giá đặc biệt"],
        "rule": "Đơn hàng đã áp dụng mã giảm giá đặc biệt theo chương trình "
                "khuyến mãi Flash Sale không được hoàn tiền (Điều 3, chính sách v4).",
        "source": "policy_refund_v4.txt",
    },
    {
        "type": "digital_product_exception",
        "keywords_task": ["license key", "license", "subscription", "kỹ thuật số",
                          "digital", "phần mềm"],
        "keywords_context": ["license key", "subscription", "hàng kỹ thuật số",
                             "sản phẩm kỹ thuật số"],
        "rule": "Sản phẩm thuộc danh mục hàng kỹ thuật số (license key, subscription) "
                "không được hoàn tiền (Điều 3, chính sách v4).",
        "source": "policy_refund_v4.txt",
    },
    {
        "type": "activated_product_exception",
        "keywords_task": ["đã kích hoạt", "đã đăng ký", "đã sử dụng",
                          "đã dùng", "đã mở seal", "activated"],
        "keywords_context": ["đã kích hoạt", "đăng ký tài khoản",
                             "đã được kích hoạt"],
        "rule": "Sản phẩm đã được kích hoạt hoặc đăng ký tài khoản "
                "không được hoàn tiền (Điều 3, chính sách v4).",
        "source": "policy_refund_v4.txt",
    },
]

# Refund eligibility conditions theo policy_refund_v4.txt Điều 2
REFUND_CONDITIONS = {
    "time_limit_days": 7,
    "conditions": [
        "Sản phẩm bị lỗi do nhà sản xuất, không phải do người dùng.",
        "Yêu cầu được gửi trong vòng 7 ngày làm việc kể từ thời điểm xác nhận đơn hàng.",
        "Đơn hàng chưa được sử dụng hoặc chưa bị mở seal.",
    ],
    "source": "policy_refund_v4.txt",
}

# Access control levels theo access_control_sop.txt
ACCESS_LEVELS = {
    1: {
        "name": "Read Only",
        "approvers": ["Line Manager"],
        "processing_days": 1,
        "emergency_bypass": False,
    },
    2: {
        "name": "Standard Access",
        "approvers": ["Line Manager", "IT Admin"],
        "processing_days": 2,
        "emergency_bypass": True,
        "emergency_note": "Level 2 có thể cấp tạm thời với approval đồng thời "
                          "của Line Manager và IT Admin on-call.",
    },
    3: {
        "name": "Elevated Access",
        "approvers": ["Line Manager", "IT Admin", "IT Security"],
        "processing_days": 3,
        "emergency_bypass": False,
    },
    4: {
        "name": "Admin Access",
        "approvers": ["IT Manager", "CISO"],
        "processing_days": 5,
        "emergency_bypass": False,
        "extra": "Training bắt buộc về security policy.",
    },
}


def _detect_refund_exceptions(task: str, context_text: str) -> list[dict]:
    """Phát hiện ngoại lệ hoàn tiền từ task và context."""
    task_lower = task.lower()
    ctx_lower = context_text.lower()
    exceptions = []

    for rule in REFUND_EXCEPTION_RULES:
        matched_in_task = any(kw in task_lower for kw in rule["keywords_task"])
        matched_in_ctx = any(kw in ctx_lower for kw in rule["keywords_context"])

        if matched_in_task or matched_in_ctx:
            exceptions.append({
                "type": rule["type"],
                "rule": rule["rule"],
                "source": rule["source"],
                "matched_in": "task" if matched_in_task else "context",
            })

    return exceptions


def _check_refund_eligibility(task: str, context_text: str) -> dict:
    """Kiểm tra điều kiện hoàn tiền theo Điều 2."""
    task_lower = task.lower()
    ctx_lower = context_text.lower()

    conditions_met = []
    conditions_missing = []

    # Check: Sản phẩm lỗi nhà sản xuất
    defect_keywords = ["lỗi", "lỗi nhà sản xuất", "defective", "hỏng", "bị lỗi"]
    if any(kw in task_lower or kw in ctx_lower for kw in defect_keywords):
        conditions_met.append("Sản phẩm bị lỗi do nhà sản xuất")
    else:
        conditions_missing.append("Chưa xác nhận sản phẩm bị lỗi do nhà sản xuất")

    # Check: Trong thời hạn 7 ngày
    time_keywords = ["trong 7 ngày", "5 ngày", "3 ngày", "hôm qua", "tuần trước",
                     "trong vòng 7", "within 7"]
    if any(kw in task_lower or kw in ctx_lower for kw in time_keywords):
        conditions_met.append("Yêu cầu trong thời hạn 7 ngày làm việc")

    # Check: Chưa sử dụng / chưa mở seal
    unused_keywords = ["chưa kích hoạt", "chưa sử dụng", "chưa dùng",
                       "chưa mở seal", "sealed", "unused"]
    if any(kw in task_lower or kw in ctx_lower for kw in unused_keywords):
        conditions_met.append("Sản phẩm chưa được sử dụng/mở seal")

    return {
        "conditions_met": conditions_met,
        "conditions_missing": conditions_missing,
        "all_met": len(conditions_missing) == 0 and len(conditions_met) >= 1,
    }


def _detect_temporal_scoping(task: str) -> str:
    """Kiểm tra temporal scoping — đơn hàng trước 01/02/2026 dùng policy v3."""
    task_lower = task.lower()
    temporal_markers = [
        "31/01", "30/01", "29/01", "trước 01/02", "trước 1/2",
        "tháng 1/2026", "01/2026", "trước ngày có hiệu lực",
        "2025", "tháng 12", "tháng 11",
    ]
    for marker in temporal_markers:
        if marker in task_lower:
            return (
                "⚠️ Đơn hàng đặt trước 01/02/2026 áp dụng chính sách hoàn tiền "
                "phiên bản 3 (không có trong tài liệu hiện tại). "
                "Cần escalate để xác nhận chính sách áp dụng."
            )
    return ""


def _detect_access_control(task: str) -> dict | None:
    """Phát hiện yêu cầu liên quan đến cấp quyền truy cập."""
    task_lower = task.lower()
    access_keywords = ["cấp quyền", "access level", "access", "quyền truy cập",
                       "level 1", "level 2", "level 3", "level 4",
                       "phê duyệt", "approval"]

    if not any(kw in task_lower for kw in access_keywords):
        return None

    # Detect access level
    detected_level = None
    for level in [4, 3, 2, 1]:  # Check từ cao xuống
        if f"level {level}" in task_lower:
            detected_level = level
            break

    # Detect emergency
    is_emergency = any(
        kw in task_lower
        for kw in ["khẩn cấp", "emergency", "p1", "sự cố", "2am", "incident"]
    )

    if detected_level and detected_level in ACCESS_LEVELS:
        level_info = ACCESS_LEVELS[detected_level]
        return {
            "type": "access_control",
            "access_level": detected_level,
            "level_name": level_info["name"],
            "required_approvers": level_info["approvers"],
            "processing_days": level_info["processing_days"],
            "is_emergency": is_emergency,
            "emergency_bypass": level_info["emergency_bypass"],
            "source": "access_control_sop.txt",
        }

    return {
        "type": "access_control",
        "access_level": None,
        "note": "Không xác định được level cụ thể. Cần thêm thông tin.",
        "source": "access_control_sop.txt",
    }


def analyze_policy(task: str, chunks: list) -> dict:
    """
    Phân tích policy dựa trên task và context chunks.

    Xử lý 2 domain chính:
    1. Refund policy (policy_refund_v4.txt)
    2. Access control (access_control_sop.txt)

    Returns:
        dict with: policy_applies, policy_name, exceptions_found,
                   source, policy_version_note, explanation,
                   refund_eligibility, access_control_info
    """
    task_lower = task.lower()
    context_text = " ".join([c.get("text", "") for c in chunks])

    # ── 1. Xác định domain ──
    is_refund = any(
        kw in task_lower
        for kw in ["hoàn tiền", "refund", "flash sale", "license", "trả hàng"]
    )
    is_access = any(
        kw in task_lower
        for kw in ["cấp quyền", "access", "quyền truy cập", "level"]
    )

    # ── 2. Phân tích Refund Policy ──
    exceptions_found = []
    refund_eligibility = {}
    policy_name = "unknown"
    explanation_parts = []

    if is_refund:
        policy_name = "refund_policy_v4"
        exceptions_found = _detect_refund_exceptions(task, context_text)
        refund_eligibility = _check_refund_eligibility(task, context_text)

        if exceptions_found:
            explanation_parts.append(
                f"Phát hiện {len(exceptions_found)} ngoại lệ: "
                + ", ".join(e["type"] for e in exceptions_found)
            )
        elif refund_eligibility.get("all_met"):
            explanation_parts.append(
                "Đủ điều kiện hoàn tiền theo Điều 2 chính sách v4."
            )
        else:
            explanation_parts.append(
                "Không tìm thấy ngoại lệ, nhưng cần xác nhận thêm điều kiện."
            )

    # ── 3. Phân tích Access Control ──
    access_control_info = None
    if is_access:
        policy_name = "access_control_sop"
        access_control_info = _detect_access_control(task)
        if access_control_info:
            level = access_control_info.get("access_level")
            if level:
                explanation_parts.append(
                    f"Yêu cầu cấp quyền Level {level} "
                    f"({access_control_info.get('level_name', '')}). "
                    f"Cần {len(access_control_info.get('required_approvers', []))} "
                    f"người phê duyệt."
                )
                if access_control_info.get("is_emergency"):
                    if access_control_info.get("emergency_bypass"):
                        explanation_parts.append(
                            "Trường hợp khẩn cấp: CÓ THỂ cấp tạm thời "
                            "(max 24h, cần Tech Lead phê duyệt bằng lời)."
                        )
                    else:
                        explanation_parts.append(
                            f"Trường hợp khẩn cấp: Level {level} KHÔNG có "
                            "emergency bypass. Phải follow quy trình chuẩn."
                        )

    # ── 4. Multi-domain: cả refund + access ──
    if is_refund and is_access:
        policy_name = "refund_policy_v4 + access_control_sop"

    # ── 5. Default nếu không match domain nào ──
    if not is_refund and not is_access:
        policy_name = "general_lookup"
        explanation_parts.append(
            "Không phát hiện policy cụ thể (refund/access). "
            "Trả về kết quả dựa trên context."
        )

    # ── 6. Temporal scoping ──
    policy_version_note = _detect_temporal_scoping(task)
    if policy_version_note:
        explanation_parts.append(policy_version_note)

    # ── 7. Xác định policy_applies ──
    policy_applies = len(exceptions_found) == 0

    sources = list({c.get("source", "unknown") for c in chunks if c})

    return {
        "policy_applies": policy_applies,
        "policy_name": policy_name,
        "exceptions_found": exceptions_found,
        "source": sources,
        "policy_version_note": policy_version_note,
        "explanation": " | ".join(explanation_parts) if explanation_parts else "No analysis.",
        "refund_eligibility": refund_eligibility,
        "access_control_info": access_control_info,
    }


# ─────────────────────────────────────────────
# Worker Entry Point
# ─────────────────────────────────────────────

def run(state: dict) -> dict:
    """
    Worker entry point — gọi từ graph.py.

    Args:
        state: AgentState dict

    Returns:
        Updated AgentState với policy_result và mcp_tools_used
    """
    task = state.get("task", "")
    chunks = state.get("retrieved_chunks", [])
    needs_tool = state.get("needs_tool", False)

    state.setdefault("workers_called", [])
    state.setdefault("history", [])
    state.setdefault("mcp_tools_used", [])

    state["workers_called"].append(WORKER_NAME)

    worker_io = {
        "worker": WORKER_NAME,
        "input": {
            "task": task,
            "chunks_count": len(chunks),
            "needs_tool": needs_tool,
        },
        "output": None,
        "error": None,
    }

    try:
        # Step 1: Nếu chưa có chunks và cần tool → gọi MCP search_kb
        if not chunks and needs_tool:
            mcp_result = _call_mcp_tool("search_kb", {"query": task, "top_k": 3})
            state["mcp_tools_used"].append(mcp_result)
            state["history"].append(f"[{WORKER_NAME}] called MCP search_kb")

            if mcp_result.get("output") and mcp_result["output"].get("chunks"):
                chunks = mcp_result["output"]["chunks"]
                state["retrieved_chunks"] = chunks

        # Step 2: Phân tích policy
        policy_result = analyze_policy(task, chunks)
        state["policy_result"] = policy_result

        # Step 3: Gọi MCP tools bổ sung nếu cần
        task_lower = task.lower()

        # 3a: Ticket info cho SLA/ticket queries
        if needs_tool and any(kw in task_lower for kw in ["ticket", "p1", "jira"]):
            mcp_result = _call_mcp_tool(
                "get_ticket_info", {"ticket_id": "P1-LATEST"}
            )
            state["mcp_tools_used"].append(mcp_result)
            state["history"].append(f"[{WORKER_NAME}] called MCP get_ticket_info")

        # 3b: Access permission cho access control queries
        if needs_tool and policy_result.get("access_control_info"):
            ac_info = policy_result["access_control_info"]
            if ac_info.get("access_level"):
                mcp_result = _call_mcp_tool(
                    "check_access_permission",
                    {
                        "access_level": ac_info["access_level"],
                        "requester_role": "employee",
                        "is_emergency": ac_info.get("is_emergency", False),
                    },
                )
                state["mcp_tools_used"].append(mcp_result)
                state["history"].append(
                    f"[{WORKER_NAME}] called MCP check_access_permission "
                    f"(level={ac_info['access_level']})"
                )
                # Enrich policy_result với MCP output
                if mcp_result.get("output") and not mcp_result["output"].get("error"):
                    policy_result["access_control_info"]["mcp_result"] = (
                        mcp_result["output"]
                    )

        # Step 4: Log worker output
        worker_io["output"] = {
            "policy_applies": policy_result["policy_applies"],
            "policy_name": policy_result["policy_name"],
            "exceptions_count": len(policy_result.get("exceptions_found", [])),
            "has_access_control": policy_result.get("access_control_info") is not None,
            "mcp_calls": len(state["mcp_tools_used"]),
            "explanation": policy_result.get("explanation", ""),
        }
        state["history"].append(
            f"[{WORKER_NAME}] policy_applies={policy_result['policy_applies']}, "
            f"policy={policy_result['policy_name']}, "
            f"exceptions={len(policy_result.get('exceptions_found', []))}, "
            f"mcp_calls={len(state['mcp_tools_used'])}"
        )

    except Exception as e:
        worker_io["error"] = {"code": "POLICY_CHECK_FAILED", "reason": str(e)}
        state["policy_result"] = {"error": str(e)}
        state["history"].append(f"[{WORKER_NAME}] ERROR: {e}")

    state.setdefault("worker_io_logs", []).append(worker_io)
    return state


# ─────────────────────────────────────────────
# Test độc lập
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Policy Tool Worker — Sprint 2 Standalone Test")
    print("=" * 60)

    test_cases = [
        {
            "name": "1. Flash Sale exception",
            "task": "Khách hàng Flash Sale yêu cầu hoàn tiền vì sản phẩm lỗi — được không?",
            "retrieved_chunks": [
                {
                    "text": "Ngoại lệ: Đơn hàng đã áp dụng mã giảm giá đặc biệt "
                            "theo chương trình khuyến mãi Flash Sale không được hoàn tiền.",
                    "source": "policy_refund_v4.txt",
                    "score": 0.9,
                }
            ],
            "needs_tool": True,
        },
        {
            "name": "2. License key + activated",
            "task": "Khách hàng muốn hoàn tiền license key đã kích hoạt.",
            "retrieved_chunks": [
                {
                    "text": "Sản phẩm thuộc danh mục hàng kỹ thuật số "
                            "(license key, subscription) không được hoàn tiền.",
                    "source": "policy_refund_v4.txt",
                    "score": 0.88,
                }
            ],
            "needs_tool": False,
        },
        {
            "name": "3. Eligible refund",
            "task": "Khách hàng yêu cầu hoàn tiền trong 5 ngày, sản phẩm lỗi, "
                    "chưa kích hoạt.",
            "retrieved_chunks": [
                {
                    "text": "Yêu cầu trong 7 ngày làm việc, sản phẩm lỗi "
                            "nhà sản xuất, chưa dùng.",
                    "source": "policy_refund_v4.txt",
                    "score": 0.85,
                }
            ],
            "needs_tool": False,
        },
        {
            "name": "4. Access Level 3 emergency",
            "task": "Cần cấp quyền Level 3 để khắc phục P1 khẩn cấp. "
                    "Quy trình là gì?",
            "retrieved_chunks": [
                {
                    "text": "Level 3 — Elevated Access: Phê duyệt: "
                            "Line Manager + IT Admin + IT Security.",
                    "source": "access_control_sop.txt",
                    "score": 0.91,
                }
            ],
            "needs_tool": True,
        },
        {
            "name": "5. Temporal scoping (trước 01/02)",
            "task": "Đơn hàng đặt 30/01/2026, khách yêu cầu hoàn tiền. "
                    "Áp dụng chính sách nào?",
            "retrieved_chunks": [
                {
                    "text": "Chính sách này áp dụng cho tất cả các đơn hàng "
                            "kể từ ngày 01/02/2026. Các đơn hàng đặt trước ngày "
                            "có hiệu lực sẽ áp dụng theo chính sách hoàn tiền "
                            "phiên bản 3.",
                    "source": "policy_refund_v4.txt",
                    "score": 0.87,
                }
            ],
            "needs_tool": False,
        },
    ]

    for tc in test_cases:
        print(f"\n{'─' * 50}")
        print(f"▶ {tc['name']}")
        print(f"  Task: {tc['task'][:70]}...")

        state = {
            "task": tc["task"],
            "retrieved_chunks": tc["retrieved_chunks"],
            "needs_tool": tc.get("needs_tool", False),
        }
        result = run(state)

        pr = result.get("policy_result", {})
        print(f"  policy_applies : {pr.get('policy_applies')}")
        print(f"  policy_name    : {pr.get('policy_name')}")
        print(f"  explanation    : {pr.get('explanation', '')[:80]}...")

        if pr.get("exceptions_found"):
            for ex in pr["exceptions_found"]:
                print(f"    ⚠️ {ex['type']}: {ex['rule'][:60]}...")

        if pr.get("access_control_info"):
            ac = pr["access_control_info"]
            print(f"    🔐 Level {ac.get('access_level')}: "
                  f"approvers={ac.get('required_approvers')}, "
                  f"emergency={ac.get('is_emergency')}")

        if pr.get("policy_version_note"):
            print(f"    📅 {pr['policy_version_note'][:70]}...")

        print(f"  MCP calls      : {len(result.get('mcp_tools_used', []))}")

    print(f"\n{'=' * 60}")
    print("✅ policy_tool_worker Sprint 2 test done.")
