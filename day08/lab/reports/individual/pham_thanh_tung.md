# Báo Cáo Cá Nhân — Lab Day 08: RAG Pipeline

**Họ và tên:** Phạm Thanh Tùng  
**Vai trò trong nhóm:** Retrieval Owner  
**Ngày nộp:** 2026-04-13  
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi đã làm gì trong lab này? (100-150 từ)

Tôi đảm nhận vai trò **Retrieval Owner**, chủ yếu làm việc ở **Sprint 1** và **Sprint 3**.

Trong **Sprint 1**, tôi implement hàm `get_embedding()` trong `index.py` — chọn sử dụng **OpenAI `text-embedding-3-small`** (1536 dimensions) để tạo embedding vector cho từng chunk. Đây là bước quan trọng vì chất lượng embedding ảnh hưởng trực tiếp đến khả năng tìm kiếm semantic của toàn bộ pipeline. Tôi cũng phối hợp với Nguyễn Năng Anh (người implement `build_index()`) để đảm bảo embedding được upsert chính xác vào ChromaDB, và với Dương Phương Thảo (người viết chunking logic) để test rằng mỗi chunk có metadata đầy đủ trước khi embed.

Trong **Sprint 3**, tôi implement hàm `retrieve_sparse()` trong `rag_answer.py` — xây dựng BM25 keyword search sử dụng thư viện `rank-bm25`. Hàm này load toàn bộ chunks từ ChromaDB, tokenize corpus bằng whitespace splitting, build BM25Okapi index, và trả về top-k kết quả theo BM25 score. Kết quả sparse search này được Nguyễn Năng Anh sử dụng trong `retrieve_hybrid()` để kết hợp với dense search qua Reciprocal Rank Fusion (RRF).

---

## 2. Điều tôi hiểu rõ hơn sau lab này (100-150 từ)

Sau lab này, tôi hiểu rõ hơn về **sự khác biệt giữa dense retrieval và sparse retrieval**, cũng như tại sao **hybrid retrieval** lại có giá trị.

**Dense retrieval** (embedding-based) rất mạnh khi câu hỏi được diễn đạt khác với tài liệu gốc — nó hiểu "nghĩa" chứ không chỉ khớp từ. Tuy nhiên, nó yếu với các thuật ngữ chính xác như mã lỗi, tên riêng, hay viết tắt (ví dụ: "P1", "ERR-403-AUTH").

**Sparse retrieval** (BM25) thì ngược lại — rất giỏi tìm exact term match nhưng không hiểu đồng nghĩa hay paraphrase. Khi tôi implement BM25, tôi nhận ra tokenization đơn giản (`lower().split()`) hoạt động khá tốt cho tiếng Việt ở mức cơ bản, nhưng sẽ cần Vietnamese word segmentation (như `underthesea`) để xử lý các từ ghép chính xác hơn.

Việc kết hợp cả hai qua **RRF** (Reciprocal Rank Fusion) là ý tưởng thông minh: dense bổ sung semantic understanding cho sparse, và sparse bổ sung exact matching cho dense. Đây không chỉ là lý thuyết — tôi thấy rõ qua scorecard rằng hybrid retrieval giữ được Context Recall 5.00/5 giống baseline.

---

## 3. Điều tôi ngạc nhiên hoặc gặp khó khăn (100-150 từ)

Điều khiến tôi **ngạc nhiên nhất** là baseline dense retrieval đã hoạt động rất tốt ngay từ đầu — Context Recall đạt **5.00/5**, nghĩa là retriever tìm đúng source cho 100% câu hỏi. Tôi kỳ vọng sẽ có ít nhất vài câu miss source.

**Khó khăn lớn nhất** là khi implement `retrieve_sparse()`, BM25 yêu cầu load toàn bộ documents từ ChromaDB mỗi lần query (vì BM25 cần build index trên toàn bộ corpus). Điều này không hiệu quả về performance — mỗi query đều phải gọi `collection.get()` và rebuild BM25 index. Giả thuyết ban đầu của tôi là BM25 sẽ nhanh hơn dense search (vì không cần gọi API embedding), nhưng thực tế lại chậm hơn do overhead này.

Một khó khăn khác là **thiếu dependency `rank-bm25`** ban đầu khiến hybrid retrieval không chạy được trong lần test đầu tiên. Đây là bài học về tầm quan trọng của việc kiểm tra `requirements.txt` trước khi code.

---

## 4. Phân tích một câu hỏi trong grading questions (150-200 từ)

**Câu hỏi:** gq03 — "Đơn hàng mua trong chương trình Flash Sale và đã kích hoạt sản phẩm có được hoàn tiền không?"

**Pipeline trả lời:** "Không đủ dữ liệu để trả lời câu hỏi này." → **Sai hoàn toàn (false abstain).**

**Expected answer:** Không được hoàn tiền — đơn hàng vi phạm **hai ngoại lệ** trong Điều 3: (1) đơn hàng Flash Sale và (2) sản phẩm đã kích hoạt.

**Trace root cause — loại trừ từng layer:**

- **Indexing/Chunking**: Kiểm tra source document `policy_refund_v4.txt`, Điều 3 (`=== Điều 3: Điều kiện áp dụng và ngoại lệ ===`) chỉ dài ~350 ký tự, nhỏ hơn ngưỡng `CHUNK_SIZE * 4 = 1600` ký tự trong `_split_by_size()`. Vậy **toàn bộ Điều 3 nằm gọn trong 1 chunk**, không bị cắt — chunk chứa đầy đủ cả "Flash Sale" lẫn "kích hoạt".
- **Retrieval**: Log `grading_run.json` xác nhận retriever tìm đúng source `policy/refund-v4.pdf` với 3 chunks. Retrieval **không phải vấn đề**.
- **Generation**: Đây là **root cause thực sự**. LLM nhận được chunk chứa danh sách ngoại lệ nhưng vẫn abstain. Prompt quy tắc "Answer ONLY using information explicitly stated" quá nghiêm khắc — LLM không dám kết luận "không được hoàn tiền" dù context liệt kê rõ hai ngoại lệ phù hợp.

**Đề xuất fix**: Điều chỉnh prompt — thêm hướng dẫn rõ "If the context lists exceptions or conditions that match the question, apply them to reach a conclusion" để LLM suy luận từ danh sách ngoại lệ thay vì abstain.

---

## 5. Nếu có thêm thời gian, tôi sẽ làm gì? (50-100 từ)

1. **Tối ưu BM25 tokenization cho tiếng Việt**: Thay `lower().split()` bằng Vietnamese word segmenter (`underthesea`). Kết quả eval cho thấy hybrid chưa vượt trội baseline — tôi nghi ngờ sparse search chưa đủ mạnh do tokenization quá đơn giản.

2. **Cache BM25 index**: Hiện tại `retrieve_sparse()` rebuild BM25 index mỗi lần gọi. Tôi sẽ cache BM25Okapi object ở module level để tránh overhead, giúp hybrid retrieval nhanh hơn đáng kể khi chạy scorecard 10+ câu hỏi.

---

*Lưu file này với tên: `reports/individual/pham_thanh_tung.md`*
