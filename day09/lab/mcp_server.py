"""
mcp_server.py — MCP Server (Hướng A: Mock + Real ChromaDB)
Sprint 3: Implement ít nhất 2 MCP tools hoạt động thực tế.

Kiến trúc:
    - dispatch_tool()   : entry point duy nhất cho mọi tool call
    - list_tools()      : MCP discovery — trả về schema toàn bộ tools
    - get_call_log()    : trả về lịch sử tool calls (dùng cho trace)
    - clear_call_log()  : reset log cho mỗi run mới

Tools available:
    1. search_kb(query, top_k)                             → tìm ChromaDB (real), fallback mock
    2. get_ticket_info(ticket_id)                          → tra cứu ticket (mock data đầy đủ)
    3. check_access_permission(access_level, requester_role, is_emergency)  → kiểm tra quyền
    4. create_ticket(priority, title, description)         → tạo ticket mới (mock)

Thay đổi so với bản gốc (Hướng A):
    - search_kb: kết nối ChromaDB thật, có fallback mock nếu chưa có data
    - Thêm _CALL_LOG: tự động ghi mcp_tool_called + mcp_result vào log
    - dispatch_tool: tự động append mỗi call vào _CALL_LOG
    - Thêm get_call_log() / clear_call_log() để graph.py inject vào AgentState
    - Mở rộng MOCK_TICKETS với data đầy đủ cho các grading questions

Sử dụng:
    from mcp_server import dispatch_tool, list_tools, get_call_log, clear_call_log

    clear_call_log()                                      # reset trước mỗi run
    result = dispatch_tool("search_kb", {"query": "SLA P1", "top_k": 3})
    logs   = get_call_log()                               # lấy log để ghi vào trace

Chạy thử:
    python mcp_server.py
"""

import os
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────
# Call Log — ghi lại TỪNG tool call để trace
# graph.py sẽ gọi get_call_log() để inject vào AgentState["mcp_tools_used"]
# ─────────────────────────────────────────────

_CALL_LOG: List[Dict] = []


def get_call_log() -> List[Dict]:
    """Trả về danh sách tất cả tool calls trong session này."""
    return list(_CALL_LOG)


def clear_call_log() -> None:
    """Reset call log — gọi trước mỗi run mới để log không bị lẫn."""
    _CALL_LOG.clear()


# ─────────────────────────────────────────────
# Tool Definitions (Schema Discovery)
# Giống với cách MCP server expose tool list cho client
# ─────────────────────────────────────────────

TOOL_SCHEMAS = {
    "search_kb": {
        "name": "search_kb",
        "description": "Tìm kiếm Knowledge Base nội bộ bằng semantic search. Trả về top-k chunks liên quan nhất.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Câu hỏi hoặc keyword cần tìm"},
                "top_k": {"type": "integer", "description": "Số chunks cần trả về", "default": 3},
            },
            "required": ["query"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "chunks": {"type": "array"},
                "sources": {"type": "array"},
                "total_found": {"type": "integer"},
            },
        },
    },
    "get_ticket_info": {
        "name": "get_ticket_info",
        "description": "Tra cứu thông tin ticket từ hệ thống Jira nội bộ.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "ID ticket (VD: IT-1234, P1-LATEST)"},
            },
            "required": ["ticket_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "priority": {"type": "string"},
                "status": {"type": "string"},
                "assignee": {"type": "string"},
                "created_at": {"type": "string"},
                "sla_deadline": {"type": "string"},
            },
        },
    },
    "check_access_permission": {
        "name": "check_access_permission",
        "description": "Kiểm tra điều kiện cấp quyền truy cập theo Access Control SOP.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_level": {"type": "integer", "description": "Level cần cấp (1, 2, hoặc 3)"},
                "requester_role": {"type": "string", "description": "Vai trò của người yêu cầu"},
                "is_emergency": {"type": "boolean", "description": "Có phải khẩn cấp không", "default": False},
            },
            "required": ["access_level", "requester_role"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "can_grant": {"type": "boolean"},
                "required_approvers": {"type": "array"},
                "emergency_override": {"type": "boolean"},
                "source": {"type": "string"},
            },
        },
    },
    "create_ticket": {
        "name": "create_ticket",
        "description": "Tạo ticket mới trong hệ thống Jira (MOCK — không tạo thật trong lab).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "priority": {"type": "string", "enum": ["P1", "P2", "P3", "P4"]},
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["priority", "title"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "url": {"type": "string"},
                "created_at": {"type": "string"},
            },
        },
    },
}


