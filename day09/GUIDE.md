# 📘 TEAM GUIDE: Multi-Agent Orchestration (Lab Day 09)

Chào mừng nhóm 5 người! Tài liệu này là kim chỉ nam để các bạn hoàn thành Lab Day 09 trong vòng 4 tiếng (4 sprints x 60 phút), đảm bảo đạt điểm tối đa (100 điểm) và không xảy ra xung đột code.

---

## 👥 Phân Vai & Trách Nhiệm (Team of 5)

Để tối ưu hóa hiệu suất, chúng ta sẽ phân chia 5 vai trò chuyên biệt:

1.  **Lead Supervisor (M1):** Chủ dự án `graph.py`, quản lý Shared State và logic điều phối chính.
2.  **Worker Specialist A (M2):** Phụ trách `retrieval.py` và `synthesis.py` (Domain Knowledge).
3.  **Worker Specialist B (M3):** Phụ trách `policy_tool.py` và quản lý `worker_contracts.yaml`.
4.  **MCP Architect (M4):** Xây dựng `mcp_server.py` và tích hợp các công cụ ngoại vi.
5.  **Quality & Trace Analyst (M5):** Phụ trách `eval_trace.py`, chạy thử nghiệm, viết tài liệu nhóm và giám sát deadline.

---

## ⏱️ Lộ Trình Thực Hiện (4 Sprints)

### Sprint 1: Khung Xương & Hợp Đồng (60')
*Mục tiêu: Graph chạy được với dữ liệu mock và hợp đồng rõ ràng.*

*   **M1 (Lead):** Khởi tạo `graph.py`, định nghĩa `AgentState`. Viết logic routing cơ bản (Keyword-based).
*   **M2 & M3 (Workers):** Cùng nhau chốt I/O trong `contracts/worker_contracts.yaml`. Đây là "hiến pháp" để các thành viên không dẫm chân lên nhau.
*   **M4 (MCP):** Dựng khung `mcp_server.py` với danh sách tool cần thiết (mock).
*   **M5 (Quality):** Setup môi trường, cài dependencies, chuẩn bị file `artifacts/traces/`.

### Sprint 2: Hiện Thực Hóa Workers (60')
*Mục tiêu: Các worker chạy độc lập và trả về kết quả thật.*

*   **M2:** Code logic `retrieval.py` (ChromaDB) và `synthesis.py` (LLM Prompting).
*   **M3:** Code logic `policy_tool.py`, xử lý các trường hợp ngoại lệ (Flash Sale, Digital Products).
*   **M1:** Kết nối các function của M2, M3 vào `graph.py`.
*   **M4:** Bắt đầu implement logic cho các tool trong MCP Server.
*   **M5:** Test độc lập từng worker theo contract (Unit test nhanh).

### Sprint 3: Sức Mạnh MCP & Tích Hợp (60')
*Mục tiêu: Hệ thống gọi được external tools và xử lý case phức tạp.*

*   **M4:** Hoàn thiện `mcp_server.py`.
*   **M3:** Sửa `policy_tool.py` để gọi tool qua `mcp_server.dispatch_tool()`.
*   **M1:** Tinh chỉnh Supervisor để nhận diện khi nào cần gọi MCP.
*   **M2:** Cải thiện Prompt cho Synthesis để cite nguồn đúng format `[tên_file]`.
*   **M5:** Chạy thử 15 câu test questions đầu tiên, kiểm tra trace logs.

### Sprint 4: Trace, Eval & Final Report (60')
*Mục tiêu: Chạy Grading Questions và hoàn thiện hồ sơ.*

*   **17:00 (M5):** Lấy `grading_questions.json`, chạy pipeline và tạo `artifacts/grading_run.jsonl`.
*   **M1, M2, M3, M4:** Mỗi người viết phần cá nhân trong `reports/individual/`.
*   **M5:** Tổng hợp dữ liệu so sánh Single vs Multi-agent vào `docs/single_vs_multi_comparison.md`.
*   **Cả nhóm:** Review lại `docs/routing_decisions.md` để đảm bảo logic thực tế khớp với trace.

---

## ⚔️ Chiến Thuật Tránh Xung Đột (Conflict Prevention)

1.  **Hợp đồng là trên hết:** Tuyệt đối không sửa `AgentState` hoặc I/O của worker mà không thông báo cho cả nhóm. Mọi thay đổi phải cập nhật vào `worker_contracts.yaml`.
2.  **Chia file để trị:** Mỗi thành viên làm việc trên file riêng đã phân công (M2 làm `workers/retrieval.py`, M3 làm `workers/policy_tool.py`).
3.  **Shared State:** Chỉ có **M1 (Supervisor)** được quyền ghi vào các trường điều phối (`supervisor_route`, `route_reason`). Workers chỉ ghi vào kết quả của mình (`retrieved_chunks`, `policy_result`).
4.  **Git Workflow:** Commit theo tính năng (ví dụ: `feat(worker): implement retrieval logic`). Push code ngay sau khi xong Sprint để M1 tích hợp.

---

## 🚀 Bí Kíp Đạt Điểm Tuyệt Đối

*   **Trace Visibility (20% điểm):** Đảm bảo `route_reason` của Supervisor cực kỳ chi tiết (Ví dụ: "Task contains 'refund' keyword + orders before 2026-02-01 -> route to policy_tool").
*   **Abstain (Câu gq07):** Worker synthesis phải biết nói "Không đủ thông tin" nếu không tìm thấy bằng chứng. Hallucination (bịa đặt) sẽ bị trừ 50% điểm câu đó.
*   **Multi-hop (Câu gq09):** Đây là câu 16 điểm. Đảm bảo Supervisor gọi cả 2 worker (Retrieval + Policy) cho câu này.
*   **Deadline:** Code và Trace phải xong trước **18:00**. Report có thể nộp sau nhưng không nên chủ quan.

---

## 📅 Các Mốc Thời Gian Quan Trọng
*   **14:00:** Bắt đầu Sprint 1.
*   **16:00:** Xong Sprint 3, hệ thống phải chạy ổn định với 15 câu test.
*   **17:00:** `grading_questions.json` public - **Tập trung cao độ.**
*   **17:45:** Kiểm tra lại file `grading_run.jsonl` lần cuối.
*   **18:00:** Deadline Code & Trace.


---
