"""
mcp_http.py — MCP HTTP Server (Advanced Level · Bonus +2)
Sprint 3: Wrap dispatch_tool() thành REST API theo chuẩn MCP-over-HTTP.

Tại sao file này tồn tại:
    mcp_server.py (Standard) gọi tools qua in-process function call.
    File này nâng lên Advanced bằng cách expose CÙNG tools qua HTTP,
    biến chúng thành MCP server thật mà bất kỳ client nào cũng gọi được.

Endpoints:
    GET  /health               → health check (grader dùng để verify server)
    GET  /tools/list           → MCP discovery — trả về toàn bộ tool schemas
    POST /tools/call           → MCP execution — gọi tool và trả về kết quả
    GET  /call-log             → xem toàn bộ call log của session
    DELETE /call-log           → reset call log (dùng trước mỗi grading run)

Chạy server (Terminal riêng):
    uvicorn mcp_http:app --host 0.0.0.0 --port 8765 --reload

Test nhanh:
    curl http://localhost:8765/health
    curl http://localhost:8765/tools/list
    curl -X POST http://localhost:8765/tools/call \\
         -H "Content-Type: application/json" \\
         -d '{"tool_name": "search_kb", "tool_input": {"query": "SLA P1", "top_k": 2}}'
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import uvicorn

# Import từ mcp_server.py hiện tại — không sửa gì ở đó
from mcp_server import dispatch_tool, list_tools, get_call_log, clear_call_log

# ─────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────

app = FastAPI(
    title="Day09 MCP HTTP Server",
    description=(
        "MCP-over-HTTP wrapper cho Day 09 multi-agent orchestration lab.\n\n"
        "Implements MCP tool discovery (`/tools/list`) và execution (`/tools/call`) "
        "qua REST API, cho phép bất kỳ HTTP client nào gọi tools mà không cần "
        "import trực tiếp."
    ),
    version="1.0.0",
    docs_url="/docs",   # Swagger UI tại http://localhost:8765/docs
)


# ─────────────────────────────────────────────
# Request / Response Schemas (Pydantic)
# ─────────────────────────────────────────────

class ToolCallRequest(BaseModel):
    """Body cho POST /tools/call."""
    tool_name: str
    tool_input: Dict[str, Any] = {}

    model_config = {
        "json_schema_extra": {
            "example": {
                "tool_name": "search_kb",
                "tool_input": {"query": "SLA P1 escalation", "top_k": 3},
            }
        }
    }


class ToolCallResponse(BaseModel):
    """Response từ POST /tools/call."""
    tool_name: str
    result: Dict[str, Any]
    success: bool
    timestamp: str


class HealthResponse(BaseModel):
    status: str
    tools_available: int
    server: str


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["System"])
def health():
    """
    Health check — grader dùng để verify MCP server đang chạy.
    Trả về số lượng tools có sẵn.
    """
    return HealthResponse(
        status="ok",
        tools_available=len(list_tools()),
        server="Day09 MCP HTTP Server v1.0",
    )


@app.get("/tools/list", tags=["MCP"])
def tools_list():
    """
    MCP Discovery: trả về toàn bộ tool schemas.
    Tương đương với `tools/list` trong MCP protocol.
    """
    return {
        "tools": list_tools(),
        "total": len(list_tools()),
    }


@app.post("/tools/call", response_model=ToolCallResponse, tags=["MCP"])
def tools_call(req: ToolCallRequest):
    """
    MCP Execution: nhận tool_name + tool_input, gọi tool và trả về kết quả.
    Tương đương với `tools/call` trong MCP protocol.

    dispatch_tool() xử lý toàn bộ logic và ghi log vào _CALL_LOG.
    """
    if not req.tool_name:
        raise HTTPException(status_code=400, detail="tool_name is required")

    from datetime import datetime
    result = dispatch_tool(req.tool_name, req.tool_input)
    success = "error" not in result

    return ToolCallResponse(
        tool_name=req.tool_name,
        result=result,
        success=success,
        timestamp=datetime.now().isoformat(),
    )


@app.get("/call-log", tags=["Debug"])
def call_log():
    """
    Trả về toàn bộ call log của session hiện tại.
    Dùng để debug trace hoặc verify mcp_tools_used.
    """
    logs = get_call_log()
    return {
        "calls": logs,
        "total": len(logs),
    }


@app.delete("/call-log", tags=["Debug"])
def reset_call_log():
    """
    Reset call log — gọi trước mỗi grading run mới để log không bị lẫn.
    """
    clear_call_log()
    return {"status": "cleared", "message": "Call log has been reset."}


# ─────────────────────────────────────────────
# Run Standalone
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("MCP HTTP Server — Advanced Level (Bonus +2)")
    print("=" * 60)
    print("  Swagger UI : http://localhost:8765/docs")
    print("  Health     : http://localhost:8765/health")
    print("  Tools list : http://localhost:8765/tools/list")
    print("  Tool call  : POST http://localhost:8765/tools/call")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8765, reload=False)
