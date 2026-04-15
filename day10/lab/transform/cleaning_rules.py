"""
Cleaning rules — raw export → cleaned rows + quarantine.

Baseline gồm các failure mode mở rộng (allowlist doc_id, parse ngày, HR stale version).
Sinh viên thêm ≥3 rule mới: mỗi rule phải ghi `metric_impact` (xem README — chống trivial).
"""

from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Khớp export hợp lệ trong lab (mở rộng khi nhóm thêm doc mới — phải đồng bộ contract).
ALLOWED_DOC_IDS = frozenset(
    {
        "policy_refund_v4",
        "sla_p1_2026",
        "it_helpdesk_faq",
        "hr_leave_policy",
    }
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")

# Các pattern phát hiện ghi chú migration / sync nội bộ bị leak vào dữ liệu production.
_MIGRATION_PATTERNS = re.compile(
    r"lỗi migration|sync cũ|bản cũ|migrated from|legacy merge",
    re.IGNORECASE,
)

# Minimum meaningful chunk length — chunks shorter than this are unlikely to
# carry useful policy information and can pollute retrieval results.
MIN_CHUNK_LENGTH = 10


def _norm_text(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()


def _stable_chunk_id(doc_id: str, chunk_text: str, seq: int) -> str:
    h = hashlib.sha256(f"{doc_id}|{chunk_text}|{seq}".encode("utf-8")).hexdigest()[:16]
    return f"{doc_id}_{seq}_{h}"


def _normalize_effective_date(raw: str) -> Tuple[str, str]:
    """
    Trả về (iso_date, error_reason).
    iso_date rỗng nếu không parse được.
    """
    s = (raw or "").strip()
    if not s:
        return "", "empty_effective_date"
    if _ISO_DATE.match(s):
        return s, ""
    m = _DMY_SLASH.match(s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}", ""
    return "", "invalid_effective_date_format"


# ──────────────────────────────────────────────────────────────────────
# NEW RULE 7 — Strip BOM & invisible control characters
# ──────────────────────────────────────────────────────────────────────

def strip_bom_and_control_chars(text: str) -> str:
    """Loại bỏ BOM (\ufeff), zero-width spaces và ký tự điều khiển vô hình.

    Các ký tự này có thể lọt vào khi export từ Excel / legacy DB, khiến
    dedup bằng string comparison bị sai (2 chunk giống nhau nhưng hash khác).

    metric_impact:
        - Ngăn false-negative dedup: chunk có BOM prefix sẽ vượt qua
          _norm_text() check ở baseline, tạo vector trùng trong index.
        - Khi inject dòng có BOM vào Sprint 3, rule này bắt được trong khi
          baseline thì không.
    """
    # Loại BOM đầu chuỗi
    text = text.lstrip("\ufeff")
    # Loại zero-width spaces, soft hyphens, zero-width joiners
    text = text.replace("\u200b", "")   # zero-width space
    text = text.replace("\u200c", "")   # zero-width non-joiner
    text = text.replace("\u200d", "")   # zero-width joiner
    text = text.replace("\u00ad", "")   # soft hyphen
    text = text.replace("\ufeff", "")   # BOM ở giữa chuỗi
    # Loại control chars (category Cc) nhưng giữ whitespace thường
    text = "".join(
        ch for ch in text
        if ch in ("\n", "\r", "\t", " ") or unicodedata.category(ch) != "Cc"
    )
    return text


# ──────────────────────────────────────────────────────────────────────
# NEW RULE 8 — Quarantine rows with leaked migration/sync annotations
# ──────────────────────────────────────────────────────────────────────

def quarantine_migration_note(row: Dict[str, Any]) -> str | None:
    """Phát hiện chunk_text chứa ghi chú migration / sync nội bộ bị leak.

    Các annotation như "lỗi migration", "sync cũ", "bản cũ" là metadata
    quy trình nội bộ — không nên phục vụ cho end-user qua RAG.

    metric_impact:
        - Trên CSV mẫu, row 4 (chunk_id=3, policy_refund_v4) chứa
          "ghi chú: bản sync cũ policy-v3 — lỗi migration" → bị quarantine.
        - quarantine_records tăng 4 → 5, cleaned_records giảm 6 → 5.

    Returns:
        Reason string nếu cần quarantine, None nếu row sạch.
    """
    text = row.get("chunk_text", "")
    if _MIGRATION_PATTERNS.search(text):
        return "leaked_migration_annotation"
    return None


# ──────────────────────────────────────────────────────────────────────
# NEW RULE 9 — Normalize whitespace (non-breaking, tabs, multi-space)
# ──────────────────────────────────────────────────────────────────────

def normalize_whitespace_chunk(text: str) -> str:
    """Chuẩn hoá khoảng trắng: collapse \\xa0, tab, multi-space thành 1 space.

    Đảm bảo văn bản đồng nhất trước embedding — tránh near-duplicate vectors
    chỉ khác nhau bởi loại khoảng trắng.

    metric_impact:
        - Khi inject row có \\xa0 (non-breaking space) thay vì space thường,
          baseline dedup KHÔNG bắt vì _norm_text() chỉ xử lý ASCII space.
          Rule này normalize trước khi so sánh, giúp dedup catch đúng.
        - Cải thiện embedding consistency: chunks giống nhau sinh vector
          gần nhau hơn.
    """
    # Thay thế non-breaking space và các biến thể Unicode space
    text = text.replace("\xa0", " ")       # non-breaking space
    text = text.replace("\u2007", " ")      # figure space
    text = text.replace("\u202f", " ")      # narrow no-break space
    text = text.replace("\u2003", " ")      # em space
    text = text.replace("\u2002", " ")      # en space
    text = text.replace("\t", " ")          # tab
    # Collapse multiple spaces thành single space
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


# ──────────────────────────────────────────────────────────────────────
# NEW RULE 10 — Validate minimum meaningful chunk length
# ──────────────────────────────────────────────────────────────────────

def validate_chunk_min_length(text: str, min_len: int = MIN_CHUNK_LENGTH) -> bool:
    """Kiểm tra chunk_text đạt độ dài tối thiểu có nghĩa.

    Baseline chỉ kiểm tra empty; rule này nâng ngưỡng lên min_len ký tự.
    Chunk quá ngắn thường là noise (punctuation lẻ, số đơn, stub) và
    làm giảm precision khi retrieval.

    metric_impact:
        - Khi inject row với text = "OK" hay "N/A", baseline cho qua nhưng
          rule này quarantine → quarantine_records tăng.
        - Expectation chunk_min_length_8 kiểm tương tự ở tầng validate;
          rule này chặn sớm hơn ở tầng clean, giảm false positive
          trong embedding layer.

    Returns:
        True nếu chunk đủ dài (hợp lệ), False nếu quá ngắn.
    """
    return len(text.strip()) >= min_len


def load_raw_csv(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def clean_rows(
    rows: List[Dict[str, str]],
    *,
    apply_refund_window_fix: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Trả về (cleaned, quarantine).

    Baseline (mở rộng theo narrative Day 10):
    1) Quarantine: doc_id không thuộc allowlist (export lạ / catalog sai).
    2) Chuẩn hoá effective_date sang YYYY-MM-DD; quarantine nếu không parse được.
    3) Quarantine: chunk hr_leave_policy có effective_date < 2026-01-01 (bản HR cũ / conflict version).
    4) Quarantine: chunk_text rỗng hoặc effective_date rỗng sau chuẩn hoá.
    5) Loại trùng nội dung chunk_text (giữ bản đầu).
    6) Fix stale refund: policy_refund_v4 chứa '14 ngày làm việc' → 7 ngày.
    """
    quarantine: List[Dict[str, Any]] = []
    seen_text: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    seq = 0

    for raw in rows:
        doc_id = raw.get("doc_id", "")
        text = raw.get("chunk_text", "")
        eff_raw = raw.get("effective_date", "")
        exported_at = raw.get("exported_at", "")

        # ── Baseline rule 1: allowlist doc_id ──
        if doc_id not in ALLOWED_DOC_IDS:
            quarantine.append({**raw, "reason": "unknown_doc_id"})
            continue

        # ── Baseline rule 2: effective_date normalization ──
        eff_norm, eff_err = _normalize_effective_date(eff_raw)
        if eff_err == "empty_effective_date":
            quarantine.append({**raw, "reason": "missing_effective_date"})
            continue
        if eff_err == "invalid_effective_date_format":
            quarantine.append({**raw, "reason": eff_err, "effective_date_raw": eff_raw})
            continue

        # ── Baseline rule 3: quarantine stale HR records ──
        if doc_id == "hr_leave_policy" and eff_norm < "2026-01-01":
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_policy_effective_date",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        # ── NEW RULE 7: strip BOM & control chars ──
        text = strip_bom_and_control_chars(text)

        # ── NEW RULE 9: normalize whitespace ──
        text = normalize_whitespace_chunk(text)

        # ── Baseline rule 4: quarantine empty chunk_text ──
        if not text:
            quarantine.append({**raw, "reason": "missing_chunk_text"})
            continue

        # ── NEW RULE 10: min chunk length ──
        if not validate_chunk_min_length(text):
            quarantine.append({**raw, "reason": "chunk_too_short", "chunk_text_length": len(text)})
            continue

        # ── Baseline rule 5: deduplication ──
        key = _norm_text(text)
        if key in seen_text:
            quarantine.append({**raw, "reason": "duplicate_chunk_text"})
            continue
        seen_text.add(key)

        # ── Baseline rule 6: fix stale refund window ──
        fixed_text = text
        if apply_refund_window_fix and doc_id == "policy_refund_v4":
            if "14 ngày làm việc" in fixed_text:
                fixed_text = fixed_text.replace(
                    "14 ngày làm việc",
                    "7 ngày làm việc",
                )
                fixed_text += " [cleaned: stale_refund_window]"

        # ── NEW RULE 8: quarantine migration/sync annotations ──
        # (moved AFTER rule 6 so refund-fix eval can see "14 ngày" rows
        #  before they get quarantined by migration pattern match)
        migration_reason = quarantine_migration_note({**raw, "chunk_text": fixed_text})
        if migration_reason:
            quarantine.append({**raw, "reason": migration_reason})
            continue

        seq += 1
        cleaned.append(
            {
                "chunk_id": _stable_chunk_id(doc_id, fixed_text, seq),
                "doc_id": doc_id,
                "chunk_text": fixed_text,
                "effective_date": eff_norm,
                "exported_at": exported_at or "",
            }
        )

    return cleaned, quarantine


def write_cleaned_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at\n", encoding="utf-8")
        return
    fieldnames = ["chunk_id", "doc_id", "chunk_text", "effective_date", "exported_at"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_quarantine_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at,reason\n", encoding="utf-8")
        return
    keys: List[str] = []
    seen_k: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen_k:
                seen_k.add(k)
                keys.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore", restval="")
        w.writeheader()
        for r in rows:
            w.writerow(r)
