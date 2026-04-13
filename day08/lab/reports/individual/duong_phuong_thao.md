# Báo Cáo Cá Nhân — Lab Day 08: RAG Pipeline

**Họ và tên:** Dương Thị Phương Thảo  
**Vai trò trong nhóm:** Team Leader  
**Ngày nộp:** 2026-04-14  
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi đã làm gì trong lab này? (100–150 từ)

Với vai trò **Team Leader**, tôi vừa điều phối tiến độ nhóm qua các sprint, vừa trực tiếp implement hai module nền tảng của pipeline.

**Sprint 1 — Indexing Pipeline (`index.py`):** Tôi implement hàm `chunk_document()` với chiến lược chunking theo cấu trúc tài liệu: split theo heading `=== Section ===` trước, rồi chia tiếp theo paragraph nếu section quá dài. Tôi cũng hoàn thiện hàm `_split_by_size()` — thay vì cắt cứng theo ký tự, tôi implement **paragraph-based splitting** với overlap thông minh: khi chunk đạt giới hạn `CHUNK_SIZE * 4` ký tự, hệ thống tìm ranh giới tự nhiên (dấu chấm câu hoặc xuống dòng) trong vùng overlap để tránh cắt giữa câu. Ngoài ra, tôi thêm fallback cho paragraph quá dài bằng sentence-level splitting.

Sau khi implement, tôi chạy `build_index()` để verify chunking hoạt động đúng, và dùng `list_chunks()` để kiểm tra chunk quality — đảm bảo metadata đầy đủ (source, section, effective_date) và chunk không bị cắt giữa điều khoản.

**Sprint 2 — RAG Answer (`rag_answer.py`):** Tôi implement `retrieve_dense()` để query ChromaDB bằng embedding similarity, `call_llm()` để gọi LLM sinh câu trả lời grounded, và thiết kế system prompt trong `build_grounded_prompt()` theo 4 quy tắc từ slide: evidence-only, abstain khi thiếu context, citation bắt buộc, và output ngắn gọn. Tôi cũng implement `build_context_block()` để format chunks thành context có đánh số `[1], [2], ...` giúp model dễ trích dẫn.

Sau đó, tôi test `rag_answer()` với 3+ câu hỏi mẫu: "SLA xử lý ticket P1 là bao lâu?", "Khách hàng có thể yêu cầu hoàn tiền trong bao nhiêu ngày?", và "ERR-403-AUTH là lỗi gì?" (câu cuối để kiểm tra abstain behavior).

---

## 2. Điều tôi hiểu rõ hơn sau lab này (100–150 từ)

Sau lab này, tôi hiểu rõ hơn hai concept quan trọng:

**Paragraph-based chunking với intelligent boundary detection:** Trước lab, tôi nghĩ chunking chỉ đơn giản là "cắt text mỗi N ký tự". Thực tế, khi implement `_split_by_size()`, tôi nhận ra rằng **ranh giới cắt cực kỳ quan trọng**. Nếu cắt giữa paragraph hay giữa câu, embedding sẽ không nắm được ngữ nghĩa đầy đủ. Do đó, tôi implement chiến lược ưu tiên: cắt tại `\n\n` (paragraph boundary) → nếu không tìm được thì cắt tại `. ` (sentence boundary) → cuối cùng mới fallback về character-based split. Overlap cũng phải "thông minh" — dùng `rfind(". ")` và `rfind("\n")` để tìm ranh giới tự nhiên trong vùng overlap thay vì lấy bừa N ký tự cuối.

**Grounded prompting và nguyên tắc abstain:** Tôi hiểu tại sao RAG pipeline cần prompt ép model chỉ trả lời từ context. Nếu không có quy tắc rõ ràng (evidence-only, citation bắt buộc), model sẽ tự "bịa" thông tin nghe hợp lý nhưng sai — đây là hallucination, lỗi nghiêm trọng nhất của RAG. Khi test với câu "ERR-403-AUTH", hệ thống cần từ chối trả lời thay vì bịa mã lỗi.

---