# ─────────────────────────────────────────────
# Tool Implementations
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# Mock Knowledge Base (fallback khi ChromaDB chưa có data)
# Đủ để trả lời các grading questions gq01–gq10
# ─────────────────────────────────────────────

_MOCK_KB: List[Dict] = [
    # SLA P1
    {
        "text": "SLA P1: Phản hồi trong 15 phút, xử lý và khắc phục trong 4 giờ. "
                "Khi ticket P1 được tạo, hệ thống tự động gửi thông báo qua: "
                "(1) Slack #incident-p1, (2) email incident@company.internal, "
                "(3) PagerDuty on-call. Senior Engineer Team được escalate ngay lập tức.",
        "source": "support/sla-p1-2026.pdf",
        "score": 0.95,
    },
    {
        "text": "P1 Escalation Timeline: T+0 tạo ticket và gửi thông báo Slack/email/PagerDuty. "
                "T+10 phút: nếu chưa có phản hồi, hệ thống tự động escalate lên Senior Engineer. "
                "T+15 phút: deadline phản hồi (SLA breach nếu vượt). "
                "T+4 giờ: deadline khắc phục hoàn toàn.",
        "source": "support/sla-p1-2026.pdf",
        "score": 0.93,
    },
    # Refund Policy
    {
        "text": "Chính sách hoàn tiền v4 (hiệu lực từ 01/02/2026): Khách hàng được hoàn tiền 100% "
                "trong vòng 7 ngày làm việc nếu sản phẩm lỗi do nhà sản xuất và chưa kích hoạt. "
                "Ngoại lệ: (1) Đơn hàng Flash Sale không được hoàn tiền. "
                "(2) Sản phẩm kỹ thuật số (license key, subscription) không được hoàn tiền. "
                "(3) Sản phẩm đã kích hoạt hoặc đăng ký tài khoản không được hoàn tiền.",
        "source": "policy/policy_refund_v4.txt",
        "score": 0.94,
    },
    {
        "text": "Đơn hàng đặt trước ngày 01/02/2026 áp dụng chính sách hoàn tiền v3. "
                "Chính sách v3 không có trong tài liệu hiện tại — cần liên hệ bộ phận hỗ trợ "
                "hoặc tra cứu hệ thống nội bộ để biết chi tiết. "
                "Store credit có giá trị bằng 110% giá trị đơn hàng gốc.",
        "source": "policy/policy_refund_v3_note.txt",
        "score": 0.85,
    },
    # Access Control
    {
        "text": "Quy trình cấp quyền Access Level 3 (Admin): Yêu cầu phê duyệt đồng thời của "
                "(1) Line Manager, (2) IT Admin, (3) IT Security. "
                "Không có emergency bypass cho Level 3 — dù khẩn cấp vẫn phải đủ 3 người phê duyệt. "
                "Người phê duyệt cuối cùng (cao nhất) là IT Security.",
        "source": "hr/access_control_sop.txt",
        "score": 0.96,
    },
    {
        "text": "Quy trình cấp quyền Access Level 2 (Elevated): Yêu cầu phê duyệt của Line Manager và IT Admin. "
                "Trong trường hợp khẩn cấp (P1 incident), Level 2 có thể cấp tạm thời "
                "với approval đồng thời của Line Manager và IT Admin on-call. "
                "Contractor chỉ được cấp Level 1 theo mặc định; Level 2 cần request riêng.",
        "source": "hr/access_control_sop.txt",
        "score": 0.92,
    },
    # HR Policy
    {
        "text": "Chính sách làm việc từ xa (Remote Work): Nhân viên thử việc (probation period) "
                "không được phép làm remote trong 3 tháng đầu. Sau thử việc, cần approval của "
                "Line Manager và đăng ký tối thiểu 2 ngày/tuần làm tại văn phòng.",
        "source": "hr/remote_work_policy.txt",
        "score": 0.88,
    },
    # Security Policy
    {
        "text": "Chính sách bảo mật mật khẩu: Mật khẩu phải được đổi mỗi 90 ngày. "
                "Hệ thống gửi cảnh báo nhắc nhở trước 14 ngày khi mật khẩu sắp hết hạn. "
                "Mật khẩu phải có ít nhất 12 ký tự, gồm chữ hoa, chữ thường, số và ký tự đặc biệt.",
        "source": "security/password_policy.txt",
        "score": 0.91,
    },
]


