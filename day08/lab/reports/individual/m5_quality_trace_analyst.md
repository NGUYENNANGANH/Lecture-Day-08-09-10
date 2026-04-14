# Báo Cáo Cá Nhân — Lab Day 08: RAG Pipeline

**Họ và tên:** [Tên thành viên M5]  
**Vai trò trong nhóm:** Quality & Trace Analyst (M5)  
**Ngày nộp:** 2026-04-14  
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi đã làm gì trong lab này? (100-150 từ)

Tôi đảm nhận vai trò **Quality & Trace Analyst (M5)**, phụ trách chính ở **Sprint 4** — thiết kế hệ thống tracing, chạy thử nghiệm, đánh giá chất lượng pipeline, và viết tài liệu đánh giá.

Công việc cụ thể:

1. **Thiết kế và implement `eval_trace.py`** — module tracing hoàn chỉnh cho pipeline RAG. Module này log chi tiết từng bước: input query → retrieved chunks (kèm scores, metadata) → generated answer → evaluation metrics → latency. Hỗ trợ 3 chế độ: single query trace, batch test (10 câu), và A/B comparison (baseline dense vs variant hybrid).

2. **Chạy batch test** với 10 test questions trên cả 2 config (dense và hybrid), tạo ra structured JSON traces và markdown summary tự động.

3. **Phân tích failure modes** — phân loại lỗi theo 5 loại: false_abstain, hallucination, incomplete, irrelevant, retrieval_miss. Xác định rằng bottleneck chính nằm ở generation (prompt quá nghiêm) chứ không phải retrieval.

4. **Xây dựng quality checklist** — checklist 12 mục kiểm tra cho mỗi query, bao gồm retrieval layer, generation layer, abstain logic, và edge cases.

---

## 2. Điều tôi hiểu rõ hơn sau lab này (100-150 từ)

Sau lab, tôi hiểu rõ hơn về **tầm quan trọng của structured tracing** trong việc debug hệ thống AI.

Khi bắt đầu, tôi nghĩ chỉ cần đọc answer output là biết pipeline hoạt động tốt hay không. Nhưng khi implement `eval_trace.py`, tôi nhận ra rằng **cùng một answer sai có thể do 3 nguyên nhân hoàn toàn khác nhau**: (1) index lỗi → chunk bị cắt giữa điều khoản, (2) retrieval lỗi → không tìm đúng source, hoặc (3) generation lỗi → LLM bịa hoặc abstain sai. Nếu không trace từng layer, không thể biết lỗi ở đâu để fix.

Ví dụ cụ thể: câu q07 ("Approval Matrix") có **context recall = 5/5** (retrieval đúng!) nhưng **faithfulness = 1/5** (answer sai!). Nếu chỉ nhìn answer sai, dễ kết luận nhầm rằng retrieval cần cải thiện. Trace cho thấy root cause nằm ở **prompt engineering** — grounding instruction quá nghiêm khiến LLM không dám map alias.

---

## 3. Điều tôi ngạc nhiên hoặc gặp khó khăn (100-150 từ)

Điều **ngạc nhiên nhất** là kết quả A/B comparison:

| Metric | Baseline (Dense) | Variant (Hybrid) | Delta |
|--------|------------------|-------------------|-------|
| Faithfulness | 4.40 | 4.00 | **-0.40** 🔻 |
| Relevance | 5.00 | 5.00 | 0.00 |
| Context Recall | 5.00 | 5.00 | 0.00 |
| Completeness | 3.40 | 3.20 | **-0.20** 🔻 |

Hybrid **tệ hơn** baseline ở cả 2 metrics quan trọng. BM25 sparse search thêm noise thay vì bổ trợ — tokenization `lower().split()` quá đơn giản cho tiếng Việt.

**Khó khăn lớn nhất** khi thiết kế eval_trace là quyết định **trace bao sâu mà không quá verbose**. Nếu log toàn bộ prompt (hàng nghìn chars) thì JSON quá lớn. Nếu cắt quá ngắn thì mất context debug. Giải pháp: `text_preview` giới hạn 200 chars cho chunks, 500 chars cho prompt, kèm `text_length` và `prompt_tokens_est` để biết full size khi cần.

---

## 4. Phân tích một câu hỏi trong grading questions (150-200 từ)

**Câu hỏi:** gq03 — "Đơn hàng mua trong chương trình Flash Sale và đã kích hoạt sản phẩm có được hoàn tiền không?"

**Kết quả pipeline:** "Không đủ dữ liệu để trả lời câu hỏi này." → **Cần kiểm tra**

**Trace root cause — loại trừ từng layer:**

1. **Indexing**: File `policy_refund_v4.txt` đã được index đầy đủ. Chunking theo heading `===` tạo các section riêng biệt cho "Điều kiện hoàn tiền", "Ngoại lệ", "Quy trình". Metadata: `source=policy/refund-v4.pdf`, `department=CS`.

2. **Retrieval**: Pipeline **đã retrieve đúng source** — `policy/refund-v4.pdf` nằm trong `sources` output. Context recall = tốt. Chunk chứa phần "Ngoại lệ không hoàn tiền" (license key, subscription, activated product) đã được retrieve.

3. **Generation**: **Đây là điểm thất bại tiềm năng**. Câu hỏi hỏi 2 điều kiện kết hợp: (a) Flash Sale VÀ (b) đã kích hoạt. Nếu tài liệu có đề cập "đã kích hoạt sản phẩm" là ngoại lệ nhưng KHÔNG nhắc đến "Flash Sale" cụ thể, LLM phải suy luận: "Flash Sale không phải ngoại lệ riêng, nhưng kích hoạt sản phẩm thì đúng là ngoại lệ." Prompt "Do NOT guess, infer" khiến LLM abstain thay vì suy luận hợp lý.

**Failure mode:** `false_abstain` — context có thông tin cho phần "kích hoạt sản phẩm" nhưng LLM không dám kết hợp với điều kiện "Flash Sale" vì prompt quá nghiêm.

**Fix đề xuất:** Điều chỉnh prompt: "You may combine multiple conditions from the context to answer compound questions, but each individual condition must be explicitly stated in the context."

---

## 5. Nếu có thêm thời gian, tôi sẽ làm gì? (50-100 từ)

1. **Implement LLM-as-Judge** trong `eval_trace.py`: Thay vì keyword matching cho faithfulness/completeness, gọi LLM đánh giá lại answer vs context. Kỳ vọng: scoring chính xác hơn cho câu paraphrase đúng nhưng dùng từ khác (hiện tại bị đánh grounding ratio thấp sai).

2. **Thêm regression test**: Sau mỗi thay đổi config/prompt, chạy lại batch trace và compare với trace trước. Tự động detect câu nào bị regression (score giảm) để tránh fix 1 câu nhưng làm hỏng câu khác.

---
