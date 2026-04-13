# Báo Cáo Cá Nhân — Lab Day 08: RAG Pipeline

**Họ và tên:** Mai Phi Hiếu  
**Vai trò trong nhóm:** Documentation Owner  
**Ngày nộp:** 2026-04-13  
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi đã làm gì trong lab này? (100-150 từ)

Tôi đảm nhận vai trò **Documentation Owner**, chịu trách nhiệm chính trong **Sprint 4**. Công việc cụ thể của tôi gồm:

- **Viết `docs/architecture.md`**: Mô tả chi tiết kiến trúc pipeline từ indexing đến generation. Tôi phải đọc hiểu toàn bộ code của các thành viên khác (`index.py` của Tùng và Anh, `rag_answer.py` của Thảo) để giải thích chính xác cách chunking hoạt động, cách dense/hybrid retrieval truy xuất, và cách prompt grounding ép LLM trả lời có citation.

- **Viết `docs/tuning-log.md`**: Ghi lại kết quả baseline (Faithfulness 4.40, Relevance 5.00, Context Recall 5.00, Completeness 3.40), phân tích câu hỏi yếu nhất (q07 false abstain, q10 false abstain), và document lỗi variant crash do thiếu `rank-bm25`.

- **Viết `reports/group_report.md`**: Tổng hợp phân công, mô tả hệ thống, demo input/output, đánh giá ưu nhược điểm.

Công việc của tôi kết nối với phần còn lại: tôi cần hiểu output của Eval Owner (Ngọc Hiếu) để điền scorecard, hiểu logic code của Retrieval team (Tùng, Anh) để mô tả data flow, và hiểu prompt của Tech Lead (Thảo) để giải thích generation rules.

---

## 2. Điều tôi hiểu rõ hơn sau lab này (100-150 từ)

Tôi hiểu rõ hơn về **mối quan hệ giữa retrieval quality và generation quality** — và chúng không phải lúc nào cũng tương quan.

Ví dụ cụ thể: câu q07 ("Approval Matrix") có **Context Recall = 5/5** (retriever tìm đúng source) nhưng **Faithfulness = 1/5** (LLM trả "Không đủ dữ liệu"). Điều này cho thấy retrieval tốt là cần thiết nhưng chưa đủ — **prompt engineering** quyết định LLM có biết khai thác context hay không. Prompt quá nghiêm ("Do NOT guess, infer") khiến LLM sợ suy luận dù thông tin có trong context.

Tôi cũng hiểu tại sao **chunking theo heading** tốt hơn chunking cố định. Khi đọc code `chunk_document()`, thấy rằng split theo `=== Section ===` giữ nguyên ngữ nghĩa mỗi điều khoản. Nếu cắt theo character count cứng, một điều khoản có thể bị chia đôi → retriever tìm được nửa trên nhưng mất nửa dưới.

---

## 3. Điều tôi ngạc nhiên hoặc gặp khó khăn (100-150 từ)

Điều ngạc nhiên nhất là **variant hybrid hoàn toàn crash** chỉ vì thiếu một package `rank-bm25`. Toàn bộ 10 câu scorecard variant trả về `ERROR: No module named 'rank_bm25'`, dẫn đến A/B comparison vô nghĩa (baseline vs crash). Đây là bài học về **dependency management**: code logic đúng nhưng environment thiếu 1 package = hệ thống chết hoàn toàn.

Khó khăn lớn nhất khi viết documentation là **phải hiểu code của người khác**. Ví dụ, hàm `_split_by_size()` có 3 nhánh logic (paragraph-based → character-based → fallback boundary detection), mỗi nhánh có overlap khác nhau. Tôi phải trace từng nhánh để mô tả chính xác trong architecture.md mà không suy đoán sai.

Giả thuyết ban đầu: tôi nghĩ retrieval là bottleneck chính. Thực tế: Context Recall = 5.00/5 — retrieval gần như hoàn hảo. Bottleneck thực sự nằm ở **generation** (Completeness chỉ 3.40/5) và **prompt quá nghiêm** (false abstain).

---

## 4. Phân tích một câu hỏi trong scorecard (150-200 từ)

**Câu hỏi:** q07 — "Approval Matrix để cấp quyền hệ thống là tài liệu nào?"

**Phân tích:**

**Pipeline xử lý q07 theo baseline (dense):**

1. **Indexing**: ✅ File `access_control_sop.txt` được index đúng, chunk đầu tiên chứa dòng "Ghi chú: Tài liệu này trước đây có tên Approval Matrix for System Access". Metadata source = `it/access-control-sop.md`.

2. **Retrieval**: ✅ `retrieve_dense()` tìm được đúng source — Context Recall = 5/5. Dense embedding nhận ra "Approval Matrix" liên quan đến access control dù không phải exact match.

3. **Generation**: ❌ **Đây là failure point.** LLM nhận context có thông tin "trước đây có tên Approval Matrix" nhưng vẫn trả "Không đủ dữ liệu để trả lời câu hỏi này." 

**Root cause**: Prompt instruction `"Do NOT guess, infer, or use your own knowledge"` khiến LLM diễn giải rằng việc map "Approval Matrix" (query) → "Access Control SOP" (context) là "infer" — nên abstain cho an toàn.

**Failure mode**: **False abstain ở generation layer**, không phải retrieval layer.

**Fix đề xuất**: Điều chỉnh prompt thành "You may draw reasonable conclusions directly supported by the context, but do not add facts from external knowledge." Điều này cho phép mapping alias mà không vi phạm grounding principle.

**Variant có cải thiện không?** Không test được (crash). Nhưng về lý thuyết, hybrid có thể **cải thiện ranking** (BM25 match "Approval Matrix" trực tiếp) → chunk chứa alias rank cao hơn → LLM có context rõ hơn. Tuy nhiên, root cause nằm ở prompt, không phải retrieval — nên hybrid có thể không đủ để fix.

---

## 5. Nếu có thêm thời gian, tôi sẽ làm gì? (50-100 từ)

1. **Điều chỉnh prompt giảm false abstain**: Kết quả eval cho thấy q07 và q10 đều false abstain dù context recall = 5/5. Tôi sẽ sửa instruction thành "draw reasonable conclusions from context" thay vì "Do NOT infer" → kỳ vọng Faithfulness q07 tăng từ 1 lên 4-5.

2. **Implement LLM-as-Judge**: Scoring hiện tại dùng keyword matching (grounding ratio) — không công bằng cho answer paraphrase đúng ý nhưng dùng từ khác. LLM-as-Judge sẽ cho semantic scoring chính xác hơn, đặc biệt với corpus tiếng Việt.

---

*Tổng: ~750 từ*