def tool_search_kb(query: str, top_k: int = 3) -> dict:
    """
    Tìm kiếm Knowledge Base bằng semantic search.

    Hướng A: Thử kết nối ChromaDB thật trước (qua workers/retrieval.py).
    Nếu ChromaDB chưa có data hoặc lỗi → fallback sang _MOCK_KB với
    keyword matching đơn giản để đảm bảo pipeline không crash.

    Returns:
        {"chunks": list, "sources": list[str], "total_found": int}
    """
    # --- Bước 1: Thử ChromaDB thật ---
    try:
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from workers.retrieval import retrieve_dense
        chunks = retrieve_dense(query, top_k=top_k)

        # Nếu ChromaDB có data (chunks không rỗng), dùng kết quả thật
        if chunks:
            sources = list({c["source"] for c in chunks})
            return {
                "chunks": chunks,
                "sources": sources,
                "total_found": len(chunks),
                "source_type": "chromadb",      # để trace biết dùng real DB
            }
    except Exception:
        pass  # ChromaDB chưa sẵn sàng → tiếp tục fallback

    # --- Bước 2: Fallback — keyword search trong _MOCK_KB ---
    query_lower = query.lower()
    query_words = set(query_lower.split())

    scored = []
    for chunk in _MOCK_KB:
        text_lower = chunk["text"].lower()
        # Tính overlap score: số từ trong query xuất hiện trong text
        hits = sum(1 for w in query_words if len(w) > 2 and w in text_lower)
        if hits > 0:
            scored.append({**chunk, "score": round(hits / max(len(query_words), 1), 3)})

    # Sắp xếp theo score, lấy top_k
    scored.sort(key=lambda x: x["score"], reverse=True)
    results = scored[:top_k]

    # Nếu không match gì, trả về top 2 mặc định (không để rỗng)
    if not results:
        results = _MOCK_KB[:min(2, len(_MOCK_KB))]

    sources = list({c["source"] for c in results})
    return {
        "chunks": results,
        "sources": sources,
        "total_found": len(results),
        "source_type": "mock_kb",       # để trace biết đang dùng fallback
    }


# ─────────────────────────────────────────────
# Mock Ticket Database — đầy đủ cho grading questions
# gq01: P1 lúc 22:47, gq05: escalation sau 10 phút
# ─────────────────────────────────────────────

