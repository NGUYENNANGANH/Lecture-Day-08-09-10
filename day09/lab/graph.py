"""
graph.py — Supervisor Orchestrator
Sprint 1: Implement AgentState, supervisor_node, route_decision và kết nối graph.

Kiến trúc:
    Input → Supervisor → [retrieval_worker | policy_tool_worker | human_review] → synthesis → Output

Chạy thử:
    python graph.py
"""

import json
import os
import time
from datetime import datetime
from typing import Literal, Optional, TypedDict
from mcp_server import clear_call_log, get_call_log

# LangGraph library
from langgraph.graph import END, StateGraph

# ─────────────────────────────────────────────
# 1. Shared State
# ─────────────────────────────────────────────


class AgentState(TypedDict):
    task: str
    route_reason: str
    risk_high: bool
    needs_tool: bool
    hitl_triggered: bool
    retrieved_chunks: list
    retrieved_sources: list
    policy_result: dict
    mcp_tools_used: list
    final_answer: str
    sources: list
    confidence: float
    history: list
    workers_called: list
    supervisor_route: str
    latency_ms: Optional[int]
    run_id: str
    worker_io_logs: list


def make_initial_state(task: str) -> AgentState:
    return {
        "task": task,
        "route_reason": "",
        "risk_high": False,
        "needs_tool": False,
        "hitl_triggered": False,
        "retrieved_chunks": [],
        "retrieved_sources": [],
        "policy_result": {},
        "mcp_tools_used": [],
        "final_answer": "",
        "sources": [],
        "confidence": 0.0,
        "history": [],
        "workers_called": [],
        "supervisor_route": "",
        "latency_ms": None,
        "run_id": f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "worker_io_logs": [],
    }


# ─────────────────────────────────────────────
# 2. Supervisor Node (Routing Logic chuẩn hợp đồng)
# ─────────────────────────────────────────────


def supervisor_node(state: AgentState) -> AgentState:
    task = state["task"].lower()
    state["history"].append(f"[supervisor] received task: {state['task'][:80]}")

    # Từ khóa định tuyến theo worker_contracts.yaml
    policy_keywords = [
        "hoàn tiền",
        "refund",
        "flash sale",
        "license",
        "cấp quyền",
        "access level",
    ]
    retrieval_keywords = ["p1", "sla", "ticket", "escalation", "sự cố"]
    risk_keywords = ["emergency", "khẩn cấp", "2am", "err-"]

    # Mặc định
    route = "retrieval_worker"
    route_reason = "default fallback route -> retrieval_worker."
    needs_tool = False
    risk_high = False

    # Kiểm tra risk
    if any(kw in task for kw in risk_keywords):
        risk_high = True

    # Logic định tuyến
    if any(kw in task for kw in policy_keywords):
        route = "policy_tool_worker"
        needs_tool = True
        route_reason = (
            f"Task contains policy/access keywords -> policy_tool_worker "
            f"[MCP: will use dispatch_tool(search_kb + check_access_permission)]"
        )
    elif any(kw in task for kw in retrieval_keywords):
        route = "retrieval_worker"
        route_reason = (
            f"Task contains retrieval keywords (P1/SLA/Ticket) -> retrieval_worker "
            f"[MCP: not needed, direct ChromaDB retrieval]"
        )

    # Override: Mã lỗi không rõ + risk_high -> HITL
    if "err-" in task and risk_high:
        route = "human_review"
        needs_tool = False
        route_reason = (
            "Unknown error code detected + high risk -> human_review "
            "[MCP: suspended, awaiting human approval]"
        )

    # Cập nhật trạng thái
    state["supervisor_route"] = route
    state["route_reason"] = route_reason
    state["needs_tool"] = needs_tool
    state["risk_high"] = risk_high
    state["history"].append(f"[supervisor] route={route} reason={route_reason}")

    return state


# ─────────────────────────────────────────────
# 3. Route Decision (Conditional Edge)
# ─────────────────────────────────────────────


def route_decision(state: AgentState) -> str:
    """Trả về tên worker tiếp theo từ supervisor_route."""
    return state.get("supervisor_route", "retrieval_worker")


# ─────────────────────────────────────────────
# 4. Human Review Node
# ─────────────────────────────────────────────