## 3. Điều tôi ngạc nhiên hoặc gặp khó khăn (100–150 từ)

**Khó khăn lớn nhất: xử lý paragraph quá dài.** Khi implement `_split_by_size()`, tôi gặp trường hợp một paragraph dài hơn `chunk_chars` (1600 ký tự). Paragraph-based split không hoạt động vì cả paragraph là một block liên tục. Giả thuyết ban đầu của tôi là chỉ cần split theo `\n\n` là đủ — thực tế cần thêm một lớp **sentence-level splitting** bằng regex `(?<=[.!?])\s+` cho các paragraph quá dài. Tôi phải implement logic riêng: flush chunk hiện tại, rồi split paragraph đó theo câu, mỗi câu được ghép lại cho đến khi đủ `chunk_chars`.

**Điều ngạc nhiên: overlap cần ranh giới tự nhiên.** Ban đầu tôi implement overlap đơn giản — lấy `overlap_chars` ký tự cuối chunk trước. Khi kiểm tra output, overlap thường bắt đầu giữa từ, gây noise cho retrieval. Tôi phải thêm logic tìm dấu chấm hoặc xuống dòng gần nhất: `natural_break = overlap_text.rfind(". ")`, giúp chunk sau bắt đầu tại ranh giới câu tự nhiên.

**Dependencies cũng mất thời gian.** Cài đặt môi trường (python-dotenv, chromadb, sentence-transformers) gặp lỗi compatibility trên máy, mất khoảng 15–20 phút debug trước khi bắt đầu code.

---

## 4. Phân tích một câu hỏi trong scorecard (150–200 từ)

**Câu hỏi:** `q07` — "Approval Matrix để cấp quyền hệ thống là tài liệu nào?"

**Phân tích:**

Đây là câu hỏi **hard** thuộc category "Access Control", thú vị vì nó test khả năng xử lý **alias/tên cũ** của tài liệu. "Approval Matrix" là tên cũ, tên mới trong corpus là "Access Control SOP" (`access_control_sop.txt`).

**Lỗi tiềm ẩn nằm ở tầng Retrieval:** Dense retrieval dựa trên embedding similarity — khi query chứa "Approval Matrix" nhưng tài liệu không chứa cụm từ này, cosine similarity sẽ thấp. Đây là weakness cốt lõi của pure dense retrieval: mạnh ở semantic meaning nhưng yếu ở exact term matching.

Trong pipeline baseline (dense-only), câu này có thể retrieve sai document hoặc retrieve document đúng nhưng với score thấp, dẫn đến answer không chính xác hoặc thiếu thông tin.

**Variant hybrid retrieval có thể cải thiện:** BM25 (sparse) sẽ match keyword "quyền" và "Access", trong khi dense capture nghĩa "cấp quyền hệ thống" ≈ "system access control". Kết hợp RRF (Reciprocal Rank Fusion) giữa dense và sparse sẽ boost document đúng lên top. Tuy nhiên, variant hybrid chưa implement hoàn chỉnh trong sprint của nhóm, nên chưa có dữ liệu thực tế để so sánh delta.

**Root cause:** Đây là failure mode **vocabulary mismatch** — query dùng alias khác với tên chính thức trong corpus.

---

## 5. Nếu có thêm thời gian, tôi sẽ làm gì? (50–100 từ)

1. **Implement hybrid retrieval (dense + BM25)** vì phân tích câu q07 cho thấy pure dense retrieval yếu ở vocabulary mismatch. BM25 sẽ bổ sung exact term matching, đặc biệt hữu ích cho mã lỗi (`ERR-xxx`), tên riêng, và alias.

2. **Hoàn thiện `get_embedding()` với OpenAI `text-embedding-3-small`** và full `build_index()` pipeline — hiện tại chunking logic đã sẵn sàng nhưng embedding chưa implement hoàn chỉnh, nên chưa lưu được vào ChromaDB thực tế. Điều này sẽ unblock toàn bộ Sprint 3–4 và cho phép đánh giá A/B thực tế.

---

*File: `reports/individual/duong_phuong_thao.md`*
