# Báo Cáo Cá Nhân — Lab Day 08: RAG Pipeline

**Họ và tên:** Nguyễn Năng Anh  
**Vai trò trong nhóm:** Retrieval Owner  
**Ngày nộp:** 2026-04-13  
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi đã làm gì trong lab này? (100-150 từ)

Tôi đảm nhận vai trò **Retrieval Owner**, phụ trách chính ở **Sprint 1** và **Sprint 3**.

Trong **Sprint 1**, tôi implement hàm `build_index()` trong `index.py` — pipeline hoàn chỉnh từ đọc file đến lưu vào vector store. Cụ thể, tôi khởi tạo ChromaDB `PersistentClient` với collection `rag_lab` (cosine similarity), duyệt qua 5 file `.txt` trong `data/docs/`, gọi `preprocess_document()` và `chunk_document()` (do Phương Thảo viết), rồi với mỗi chunk gọi `get_embedding()` (do Thanh Tùng implement) và `upsert` vào ChromaDB với ID format `{filename}_{index}`. Tôi cũng xử lý edge case khi thư mục rỗng hoặc không tạo được chunk.

Trong **Sprint 3**, tôi implement hàm `retrieve_hybrid()` trong `rag_answer.py` — kết hợp dense retrieval và sparse retrieval (BM25) bằng **Reciprocal Rank Fusion (RRF)**. Tôi thiết kế hệ thống cộng dồn điểm RRF với hằng số K=60 (tiêu chuẩn), trọng số dense 0.6 và sparse 0.4, sử dụng dictionary để merge kết quả từ hai nguồn, sort theo RRF score giảm dần và trả về top-k.

---

## 2. Điều tôi hiểu rõ hơn sau lab này (100-150 từ)

Sau lab, tôi hiểu rõ hơn về **tầm quan trọng của indexing pipeline** và tại sao nó là nền tảng cho toàn bộ hệ thống RAG.

Khi implement `build_index()`, tôi nhận ra rằng quyết định **embedding model** và **vector store config** ảnh hưởng xuyên suốt pipeline — nếu index sai, retrieval và generation đều sai theo. Ví dụ, ChromaDB dùng `hnsw:space = "cosine"` nghĩa là khi query, `distance = 1 - similarity`, nên `retrieve_dense()` phải convert ngược lại (`score = 1 - distance`). Nếu nhầm metric, ranking sẽ đảo ngược hoàn toàn.

Về RRF fusion, tôi hiểu rằng **cộng dồn rank** thay vì cộng dồn raw score là key insight — hai hệ thống có scale score hoàn toàn khác nhau (cosine similarity 0-1 vs BM25 score 0-∞), nên không thể cộng trực tiếp. RRF chuẩn hóa bằng cách chỉ dùng **thứ hạng**, giúp merge công bằng bất kể scale.

---

## 3. Điều tôi ngạc nhiên hoặc gặp khó khăn (100-150 từ)

Điều **ngạc nhiên nhất** là kết quả A/B cho thấy hybrid **không tốt hơn** baseline dense. Faithfulness giảm 0.40, Completeness giảm 0.20. Tôi kỳ vọng BM25 bổ trợ exact keyword matching sẽ cải thiện, nhưng thực tế thì sparse results đôi khi thêm **noise** — BM25 whitespace tokenization `lower().split()` quá đơn giản cho tiếng Việt, dẫn đến ranking không chính xác khi gặp từ ghép hoặc stopword.

**Khó khăn lớn nhất** khi implement `retrieve_hybrid()` là xử lý **trùng lặp chunk** giữa dense và sparse results. Một chunk có thể xuất hiện ở cả hai danh sách với rank khác nhau — tôi phải dùng dictionary với key là `doc_text` để cộng dồn RRF score. Ban đầu tôi dùng chunk ID làm key, nhưng phát hiện ChromaDB trả về documents mà không kèm ID trong kết quả query, nên phải chuyển sang dùng text content làm key thay thế.

---

## 4. Phân tích một câu hỏi trong grading questions (150-200 từ)

**Câu hỏi:** gq01 — "SLA xử lý ticket P1 đã thay đổi như thế nào so với phiên bản trước?"

**Kết quả pipeline:** "SLA P1 đã thay đổi từ 6 giờ xuống 4 giờ cho quy trình xử lý và khắc phục [1]." → **Partial** — chỉ nêu thay đổi resolution time mà bỏ qua first response 15 phút, escalation 10 phút, và stakeholder update mỗi 30 phút.

**Trace root cause — loại trừ từng layer:**

1. **Indexing**: Kiểm tra file `sla_p1_2026.txt` — chunking theo heading `===` tạo 5 chunk riêng biệt. Thông tin "phản hồi ban đầu: 15 phút" nằm ở **Phần 2** (SLA theo mức ưu tiên), còn "resolution từ 6h xuống 4h" nằm ở **Phần 5** (Lịch sử phiên bản). Hai section khác nhau = **hai chunk tách rời**. `build_index()` (hàm tôi implement) index đúng theo thiết kế, nhưng vô tình tách hai thông tin liên quan vào hai chunk.

2. **Retrieval**: **Đây là failure point.** Với `top_k_select=3`, pipeline chỉ chọn 3 chunk đưa vào prompt. Query "thay đổi so với phiên bản trước" khớp semantic mạnh nhất với **Phần 5** (lịch sử phiên bản) → chunk này rank cao. Chunk **Phần 2** (SLA chi tiết) có thể bị đẩy xuống ngoài top-3 vì embedding ít liên quan đến từ "thay đổi" và "phiên bản trước".

3. **Generation**: LLM trả lời đúng từ context nhận được (Phần 5), nhưng thiếu context Phần 2 → incomplete.

**Failure mode:** Retrieval chọn đúng source nhưng **sai chunk** — chunk lịch sử thay đổi thay vì chunk SLA chi tiết hiện tại.

**Fix đề xuất:** Tăng `top_k_select` từ 3 lên 5 để LLM nhận được nhiều chunk hơn từ cùng source, hoặc implement metadata filtering theo `section` để ưu tiên cả "SLA hiện tại" lẫn "lịch sử" khi query hỏi về "thay đổi".

---

## 5. Nếu có thêm thời gian, tôi sẽ làm gì? (50-100 từ)

1. **Cache BM25 index ở module level**: Hiện tại `retrieve_sparse()` rebuild BM25 mỗi lần query — rất lãng phí. Kết quả scorecard cho thấy phải chạy 10 lần rebuild cho 10 câu. Tôi sẽ khởi tạo BM25 index một lần khi import module, giảm overhead đáng kể.

2. **Điều chỉnh trọng số RRF theo kết quả A/B**: Scorecard variant cho thấy sparse đang thêm noise. Tôi sẽ thử tăng `dense_weight` lên 0.8 và giảm `sparse_weight` xuống 0.2 để dense vẫn chiếm ưu thế, sparse chỉ bổ trợ khi exact match rõ ràng.

---