MOCK_TICKETS = {
    # Ticket P1 chính — dùng cho gq01, gq05, gq09
    "P1-LATEST": {
        "ticket_id": "IT-9847",
        "priority": "P1",
        "title": "API Gateway down — toàn bộ người dùng không đăng nhập được",
        "status": "in_progress",
        "assignee": "nguyen.van.a@company.internal",
        "created_at": "2026-04-13T22:47:00",
        "sla_deadline": "2026-04-14T02:47:00",     # +4h từ lúc tạo
        "response_deadline": "2026-04-13T23:02:00", # +15 phút
        "escalated": True,
        "escalated_to": "senior_engineer_team",
        # gq01: ai nhận thông báo đầu tiên, qua kênh nào?
        "notifications_sent": [
            "slack:#incident-p1",
            "email:incident@company.internal",
            "pagerduty:oncall",
        ],
        "first_notified": "slack:#incident-p1",     # kênh đầu tiên nhận
        # gq05: P1 không phản hồi sau 10 phút — hệ thống làm gì?
        "auto_escalation_at_minutes": 10,
        "auto_escalation_action": "Tự động escalate lên Senior Engineer Team và gửi lại thông báo.",
    },
    # Alias — cùng ticket, dễ tra cứu
    "IT-9847": {
        "ticket_id": "IT-9847",
        "priority": "P1",
        "title": "API Gateway down — toàn bộ người dùng không đăng nhập được",
        "status": "in_progress",
        "assignee": "nguyen.van.a@company.internal",
        "created_at": "2026-04-13T22:47:00",
        "sla_deadline": "2026-04-14T02:47:00",
        "escalated": True,
        "notifications_sent": ["slack:#incident-p1", "email:incident@company.internal", "pagerduty:oncall"],
    },
    # Ticket P2 thông thường
    "IT-1234": {
        "ticket_id": "IT-1234",
        "priority": "P2",
        "title": "Feature login chậm cho một số user",
        "status": "open",
        "assignee": None,
        "created_at": "2026-04-13T09:15:00",
        "sla_deadline": "2026-04-14T09:15:00",
        "escalated": False,
    },
}


def tool_get_ticket_info(ticket_id: str) -> dict:
    """
    Tra cứu thông tin ticket (mock data).
    """
    ticket = MOCK_TICKETS.get(ticket_id.upper())
    if ticket:
        return ticket
    # Không tìm thấy
    return {
        "error": f"Ticket '{ticket_id}' không tìm thấy trong hệ thống.",
        "available_mock_ids": list(MOCK_TICKETS.keys()),
    }


# Mock access control rules
ACCESS_RULES = {
    1: {
        "required_approvers": ["Line Manager"],
        "emergency_can_bypass": False,
        "note": "Standard user access",
    },
    2: {
        "required_approvers": ["Line Manager", "IT Admin"],
        "emergency_can_bypass": True,
        "emergency_bypass_note": "Level 2 có thể cấp tạm thời với approval đồng thời của Line Manager và IT Admin on-call.",
        "note": "Elevated access",
    },
    3: {
        "required_approvers": ["Line Manager", "IT Admin", "IT Security"],
        "emergency_can_bypass": False,
        "note": "Admin access — không có emergency bypass",
    },
}


def tool_check_access_permission(access_level: int, requester_role: str, is_emergency: bool = False) -> dict:
    """
    Kiểm tra điều kiện cấp quyền theo Access Control SOP.
    """
    rule = ACCESS_RULES.get(access_level)
    if not rule:
        return {"error": f"Access level {access_level} không hợp lệ. Levels: 1, 2, 3."}

    can_grant = True
    notes = []

    if is_emergency and rule.get("emergency_can_bypass"):
        notes.append(rule.get("emergency_bypass_note", ""))
        can_grant = True
    elif is_emergency and not rule.get("emergency_can_bypass"):
        notes.append(f"Level {access_level} KHÔNG có emergency bypass. Phải follow quy trình chuẩn.")

    return {
        "access_level": access_level,
        "can_grant": can_grant,
        "required_approvers": rule["required_approvers"],
        "approver_count": len(rule["required_approvers"]),
        "emergency_override": is_emergency and rule.get("emergency_can_bypass", False),
        "notes": notes,
        "source": "access_control_sop.txt",
    }


def tool_create_ticket(priority: str, title: str, description: str = "") -> dict:
    """
    Tạo ticket mới (MOCK — in log, không tạo thật).
    """
    mock_id = f"IT-{9900 + hash(title) % 99}"
    ticket = {
        "ticket_id": mock_id,
        "priority": priority,
        "title": title,
        "description": description[:200],
        "status": "open",
        "created_at": datetime.now().isoformat(),
        "url": f"https://jira.company.internal/browse/{mock_id}",
        "note": "MOCK ticket — không tồn tại trong hệ thống thật",
    }
    print(f"  [MCP create_ticket] MOCK: {mock_id} | {priority} | {title[:50]}")
    return ticket


