"""Strategy decision logger.

Записва decision points + hero actions в JSONL за постериорен анализ на:
- Дали следваш съветите
- Dalyстратегическите препоръки са добри на дълъг срок
- Кои спотове имат най-много разминавания съвет ↔ реално действие

Файлът расте append-only. Един ред = един event (decision или action).
Event schema:
  {
    "ts": ISO-8601 timestamp,
    "type": "advice" | "action" | "hand_start" | "hand_end",
    "hand_id": str,
    # for "advice":
    "street": "preflop"|"flop"|"turn"|"river",
    "pos": "UTG"|"MP"|"CO"|"BTN"|"SB"|"BB",
    "hole": "AhKs",
    "board": "AdKc9h",
    "facing_bet": bool,
    "pot_bb": float|null,
    "stack_bb": float|null,
    "num_opponents": int,
    "advice": {"action": str, "hand_label": str, "reason": str, "sizing": str},
    # for "action":
    "action_code": "F"|"c"|"C"|"B"|"E"|"P"|"p",
    "amount": int,
    "seq": int,
  }
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Default лог файл — в папката на проекта
DEFAULT_LOG_PATH = Path(__file__).parent / "hand_log.jsonl"

# Мапинг на action codes → човешки имена
ACTION_CODE_NAMES = {
    "F": "FOLD",
    "c": "CHECK",
    "C": "CALL",
    "B": "BET",
    "E": "RAISE",
    "P": "POST_BB",
    "p": "POST_SB",
    "Q": "POST_ANTE",
    "s": "SITOUT",
    "M": "MUCK",
}


def _cards_to_str(cards: Optional[List[Tuple[str, str]]]) -> str:
    """[(A,h),(K,s)] → 'AhKs'."""
    if not cards:
        return ""
    return "".join(f"{r}{s}" for r, s in cards)


class StrategyLogger:
    """Thread-unsafe но simple append-only JSONL писач.

    Използване от `poker_live.py`:
      logger = StrategyLogger()
      logger.log_advice(state, advice_dict)
      logger.log_action(hand_id, action_code, amount, seq)
      logger.log_hand_start(hand_id)
      logger.log_hand_end(hand_id)
    """

    def __init__(self, path: Optional[Path] = None, enabled: bool = True):
        self.path = Path(path) if path else DEFAULT_LOG_PATH
        self.enabled = enabled
        # Дедупликация на advice — не логваме един и същ съвет повторно
        # в същия спот (при poll-ове, които не носят нова информация).
        self._last_advice_key: Optional[str] = None
        self._last_hand_id: Optional[str] = None

    def _write(self, event: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            event["ts"] = datetime.now().isoformat(timespec="seconds")
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False))
                f.write("\n")
        except OSError:
            # Не искаме logging грешки да чупят UI-а
            pass

    def log_hand_start(self, hand_id: str) -> None:
        if hand_id == self._last_hand_id:
            return
        self._last_hand_id = hand_id
        self._last_advice_key = None
        self._write({"type": "hand_start", "hand_id": hand_id})

    def log_hand_end(self, hand_id: str) -> None:
        self._write({"type": "hand_end", "hand_id": hand_id})

    def log_advice(
        self,
        hand_id: Optional[str],
        street: str,
        pos: Optional[str],
        hole: Optional[List[Tuple[str, str]]],
        board: Optional[List[Tuple[str, str]]],
        facing_bet: bool,
        pot_bb: Optional[float],
        stack_bb: Optional[float],
        num_opponents: int,
        advice: Dict[str, Any],
    ) -> None:
        """Записва decision point. Дедуплиира идентични последователни advices."""
        if not hand_id:
            return
        hole_str = _cards_to_str(hole)
        board_str = _cards_to_str(board)
        # Дедуп: хеш от (hand_id, street, hole, board, action)
        key = (
            f"{hand_id}|{street}|{hole_str}|{board_str}|"
            f"{advice.get('action', '')}|{facing_bet}"
        )
        if key == self._last_advice_key:
            return
        self._last_advice_key = key
        self._write({
            "type": "advice",
            "hand_id": hand_id,
            "street": street,
            "pos": pos,
            "hole": hole_str,
            "board": board_str,
            "facing_bet": bool(facing_bet),
            "pot_bb": pot_bb,
            "stack_bb": stack_bb,
            "num_opponents": int(num_opponents) if num_opponents else 1,
            "advice": {
                "action": advice.get("action", ""),
                "hand_label": advice.get("hand", ""),
                "reason": advice.get("reason", ""),
                "sizing": advice.get("sizing", ""),
            },
        })

    # Outcome markers (не са решения — филтрират се от agreement stats)
    OUTCOME_CODES = frozenset({"W", "L", "M", "s"})
    # Auto-posted blinds/antes — не са решения на играча
    AUTO_CODES = frozenset({"P", "p", "Q"})

    def log_action(
        self,
        hand_id: str,
        action_code: str,
        amount: int = 0,
        seq: Optional[int] = None,
    ) -> None:
        """Записва реалното hero действие от PS лога."""
        if not hand_id:
            return
        # Игнорирай auto-posted blinds/antes — не са решения на играча
        if action_code in self.AUTO_CODES:
            return
        self._write({
            "type": "action",
            "hand_id": hand_id,
            "action_code": action_code,
            "action_name": ACTION_CODE_NAMES.get(action_code, action_code),
            "amount": int(amount),
            "seq": seq,
        })


# ═══ Анализ helpers (за бъдещ пост-процесинг) ════════════════════════════
def load_events(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Прочита всички events от JSONL."""
    p = Path(path) if path else DEFAULT_LOG_PATH
    if not p.exists():
        return []
    events: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def group_by_hand(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Групира events по hand_id, в реда на появяване."""
    by_hand: Dict[str, List[Dict[str, Any]]] = {}
    for e in events:
        hid = e.get("hand_id")
        if not hid:
            continue
        by_hand.setdefault(hid, []).append(e)
    return by_hand


def _normalize_advice_tokens(advice_act: str) -> set:
    """Извлича действеня tokens от advice string.

    Премахва препинателни знаци и annotations: "3-BET / CALL (силна)" →
    {"3-BET", "CALL", "RAISE"} (3-BET е alias на RAISE в PS лога).

    Връща set на action tokens които биха се считали за съгласие с hero-то действие.
    """
    s = advice_act.upper()
    # Премахни bracketed annotations
    for ch in "()[]{}":
        s = s.replace(ch, " ")
    # Нормализирай separators
    for sep in ("/", ",", "+", "|"):
        s = s.replace(sep, " ")
    tokens = set(t.strip() for t in s.split() if t.strip())
    # Remove non-action words
    noise = {"BLUFF", "VALUE", "SEMI-BLUFF", "POT", "CONTROL", "DONK",
             "THIN", "BARREL", "PROBE", "FLOAT", "STAB",
             "МАРГИНАЛНО", "СИЛНА", "СЛАБА", "SMALL", "BIG",
             "BB", "IP", "OOP", "VS", "ЗАВИСИ"}
    tokens = {t for t in tokens if t not in noise and not t.endswith("X")
              and not t.replace(".", "").replace("X", "").isdigit()}
    # 3-BET / 4-BET / ALL-IN → RAISE (PS лог ги вижда като E=RAISE)
    alias = {
        "3-BET": {"RAISE"}, "3BET": {"RAISE"},
        "4-BET": {"RAISE"}, "4BET": {"RAISE"},
        "5-BET": {"RAISE"}, "5BET": {"RAISE"},
        "ALL-IN": {"RAISE", "CALL"},  # allin може да е raise или call
        "SHOVE": {"RAISE"},
        "OPEN": {"RAISE"}, "RFI": {"RAISE"},
    }
    expanded = set(tokens)
    for t in list(tokens):
        expanded.update(alias.get(t, set()))
    return expanded


def agreement_stats(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """За всяка ръка сравнява последния advice с hero action.
    Връща: total hands with decision, agreement pct, disagreement breakdown.

    Филтрира outcome codes (W/L/M/s) — те не са решения, а резултати от showdown.
    """
    by_hand = group_by_hand(events)
    total = 0
    agree = 0
    disagreements: List[Dict[str, Any]] = []
    outcome_codes = StrategyLogger.OUTCOME_CODES
    for hid, evs in by_hand.items():
        # Вземи последния advice преди всяко action
        last_advice_by_street: Dict[str, Dict[str, Any]] = {}
        for e in evs:
            if e["type"] == "advice":
                last_advice_by_street[e.get("street", "?")] = e
            elif e["type"] == "action":
                # Skip outcome markers (showdown results, не decisions)
                if e.get("action_code") in outcome_codes:
                    continue
                # Pair с най-новия advice
                if not last_advice_by_street:
                    continue
                # Вземи най-скорошния
                adv = list(last_advice_by_street.values())[-1]
                advice_act = adv["advice"]["action"]
                hero_act = e.get("action_name", "").upper()
                total += 1
                tokens = _normalize_advice_tokens(advice_act)
                if hero_act in tokens:
                    agree += 1
                else:
                    disagreements.append({
                        "hand_id": hid,
                        "street": adv.get("street"),
                        "hole": adv.get("hole"),
                        "board": adv.get("board"),
                        "advised": advice_act.upper(),
                        "actual": hero_act,
                    })
    return {
        "total_decisions": total,
        "agreed": agree,
        "agreement_pct": (agree / total * 100) if total else 0.0,
        "disagreements": disagreements,
    }


if __name__ == "__main__":
    # CLI quick stats
    evs = load_events()
    print(f"Total events: {len(evs)}")
    stats = agreement_stats(evs)
    print(f"Decisions: {stats['total_decisions']}, "
          f"agreement: {stats['agreement_pct']:.1f}%")
    for d in stats["disagreements"][-5:]:
        print(f"  {d['hand_id']} {d['street']} {d['hole']}|{d['board']}: "
              f"advised={d['advised']} actual={d['actual']}")
