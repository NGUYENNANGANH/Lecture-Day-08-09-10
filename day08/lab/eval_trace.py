"""
eval_trace.py — Sprint 2: Production-Level Eval & Trace System (M5)
=====================================================================
Hệ thống tracing & evaluation nâng cấp cho RAG pipeline.

Sprint 2 Upgrades vs Sprint 1:
  ✓ Full chunk text logging (not just preview)
  ✓ Full prompt sent to LLM
  ✓ Per-step latency (embed → retrieve → generate → score)
  ✓ Precision@K metric
  ✓ Enhanced failure mode with root-cause layer
  ✓ Ground truth comparison
  ✓ CSV export for spreadsheet analysis
  ✓ Edge case handling (empty query, pipeline errors)

Cách chạy:
  python eval_trace.py                          # Batch test 10 câu (dense)
  python eval_trace.py --mode hybrid            # Batch test (hybrid)
  python eval_trace.py --query "SLA P1?"        # Chạy 1 câu
  python eval_trace.py --ab                     # A/B comparison
  python eval_trace.py --grading                # Trace grading questions
  python eval_trace.py --extended               # Chạy extended test set (20 câu)

Author: Quality & Trace Analyst (M5) — Sprint 2
"""

import csv
import json
import os
import re
import time
import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

# =============================================================================
# CẤU HÌNH
# =============================================================================

LAB_DIR = Path(__file__).parent
TEST_QUESTIONS_PATH = LAB_DIR / "data" / "test_questions.json"
EXTENDED_QUESTIONS_PATH = LAB_DIR / "data" / "extended_test_questions.json"
GRADING_QUESTIONS_PATH = LAB_DIR / "data" / "grading.json"
TRACES_DIR = LAB_DIR / "logs" / "traces"
RESULTS_DIR = LAB_DIR / "results"

# Sprint 2: Không giới hạn text — log full nội dung chunk + prompt
CHUNK_TEXT_FULL = True  # True = log full text, False = preview 200 chars


# =============================================================================
# HELPERS
# =============================================================================


def _now_iso() -> str:
    return datetime.now().isoformat()