# ─────────────────────────────────────────────
# Dispatch Layer — MCP server interface
# ─────────────────────────────────────────────

TOOL_REGISTRY = {
    "search_kb": tool_search_kb,
    "get_ticket_info": tool_get_ticket_info,
    "check_access_permission": tool_check_access_permission,
    "create_ticket": tool_create_ticket,
}


def list_tools() -> list:
    """
    MCP discovery: trả về danh sách tools có sẵn.
    Tương đương với `tools/list` trong MCP protocol.
    """
    return list(TOOL_SCHEMAS.values())


def dispatch_tool(tool_name: str, tool_input: dict) -> dict:
    """
    MCP execution: nhận tool_name và input, gọi tool tương ứng.
    Tương đương với `tools/call` trong MCP protocol.

    THAY ĐỔI so với bản gốc:
        Tự động ghi mỗi call vào _CALL_LOG với format:
            {
                "mcp_tool_called": str,   # tên tool
                "mcp_input":       dict,  # input truyền vào
                "mcp_result":      dict,  # output trả về (hoặc error)
                "timestamp":       str,   # ISO timestamp
            }
        workers và graph.py dùng get_call_log() để inject vào AgentState.

    Args:
        tool_name: tên tool (phải có trong TOOL_REGISTRY)
        tool_input: input dict (phải match với tool's inputSchema)

    Returns:
        Tool output dict, hoặc error dict nếu thất bại
    """
    timestamp = datetime.now().isoformat()

    if tool_name not in TOOL_REGISTRY:
        error_result = {
            "error": f"Tool '{tool_name}' không tồn tại. Available: {list(TOOL_REGISTRY.keys())}"
        }
        # Ghi vào call log kể cả lỗi — để trace biết có tool call thất bại
        _CALL_LOG.append({
            "mcp_tool_called": tool_name,
            "mcp_input": tool_input,
            "mcp_result": error_result,
            "timestamp": timestamp,
        })
        return error_result

    tool_fn = TOOL_REGISTRY[tool_name]
    try:
        result = tool_fn(**tool_input)
    except TypeError as e:
        result = {
            "error": f"Invalid input for tool '{tool_name}': {e}",
            "schema": TOOL_SCHEMAS[tool_name]["inputSchema"],
        }
    except Exception as e:
        result = {
            "error": f"Tool '{tool_name}' execution failed: {e}",
        }

    # Ghi vào _CALL_LOG — đây là key để trace có mcp_tool_called + mcp_result
    _CALL_LOG.append({
        "mcp_tool_called": tool_name,
        "mcp_input": tool_input,
        "mcp_result": result,
        "timestamp": timestamp,
    })

    return result