def human_review_node(state: AgentState) -> AgentState:
    state["hitl_triggered"] = True
    state["history"].append("[human_review] HITL triggered — awaiting human input")
    state["workers_called"].append("human_review")

    print(
        f"\n⚠️  HITL TRIGGERED | Task: {state['task']} | Action: Auto-approving in lab mode\n"
    )

    # Ép luồng đi tiếp về retrieval sau khi approve
    state["supervisor_route"] = "retrieval_worker"
    state["route_reason"] += " | human approved -> retrieval"
    return state


# ─────────────────────────────────────────────
# 5. Worker Nodes (Đã mở comment để gọi Worker thật)
# ─────────────────────────────────────────────

from workers.policy_tool import run as policy_tool_run
from workers.retrieval import run as retrieval_run
from workers.synthesis import run as synthesis_run


def retrieval_worker_node(state: AgentState) -> AgentState:
    return retrieval_run(state)


def policy_tool_worker_node(state: AgentState) -> AgentState:
    # Policy thường cần context, nên ta lấy document trước nếu chưa có
    if not state.get("retrieved_chunks"):
        state = retrieval_run(state)
    return policy_tool_run(state)


def synthesis_worker_node(state: AgentState) -> AgentState:
    return synthesis_run(state)


# ─────────────────────────────────────────────
# 6. Build Graph (Kiến trúc LangGraph đã được sửa lỗi)
# ─────────────────────────────────────────────


def build_graph():
    # Khởi tạo Graph với cấu trúc State
    workflow = StateGraph(AgentState)

    # 1. Add Nodes
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("retrieval_worker", retrieval_worker_node)
    workflow.add_node("policy_tool_worker", policy_tool_worker_node)
    workflow.add_node("human_review", human_review_node)
    workflow.add_node("synthesis", synthesis_worker_node)

    # 2. Set Entry Point
    workflow.set_entry_point("supervisor")

    # 3. Add Conditional Edges từ Supervisor
    workflow.add_conditional_edges(
        "supervisor",
        route_decision,
        {
            "retrieval_worker": "retrieval_worker",
            "policy_tool_worker": "policy_tool_worker",
            "human_review": "human_review",
        },
    )

    # 4. Normal Edges nối về Synthesis
    workflow.add_edge("retrieval_worker", "synthesis")
    workflow.add_edge("policy_tool_worker", "synthesis")
    workflow.add_edge(
        "human_review", "retrieval_worker"
    )  # Review xong thì đi kiếm context

    # 5. Đóng Graph
    workflow.add_edge("synthesis", END)

    return workflow.compile()


# ─────────────────────────────────────────────
# 7. Public API
# ─────────────────────────────────────────────

_graph = build_graph()


def run_graph(task: str) -> AgentState:
    clear_call_log()           # reset trước mỗi run
    state = make_initial_state(task)
    start_time = time.time()

    # Chạy LangGraph
    result = _graph.invoke(state)
    result["mcp_tools_used"] = get_call_log()  # inject vào trace

    result["latency_ms"] = int((time.time() - start_time) * 1000)
    result["history"].append(f"[graph] completed in {result['latency_ms']}ms")
    return result


def save_trace(state: AgentState, output_dir: str = "./artifacts/traces") -> str:
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{output_dir}/{state['run_id']}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return filename


# ─────────────────────────────────────────────
# 8. Manual Test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Day 09 Lab — Supervisor-Worker Graph (LangGraph Fixed)")
    print("=" * 60)

    test_queries = [
        "SLA xử lý ticket P1 là bao lâu?",
        "Khách hàng Flash Sale yêu cầu hoàn tiền vì sản phẩm lỗi — được không?",
        "Cần cấp quyền Level 3 để khắc phục P1 khẩn cấp. Quy trình là gì?",
    ]

    for query in test_queries:
        print(f"\n▶ Query: {query}")
        result = run_graph(query)
        print(f"  Route   : {result['supervisor_route']}")
        print(f"  Reason  : {result['route_reason']}")
        print(f"  Workers : {result['workers_called']}")
        print(f"  Answer  : {result['final_answer'][:100]}...")
        print(f"  Confidence: {result['confidence']}")
        print(f"  Latency : {result['latency_ms']}ms")
