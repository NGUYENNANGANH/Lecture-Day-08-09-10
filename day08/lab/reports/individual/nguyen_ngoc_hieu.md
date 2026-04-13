# Báo Cáo Cá Nhân — Lab Day 08: RAG Pipeline

**Họ và tên:** Nguyễn Ngọc Hiếu
**Vai trò trong nhóm:** Eval Owner
**Ngày nộp:** 2026-04-13
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi đã làm gì trong lab này? (100-150 từ)

> Mô tả cụ thể phần bạn đóng góp vào pipeline:
Em làm chủ yếu Sprint 3.
Em implement các hàm tính điểm (faithfullness, relevance, recall, completeness). em dùng phương pháp heuristic thay vì llm-as-judge để nhóm có thể chạy test nhanh và dễ debug logic hơn.
Công việc của em giúp TechLead và Doc Owner có số liệu thực tế để đánh giá pipeline đang mạnh, yếu ở đâu.

_________________

---

## 2. Điều tôi hiểu rõ hơn sau lab này (100-150 từ)

Sau bài lab, e biết thêm về hiện tượng False Abstain. Retriever mang về đúng chunk tài liệu nhưng nếu system prompt quá khắt khe hoặc thông tin chunk rối thì llm sẽ trả lời không đủ dữu liệu. Khâu generation (grounded prompt) cần hướng dẫn llm cách link các từ đồng nghĩa hoặc alias với nhau để không bỏ lỡ thông tin.

_________________

---

## 3. Điều tôi ngạc nhiên hoặc gặp khó khăn (100-150 từ)

Điều ngạc nhiên nhất là hybrid khi chạy, điểm số không tốt hơn baseline. Điểm completeness của nhóm bị tụt từ 3.40 xuống 3.20. Điều này chứng minh rằng không phải càng kết hợp nhiều cách search (dense + sparse) thì kết quả càng đầy đủ. RRF fusion đôi khi đưa thêm noise khiến LLM bị nhiễu.


_________________

---

## 4. Phân tích một câu hỏi trong scorecard (150-200 từ)

**Câu hỏi:** q07 - "Approval Matrix để cấp quyền hệ thống là tài liệu nào"

**Phân tích:**

Ở cấu hình Baseline (Dense), pipeline fail hoàn toàn: Faithfulness 1/5 và Completeness 1/5 do LLM trả lời "Không đủ dữ liệu".

Lỗi ở đây nằm hoàn toàn ở khâu Generation, không phải Retrieval. Thực tế, điểm Context Recall vẫn đạt 5/5, tức là thuật toán embedding đã thành công lấy đúng file access-control-sop.md đẩy vào prompt. Tuy nhiên, do prompt bắt LLM phải bám cực sát vào chứng cứ, LLM không đủ tự tin để nhận diện "Approval Matrix" chính là tên cũ được ghi chú trong file SOP này.

Khi chuyển sang Variant (Hybrid Retrieval), nhóm kỳ vọng thuật toán BM25 (chuyên bắt keyword exact-match) sẽ giúp chunk chứa chữ "Approval Matrix" được rank cao hơn. Nhưng kết quả thực tế trên scorecard Variant vẫn là 1/5. Việc đổi thuật toán Retrieval vô tác dụng khi bản thân LLM đang bị ràng buộc quá chặt bởi prompt chống bịa (anti-hallucination) ở khâu Generation.

## 5. Nếu có thêm thời gian, tôi sẽ làm gì? (50-100 từ)

Thứ nhất, em sẽ implement hàm LLM-as-Judge trong eval.py thay cho hàm heuristic. Cách đếm từ khóa đè (Jaccard) hiện tại của em hơi cứng nhắc, đánh giá Completeness đôi khi chưa phản ánh đúng ngữ nghĩa thực tế.

Thứ hai, dựa trên kết quả Context Recall đã đạt 5/5, em sẽ không cố tune khâu Retrieval nữa. Thay vào đó, em sẽ thử nghiệm biến đổi System Prompt (Query Transform hoặc nới lỏng Grounding Rules) để giảm tỷ lệ False Abstain cho câu q07 và q10.
_________________

---