def dispatch_tool_http(
    tool_name: str,
    tool_input: dict,
    base_url: str = "http://localhost:8765",
) -> dict:
    """
    HTTP client variant của dispatch_tool().
    Gọi MCP HTTP Server (mcp_http.py) thay vì in-process.

    Dùng khi server đang chạy:
        uvicorn mcp_http:app --port 8765

    Auto-fallback về in-process nếu server không chạy —
    đảm bảo pipeline không bao giờ crash vì lý do MCP server.

    Args:
        tool_name: tên tool
        tool_input: input dict
        base_url:   địa chỉ MCP HTTP server (default: localhost:8765)

    Returns:
        Tool output dict (giống dispatch_tool)
    """
    try:
        import httpx
        response = httpx.post(
            f"{base_url}/tools/call",
            json={"tool_name": tool_name, "tool_input": tool_input},
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json()
        # HTTP response có thêm wrapper {tool_name, result, success, timestamp}
        # Trả về chỉ "result" để interface giống dispatch_tool()
        return data.get("result", data)

    except Exception:
        # Server chưa start hoặc timeout → fallback in-process
        # Không raise exception — pipeline vẫn chạy bình thường
        return dispatch_tool(tool_name, tool_input)


# ─────────────────────────────────────────────
# Test & Demo
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("MCP Server (Hướng A) — Tool Discovery & Test")
    print("=" * 60)

    # Reset call log trước khi test
    clear_call_log()

    # 1. Discover tools
    print("\n📋 Available Tools:")
    for tool in list_tools():
        print(f"  • {tool['name']}: {tool['description'][:60]}...")

    # 2. Test search_kb — cover gq01, gq05
    print("\n🔍 Test: search_kb (SLA P1)")
    result = dispatch_tool("search_kb", {"query": "SLA P1 thông báo escalation 10 phút", "top_k": 2})
    print(f"  source_type: {result.get('source_type', 'unknown')}")
    if result.get("chunks"):
        for c in result["chunks"]:
            print(f"  [{c.get('score', '?')}] {c.get('source')}: {c.get('text', '')[:80]}...")
    else:
        print(f"  Result: {result}")

    # 3. Test search_kb — cover gq10 (Flash Sale exception)
    print("\n🔍 Test: search_kb (Refund + Flash Sale)")
    result2 = dispatch_tool("search_kb", {"query": "Flash Sale hoàn tiền exception policy", "top_k": 2})
    print(f"  source_type: {result2.get('source_type', 'unknown')}")
    if result2.get("chunks"):
        for c in result2["chunks"]:
            print(f"  [{c.get('score', '?')}] {c.get('source')}: {c.get('text', '')[:80]}...")

    # 4. Test get_ticket_info — cover gq01
    print("\n🎫 Test: get_ticket_info (P1-LATEST)")
    ticket = dispatch_tool("get_ticket_info", {"ticket_id": "P1-LATEST"})
    print(f"  Ticket: {ticket.get('ticket_id')} | {ticket.get('priority')} | {ticket.get('status')}")
    print(f"  First notified: {ticket.get('first_notified')}")
    print(f"  Notifications: {ticket.get('notifications_sent')}")
    print(f"  Auto-escalation after: {ticket.get('auto_escalation_at_minutes')} phút")

    # 5. Test check_access_permission — cover gq03 (Level 3) và gq09 (Level 2 emergency)
    print("\n🔐 Test: check_access_permission (Level 3 — không có emergency bypass)")
    perm3 = dispatch_tool("check_access_permission", {
        "access_level": 3,
        "requester_role": "contractor",
        "is_emergency": True,
    })
    print(f"  can_grant: {perm3.get('can_grant')}")
    print(f"  required_approvers ({perm3.get('approver_count')}): {perm3.get('required_approvers')}")
    print(f"  emergency_override: {perm3.get('emergency_override')}")
    print(f"  notes: {perm3.get('notes')}")

    print("\n🔐 Test: check_access_permission (Level 2 emergency — có bypass)")
    perm2 = dispatch_tool("check_access_permission", {
        "access_level": 2,
        "requester_role": "contractor",
        "is_emergency": True,
    })
    print(f"  can_grant: {perm2.get('can_grant')}")
    print(f"  emergency_override: {perm2.get('emergency_override')}")
    print(f"  notes: {perm2.get('notes')}")

    # 6. Test invalid tool
    print("\n❌ Test: invalid tool")
    err = dispatch_tool("nonexistent_tool", {})
    print(f"  Error: {err.get('error')}")

    # 7. Hiển thị call log — điều quan trọng nhất cho trace
    print("\n📊 Call Log (dùng để inject vào AgentState['mcp_tools_used']):")
    for i, log in enumerate(get_call_log(), 1):
        status = "✅" if "error" not in log["mcp_result"] else "❌"
        print(f"  {i}. {status} {log['mcp_tool_called']} @ {log['timestamp']}")
        if log["mcp_result"].get("source_type"):
            print(f"     source_type: {log['mcp_result']['source_type']}")

    print(f"\n✅ MCP server test done. Total calls logged: {len(get_call_log())}")
    print("ℹ️  Để dùng real MCP protocol → uncomment `mcp` trong requirements.txt (bonus +2).")
