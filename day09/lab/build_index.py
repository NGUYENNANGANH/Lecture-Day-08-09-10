"""
build_index.py — Build ChromaDB index từ các tài liệu nội bộ.
Sprint 2: Tạo index cho retrieval_worker.

Chạy: python build_index.py
"""

import os
import re
import chromadb
from sentence_transformers import SentenceTransformer


DOCS_DIR = "./data/docs"
CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "day09_docs"

# Chunk splitting config
CHUNK_SIZE = 500  # ký tự tối đa mỗi chunk
CHUNK_OVERLAP = 50  # overlap giữa các chunk


def split_by_sections(text: str, source: str) -> list[dict]:
    """Tách tài liệu thành chunks theo sections (=== ... ===)."""
    # Split theo section headers
    pattern = r"===\s*(.*?)\s*==="
    sections = re.split(pattern, text)

    chunks = []
    # sections[0] = header trước section đầu tiên
    # sections[1] = tên section 1, sections[2] = nội dung section 1, ...

    # Header chunk (metadata)
    header = sections[0].strip()
    if header:
        chunks.append({
            "text": header,
            "source": source,
            "section": "header",
        })

    # Section chunks
    for i in range(1, len(sections), 2):
        section_name = sections[i].strip() if i < len(sections) else ""
        section_content = sections[i + 1].strip() if i + 1 < len(sections) else ""

        if not section_content:
            continue

        # Nếu section ngắn, giữ nguyên
        if len(section_content) <= CHUNK_SIZE:
            chunks.append({
                "text": f"{section_name}\n{section_content}",
                "source": source,
                "section": section_name,
            })
        else:
            # Split section dài thành sub-chunks
            paragraphs = section_content.split("\n\n")
            current = ""
            for para in paragraphs:
                if len(current) + len(para) > CHUNK_SIZE and current:
                    chunks.append({
                        "text": f"{section_name}\n{current.strip()}",
                        "source": source,
                        "section": section_name,
                    })
                    current = para
                else:
                    current += "\n\n" + para if current else para
            if current.strip():
                chunks.append({
                    "text": f"{section_name}\n{current.strip()}",
                    "source": source,
                    "section": section_name,
                })

    return chunks


def build_index() -> None:
    """Build ChromaDB index từ tất cả docs."""
    print("[BUILD] Building ChromaDB index...")

    # Load embedding model
    print("  Loading SentenceTransformer model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    # Init ChromaDB
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    # Xóa collection cũ nếu có, tạo mới
    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"  [DEL] Deleted old collection '{COLLECTION_NAME}'")
    except Exception:
        pass

    collection = client.get_or_create_collection(
        COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    # Process mỗi file
    all_chunks: list[dict] = []
    for fname in sorted(os.listdir(DOCS_DIR)):
        fpath = os.path.join(DOCS_DIR, fname)
        if not os.path.isfile(fpath) or not fname.endswith(".txt"):
            continue

        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        chunks = split_by_sections(content, fname)
        all_chunks.extend(chunks)
        print(f"  [DOC] {fname}: {len(chunks)} chunks")

    if not all_chunks:
        print("[ERROR] No chunks found! Check docs directory.")
        return

    # Embed & add
    print(f"\n  Embedding {len(all_chunks)} chunks...")
    texts = [c["text"] for c in all_chunks]
    embeddings = model.encode(texts, show_progress_bar=True).tolist()

    ids = [f"chunk_{i:03d}" for i in range(len(all_chunks))]
    metadatas = [
        {"source": c["source"], "section": c.get("section", "")}
        for c in all_chunks
    ]

    collection.add(
        ids=ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    print(f"\n[OK] Index built: {collection.count()} chunks in '{COLLECTION_NAME}'")

    # Verify
    print("\n[VERIFY] Verification query: 'SLA P1'")
    test_q = model.encode(["SLA ticket P1 là bao lâu?"]).tolist()
    results = collection.query(
        query_embeddings=test_q,
        n_results=3,
        include=["documents", "distances", "metadatas"],
    )
    for i, (doc, dist, meta) in enumerate(zip(
        results["documents"][0],
        results["distances"][0],
        results["metadatas"][0],
    )):
        score = round(1 - dist, 4)
        print(f"  [{score:.4f}] {meta['source']}: {doc[:80]}...")


if __name__ == "__main__":
    build_index()