def _generate_trace_id(query_id: str, mode: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"trace_{query_id}_{mode}_{ts}"


def _truncate(text: str, max_len: int = 200) -> str:
    if not text:
        return ""
    return text if len(text) <= max_len else text[:max_len] + "..."


def _estimate_tokens(text: str) -> int:
    return len(text) // 4 if text else 0


def _safe_get_score(eval_dict: Any, metric: str) -> Any:
    """Safely extract score from nested evaluation dict."""
    if not isinstance(eval_dict, dict):
        return None
    m = eval_dict.get(metric)
    if isinstance(m, dict):
        return m.get("score")
    return None


# =============================================================================
# PRECISION@K — Sprint 2 new metric
# =============================================================================


def compute_precision_at_k(
    chunks_used: List[Dict[str, Any]],
    expected_sources: List[str],
    k: int = 3,
) -> Dict[str, Any]:
    """
    Precision@K: Trong top-K chunks đã chọn, bao nhiêu chunk là relevant?

    Relevant = chunk có source khớp với expected_sources.

    Precision@3 = relevant_chunks_in_top3 / 3
    """
    if not expected_sources:
        return {"precision": None, "relevant_count": 0, "k": k, "notes": "No expected sources"}

    expected_clean = set()
    for s in expected_sources:
        expected_clean.add(s.split("/")[-1].split(".")[0].lower())

    top_k = chunks_used[:k]
    relevant = 0
    for chunk in top_k:
        src = chunk.get("metadata", {}).get("source", "").lower()
        if any(e in src for e in expected_clean):
            relevant += 1

    precision = relevant / k if k > 0 else 0
    return {
        "precision": round(precision, 4),
        "relevant_count": relevant,
        "k": k,
        "notes": f"{relevant}/{k} chunks relevant in top-{k}",
    }


# =============================================================================
# CORE TRACE FUNCTION — Sprint 2 Enhanced
# =============================================================================


def trace_single_query(
    query: str,
    query_id: str = "custom",
    retrieval_mode: str = "dense",
    top_k_search: int = 10,
    top_k_select: int = 3,
    use_rerank: bool = False,
    expected_answer: str = "",
    expected_sources: Optional[List[str]] = None,
    difficulty: str = "unknown",
    category: str = "unknown",
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Chạy 1 query qua RAG pipeline và ghi trace chi tiết.

    Sprint 2 enhancements:
      - Full chunk text (not truncated)
      - Full prompt sent to LLM
      - Separate timing: retrieval_ms, generation_ms, scoring_ms
      - Precision@K metric
      - Root-cause failure layer identification
      - Ground truth vs actual comparison
    """
    # Lazy imports — chỉ import khi cần để tránh lỗi circular
    from rag_answer import (
        rag_answer,
        build_context_block,
        build_grounded_prompt,
        retrieve_dense,
        retrieve_hybrid,
        retrieve_sparse,
    )

    if expected_sources is None:
        expected_sources = []

    # ─── Initialize trace structure ───
    trace = {
        "trace_id": _generate_trace_id(query_id, retrieval_mode),
        "timestamp": _now_iso(),
        "sprint": 2,
        # --- Input ---
        "input": {
            "query": query,
            "query_id": query_id,
        },
        # --- Config snapshot ---
        "config": {
            "retrieval_mode": retrieval_mode,
            "top_k_search": top_k_search,
            "top_k_select": top_k_select,
            "use_rerank": use_rerank,
            "llm_model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
            "embedding_model": "text-embedding-3-small",
            "temperature": 0,
            "max_tokens": 512,
        },
        # --- Retrieval trace ---
        "retrieval": {
            "all_candidates_count": 0,
            "selected_count": 0,
            "all_candidates": [],   # Sprint 2: top-K candidates BEFORE select
            "selected_chunks": [],  # Sprint 2: final chunks sent to LLM
        },
        # --- Generation trace ---
        "generation": {
            "full_prompt": "",      # Sprint 2: FULL prompt (not truncated)
            "prompt_tokens_est": 0,
            "context_block": "",    # Sprint 2: raw context block
            "answer": "",
            "sources_cited": [],
        },
        # --- Evaluation ---
        "evaluation": {
            "faithfulness": None,
            "relevance": None,
            "context_recall": None,
            "completeness": None,
            "precision_at_k": None,  # Sprint 2: new metric
            "overall_score": None,
            "overall_pass": None,
            "failure_mode": None,
            "failure_layer": None,   # Sprint 2: index/retrieval/generation
        },
        # --- Latency breakdown ---
        "latency": {
            "retrieval_ms": 0,
            "generation_ms": 0,
            "scoring_ms": 0,
            "total_ms": 0,
        },
        # --- Ground truth ---
        "expected": {
            "answer": expected_answer,
            "sources": expected_sources,
            "difficulty": difficulty,
            "category": category,
        },
        # --- Comparison ---
        "comparison": {
            "answer_matches_expected": None,
            "sources_match": None,
            "key_facts_found": [],
            "key_facts_missing": [],
        },
    }

    total_start = time.time()

    if verbose:
        print(f"\n{'─'*70}")
        print(f"🔍 [{query_id}] {query}")
        print(f"   ⚙️  mode={retrieval_mode} | search_k={top_k_search} | select_k={top_k_select}")

    # ===================== STEP 1: RETRIEVAL =====================
    retrieval_start = time.time()

    try:
        # --- 1a: Get ALL candidates (before select/rerank) ---
        if retrieval_mode == "dense":
            all_candidates = retrieve_dense(query, top_k=top_k_search)
        elif retrieval_mode == "sparse":
            all_candidates = retrieve_sparse(query, top_k=top_k_search)
        elif retrieval_mode == "hybrid":
            all_candidates = retrieve_hybrid(query, top_k=top_k_search)
        else:
            raise ValueError(f"Invalid retrieval_mode: {retrieval_mode}")

        retrieval_ms = (time.time() - retrieval_start) * 1000

        # --- 1b: Select top-k ---
        selected_chunks = all_candidates[:top_k_select]

        # --- Trace ALL candidates (Sprint 2: full ranking visibility) ---
        trace["retrieval"]["all_candidates_count"] = len(all_candidates)
        trace["retrieval"]["selected_count"] = len(selected_chunks)

        for rank, chunk in enumerate(all_candidates, 1):
            meta = chunk.get("metadata", {})
            candidate_trace = {
                "rank": rank,
                "selected": rank <= top_k_select,
                "score": round(chunk.get("score", 0), 6),
                "text": chunk.get("text", "") if CHUNK_TEXT_FULL else _truncate(chunk.get("text", "")),
                "text_length_chars": len(chunk.get("text", "")),
                "metadata": {
                    "source": meta.get("source", "unknown"),
                    "section": meta.get("section", ""),
                    "department": meta.get("department", "unknown"),
                    "effective_date": meta.get("effective_date", "unknown"),
                    "access": meta.get("access", "internal"),
                },
            }
            trace["retrieval"]["all_candidates"].append(candidate_trace)

        # Selected chunks separately for quick access
        for rank, chunk in enumerate(selected_chunks, 1):
            meta = chunk.get("metadata", {})
            trace["retrieval"]["selected_chunks"].append({
                "rank": rank,
                "score": round(chunk.get("score", 0), 6),
                "source": meta.get("source", "unknown"),
                "section": meta.get("section", ""),
                "text_preview": _truncate(chunk.get("text", ""), 150),
            })

        if verbose:
            print(f"   📄 Retrieved {len(all_candidates)} candidates → selected {len(selected_chunks)}")
            for i, c in enumerate(selected_chunks):
                src = c.get("metadata", {}).get("source", "?")
                sec = c.get("metadata", {}).get("section", "?")
                score = c.get("score", 0)
                print(f"      [{i+1}] score={score:.4f} | {src} | {sec}")

        # ===================== STEP 2: GENERATION =====================
        generation_start = time.time()

        # Build context and prompt
        context_block = build_context_block(selected_chunks)
        full_prompt = build_grounded_prompt(query, context_block)

        # Call LLM
        from rag_answer import call_llm
        answer = call_llm(full_prompt)

        generation_ms = (time.time() - generation_start) * 1000

        # Extract cited sources
        sources = list({c["metadata"].get("source", "unknown") for c in selected_chunks})

        # --- Trace generation ---
        trace["generation"]["full_prompt"] = full_prompt
        trace["generation"]["prompt_tokens_est"] = _estimate_tokens(full_prompt)
        trace["generation"]["context_block"] = context_block
        trace["generation"]["answer"] = answer
        trace["generation"]["sources_cited"] = sources

        trace["latency"]["retrieval_ms"] = round(retrieval_ms, 1)
        trace["latency"]["generation_ms"] = round(generation_ms, 1)

        if verbose:
            print(f"   💬 Answer: {_truncate(answer, 120)}")
            print(f"   📎 Sources: {sources}")

    except Exception as e:
        elapsed = (time.time() - retrieval_start) * 1000
        trace["generation"]["answer"] = f"PIPELINE_ERROR: {str(e)}"
        trace["evaluation"]["failure_mode"] = "pipeline_error"
        trace["evaluation"]["failure_layer"] = "system"
        trace["latency"]["retrieval_ms"] = round(elapsed, 1)

        if verbose:
            print(f"   ❌ Pipeline Error: {e}")

        answer = ""
        selected_chunks = []
        all_candidates = []
        sources = []

    # ===================== STEP 3: SCORING =====================
    scoring_start = time.time()

    try:
        from eval import (
            score_faithfulness,
            score_answer_relevance,
            score_context_recall,
            score_completeness,
        )

        if answer and "PIPELINE_ERROR" not in answer:
            faith = score_faithfulness(answer, selected_chunks)
            relev = score_answer_relevance(query, answer)
            recall = score_context_recall(selected_chunks, expected_sources)
            compl = score_completeness(query, answer, expected_answer)
            prec = compute_precision_at_k(selected_chunks, expected_sources, k=top_k_select)

            trace["evaluation"]["faithfulness"] = faith
            trace["evaluation"]["relevance"] = relev
            trace["evaluation"]["context_recall"] = recall
            trace["evaluation"]["completeness"] = compl
            trace["evaluation"]["precision_at_k"] = prec

            # Overall score
            valid_scores = [
                s for s in [
                    faith.get("score"),
                    relev.get("score"),
                    recall.get("score"),
                    compl.get("score"),
                ] if s is not None
            ]
            avg = sum(valid_scores) / len(valid_scores) if valid_scores else 0
            trace["evaluation"]["overall_score"] = round(avg, 2)
            trace["evaluation"]["overall_pass"] = avg >= 3.5

            # Failure classification
            fm, fl = _classify_failure_v2(
                answer, selected_chunks, all_candidates,
                faith, relev, recall, compl, expected_answer, expected_sources
            )
            trace["evaluation"]["failure_mode"] = fm
            trace["evaluation"]["failure_layer"] = fl

            # Ground truth comparison
            trace["comparison"] = _compare_with_ground_truth(
                answer, expected_answer, sources, expected_sources
            )

            if verbose:
                f_s = faith.get("score", "?")
                r_s = relev.get("score", "?")
                rc_s = recall.get("score", "?")
                c_s = compl.get("score", "?")
                p_s = prec.get("precision", "?")
                print(f"   📊 Scores: F={f_s} R={r_s} Rc={rc_s} C={c_s} P@K={p_s}")
                if fm:
                    print(f"   ⚠️  Failure: {fm} (layer: {fl})")
                status = "✅ PASS" if avg >= 3.5 else "❌ FAIL"
                print(f"   {status} (avg={avg:.2f})")

    except Exception as e:
        if verbose:
            print(f"   ⚠️  Scoring error: {e}")

    scoring_ms = (time.time() - scoring_start) * 1000
    total_ms = (time.time() - total_start) * 1000

    trace["latency"]["scoring_ms"] = round(scoring_ms, 1)
    trace["latency"]["total_ms"] = round(total_ms, 1)

    if verbose:
        r_ms = trace["latency"]["retrieval_ms"]
        g_ms = trace["latency"]["generation_ms"]
        s_ms = trace["latency"]["scoring_ms"]
        print(f"   ⏱️  Latency: retrieve={r_ms:.0f}ms | generate={g_ms:.0f}ms | score={s_ms:.0f}ms | total={total_ms:.0f}ms")

    return trace


# =============================================================================
# FAILURE MODE CLASSIFICATION v2 — Sprint 2
# =============================================================================


def _classify_failure_v2(
    answer: str,
    selected_chunks: List[Dict],
    all_candidates: List[Dict],
    faith: Dict,
    relev: Dict,
    recall: Dict,
    compl: Dict,
    expected_answer: str,
    expected_sources: List[str],
) -> Tuple[Optional[str], Optional[str]]:
    """
    Enhanced failure classification with root-cause layer.

    Returns:
        (failure_mode, failure_layer)
        failure_layer: "index" | "retrieval" | "generation" | None
    """
    is_abstain = "không đủ dữ liệu" in answer.lower() if answer else False
    f_score = faith.get("score") if faith else None
    rc_score = recall.get("score") if recall else None
    c_score = compl.get("score") if compl else None
    r_score = relev.get("score") if relev else None

    # 1. False abstain — context recall OK nhưng model abstain sai
    if is_abstain and rc_score and rc_score >= 4:
        if expected_answer and "không" not in expected_answer.lower()[:30]:
            return "false_abstain", "generation"

    # 2. Retrieval miss — expected source không trong candidates
    if rc_score is not None and rc_score <= 2:
        # Check nếu source nằm trong ALL candidates (index OK nhưng ranking miss)
        all_sources = set()
        for c in all_candidates:
            all_sources.add(c.get("metadata", {}).get("source", "").lower())

        expected_clean = set()
        for s in expected_sources:
            expected_clean.add(s.split("/")[-1].split(".")[0].lower())

        in_candidates = any(
            any(ec in src for ec in expected_clean)
            for src in all_sources
        )

        if in_candidates:
            return "ranking_miss", "retrieval"  # Index OK, ranking bad
        else:
            return "retrieval_miss", "index"  # Not even in candidates → index issue

    # 3. Hallucination
    if f_score and f_score <= 2 and not is_abstain:
        return "hallucination", "generation"

    # 4. Irrelevant answer
    if r_score and r_score <= 2:
        return "irrelevant", "generation"

    # 5. Incomplete answer
    if c_score and c_score <= 2:
        return "incomplete", "generation"

    return None, None


# =============================================================================
# GROUND TRUTH COMPARISON — Sprint 2
# =============================================================================


def _compare_with_ground_truth(
    answer: str,
    expected_answer: str,
    actual_sources: List[str],
    expected_sources: List[str],
) -> Dict[str, Any]:
    """
    So sánh answer thực tế với ground truth.
    Trích xuất key facts từ expected answer và kiểm tra.
    """
    if not expected_answer:
        return {
            "answer_matches_expected": None,
            "sources_match": None,
            "key_facts_found": [],
            "key_facts_missing": [],
        }

    answer_lower = answer.lower() if answer else ""
    expected_lower = expected_answer.lower()

    # Extract key facts: numbers, proper nouns, technical terms
    # Numbers (e.g., "15 phút", "4 giờ", "7 ngày", "5 lần")
    number_patterns = re.findall(r'\d+\s*(?:phút|giờ|ngày|lần|%|tháng|tuần)', expected_lower)
    # Key phrases (3+ word sequences excluding stopwords)
    key_phrases = re.findall(r'[A-Za-zÀ-ỹ]{3,}(?:\s+[A-Za-zÀ-ỹ]{3,}){1,3}', expected_lower)

    key_facts = list(set(number_patterns + key_phrases[:5]))  # max 5 phrases

    found = [f for f in key_facts if f in answer_lower]
    missing = [f for f in key_facts if f not in answer_lower]

    # Source match
    expected_clean = {s.split("/")[-1].split(".")[0].lower() for s in expected_sources}
    actual_clean = {s.split("/")[-1].split(".")[0].lower() for s in actual_sources if s}
    sources_match = expected_clean.issubset(actual_clean) if expected_clean else None

    return {
        "answer_matches_expected": len(found) / len(key_facts) if key_facts else None,
        "sources_match": sources_match,
        "key_facts_found": found,
        "key_facts_missing": missing,
    }


# =============================================================================
# BATCH TEST RUNNER
# =============================================================================


def run_batch_trace(
    retrieval_mode: str = "dense",
    test_questions_path: Optional[Path] = None,
    verbose: bool = True,
) -> List[Dict[str, Any]]:
    """Chạy batch test và tạo traces cho tất cả câu hỏi."""
    if test_questions_path is None:
        test_questions_path = TEST_QUESTIONS_PATH

    with open(test_questions_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    print(f"\n{'='*70}")
    print(f"📋 BATCH TRACE: {len(questions)} questions | mode={retrieval_mode}")
    print(f"{'='*70}")

    traces = []
    for q in questions:
        trace = trace_single_query(
            query=q["question"],
            query_id=q.get("id", "unknown"),
            retrieval_mode=retrieval_mode,
            expected_answer=q.get("expected_answer", ""),
            expected_sources=q.get("expected_sources", []),
            difficulty=q.get("difficulty", "unknown"),
            category=q.get("category", "unknown"),
            verbose=verbose,
        )
        traces.append(trace)

    # Save
    json_path = _save_traces_json(traces, f"batch_{retrieval_mode}")
    csv_path = _save_traces_csv(traces, f"batch_{retrieval_mode}")
    md_path = _save_summary_md(traces, f"batch_{retrieval_mode}")

    # Print summary
    _print_results_table(traces, retrieval_mode)

    return traces


def run_ab_trace(verbose: bool = True) -> Dict[str, List[Dict]]:
    """A/B comparison traces: baseline (dense) vs variant (hybrid)."""
    print(f"\n{'='*70}")
    print("🔬 A/B TRACE COMPARISON")
    print(f"{'='*70}")

    baseline = run_batch_trace("dense", verbose=verbose)
    variant = run_batch_trace("hybrid", verbose=verbose)

    _print_ab_comparison(baseline, variant)

    return {"baseline": baseline, "variant": variant}


def run_grading_trace(verbose: bool = True) -> List[Dict[str, Any]]:
    """Trace cho grading questions."""
    if not GRADING_QUESTIONS_PATH.exists():
        print(f"❌ File not found: {GRADING_QUESTIONS_PATH}")
        return []
    return run_batch_trace(
        retrieval_mode="hybrid",
        test_questions_path=GRADING_QUESTIONS_PATH,
        verbose=verbose,
    )


def run_extended_trace(mode: str = "dense", verbose: bool = True) -> List[Dict[str, Any]]:
    """Chạy extended test set (20 câu bao gồm edge cases)."""
    if not EXTENDED_QUESTIONS_PATH.exists():
        print(f"❌ File not found: {EXTENDED_QUESTIONS_PATH}")
        print("   Generating extended test set...")
        _generate_extended_test_set()

    return run_batch_trace(
        retrieval_mode=mode,
        test_questions_path=EXTENDED_QUESTIONS_PATH,
        verbose=verbose,
    )


# =============================================================================
# OUTPUT: JSON / CSV / MARKDOWN
# =============================================================================


def _save_traces_json(traces: List[Dict], label: str) -> Path:
    """Lưu full traces ra JSON."""
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = TRACES_DIR / f"traces_{label}_{ts}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(traces, f, ensure_ascii=False, indent=2)

    print(f"\n💾 JSON traces → {filepath}")
    return filepath


def _save_traces_csv(traces: List[Dict], label: str) -> Path:
    """Sprint 2: Export traces ra CSV cho phân tích bằng spreadsheet."""
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = TRACES_DIR / f"traces_{label}_{ts}.csv"

    headers = [
        "query_id", "category", "difficulty", "query",
        "answer", "expected_answer",
        "retrieval_mode", "candidates_count", "selected_count",
        "top1_source", "top1_score", "top1_section",
        "faithfulness", "relevance", "context_recall", "completeness",
        "precision_at_k", "overall_score", "pass",
        "failure_mode", "failure_layer",
        "sources_match", "key_facts_found", "key_facts_missing",
        "retrieval_ms", "generation_ms", "total_ms",
    ]

    rows = []
    for t in traces:
        ev = t.get("evaluation", {})
        comp = t.get("comparison", {})
        lat = t.get("latency", {})
        sel = t["retrieval"].get("selected_chunks", [])

        row = {
            "query_id": t["input"]["query_id"],
            "category": t["expected"].get("category", ""),
            "difficulty": t["expected"].get("difficulty", ""),
            "query": t["input"]["query"],
            "answer": t["generation"].get("answer", "")[:300],
            "expected_answer": t["expected"].get("answer", "")[:300],
            "retrieval_mode": t["config"]["retrieval_mode"],
            "candidates_count": t["retrieval"].get("all_candidates_count", 0),
            "selected_count": t["retrieval"].get("selected_count", 0),
            "top1_source": sel[0]["source"] if sel else "",
            "top1_score": sel[0]["score"] if sel else "",
            "top1_section": sel[0].get("section", "") if sel else "",
            "faithfulness": _safe_get_score(ev, "faithfulness"),
            "relevance": _safe_get_score(ev, "relevance"),
            "context_recall": _safe_get_score(ev, "context_recall"),
            "completeness": _safe_get_score(ev, "completeness"),
            "precision_at_k": ev.get("precision_at_k", {}).get("precision") if isinstance(ev.get("precision_at_k"), dict) else None,
            "overall_score": ev.get("overall_score"),
            "pass": ev.get("overall_pass"),
            "failure_mode": ev.get("failure_mode", ""),
            "failure_layer": ev.get("failure_layer", ""),
            "sources_match": comp.get("sources_match"),
            "key_facts_found": len(comp.get("key_facts_found", [])),
            "key_facts_missing": len(comp.get("key_facts_missing", [])),
            "retrieval_ms": lat.get("retrieval_ms", 0),
            "generation_ms": lat.get("generation_ms", 0),
            "total_ms": lat.get("total_ms", 0),
        }
        rows.append(row)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    print(f"📊 CSV export → {filepath}")
    return filepath


def _save_summary_md(traces: List[Dict], label: str) -> Path:
    """Markdown summary report."""
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = TRACES_DIR / f"summary_{label}_{ts}.md"

    metrics = ["faithfulness", "relevance", "context_recall", "completeness"]

    md = f"# Eval Trace Summary: {label}\n"
    md += f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  \n"
    md += f"**Sprint:** 2  \n"
    md += f"**Queries:** {len(traces)}  \n\n"

    # Averages
    md += "## Average Scores\n\n"
    md += "| Metric | Score | Notes |\n|--------|-------|-------|\n"
    for metric in metrics:
        scores = [_safe_get_score(t["evaluation"], metric) for t in traces]
        scores = [s for s in scores if s is not None]
        avg = sum(scores) / len(scores) if scores else None
        status = "✅" if (avg and avg >= 4) else ("⚠️" if (avg and avg >= 3) else "❌") if avg else "—"
        md += f"| {metric.replace('_',' ').title()} | {f'{avg:.2f}/5' if avg else 'N/A'} | {status} |\n"

    # Per-question detail
    md += "\n## Per-Question Results\n\n"
    md += "| ID | Diff. | F | R | Rc | C | P@K | Pass | Failure | Layer | Latency |\n"
    md += "|----|-------|---|---|----|----|-----|------|---------|-------|--------|\n"

    for t in traces:
        ev = t["evaluation"]
        qid = t["input"]["query_id"]
        diff = t["expected"].get("difficulty", "?")[:4]
        f_s = _safe_get_score(ev, "faithfulness") or "?"
        r_s = _safe_get_score(ev, "relevance") or "?"
        rc_s = _safe_get_score(ev, "context_recall") or "?"
        c_s = _safe_get_score(ev, "completeness") or "?"
        p_s = ev.get("precision_at_k", {}).get("precision", "?") if isinstance(ev.get("precision_at_k"), dict) else "?"
        passed = "✅" if ev.get("overall_pass") else "❌"
        fm = ev.get("failure_mode", "") or "—"
        fl = ev.get("failure_layer", "") or "—"
        lat = t["latency"].get("total_ms", 0)

        md += f"| {qid} | {diff} | {f_s} | {r_s} | {rc_s} | {c_s} | {p_s} | {passed} | {fm} | {fl} | {lat:.0f}ms |\n"

    # Failure analysis
    failures = [(t["evaluation"].get("failure_mode"), t["evaluation"].get("failure_layer"))
                for t in traces if t["evaluation"].get("failure_mode")]
    if failures:
        md += "\n## Failure Analysis\n\n"
        layers = Counter(fl for _, fl in failures)
        md += "### By Layer\n"
        for layer, cnt in layers.most_common():
            md += f"- **{layer}**: {cnt} failures\n"

        modes = Counter(fm for fm, _ in failures)
        md += "\n### By Mode\n"
        for mode, cnt in modes.most_common():
            md += f"- **{mode}**: {cnt} occurrences\n"
            for t in traces:
                if t["evaluation"].get("failure_mode") == mode:
                    md += f"  - `{t['input']['query_id']}`: {_truncate(t['input']['query'], 50)}\n"

    filepath.write_text(md, encoding="utf-8")
    print(f"📝 Summary → {filepath}")
    return filepath


# =============================================================================
# CONSOLE OUTPUT
# =============================================================================


def _print_results_table(traces: List[Dict], label: str) -> None:
    """Rich console table output."""
    print(f"\n{'='*80}")
    print(f"📊 RESULTS TABLE: {label} ({len(traces)} queries)")
    print(f"{'='*80}")

    header = (
        f"{'ID':<6} {'Cat':<14} {'Diff':<6} "
        f"{'F':>2} {'R':>2} {'Rc':>2} {'C':>2} {'P@K':>4} "
        f"{'Avg':>4} {'Pass':>4} {'Failure':<16} {'Layer':<10} {'ms':>5}"
    )
    print(header)
    print("─" * 80)

    total_pass = 0
    sums = {"f": 0, "r": 0, "rc": 0, "c": 0, "p": 0}
    counts = {"f": 0, "r": 0, "rc": 0, "c": 0, "p": 0}

    for t in traces:
        ev = t["evaluation"]
        qid = t["input"]["query_id"]
        cat = t["expected"].get("category", "?")[:12]
        diff = t["expected"].get("difficulty", "?")[:4]

        f_s = _safe_get_score(ev, "faithfulness")
        r_s = _safe_get_score(ev, "relevance")
        rc_s = _safe_get_score(ev, "context_recall")
        c_s = _safe_get_score(ev, "completeness")
        p_s = ev.get("precision_at_k", {}).get("precision") if isinstance(ev.get("precision_at_k"), dict) else None
        avg = ev.get("overall_score", 0) or 0
        passed = "✅" if ev.get("overall_pass") else "❌"
        fm = (ev.get("failure_mode") or "—")[:14]
        fl = (ev.get("failure_layer") or "—")[:8]
        lat = t["latency"].get("total_ms", 0)

        if ev.get("overall_pass"):
            total_pass += 1

        for key, val in [("f", f_s), ("r", r_s), ("rc", rc_s), ("c", c_s), ("p", p_s)]:
            if val is not None:
                sums[key] += val
                counts[key] += 1

        print(
            f"{qid:<6} {cat:<14} {diff:<6} "
            f"{str(f_s or '?'):>2} {str(r_s or '?'):>2} {str(rc_s or '?'):>2} {str(c_s or '?'):>2} "
            f"{f'{p_s:.1f}' if p_s is not None else '?':>4} "
            f"{avg:>4.1f} {passed:>4} {fm:<16} {fl:<10} {lat:>4.0f}ms"
        )

    # Averages
    print("─" * 80)
    f_a = sums["f"]/counts["f"] if counts["f"] else 0
    r_a = sums["r"]/counts["r"] if counts["r"] else 0
    rc_a = sums["rc"]/counts["rc"] if counts["rc"] else 0
    c_a = sums["c"]/counts["c"] if counts["c"] else 0
    p_a = sums["p"]/counts["p"] if counts["p"] else 0

    print(
        f"{'AVG':<6} {'':14} {'':6} "
        f"{f_a:>2.0f} {r_a:>2.0f} {rc_a:>2.0f} {c_a:>2.0f} {p_a:>4.1f} "
        f"{'':>4} {total_pass}/{len(traces)}"
    )

    # Failure summary
    failures = [t["evaluation"].get("failure_mode") for t in traces if t["evaluation"].get("failure_mode")]
    if failures:
        print(f"\n⚠️  Failures: {Counter(failures).most_common()}")

    latencies = [t["latency"].get("total_ms", 0) for t in traces]
    print(f"⏱️  Latency: avg={sum(latencies)/len(latencies):.0f}ms | "
          f"min={min(latencies):.0f}ms | max={max(latencies):.0f}ms")


def _print_ab_comparison(baseline: List[Dict], variant: List[Dict]) -> None:
    """A/B comparison output."""
    print(f"\n{'='*70}")
    print("🔬 A/B COMPARISON: Baseline (dense) vs Variant (hybrid)")
    print(f"{'='*70}")

    metrics = ["faithfulness", "relevance", "context_recall", "completeness"]

    def _avg(traces, metric):
        scores = [_safe_get_score(t["evaluation"], metric) for t in traces]
        scores = [s for s in scores if s is not None]
        return sum(scores)/len(scores) if scores else None

    print(f"{'Metric':<20} {'Baseline':>10} {'Variant':>10} {'Delta':>8} {'Winner':>8}")
    print("─" * 60)

    for m in metrics:
        b = _avg(baseline, m)
        v = _avg(variant, m)
        d = (v - b) if (b is not None and v is not None) else None
        w = ("Variant" if d and d > 0.1 else ("Baseline" if d and d < -0.1 else "Tie")) if d is not None else "N/A"
        print(f"{m:<20} {f'{b:.2f}' if b else 'N/A':>10} {f'{v:.2f}' if v else 'N/A':>10} "
              f"{f'{d:+.2f}' if d is not None else 'N/A':>8} {w:>8}")

    # Pass rate
    b_pass = sum(1 for t in baseline if t["evaluation"].get("overall_pass"))
    v_pass = sum(1 for t in variant if t["evaluation"].get("overall_pass"))
    print(f"\n{'Pass Rate':<20} {f'{b_pass}/{len(baseline)}':>10} {f'{v_pass}/{len(variant)}':>10}")


# =============================================================================
# EXTENDED TEST SET GENERATOR — Sprint 2
# =============================================================================


def _generate_extended_test_set() -> None:
    """Tạo bộ extended test set gồm 20 câu (gốc 10 + 10 mới)."""

    # Load câu gốc
    with open(TEST_QUESTIONS_PATH, "r", encoding="utf-8") as f:
        original = json.load(f)

    # 5 câu multi-hop / suy luận
    multi_hop = [
        {
            "id": "mh01",
            "question": "So sánh quy trình phê duyệt cấp quyền Level 2 và Level 3 — khác nhau ở điểm nào?",
            "expected_answer": "Level 2 cần Line Manager + IT Admin phê duyệt. Level 3 cần thêm IT Security. Sự khác biệt chính là Level 3 yêu cầu thêm lớp phê duyệt bảo mật.",
            "expected_sources": ["it/access-control-sop.md"],
            "difficulty": "hard",
            "category": "Multi-hop",
            "note": "So sánh 2 sections trong cùng 1 doc"
        },
        {
            "id": "mh02",
            "question": "Nếu xảy ra sự cố P1 lúc nửa đêm và cần cấp quyền khẩn cấp, ai phê duyệt và quyền tồn tại bao lâu?",
            "expected_answer": "Tech Lead phê duyệt bằng lời, On-call IT Admin cấp quyền tạm thời max 24 giờ. Sau 24 giờ phải có ticket chính thức.",
            "expected_sources": ["it/access-control-sop.md", "support/sla-p1-2026.pdf"],
            "difficulty": "hard",
            "category": "Cross-doc",
            "note": "Cần kết hợp SLA doc + Access Control SOP"
        },
        {
            "id": "mh03",
            "question": "Nhân viên mới (chưa qua probation) muốn làm remote và cần cấp quyền VPN — quy trình đầy đủ là gì?",
            "expected_answer": "Nhân viên chưa qua probation không được làm remote. VPN access cần request qua IT Helpdesk.",
            "expected_sources": ["hr/leave-policy-2026.pdf", "support/helpdesk-faq.md"],
            "difficulty": "hard",
            "category": "Cross-doc",
            "note": "Kết hợp HR policy + IT FAQ"
        },
        {
            "id": "mh04",
            "question": "Liệt kê tất cả các trường hợp KHÔNG được hoàn tiền theo chính sách hiện hành.",
            "expected_answer": "Ngoại lệ không hoàn tiền: (1) Sản phẩm kỹ thuật số (license key, subscription), (2) Sản phẩm đã kích hoạt/sử dụng, (3) Đơn hàng quá 7 ngày làm việc.",
            "expected_sources": ["policy/refund-v4.pdf"],
            "difficulty": "hard",
            "category": "Multi-section",
            "note": "Cần tổng hợp từ nhiều section trong cùng 1 doc"
        },
        {
            "id": "mh05",
            "question": "SLA P1 hiện tại khác gì so với phiên bản trước? Liệt kê cụ thể các thay đổi.",
            "expected_answer": "Resolution time giảm từ 6 giờ xuống 4 giờ. First response vẫn 15 phút.",
            "expected_sources": ["support/sla-p1-2026.pdf"],
            "difficulty": "hard",
            "category": "Version comparison",
            "note": "Cần tìm section lịch sử phiên bản"
        },
    ]

    # 5 câu edge case
    edge_cases = [
        {
            "id": "ec01",
            "question": "ERR-500-TIMEOUT xảy ra khi nào và cách khắc phục?",
            "expected_answer": "Không có thông tin về ERR-500-TIMEOUT trong tài liệu hiện có.",
            "expected_sources": [],
            "difficulty": "hard",
            "category": "Abstain",
            "note": "Mã lỗi không tồn tại — must abstain"
        },
        {
            "id": "ec02",
            "question": "Chính sách hoàn tiền có áp dụng cho đối tác (partner) không?",
            "expected_answer": "Tài liệu chính sách hoàn tiền không đề cập đến đối tác. Chính sách hiện tại chỉ áp dụng cho khách hàng.",
            "expected_sources": ["policy/refund-v4.pdf"],
            "difficulty": "hard",
            "category": "Ambiguous",
            "note": "Query về đối tượng không có trong docs — partial context"
        },
        {
            "id": "ec03",
            "question": "What is the SLA for P1 tickets?",
            "expected_answer": "P1 ticket SLA: first response within 15 minutes, resolution within 4 hours.",
            "expected_sources": ["support/sla-p1-2026.pdf"],
            "difficulty": "medium",
            "category": "Bilingual",
            "note": "English query on Vietnamese docs"
        },
        {
            "id": "ec04",
            "question": "Tại sao công ty lại chọn chính sách hoàn tiền 7 ngày?",
            "expected_answer": "Tài liệu không giải thích lý do chọn 7 ngày. Chỉ nêu quy định là 7 ngày làm việc.",
            "expected_sources": ["policy/refund-v4.pdf"],
            "difficulty": "hard",
            "category": "Why-question",
            "note": "Hỏi 'tại sao' — docs chỉ có 'cái gì'"
        },
        {
            "id": "ec05",
            "question": "Mật khẩu cần đổi mấy ngày một lần, và nếu quên mật khẩu thì phải làm gì?",
            "expected_answer": "Mật khẩu phải đổi mỗi 90 ngày, hệ thống nhắc 7 ngày trước. Quên mật khẩu: tự reset qua SSO portal hoặc liên hệ IT Helpdesk.",
            "expected_sources": ["support/helpdesk-faq.md"],
            "difficulty": "medium",
            "category": "Multi-part",
            "note": "2 câu hỏi trong 1 — cần trả lời cả 2 phần"
        },
    ]

    extended = original + multi_hop + edge_cases

    LAB_DIR.joinpath("data").mkdir(parents=True, exist_ok=True)
    with open(EXTENDED_QUESTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(extended, f, ensure_ascii=False, indent=2)

    print(f"✅ Extended test set created: {EXTENDED_QUESTIONS_PATH} ({len(extended)} questions)")


# =============================================================================
# CONVENIENCE
# =============================================================================


def quick_trace(query: str, mode: str = "dense") -> Dict:
    """Quick trace cho 1 query — dùng khi debug nhanh."""
    return trace_single_query(query=query, query_id="debug", retrieval_mode=mode, verbose=True)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="RAG Pipeline — Eval Trace v2 (M5 Sprint 2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python eval_trace.py                          # Batch test 10 câu (dense)
  python eval_trace.py --mode hybrid            # Batch test (hybrid)
  python eval_trace.py --query "SLA P1?"        # Single query trace
  python eval_trace.py --ab                     # A/B comparison
  python eval_trace.py --grading                # Grading questions
  python eval_trace.py --extended               # Extended 20-question test
  python eval_trace.py --extended --mode hybrid # Extended + hybrid mode
        """,
    )

    parser.add_argument("--query", type=str, help="Trace 1 query cụ thể")
    parser.add_argument("--mode", type=str, default="dense",
                        choices=["dense", "sparse", "hybrid"])
    parser.add_argument("--ab", action="store_true", help="A/B comparison")
    parser.add_argument("--grading", action="store_true", help="Grading questions")
    parser.add_argument("--extended", action="store_true", help="Extended 20-question test")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-query output")

    args = parser.parse_args()
    verbose = not args.quiet

    print("=" * 70)
    print("🔬 RAG Pipeline — Eval Trace v2 (M5 Sprint 2)")
    print("=" * 70)

    if args.query:
        trace = trace_single_query(query=args.query, retrieval_mode=args.mode, verbose=verbose)
        _save_traces_json([trace], f"single_{args.mode}")
    elif args.ab:
        run_ab_trace(verbose=verbose)
    elif args.grading:
        run_grading_trace(verbose=verbose)
    elif args.extended:
        run_extended_trace(mode=args.mode, verbose=verbose)
    else:
        run_batch_trace(retrieval_mode=args.mode, verbose=verbose)

    print(f"\n{'='*70}")
    print("✅ Eval trace v2 complete!")
    print(f"📁 Traces: {TRACES_DIR}")
    print(f"{'='*70}")
