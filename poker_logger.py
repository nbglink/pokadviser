"""
Poker Advisor — centralized logging.

Пише два файла в ./logs/ до poker_live.py:

1. advisor.log — human-readable, ротиращ (5MB × 5 backups).
   Формат:
     2026-04-14 17:56:35.123 [LEVEL] [TAG] message
   Tags: [HAND] [SCAN] [UI] [CORRECTION] [ERROR]

2. scans.jsonl — machine-readable JSON Lines, 1 ред на scan.
   Schema:
     {
       "ts": iso8601,
       "hand_id": str|null,
       "window_title": str|null,
       "window_rect": [x1,y1,x2,y2]|null,
       "duration_ms": int,
       "cards": [[rank,suit], [rank,suit]]|null,
       "confidence": float,
       "details": [[r,r_conf,s,s_conf], ...],
       "detectors": [str, ...],
       "calibrated": bool,
       "easyocr": bool,
       "tesseract": bool,
       "outcome": "pending"|"auto_accepted"|"confirm_accepted"|
                  "confirm_rejected"|"low_conf_fallback"|"error",
       "user_corrected_to": [[r,s],[r,s]]|null,  // попълва се при correction
       "error": str|null
     }

Records в scans.jsonl се identify-ват чрез scan_id (int monotonic).
Когато юзърът коригира карти, update-ваме последния scan запис със scan_id.

Usage:
    import poker_logger
    poker_logger.setup()         # веднъж при старт
    log = poker_logger.get_logger(__name__)
    log.info("[HAND] new hand #%s", hand_id)

    # За scan events:
    scan_id = poker_logger.record_scan({...})
    poker_logger.update_scan_outcome(scan_id, "auto_accepted")
    poker_logger.record_correction(scan_id, user_cards)
"""
from __future__ import annotations
import json
import logging
import logging.handlers
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ── Paths ──────────────────────────────────────────────────────────────
_MODULE_DIR = Path(__file__).resolve().parent
LOG_DIR = _MODULE_DIR / "logs"
ADVISOR_LOG = LOG_DIR / "advisor.log"
SCANS_JSONL = LOG_DIR / "scans.jsonl"
HANDS_JSONL = LOG_DIR / "hands.jsonl"

# ── State ──────────────────────────────────────────────────────────────
_initialized = False
_scan_counter = 0
_scan_lock = threading.Lock()
# Кеш на scan records keyed by scan_id → за да можем да ги update-ваме
# (outcome, user_corrected_to) до момента, в който ги flush-нем на диск.
# Flush-ваме когато:
#   - hand_id се смени (записваме всички pending от старата ръка)
#   - при изход (atexit)
_pending_scans: dict[int, dict] = {}
_pending_lock = threading.Lock()


