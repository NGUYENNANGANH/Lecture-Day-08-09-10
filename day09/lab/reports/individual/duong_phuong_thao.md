# Báo Cáo Cá Nhân — Lab Day 09: Multi-Agent Orchestration

**Họ và tên:** Dương Phương Thảo  
**Vai trò trong nhóm:** MCP Architect (M4) — mcp_server.py, mcp_http.py, external tools, FastAPI integration  
**Ngày nộp:** 2026-04-14  
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi phụ trách phần nào? (~130 từ)

**Module/file tôi chịu trách nhiệm:**
- File chính: `mcp_server.py` — xây dựng mock MCP Server theo chuẩn cung cấp các công cụ cho worker.
- Module mở rộng: `mcp_http.py` — hiện thực FastAPI HTTP server để nâng cấp giao tiếp MCP (đạt điểm thưởng Advanced bonus +2).
- Tích hợp vào Worker: `workers/policy_tool.py` — thay đổi tool dispatching để worker giao tiếp gián tiếp qua HTTP thay vì gọi hàm trực tiếp.

**Cách công việc của tôi kết nối với phần của thành viên khác:**
MCP server đóng vai trò kết nối giữa `policy_tool_worker` (do M3 phụ trách) với các nguồn cung cấp dữ liệu bên ngoài. Thay vì để worker trực tiếp thao tác với cơ sở dữ liệu `ChromaDB` hoặc hệ thống ticket, tôi cung cấp qua MCP interface với `search_kb`, `get_ticket_info`, `check_access_permission`, và `create_ticket`. Bất kỳ yêu cầu nào lấy context ngoài lề sẽ đi qua `dispatch_tool_http` của tôi trước khi trả về state cho worker.

**Bằng chứng:** Các commit: `feat(mcp): add FastAPI HTTP server for MCP Advanced bonus +2`, và `initialize ChromaDB storage and update mcp_server configuration`. 

---

## 2. Tôi đã ra một quyết định kỹ thuật gì? (~180 từ)

**Quyết định:** Chuyển đổi từ gọi hàm trực tiếp (Mock in-process) sang giao tiếp qua HTTP API (MCP HTTP Server dùng FastAPI) cho việc dispatch tool.

Để hiện thực module chức năng, bản thảo ban đầu (Sprint 3) gợi ý sử dụng class Python Mock cơ bản. Việc này dù tiết kiệm thời gian nhưng sẽ làm hệ thống tight-coupled, không phản ánh đúng chuẩn kiến trúc client-server của Model Context Protocol thực tế. Do đó, tôi quyết định chọn **phương án Advanced (+2 bonus)**: tạo server HTTP thực thụ chạy bằng FastAPI, host các tool qua REST endpoint (`POST /mcp/v1/tools/call`), và thiết lập `httpx` client ở phía `policy_tool`.

**Các lựa chọn thay thế:**
1. MCP In-process (Local function): Dễ cài đặt, siêu nhanh (latency thấp) nhưng thiếu tính mô phỏng hệ thống phân tán, giới hạn khả năng mở rộng sang các language khác.
2. Thư viện `mcp` chuẩn: Quá phức tạp cho scope nhỏ của bài Lab và dễ có lỗi dependency.

**Trade-off:**
Sử dụng HTTP Server tăng latency (mất vài chục ms do network layer) và yêu cầu xử lý bất đồng bộ (hoặc request retry error handling), đồng thời cần chạy `uvicorn` background. Đổi lại, hệ thống cực kì linh hoạt và decoupled hoàn toàn worker với tool provider, sát với thiết kế production. 

**Bằng chứng từ trace:**
Trace ghi nhận array `mcp_tools_used` xuất hiện rõ ràng từng lời gọi công cụ, ví dụ:
`mcp_tools_used: [{"tool": "check_access_permission", "input": {"level": 2}, ...}]`

---

## 3. Tôi đã sửa một lỗi gì? (~150 từ)

**Lỗi:** `policy_tool_worker` bị rớt (crash) hoặc đứng khi không kết nối được tới MCP Server nếu server chưa kịp khởi động.

**Symptom:** Lúc test graph (`graph.py`), lỗi `httpx.ConnectError` thỉnh thoảng xuất hiện, làm gián đoạn toàn bộ orchestration luồng P1 SLA và access control, khiến fallback policy của generator sai.

**Root cause:** Khi tôi refactor sang HTTP, `httpx.Client()` không có cơ chế fallback. Nếu `uvicorn` server down hoặc port bị chiếm, HTTP client fail ngay lập tức, báo exception phá vỡ schema `AgentState`. 

**Cách sửa:**
Tôi thêm tính năng **cơ chế tự động Fallback về local function** vào hàm client tại file `mcp_server.py`. Khi HTTP request exception xảy ra, tôi bắt khối except, in log file cảnh báo "HTTP Server không phản hồi, fallback về local `dispatch_tool()`", đảm bảo hệ thống vẫn tiếp tục duy trì dịch vụ.

**Bằng chứng trước/sau:**
Trước khi sửa: Worker văng Unhandled Exception trên console, trace pipeline không lưu lại được kết quả.
Sau khi sửa: Dù tắt server FastAPI, worker `policy_tool` tự động cảnh báo và gọi hàm local. Pipeline eval pass bình thường.

---

## 4. Tôi tự đánh giá đóng góp của mình (~120 từ)

**Tôi làm tốt nhất ở điểm nào?**
Tôi đã thiết kế tách biệt (decoupling) triệt để các nguồn dữ liệu bên ngoài qua cổng MCP. Khởi tạo Chroma vector store ngay trong server và expose `search_kb` thành tool. Tích hợp chuẩn API giúp dễ dàng gọi tool mà không cần hard-code cơ sở dữ liệu trong worker. Lấy luôn được điểm thưởng cho feature FastAPI HTTP server.

**Tôi làm chưa tốt hoặc còn yếu ở điểm nào?**
Chưa có thời gian xây dựng retry mechanism hoặc circuit breaker hoàn chỉnh cho HTTP request. Đồng thời, lúc debug dependency hơi chậm ở giai đoạn đầu của Sprint 3. 

**Nhóm phụ thuộc vào tôi ở đâu?**
Các worker (đặc biệt policy_tool của M3) cần MCP server của tôi để lấy data ticket thực và quyền SLA. `eval_trace` (M5) cũng phụ thuộc định dạng log `mcp_tools_used` tôi xuất ra để chấm điểm tracing. Mất MCP, pipeline sẽ hụt toàn bộ câu hỏi liên quan tới SLA và hệ thống phân quyền.

---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì? (~80 từ)

Tôi sẽ cấu hình **bất đồng bộ (`asyncio` và `httpx.AsyncClient`)** trên toàn bộ pipeline của mình. Hiện tại, server/client đang chặn luồng (blocking). Nếu có asyncio đồng bộ hóa, StateGraph của LangGraph có thể thực thi đa luồng, gọi song song nhiều external tools để lấy context cùng lúc. Điều này giúp độ trễ của hệ thống (hiện đang ~2500ms) ở những câu multi-hop giảm đáng kể do giải quyết được nghẽn cổ chai mạng I/O.
