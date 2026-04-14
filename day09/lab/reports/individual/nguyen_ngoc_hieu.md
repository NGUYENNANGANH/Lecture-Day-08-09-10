# Báo Cáo Cá Nhân — Lab Day 09: Multi-Agent Orchestration

**Họ và tên:** Nguyễn Ngọc Hiếu
**Vai trò trong nhóm:** Supervisor Owner
**Ngày nộp:** 2026-04-14

---

## 1. Tôi phụ trách phần nào? (100–150 từ)

Trong dự án Lab Day 09, tôi chịu trách nhiệm chính về điều phối của toàn bộ hệ thống. Tôi đảm nhiệm việc thiết kế file `graph.py`.

**Module/file tôi chịu trách nhiệm:**
- File chính: `graph.py`
- Functions tôi implement: `supervisor_node`, `route_decision`,  `human_review_node`, `retrieval_worker_node`, `policy_tool_worker_node`, `synthesis_worker_node`, `build_graph`

**Cách công việc của tôi kết nối với phần của thành viên khác:**

Tôi đóng vai trò kết nối. Tôi nhận kết quả Retrieval từ M2 và kết quả Policy từ M3 để cập nhật vào State, sau đó điều phối dữ liệu đó tới Synthesis worker. Nếu không có phần Graph của tôi, các Worker của M2, M3 và M4 sẽ không thể giao tiếp với nhau để tạo ra câu trả lời cuối cùng.


**Bằng chứng (commit hash, file có comment tên bạn, v.v.):**

- commit hash: `cb13eee`,`cb13eee`


---

## 2. Tôi đã ra một quyết định kỹ thuật gì? (150–200 từ)

**Quyết định:**  Tôi chọn triển khai **Keyword-based Routing kết hợp với Multi-signal Detection** thay vì sử dụng một LLM Classifier riêng biệt cho bước Supervisor.

**Lý do:**

Việc gọi thêm một LLM chỉ để phân loại task sẽ làm tăng độ trễ (latency) thêm khoảng 1-2 giây và tốn thêm chi phí token không cần thiết. Với 5 bộ tài liệu có domain rất rõ ràng (Refund, SLA, Access Control), việc sử dụng tập hợp các từ khóa đặc trưng là đủ để đạt độ chính xác trên 90%.

**Trade-off đã chấp nhận:**


Hệ thống có thể bỏ sót các câu hỏi được diễn đạt quá gián tiếp mà không chứa từ khóa nhạy cảm. Tuy nhiên, tôi đã bù đắp bằng một `default fallback` về `retrieval_worker` để đảm bảo hệ thống luôn có dữ liệu thay vì trả về lỗi.

**Bằng chứng từ trace/code:**

```python
# Multi-signal detection cho SLA + notification detail
notification_keywords = ["thông báo", "notification", "kênh", "notify", "channel"]
sla_detail_keywords = ["p1", "sla", "ticket"]

needs_ticket_detail = (
    any(kw in task for kw in sla_detail_keywords) and
    any(kw in task for kw in notification_keywords)
)
```

---

## 3. Tôi đã sửa một lỗi gì? (150–200 từ)

**Lỗi:** Sai lệch kênh thông báo trong các câu hỏi về sự cố P1 (gq01, gq09).

**Symptom (pipeline làm gì sai?):**

Khi test với câu hỏi: *"SLA P1 được tạo lúc 22:47. Ai nhận thông báo đầu tiên và qua kênh nào?"*, hệ thống chỉ trả về thông tin chung chung từ tài liệu văn bản như "thông báo cho stakeholders" mà không liệt kê được 3 kênh cụ thể (Slack, Email, PagerDuty).


**Root cause (lỗi nằm ở đâu — indexing, routing, contract, worker logic?):**

Supervisor nhận diện từ khóa "P1" và đẩy task vào `retrieval_worker`. Worker này chỉ đọc file `sla_p1_2026.txt` (vốn không chứa các thông số kỹ thuật động). Trong khi đó, dữ liệu đúng nằm ở MCP tool `get_ticket_info`, nhưng worker `retrieval` không có quyền gọi MCP.

**Cách sửa:**

Tôi đã sửa lại hàm `supervisor_node`. Tôi thêm một logic kiểm tra chéo (multi-signal): Nếu câu hỏi chứa từ khóa SLA/P1 **VÀ** đồng thời hỏi về "thông báo/kênh/kết nối", tôi sẽ ép hệ thống route sang `policy_tool_worker`. Worker này đã được M3 cấu hình để gọi MCP `get_ticket_info`, từ đó lấy được dữ liệu thời gian thực về các kênh notification.

**Bằng chứng trước/sau:**

- **Trước:** Trace ghi `supervisor_route: retrieval_worker`, câu trả lời thiếu thông tin kênh.
- **Sau:** Trace ghi `supervisor_route: policy_tool_worker`, kết quả trả về đầy đủ: *"Thông báo được gửi qua Slack #incident-p1, Email và PagerDuty."

---

## 4. Tôi tự đánh giá đóng góp của mình (100–150 từ)


**Tôi làm tốt nhất ở điểm nào?**


Tôi đã xây dựng được một khung xương (Graph) ổn định bằng LangGraph. Việc quản lý State chặt chẽ giúp nhóm dễ dàng theo dõi được `history` và `worker_io_logs`, giúp việc debug của cả nhóm nhanh hơn.


**Tôi làm chưa tốt hoặc còn yếu ở điểm nào?**

Danh sách từ khóa (keywords) của tôi vẫn còn thủ công. Nếu dự án mở rộng lên 50 tài liệu, cách tiếp cận này sẽ trở nên khó bảo trì.


**Nhóm phụ thuộc vào tôi ở đâu?** _(Phần nào của hệ thống bị block nếu tôi chưa xong?)_

Tôi giữ chìa khóa tích hợp. Nếu Graph lỗi, code của M2, M3 dù tốt đến đâu cũng không thể ghép nối. Tôi là người đảm bảo các contracts I/O được thực thi đúng trong luồng chạy.

**Phần tôi phụ thuộc vào thành viên khác:** _(Tôi cần gì từ ai để tiếp tục được?)_

Tôi phụ thuộc hoàn toàn vào **M2 (Retrieval)** và **M3 (Policy)** để nhận dữ liệu đầu vào chuẩn xác. Nếu M2 trả về format chunks sai hoặc M3 thay đổi cấu trúc `policy_result` mà không báo trước, Shared State của tôi sẽ bị hỏng dữ liệu. 


---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì? (50–100 từ)


Tôi sẽ triển khai **LLM-based Routing Fallback**. Cụ thể: Nếu Supervisor không tìm thấy từ khóa nào trong task, thay vì fallback về Retrieval, tôi sẽ gọi một LLM giá rẻ (như gpt-4o-mini) với một prompt cực ngắn để phân loại ý định. Điều này sẽ giúp xử lý được các câu hỏi mang tính ẩn dụ hoặc dùng thuật ngữ mới mà bộ từ khóa chưa cập nhật, tăng `Routing Accuracy` lên mức tuyệt đối.

---