def setup(level: int = logging.INFO) -> None:
    """Инициализира logging. Idempotent — безопасно е да го викнеш многократно."""
    global _initialized
    if _initialized:
        return
    LOG_DIR.mkdir(exist_ok=True)

    root = logging.getLogger("poker")
    root.setLevel(level)
    root.propagate = False

    # Махни стари handler-и (reload safety)
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Ротиращ файл: 5MB × 5 backups
    fh = logging.handlers.RotatingFileHandler(
        ADVISOR_LOG, maxBytes=5 * 1024 * 1024, backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    fh.setLevel(level)
    root.addHandler(fh)

    # Console handler за WARNING+ (да не спамим конзолата)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.WARNING)
    root.addHandler(ch)

    _initialized = True
    root.info("[INIT] poker_logger initialized; log_dir=%s", LOG_DIR)

    # atexit flush — гарантира че pending scans се записват при exit
    import atexit
    atexit.register(_flush_all_pending)


def get_logger(name: str = "poker") -> logging.Logger:
    """Връща logger child; винаги под корен 'poker'."""
    if not _initialized:
        setup()
    if name == "poker" or name.startswith("poker."):
        return logging.getLogger(name)
    return logging.getLogger(f"poker.{name}")


# ── Scan records ───────────────────────────────────────────────────────
def record_scan(data: dict[str, Any]) -> int:
    """
    Регистрира нов scan запис. Връща scan_id (int) който може да се ползва за
    последващи update-и (outcome, correction).

    Записът остава in-memory докато не го flush-нем (при hand change или exit).
    Това е OK защото typical hand има ≤1 scan → никога не държим >5-10 records.

    Expected keys in data (всичко е optional, missing → null):
      hand_id, window_title, window_rect, duration_ms,
      cards, confidence, details, detectors,
      calibrated, easyocr, tesseract, error
    """
    global _scan_counter
    with _scan_lock:
        _scan_counter += 1
        sid = _scan_counter

    record = {
        "scan_id": sid,
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "hand_id": data.get("hand_id"),
        "window_title": data.get("window_title"),
        "window_rect": data.get("window_rect"),
        "duration_ms": data.get("duration_ms"),
        "cards": data.get("cards"),
        "confidence": data.get("confidence"),
        "details": data.get("details"),
        "detectors": data.get("detectors"),
        "calibrated": data.get("calibrated"),
        "easyocr": data.get("easyocr"),
        "tesseract": data.get("tesseract"),
        "outcome": data.get("outcome", "pending"),
        "user_corrected_to": None,
        "error": data.get("error"),
    }
    with _pending_lock:
        _pending_scans[sid] = record

    # Дублиран еntry в human-readable log
    lg = get_logger()
    cards_str = _fmt_cards(record["cards"])
    conf = record.get("confidence")
    conf_str = f"{conf:.2f}" if isinstance(conf, (int, float)) else "?"
    lg.info(
        "[SCAN] id=%d hand=%s cards=%s conf=%s dur=%sms det=%s",
        sid, record["hand_id"] or "-",
        cards_str, conf_str,
        record.get("duration_ms") or "?",
        ",".join(record.get("detectors") or []) or "-",
    )
    return sid


def update_scan_outcome(scan_id: int, outcome: str) -> None:
    """Update-ва outcome на pending scan запис."""
    with _pending_lock:
        rec = _pending_scans.get(scan_id)
        if rec is None:
            return
        rec["outcome"] = outcome
    get_logger().info("[SCAN] id=%d outcome=%s", scan_id, outcome)


def record_correction(scan_id: Optional[int], user_cards: list) -> None:
    """
    Юзърът е коригирал scan-предсказаните карти. Записва какво реално е било.

    Ако scan_id не е None, updates existing record.
    Винаги логва в advisor.log.
    """
    lg = get_logger()
    fmt_user = _fmt_cards(user_cards)
    if scan_id is None:
        lg.info("[CORRECTION] user_cards=%s (no prior scan)", fmt_user)
        return
    with _pending_lock:
        rec = _pending_scans.get(scan_id)
        if rec is not None:
            rec["user_corrected_to"] = [list(c) for c in user_cards]
            predicted = _fmt_cards(rec.get("cards"))
            lg.info(
                "[CORRECTION] id=%d predicted=%s actual=%s",
                scan_id, predicted, fmt_user,
            )
        else:
            lg.info("[CORRECTION] id=%d (already flushed) actual=%s",
                    scan_id, fmt_user)


def flush_hand(hand_id: Optional[str]) -> None:
    """
    Flush pending scans за дадена ръка (напр. при new_hand, преди update на
    _last_hand). Ако hand_id е None → flush всички.
    """
    with _pending_lock:
        to_flush = [
            sid for sid, rec in _pending_scans.items()
            if hand_id is None or rec.get("hand_id") == hand_id
        ]
        if not to_flush:
            return
        records = [_pending_scans.pop(sid) for sid in to_flush]
    _write_jsonl(SCANS_JSONL, records)


def _flush_all_pending() -> None:
    """Atexit hook — flush всички pending scans."""
    try:
        flush_hand(None)
    except Exception:
        pass


# ── Hand summary (end-of-hand decision audit) ─────────────────────────
def record_hand_summary(data: dict[str, Any]) -> None:
    """
    Записва end-of-hand summary в hands.jsonl (append-only, never updated).

    Expected keys:
      hand_id, position, num_players, hole_cards, cards_source,
      board, preflop_rec, flop_rec, turn_rec, river_rec,
      advisor_line (str)
    """
    record = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        **data,
    }
    _write_jsonl(HANDS_JSONL, [record])


# ── Internals ──────────────────────────────────────────────────────────
def _fmt_cards(cards) -> str:
    """Форматира [(r,s),(r,s)] → 'Qs 2d' за човешко четене в advisor.log."""
    if not cards:
        return "-"
    try:
        return " ".join(f"{c[0]}{c[1]}" for c in cards)
    except Exception:
        return str(cards)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Atomic append на JSON Lines. Всеки record → 1 ред."""
    if not records:
        return
    try:
        path.parent.mkdir(exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False, default=str))
                f.write("\n")
    except Exception as e:
        try:
            get_logger().error("[ERROR] JSONL write failed path=%s err=%s",
                               path, e)
        except Exception:
            pass
