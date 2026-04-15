"""
Expectation suite đơn giản (không bắt buộc Great Expectations).

Sinh viên có thể thay bằng GE / pydantic / custom — miễn là có halt có kiểm soát.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass
class ExpectationResult:
    name: str
    passed: bool
    severity: str  # "warn" | "halt"
    detail: str


def run_expectations(cleaned_rows: List[Dict[str, Any]]) -> Tuple[List[ExpectationResult], bool]:
    """
    Trả về (results, should_halt).

    should_halt = True nếu có bất kỳ expectation severity halt nào fail.
    """
    results: List[ExpectationResult] = []

    # E1: có ít nhất 1 dòng sau clean
    ok = len(cleaned_rows) >= 1
    results.append(
        ExpectationResult(
            "min_one_row",
            ok,
            "halt",
            f"cleaned_rows={len(cleaned_rows)}",
        )
    )

    # E2: không doc_id rỗng
    bad_doc = [r for r in cleaned_rows if not (r.get("doc_id") or "").strip()]
    ok2 = len(bad_doc) == 0
    results.append(
        ExpectationResult(
            "no_empty_doc_id",
            ok2,
            "halt",
            f"empty_doc_id_count={len(bad_doc)}",
        )
    )

    # E3: policy refund không được chứa cửa sổ sai 14 ngày (sau khi đã fix)
    bad_refund = [
        r
        for r in cleaned_rows
        if r.get("doc_id") == "policy_refund_v4"
        and "14 ngày làm việc" in (r.get("chunk_text") or "")
    ]
    ok3 = len(bad_refund) == 0
    results.append(
        ExpectationResult(
            "refund_no_stale_14d_window",
            ok3,
            "halt",
            f"violations={len(bad_refund)}",
        )
    )

    # E4: chunk_text đủ dài
    short = [r for r in cleaned_rows if len((r.get("chunk_text") or "")) < 8]
    ok4 = len(short) == 0
    results.append(
        ExpectationResult(
            "chunk_min_length_8",
            ok4,
            "warn",
            f"short_chunks={len(short)}",
        )
    )

    # E5: effective_date đúng định dạng ISO sau clean (phát hiện parser lỏng)
    iso_bad = [
        r
        for r in cleaned_rows
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", (r.get("effective_date") or "").strip())
    ]
    ok5 = len(iso_bad) == 0
    results.append(
        ExpectationResult(
            "effective_date_iso_yyyy_mm_dd",
            ok5,
            "halt",
            f"non_iso_rows={len(iso_bad)}",
        )
    )

    # E6: không còn marker phép năm cũ 10 ngày trên doc HR (conflict version sau clean)
    bad_hr_annual = [
        r
        for r in cleaned_rows
        if r.get("doc_id") == "hr_leave_policy"
        and "10 ngày phép năm" in (r.get("chunk_text") or "")
    ]
    ok6 = len(bad_hr_annual) == 0
    results.append(
        ExpectationResult(
            "hr_leave_no_stale_10d_annual",
            ok6,
            "halt",
            f"violations={len(bad_hr_annual)}",
        )
    )
        # --- EXPECTATIONS MỚI (thêm bởi nhóm) ---

    # E7 (mới): exported_at phải là ISO datetime hợp lệ trên cleaned rows
    # metric_impact: nếu exported_at không đúng format → freshness_check sẽ không tính được SLA
    import re as _re
    bad_exported = [
        r
        for r in cleaned_rows
        if not _re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
            (r.get("exported_at") or "").strip(),
        )
    ]
    ok7 = len(bad_exported) == 0
    results.append(
        ExpectationResult(
            "exported_at_valid_iso_datetime",
            ok7,
            "halt",
            f"invalid_exported_at={len(bad_exported)}",
        )
    )

    # E8 (mới): Không chunk nào chứa marker "bản cũ"/"lỗi migration"/"sync cũ" 
    # → cảnh báo data chưa được clean triệt để
    # metric_impact: khi --no-refund-fix, chunk 3 chứa "bản sync cũ" → FAIL (warn)
    STALE_MARKERS = ["bản cũ", "sync cũ", "lỗi migration", "deprecated"]
    bad_marker = [
        r for r in cleaned_rows
        if any(m in (r.get("chunk_text") or "").lower() for m in STALE_MARKERS)
    ]
    ok8 = len(bad_marker) == 0
    results.append(
        ExpectationResult(
            "chunk_text_no_stale_markers",
            ok8,
            "warn",
            f"stale_marker_chunks={len(bad_marker)}",
        )
    )


    halt = any(not r.passed and r.severity == "halt" for r in results)
    return results, halt
